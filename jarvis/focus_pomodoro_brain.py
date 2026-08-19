"""JARVIS FOCUS/POMODORO SKILLS: a real focus-session engine, not advice.

Three voice skills backed by a live engine (module-level singleton
``PomodoroManager``, threading.Lock-safe, driven by a background daemon
thread on the monotonic clock):

    - fx_start  : "start a focus session" / "start pomodoro" /
                  "start a 50 minute focus session" -> begins the cycle;
                  default 25 min work / 5 min short break, long break
                  (15 min) after every 4 rounds. Executors return
                  immediately - the tracking happens off-thread.
    - fx_status : "focus status" / "pomodoro status" -> phase, time
                  remaining, round number, sessions completed today.
    - fx_stop   : "end focus session" / "stop pomodoro" -> ends early
                  with stats for the session.

State machine: work -> short break -> work ... with a long break after
every ``rounds_per_long`` completed work rounds. Rounds completed today
are tracked in memory only, keyed on the calendar day.

On every phase transition the manager announces through the app object
duck-typed exactly like main.TimerManager consumers: guarded getattr for
``app.say(text)`` then ``app._notify(...)`` , each try/except-wrapped.
A misbehaving app can never crash the tracker thread.

This module never imports main. Stdlib only.
"""

from __future__ import annotations

import datetime
import re
import threading
import time

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("focus_pomodoro_brain")

# ==========================================================================
# Tunables (defaults per the classic pomodoro technique)
# ==========================================================================
DEFAULT_WORK_S = 1500        # 25 minutes
DEFAULT_SHORT_S = 300        # 5 minutes
DEFAULT_LONG_S = 900         # 15 minutes
DEFAULT_ROUNDS_PER_LONG = 4  # long break after every 4 work rounds
DEFAULT_POLL_S = 1.0         # tracker thread wake-up cadence

MIN_WORK_S = 60              # clamps for spoken durations
MAX_WORK_S = 4 * 3600

_PHASE_LABELS = {
    "work": "deep work",
    "short_break": "short break",
    "long_break": "long break",
}


# ==========================================================================
# Notification seam (duck-typed app; mirrors main.TimerManager consumers)
# ==========================================================================

def _announce(app, text: str) -> None:
    """Best-effort announce: ``app.say(text)`` then ``app._notify(text)``.

    Every step is getattr-guarded and exception-swallowed - notifications
    are strictly fire-and-forget and must never propagate.
    """
    if app is None or not text:
        return
    try:
        say = getattr(app, "say", None)
    except Exception:
        say = None
    if callable(say):
        try:
            say(text)
        except Exception:
            log.exception("app.say failed")
    try:
        notify = getattr(app, "_notify", None)
    except Exception:
        notify = None
    if callable(notify):
        try:
            try:
                notify("JARVIS Focus", text)      # main.JarvisApp signature
            except TypeError:
                notify(text)                      # one-arg duck type
        except Exception:
            log.exception("app._notify failed")


# ==========================================================================
# Engine
# ==========================================================================

