"""JARVIS LIVE SCREEN BRAIN: Clicky-style screen-awareness skills.

Brain-level screen skills layered on top of JARVIS's existing vision stack.
main.JarvisBot already screenshots the display and queries Groq vision; this
module NEVER imports main. Instead it talks through two seams any host can
plug into:

* :func:`take_screenshot` - current screen -> base64 PNG. Uses pyautogui when
  importable, otherwise falls back to the macOS ``screencapture -x`` utility
  written to a temp file. Returns ``None`` when both fail.
* :func:`ask_vision`      - (app, b64_png, question) -> answer text or
  ``None``. Prefers ``app._ask_vision`` when present; otherwise posts
  directly to the Groq REST API using env ``GROQ_API_KEY`` and model
  ``meta-llama/llama-4-scout-17b-16e-instruct``. Offline / no key -> ``None``.

Registered skills (via :func:`register`):

* ``ls_whats_on_screen``  - describe what is currently on screen
* ``ls_where_is``         - locate a UI element, report pixel coordinates
* ``ls_read_screen``      - transcribe on-screen text blocks
* ``ls_explain_screen``   - step-by-step tutorial for the current screen
* ``ls_watch_start``      - background watcher capturing every 30 seconds
* ``ls_watch_stop``       - stand the watcher down
* ``ls_screen_digest``    - recall the watcher's latest observation

The watcher stores its newest digest in the module variable ``LAST_DIGEST``
and is disabled entirely when env ``JARVIS_TEST=1``. Every executor is
persona-safe: failures degrade to honest ", sir." replies instead of raising.
"""

from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import tempfile
import threading
import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("live_screen_brain")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
WATCH_INTERVAL_SECONDS = 30.0


# ==========================================================================
# Seams: screenshot + vision
# ==========================================================================

def take_screenshot():
    """Capture the screen; return base64 PNG text, or ``None`` on failure.

    Order: multi-monitor stitched capture (all displays, Clicky-grade)
    -> pyautogui primary -> macOS ``screencapture -x``. The stitched
    path is skipped under JARVIS_TEST=1 so unit tests can stub the
    legacy paths deterministically.
    """
    if os.environ.get("JARVIS_TEST") != "1":
        try:
            import multi_monitor
            png = multi_monitor.capture_all_stitched()
            if png:
                return base64.b64encode(png).decode("ascii")
        except Exception as exc:
            log.debug("multi-monitor capture unavailable: %s", exc)
    try:
        import pyautogui
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        log.debug("pyautogui screenshot unavailable: %s", exc)
    return _screencapture_b64()


def _screencapture_b64():
    """macOS fallback: ``screencapture -x`` into a temp png, base64-encoded."""
    path = None
    try:
        fd, path = tempfile.mkstemp(prefix="jarvis_screen_", suffix=".png")
        os.close(fd)
        proc = subprocess.run(["screencapture", "-x", path],
                              capture_output=True, timeout=10)
        if proc.returncode != 0 or not os.path.getsize(path):
            return None
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    except Exception as exc:
        log.debug("screencapture fallback failed: %s", exc)
        return None
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def ask_vision(app, b64_png, question):
    """Ask the vision model about a frame; return text answer or ``None``.

    Prefers the host's ``app._ask_vision(b64_png, question)`` seam when it
    exists (its answer is treated as authoritative, including failures);
    otherwise falls back to direct Groq REST using ``GROQ_API_KEY``.
    """
    fn = getattr(app, "_ask_vision", None)
    if callable(fn):
        try:
            answer = fn(b64_png, question)
        except Exception as exc:
            log.debug("app._ask_vision raised: %s", exc)
            answer = None
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return None
    return _groq_rest_vision(b64_png, question)


def _groq_rest_vision(b64_png, question):
    """Direct Groq chat-completions vision call; ``None`` when impossible."""
    api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key or requests is None or not b64_png:
        return None
    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_VISION_MODEL,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": question},
                        {"type": "image_url", "image_url": {
                            "url": f"data:image/png;base64,{b64_png}",
                        }},
                    ]},
                ],
                "max_tokens": 1024,
            },
            timeout=30,
        )
        data = resp.json()
        choices = (data or {}).get("choices") or [{}]
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        return None
    except Exception as exc:
        log.debug("groq vision request failed: %s", exc)
        return None


# ==========================================================================
# Parsing helpers + persona plumbing
# ==========================================================================

_COORD_RE = re.compile(r"(?<!\d)(\d{1,5})\s*,\s*(\d{1,5})(?!\d)")


