"""Clicky-style GLOBAL hold-a-hotkey push-to-talk engine.

System-wide PTT for JARVIS: hold a hotkey combo anywhere in the OS and
``on_start``/``on_stop`` fire exactly once per press/release cycle, even when
the app is unfocused. Designed as an engine for ``main.py`` -- no brain
registration happens here.

Graceful degradation (never raises on missing pieces):
    * pynput not importable      -> ``available=False``, ``start()`` -> False
    * listener factory ImportError -> same unavailable path
    * macOS permission missing   -> ``is_trusted()`` -> False (informational)

Usage:
    ptt = GlobalPTT(on_start=start_recording, on_stop=finish_recording)
    if ptt.start():
        ...  # later: ptt.stop()

Singleton convenience for embedders:
    acquire(on_start=..., on_stop=...)   # idempotent
    release()                            # stop + drop

Latency hooks: ``t_press`` / ``t_release`` (monotonic ``perf_counter``
timestamps taken at fire time) let callers assert sub-2s voice loops.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Callable, Optional, Sequence

log = logging.getLogger(__name__)

__all__ = ["GlobalPTT", "HAVE_PYNPUT", "acquire", "release", "is_trusted"]

# Optional dependency by design: probing must never raise.
try:
    import pynput  # noqa: F401

    HAVE_PYNPUT = True
except Exception:  # pragma: no cover - environment dependent
    HAVE_PYNPUT = False

DEFAULT_COMBO: tuple[str, ...] = ("ctrl_l", "alt_l")


# --------------------------------------------------------------------------- #
# macOS permission probe
# --------------------------------------------------------------------------- #
def _osa_check(argv: Sequence[str]) -> int:
    """Run *argv*, return exit code (nonzero on any failure). Test seam."""
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=3, check=False
        )
        return proc.returncode
    except Exception:
        return 1


def is_trusted() -> bool:
    """True when macOS Accessibility grants global input observation."""
    return _osa_check(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first process',
        ]
    ) == 0


# --------------------------------------------------------------------------- #
# Key tokenization: identical view for real pynput keys and test fakes
# --------------------------------------------------------------------------- #
def _norm_entry(entry: object) -> str:
    n = str(entry).strip().lower()
    return "char:" + n if len(n) == 1 else n


def _token_for(key: object) -> str:
    if isinstance(key, str):
        return _norm_entry(key)
    name = getattr(key, "name", None)
    if isinstance(name, str) and name:
        return name.lower()
    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        return "char:" + char.lower()
    return str(key).lower()


def _default_listener_factory(on_press, on_release):
    # Imported lazily so absence of pynput surfaces as ImportError at start(),
    # keeping module import side-effect free.
    from pynput import keyboard  # noqa: PLC0415 - optional dependency

    return keyboard.Listener(on_press=on_press, on_release=on_release)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class GlobalPTT:
    """Edge-triggered, re-armable global hold-to-talk.

    State machine per combo member token:
        press  -> add to held set; held == all tokens && not active
                  -> activate, fire on_start ONCE
        release-> remove from held; if active -> deactivate, fire on_stop ONCE
    OS key-repeat re-presses are absorbed (set idempotence + active guard).
    """

    #: Injection seam: replace with a fake exposing run()/stop()/join().
    LISTENER_FACTORY = staticmethod(_default_listener_factory)

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        combo: Sequence[str] = DEFAULT_COMBO,
    ) -> None:
        self.on_start = on_start
        self.on_stop = on_stop
        self.combo = tuple(_norm_entry(k) for k in combo)
        self._tokens = frozenset(self.combo)
        self._lock = threading.RLock()
        self._held: set[str] = set()
        self._listener = None
        self._thread: Optional[threading.Thread] = None
        self.active = False
        self.available = bool(HAVE_PYNPUT)
        self._running = False
        self.t_press: Optional[float] = None
        self.t_release: Optional[float] = None
        self.starts_fired = 0
        self.stops_fired = 0

    # -- introspection ----------------------------------------------------- #
    @property
    def running(self) -> bool:
        return self._running

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> bool:
        """Spawn the daemon listener thread. False when unavailable."""
        with self._lock:
            if self._running:
                return True
            if not HAVE_PYNPUT:
                self.available = False
                return False
            try:
                listener = self.LISTENER_FACTORY(
                    on_press=self._handle_press, on_release=self._handle_release
                )
            except ImportError:
                self.available = False
                return False
            except Exception:
                self.available = False
                log.exception("PTT listener factory failed")
                return False
            self._listener = listener
            self._running = True
            self._thread = threading.Thread(
                target=self._listen_loop,
                args=(listener,),
                name="jarvis-ptt-listener",
                daemon=True,
            )
            self._thread.start()
            return True

    def _listen_loop(self, listener) -> None:
        try:
            listener.run()
        except Exception:
            log.exception("PTT listener terminated unexpectedly")
        finally:
            with self._lock:
                self._running = False

    def stop(self) -> None:
        """Stop the listener and join its thread. Idempotent, never raises.

        If the combo was mid-hold, a final on_stop fires so mics/loops opened
        by on_start cannot be left dangling.
        """
        with self._lock:
            if not self._running and self._listener is None:
                self.active = False
                self._held.clear()
                return
            self._running = False
            listener, self._listener = self._listener, None
            thread, self._thread = self._thread, None
            final_cb = self.on_stop if self.active else None
            self.active = False
            self._held.clear()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        if (
            thread is not None
            and thread is not threading.current_thread()
            and thread.is_alive()
        ):
            thread.join(timeout=2.0)
        if final_cb is not None:
            self._fire("stop")

    # -- event handlers (listener thread) ----------------------------------- #
    def _handle_press(self, key: object) -> None:
        token = _token_for(key)
        with self._lock:
            if not self._running or token not in self._tokens:
                return
            self._held.add(token)
            if self.active or self._held != self._tokens:
                return
            self.active = True
        self._fire("start")

    def _handle_release(self, key: object) -> None:
        token = _token_for(key)
        with self._lock:
            if not self._running or token not in self._tokens:
                return
            self._held.discard(token)
            if not self.active:
                return
            self.active = False
        self._fire("stop")

    def _fire(self, which: str) -> None:
        with self._lock:
            if which == "start":
                self.starts_fired += 1
                self.t_press = time.perf_counter()
            else:
                self.stops_fired += 1
                self.t_release = time.perf_counter()
        cb = self.on_start if which == "start" else self.on_stop
        try:
            if cb is not None:
                cb()
        except Exception:
            log.exception("PTT %s callback raised", which)


# Expose the permission probe statically on the engine as well.
GlobalPTT.is_trusted = staticmethod(is_trusted)


# --------------------------------------------------------------------------- #
# Process-wide singleton helpers
# --------------------------------------------------------------------------- #
def _noop() -> None:
    pass


_singleton: Optional[GlobalPTT] = None
_sing_lock = threading.Lock()


def acquire(
    on_start: Optional[Callable[[], None]] = None,
    on_stop: Optional[Callable[[], None]] = None,
    combo: Sequence[str] = DEFAULT_COMBO,
) -> GlobalPTT:
    """Return the process-wide engine, creating it on first call (idempotent)."""
    global _singleton
    with _sing_lock:
        if _singleton is None:
            _singleton = GlobalPTT(
                on_start=on_start if on_start is not None else _noop,
                on_stop=on_stop if on_stop is not None else _noop,
                combo=combo,
            )
        return _singleton


def release() -> None:
    """Stop and drop the process-wide engine. Idempotent."""
    global _singleton
    with _sing_lock:
        engine, _singleton = _singleton, None
    if engine is not None:
        engine.stop()