class PomodoroManager:
    """Lock-safe pomodoro state machine tracked on the monotonic clock.

    ``_now()`` and ``_today()`` are seams: tests monkeypatch them for a
    fully deterministic, sleep-free suite.
    """

    def __init__(self, work_s: float = DEFAULT_WORK_S,
                 short_s: float = DEFAULT_SHORT_S,
                 long_s: float = DEFAULT_LONG_S,
                 rounds_per_long: int = DEFAULT_ROUNDS_PER_LONG,
                 poll: float = DEFAULT_POLL_S):
        self.work_s = int(work_s)
        self.short_s = int(short_s)
        self.long_s = int(long_s)
        self.rounds_per_long = max(1, int(rounds_per_long))
        self.poll = max(0.001, float(poll))
        self._lock = threading.RLock()
        self._sess: dict | None = None
        self._app = None
        self._thread: threading.Thread | None = None
        self._stop_evt = threading.Event()
        self._day = self._today()
        self._done_today = 0

    # ---- seams ----------------------------------------------------------
    def _now(self) -> float:
        return time.monotonic()

    def _today(self):
        return datetime.date.today()

    # ---- daily bookkeeping ----------------------------------------------
    def _roll_day_locked(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._done_today = 0

    # ---- session lifecycle ----------------------------------------------
    def start_session(self, work_s: float | None = None,
                      app=None) -> dict | None:
        """Begin a session; ``None`` if one is already running."""
        with self._lock:
            self._roll_day_locked()
            if self._sess is not None:
                return None
            if work_s:
                span = max(MIN_WORK_S, min(MAX_WORK_S, int(float(work_s))))
            else:
                span = self.work_s
            self._sess = {
                "phase": "work",
                "round": 1,
                "len": span,
                "work": span,
                "t0": self._now(),
                "rounds_done": 0,
                "focused_s": 0,
            }
            if app is not None:
                self._app = app
        self._spawn()
        return self.status()

    def _spawn(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_evt.clear()
            thread = threading.Thread(
                target=self._run, name="jarvis-focus-tracker", daemon=True)
            self._thread = thread
        thread.start()

    def _run(self) -> None:
        """Background loop; transitions must NEVER crash this thread."""
        while not self._stop_evt.wait(self.poll):
            try:
                self._tick()
            except Exception:  # defensive containment
                log.exception("focus tracker tick failed")

    def _tick(self) -> bool:
        """Apply every due transition once; returns True if any fired."""
        due: list[str] = []
        for _ in range(1000):                       # bounded catch-up loop
            with self._lock:
                sess = self._sess
                if sess is None or self._now() - sess["t0"] < sess["len"]:
                    break
                due.append(self._advance_locked(sess))
        for text in due:
            try:
                with self._lock:
                    app = self._app
                _announce(app, text)
            except Exception:                        # never crash the thread
                log.exception("transition announce failed")
        return bool(due)

    def _advance_locked(self, sess: dict) -> str:
        """Roll one finished phase forward; returns the announcement text."""
        prev_len = sess["len"]
        if sess["phase"] == "work":
            sess["rounds_done"] += 1
            sess["focused_s"] += sess["len"]
            self._done_today += 1
            mins = max(1, sess["len"] // 60)
            if sess["round"] % self.rounds_per_long == 0:
                sess["phase"] = "long_break"
                sess["len"] = self.long_s
                text = (f"Focus round {sess['round']} complete, sir - that is "
                        f"{mins} minutes of deep work banked. Long break: "
                        f"{max(1, self.long_s // 60)} minutes, well earned.")
            else:
                sess["phase"] = "short_break"
                sess["len"] = self.short_s
                text = (f"Focus round {sess['round']} complete, sir - "
                        f"{mins} minutes done. Short break: "
                        f"{max(1, self.short_s // 60)} minutes; stand up "
                        f"and stretch.")
        else:
            sess["round"] += 1
            sess["phase"] = "work"
            sess["len"] = sess["work"]
            text = (f"Break is over, sir - focus round {sess['round']} "
                    f"begins now.")
        # Schedule-based rollover: the next phase is dated from when the
        # previous one was due, so a stalled/lagging tracker catches up
        # deterministically instead of silently gifting free time.
        sess["t0"] += prev_len
        return text

    def status(self) -> dict:
        """Snapshot of engine state; safe to call anytime."""
        with self._lock:
            self._roll_day_locked()
            sess = self._sess
            out = {
                "running": sess is not None,
                "completed_today": self._done_today,
                "phase": None,
                "round": None,
                "remaining": None,
                "phase_len": None,
                "rounds_this_session": 0,
            }
            if sess is not None:
                remaining = max(0, sess["len"] - (self._now() - sess["t0"]))
                out.update(
                    phase=sess["phase"],
                    round=sess["round"],
                    remaining=int(round(remaining)),
                    phase_len=sess["len"],
                    rounds_this_session=sess["rounds_done"],
                )
            return out

    def stop_session(self) -> dict | None:
        """End early; returns stats dict, or ``None`` if nothing ran."""
        with self._lock:
            self._roll_day_locked()
            sess = self._sess
            if sess is None:
                return None
            self._sess = None
            stats = {
                "rounds": sess["rounds_done"],
                "focus_min": int(round(sess["focused_s"] / 60)),
                "completed_today": self._done_today,
                "ended_during": sess["phase"],
                "was_on_round": sess["round"],
            }
        self._stop_evt.set()          # tracker has nothing left to watch
        return stats

    def shutdown(self) -> None:
        """Stop the tracker thread and drop state (tests/teardown)."""
        self._stop_evt.set()
        with self._lock:
            self._sess = None
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    @property
    def tracker_alive(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())


# ==========================================================================
# Module-level singleton (Lock-safe lazy construction)
# ==========================================================================

_SINGLETON_LOCK = threading.Lock()
_MANAGER: PomodoroManager | None = None


def get_manager() -> PomodoroManager:
    global _MANAGER
    with _SINGLETON_LOCK:
        if _MANAGER is None:
            _MANAGER = PomodoroManager()
        return _MANAGER


# ==========================================================================
# Formatting helpers
# ==========================================================================

def _fmt_clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    mins, secs = divmod(seconds, 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}h {mins:02d}m"
    return f"{mins}m {secs:02d}s"


def _label(phase: str | None) -> str:
    return _PHASE_LABELS.get(phase or "", phase or "idle")


# ==========================================================================
# Skill 1 - fx_start
# ==========================================================================

_START_RE = re.compile(
    r"\b(?:start|begin|commence|launch|run|kick\s*off)\b[^;.!?]{0,40}?"
    r"\b(?:pomodoro|focus\s+session|focus\s+mode|deep\s*work(?:\s+session)?)\b",
    re.I)

_DUR_MIN_RE = re.compile(r"\b(\d{1,4})\s*(?:minutes?|mins?)\b", re.I)
_DUR_HOUR_RE = re.compile(r"\b(\d{1,2}(?:\.\d)?)\s*(?:hours?|hrs?)\b", re.I)
_DUR_HALF_HOUR_RE = re.compile(r"\bhalf\s+(?:of\s+)?(?:an?\s+)?hour\b", re.I)
_DUR_QUARTER_RE = re.compile(r"\bquarter\s+(?:of\s+)?(?:an?\s+)?hour\b", re.I)


def _parse_work_seconds(cmd: str) -> int | None:
    """Spoken duration -> work-block seconds; None if unspecified."""
    if _DUR_HALF_HOUR_RE.search(cmd):
        return 1800
    if _DUR_QUARTER_RE.search(cmd):
        return 900
    hm = _DUR_HOUR_RE.search(cmd)
    if hm:
        return int(float(hm.group(1)) * 3600)
    mm = _DUR_MIN_RE.search(cmd)
    if mm:
        return int(mm.group(1)) * 60
    return None


def _d_start(cmd: str):
    m = _START_RE.search(cmd)
    if not m:
        return None
    return {"cmd": cmd, "work_s": _parse_work_seconds(cmd)}


def _e_start(app, ctx) -> str:
    mgr = get_manager()
    snap = mgr.start_session(work_s=ctx.get("work_s"), app=app)
    if snap is None:
        cur = mgr.status()
        return (f"A focus session is already underway, sir - round "
                f"{cur['round']}, {_label(cur['phase'])}, "
                f"{_fmt_clock(cur['remaining'] or 0)} remaining. Say "
                f"'end focus session' if you want it stopped, sir.")
    work_min = max(1, snap["phase_len"] // 60)
    return (f"Focus session started, sir - {work_min}-minute rounds with "
            f"{max(1, mgr.short_s // 60)}-minute breaks, and a long "
            f"{max(1, mgr.long_s // 60)}-minute break after every "
            f"{mgr.rounds_per_long} rounds. I shall keep the clock; say "
            f"'focus status' anytime, sir.")


# ==========================================================================
# Skill 2 - fx_status
# ==========================================================================

_STATUS_RE = re.compile(
    r"\b(?:focus|pomodoro|pomo|deep\s*work)\s*(?:session\s*|mode\s*)?status\b"
    r"|\bstatus\s+(?:of\s+)?(?:the\s+|my\s+)?(?:focus|pomodoro)"
    r"(?:\s+session)?\b"
    r"|\bhow(?:'s| is)\s+(?:my\s+)?(?:focus|pomodoro|deep\s*work)"
    r"(?:\s+session)?(?:\s+going)?\b", re.I)


def _d_status(cmd: str):
    if _STATUS_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_status(app, ctx) -> str:
    cur = get_manager().status()
    today = cur["completed_today"]
    if not cur["running"]:
        tail = (" The day was not wasted entirely, sir."
                if today else "")
        return (f"No focus session is running at the moment, sir - "
                f"{today} session(s) completed today.{tail} Say 'start "
                f"pomodoro' whenever you are ready, sir.")
    return (f"Focus status, sir: round {cur['round']}, "
            f"{_label(cur['phase'])} phase, "
            f"{_fmt_clock(cur['remaining'])} remaining - "
            f"{today} session(s) completed today, sir.")


# ==========================================================================
# Skill 3 - fx_stop
# ==========================================================================

_STOP_RE = re.compile(
    r"\b(?:end|stop|cancel|abort|terminate|halt|kill)\b[^;.!?]{0,30}?"
    r"\b(?:pomodoro|focus\s+session|focus\s+mode|deep\s*work)\b"
    r"|\b(?:end|stop|cancel)\s+(?:the\s+|my\s+|this\s+)?focus\b", re.I)


def _d_stop(cmd: str):
    if _STOP_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_stop(app, ctx) -> str:
    stats = get_manager().stop_session()
    if stats is None:
        return ("There is no focus session to end, sir - the clock is "
                "already quiet, sir.")
    plural = "s" if stats["rounds"] != 1 else ""
    return (f"Focus session ended early, sir - {stats['rounds']} round"
            f"{plural} complete, roughly {stats['focus_min']} minute(s) of "
            f"deep work banked, {stats['completed_today']} today. A "
            f"respectable showing, sir.")


# ==========================================================================
# Registration (template: mail_skills.py)
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("fx_start", _d_start, _e_start, True),
    ("fx_status", _d_status, _e_status, True),
    ("fx_stop", _d_stop, _e_stop, True),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all focus/pomodoro skills with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("focus/pomodoro skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my focus module "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