def _extract_coords(text):
    """Pull the first 'x, y' integer pair out of messy vision prose."""
    if not text:
        return None
    m = _COORD_RE.search(text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _clean_target(raw):
    target = re.sub(r"\s+", " ", (raw or "")).strip(" ?!.,'\"")
    target = re.sub(r"^(?:the|a|an)\s+", "", target, flags=re.I)
    return target.strip()


def _persona_safe(reply):
    """Guarantee the Jarvis persona: every reply ends with ', sir.'"""
    r = (reply or "").rstrip()
    if re.search(r"\bsir\b[\s.?!]*$", r, re.I):
        return r
    if r.endswith((".", "!", "?")):
        return r[:-1].rstrip() + ", sir" + r[-1:]
    return r + ", sir."


def _offline_reply(would_line, target=None):
    lead = (f"I can't get eyes on '{target}' right now"
            if target else "My visual feed is dark right now")
    return (
        f"{lead}, sir. No screenshot, no vision pass. "
        f"If my optics were online I would {would_line} "
        "Restore the screen-capture service or the GROQ_API_KEY and ask again."
    )


# ==========================================================================
# Background watcher (disabled under JARVIS_TEST=1)
# ==========================================================================

LAST_DIGEST = None
_watch_lock = threading.Lock()
_watcher_stop = threading.Event()
_watcher_thread: threading.Thread | None = None


def _watch_once(app):
    """Single capture + digest tick; True when LAST_DIGEST was refreshed."""
    global LAST_DIGEST
    try:
        b64 = take_screenshot()
        if not b64:
            return False
        answer = ask_vision(app, b64,
                            "Briefly summarize what is currently on this "
                            "screen in two sentences.")
        if not answer:
            return False
        stamp = time.strftime("%H:%M:%S")
        with _watch_lock:
            LAST_DIGEST = f"[{stamp}] {answer.strip()}"
        return True
    except Exception:
        log.exception("screen watch tick failed")
        return False


def _watch_loop(app):
    while not _watcher_stop.is_set():
        _watch_once(app)
        if _watcher_stop.wait(WATCH_INTERVAL_SECONDS):
            break


# ==========================================================================
# Executors
# ==========================================================================

def _exec_whats_on_screen(app, ctx):
    b64 = take_screenshot()
    if not b64:
        return _offline_reply("capture your display and describe every "
                              "window, panel, and control in view")
    answer = ask_vision(app, b64,
                        "Describe everything visible on this screen in "
                        "detail: apps, windows, dialogs, and key UI elements.")
    if not answer:
        return _offline_reply("capture your display and describe every "
                              "window, panel, and control in view")
    return f"On your screen at this moment, sir:\n\n{answer}"


def _exec_where_is(app, ctx):
    target = (ctx.get("target") or "that element").strip()
    b64 = take_screenshot()
    if not b64:
        return _offline_reply("scan the interface and hand you exact pixel "
                              "coordinates for that control", target=target)
    answer = ask_vision(app, b64,
                        f"Find the UI element '{target}' in this screenshot. "
                        "Respond with ONLY its approximate center pixel "
                        "coordinates in the form 'x, y' - two integers "
                        "separated by a comma. No words, no explanation.")
    coords = _extract_coords(answer) if answer else None
    if not coords:
        return (f"I scanned twice but couldn't pin '{target}' to "
                f"coordinates, sir. Try naming the exact label shown on "
                f"the control.")
    x, y = coords
    return (f"'{target}' sits at approximately ({x}, {y}) on your screen, "
            f"sir. JarvisBot draws the marker overlay at those pixel "
            f"coordinates so you can spot it instantly.")


def _exec_read_screen(app, ctx):
    b64 = take_screenshot()
    if not b64:
        return _offline_reply("transcribe every readable text block on "
                              "screen, top to bottom")
    answer = ask_vision(app, b64,
                        "Transcribe the text visible on this screen. Group "
                        "it into logical blocks (headings, paragraphs, "
                        "lists, buttons) preserving reading order. Skip "
                        "images and icons.")
    if not answer:
        return _offline_reply("transcribe every readable text block on "
                              "screen, top to bottom")
    return f"Reading your screen aloud, sir:\n\n{answer}"


def _exec_explain_screen(app, ctx):
    b64 = take_screenshot()
    if not b64:
        return _offline_reply("break the interface down into a numbered, "
                              "step-by-step tutorial for your next moves")
    answer = ask_vision(app, b64,
                        "This is the user's current screen. Explain what "
                        "they are looking at and give a numbered step-by-"
                        "step tutorial for how to proceed with the task at "
                        "hand. Reference the visible UI elements concretely.")
    if not answer:
        return _offline_reply("break the interface down into a numbered, "
                              "step-by-step tutorial for your next moves")
    return f"Here's my step-by-step walkthrough of your screen, sir:\n\n{answer}"


def _exec_watch_start(app, ctx):
    global _watcher_thread
    if os.environ.get("JARVIS_TEST") == "1":
        return ("Screen-watch is disabled in this test environment "
                "(JARVIS_TEST=1), sir. Ordinarily I'd snapshot your display "
                "every 30 seconds and keep a running digest.")
    with _watch_lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            return "I'm already watching your screen, sir."
        _watcher_stop.clear()
        thread = threading.Thread(target=_watch_loop, args=(app,),
                                  name="jarvis-screen-watch", daemon=True)
        _watcher_thread = thread
        thread.start()
    return ("Engaged, sir. I'm watching your screen and noting a digest "
            "every 30 seconds. Say 'stop watching' whenever you want me to "
            "look away.")


def _exec_watch_stop(app, ctx):
    global _watcher_thread
    with _watch_lock:
        was_running = _watcher_thread is not None and _watcher_thread.is_alive()
        _watcher_stop.set()
        thread = _watcher_thread
        _watcher_thread = None
    if thread is not None:
        thread.join(timeout=3.0)
    if was_running:
        return ("Standing down, sir - screen-watch is stopped. My last "
                "observation remains available via 'screen digest'.")
    return "I wasn't watching anything, sir, but consider it doubly stopped."


def _exec_screen_digest(app, ctx):
    with _watch_lock:
        digest = LAST_DIGEST
    if not digest:
        return ("Nothing in my screen journal yet, sir. Say 'watch my "
                "screen' and I'll observe quietly every 30 seconds; ask "
                "for the digest again afterwards.")
    return f"Latest from my screen watch, sir:\n{digest}"


# ==========================================================================
# Detectors
# ==========================================================================

def _det_whats_on_screen(cmd):
    if re.search(r"what'?s on my screen|look at my screen|see my screen",
                 cmd, re.I):
        return {"kind": "whats_on_screen"}
    return None


def _det_where_is(cmd):
    m = re.search(r"\bwhere(?:'s|\s+is)\s+(.+)$", cmd, re.I)
    if m:
        raw = re.sub(r"\s+on\s+(?:my|the)\s+screen\s*[?.!]?\s*$", "",
                     m.group(1), flags=re.I)
    else:
        m = re.search(r"\b(?:find|locate)\s+(.+?)\s+on\s+(?:my|the)\s+screen",
                      cmd, re.I)
        if not m:
            return None
        raw = m.group(1)
    target = _clean_target(raw)
    if not target or len(target) < 2:
        return None
    return {"kind": "where_is", "target": target}


def _det_read_screen(cmd):
    if re.search(r"(?:read|transcribe)\s+(?:my|this|the)\s+screen"
                 r"(?:\s+aloud)?|read\s+(?:my|the)\s+screen\s+aloud",
                 cmd, re.I):
        return {"kind": "read_screen"}
    return None


def _det_explain_screen(cmd):
    if re.search(r"explain what i'?m looking at|help me with this screen"
                 r"|walk me through (?:this|my) screen"
                 r"|step[- ]by[- ]step (?:guide|tutorial) for this screen",
                 cmd, re.I):
        return {"kind": "explain_screen"}
    return None


def _det_watch_start(cmd):
    if re.search(r"\b(?:stop|cancel|quit|pause|don'?t)\b", cmd, re.I):
        return None
    if re.search(r"\b(?:watch|monitor)\s+my\s+screen\b"
                 r"|\b(?:start|begin)\s+watching\b"
                 r"|keep an eye on my screen", cmd, re.I):
        return {"kind": "watch_start"}
    return None


def _det_watch_stop(cmd):
    if re.search(r"\bstop\s+(?:watching|watch)(?:\s+(?:my|the)\s+screen)?\b"
                 r"|\bstop monitoring\b", cmd, re.I):
        return {"kind": "watch_stop"}
    return None


def _det_screen_digest(cmd):
    if re.search(r"screen\s+digest|catch me up on (?:my |the )?screen",
                 cmd, re.I):
        return {"kind": "screen_digest"}
    return None


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS = (
    ("ls_whats_on_screen", _det_whats_on_screen, _exec_whats_on_screen, False),
    ("ls_where_is", _det_where_is, _exec_where_is, False),
    ("ls_read_screen", _det_read_screen, _exec_read_screen, False),
    ("ls_explain_screen", _det_explain_screen, _exec_explain_screen, False),
    ("ls_watch_stop", _det_watch_stop, _exec_watch_stop, False),
    ("ls_watch_start", _det_watch_start, _exec_watch_start, False),
    ("ls_screen_digest", _det_screen_digest, _exec_screen_digest, False),
)


def _wrap(execute, name):
    def safe(app, ctx):
        try:
            return _persona_safe(str(execute(app, ctx)))
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            pretty = name.replace("ls_", "").replace("_", " ")
            return _persona_safe(f"My {pretty} module misfired: {exc}")
    safe.__name__ = f"safe_{name}"
    return safe


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register every live-screen skill with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("live screen brain registered (%d skills)", len(_SKILLS))


if __name__ == "__main__":
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
