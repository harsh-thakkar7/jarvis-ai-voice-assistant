"""JARVIS DAILY BRIEFING SKILL PACK: one spoken summary of your day.

Composes a single reply from four independent ingredients:

    - date/time  : local clock (stdlib datetime)
    - weather    : main.get_weather(location) - lazy import, never raises
    - calendar   : today's Apple Calendar events via osascript
    - mail       : unread count from Mail.app via osascript

Each ingredient fails soft: if its source is offline or unavailable that
section is skipped and the rest of the briefing still ships. If EVERY
source fails, JARVIS falls back to one short offline-friendly line.

Two skills, one shared executor:

    - br_briefing   : "good morning jarvis" / "brief me" /
                      "daily briefing" / "start my day"
    - br_day_digest : "summarize my day" / "what's my agenda"

Both register with priority=True so the briefing outranks generic
handlers (brain.py owns a bare "summarize ..." skill).

Collision safety: detectors require briefing-specific phrases; a bare
"weather", "calendar", "mail", "news" or "remind" command never matches.

OS touchpoints are the ``_run_osascript`` seam (AppleScript) and the
``_fetch_weather`` seam (main.get_weather), which tests monkeypatch.
main is imported lazily inside ``_fetch_weather`` so importing this
module stays cheap and side-effect free.
"""

from __future__ import annotations

import platform
import re
import subprocess
from datetime import datetime

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("briefing_brain")

IS_DARWIN = platform.system() == "Darwin"

OSA_TIMEOUT = 15.0
MAX_EVENTS_SPOKEN = 3       # cap calendar entries in one breath

# ==========================================================================
# USER-EDITABLE: fallback city for the weather line. main.py asks the user
# for a city when none is spoken; a briefing cannot stop and ask, so set
# your home town here (e.g. "Malibu"). Leave "" to skip weather unless the
# command names one ("brief me in Malibu").
# ==========================================================================
DEFAULT_LOCATION: str = ""


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _now() -> datetime:
    """Clock seam so tests can freeze the briefing timestamp."""
    return datetime.now()


def _fetch_weather(location: str) -> str | None:
    """Thin seam over main.get_weather; any failure becomes None."""
    try:
        import main  # lazy: keeps module import light, mirrors main only here
        return main.get_weather(location)
    except Exception:  # defensive containment - weather must never sink us
        return None


def _run_osascript(script: str, timeout: float = OSA_TIMEOUT) -> tuple[int, str]:
    """Execute an AppleScript through osascript; return (code, output).

    Never raises: failures come back as a non-zero code with the stderr
    text attached, mirroring the sibling modules' subprocess seams.
    """
    if platform.system() != "Darwin":
        return 126, "osascript is macOS-only; briefing needs a Mac"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout)
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, "osascript not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:  # defensive containment
        return 1, str(exc)[:200]


# ==========================================================================
# Ingredient AppleScripts
# ==========================================================================

_EVENTS_TODAY_SCRIPT = '''
set dayStart to current date
set time of dayStart to 0
set dayEnd to current date
set time of dayEnd to 86399
set out to ""
tell application "Calendar"
\trepeat with c in calendars
\t\tset todays to (every event of c whose start date >= dayStart and start date <= dayEnd)
\t\trepeat with e in todays
\t\t\tset out to out & (time string of (start date of e)) & " | " & (summary of e) & linefeed
\t\tend repeat
\tend repeat
end tell
return out
'''.strip()

_MAIL_UNREAD_COUNT_SCRIPT = '''
tell application "Mail"
\treturn (count of (every message of inbox whose read status is false))
end tell
'''.strip()


# ==========================================================================
# Ingredients - each returns a spoken fragment, or None to skip silently
# ==========================================================================

def _greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _ing_datetime() -> str | None:
    """'Good morning, sir - it's Monday, August 24, 9:41 AM.'"""
    try:
        now = _now()
        clock = now.strftime("%I:%M %p").lstrip("0")
        return (f"{_greeting(now.hour)}, sir - it's {now:%A}, "
                f"{now:%B} {now.day}, {clock}.")
    except Exception:  # even the clock fails soft
        return None


def _ing_weather(location: str | None) -> str | None:
    if not location:
        return None          # no city spoken and no DEFAULT_LOCATION set
    text = _fetch_weather(location)
    if not text or not str(text).strip():
        return None
    return str(text).strip()


def _parse_event_rows(out: str) -> list[tuple[str, str]]:
    """'time string | summary' lines -> ordered (stamp, summary) pairs."""
    rows = []
    for line in (out or "").splitlines():
        line = line.strip()
        if "|" in line:
            stamp, _, summary = line.partition("|")
            if stamp.strip() and summary.strip():
                rows.append((stamp.strip(), summary.strip()))
    rows.sort(key=lambda pair: _event_sort_key(pair[0]))
    return rows


def _event_sort_key(stamp: str):
    """Numeric time-of-day first ('9:30 AM' beats '2:00 PM'); raw text
    as the fallback for locale formats strptime cannot read."""
    try:
        return (0, datetime.strptime(stamp, "%I:%M %p").time(), "")
    except ValueError:
        return (1, datetime.min.time(), stamp.lower())


def _ing_events() -> str | None:
    try:
        code, out = _run_osascript(_EVENTS_TODAY_SCRIPT)
    except Exception:
        return None
    if code != 0:
        return None
    rows = _parse_event_rows(out)
    if not rows:
        return "Your calendar is wide open today."
    shown = rows[:MAX_EVENTS_SPOKEN]
    listing = "; ".join(f"{stamp} {summary}" for stamp, summary in shown)
    extra = "" if len(rows) <= MAX_EVENTS_SPOKEN \
        else f" plus {len(rows) - MAX_EVENTS_SPOKEN} more"
    return (f"You have {len(rows)} event(s) today: {listing}{extra}.")


def _ing_mail() -> str | None:
    try:
        code, out = _run_osascript(_MAIL_UNREAD_COUNT_SCRIPT)
    except Exception:
        return None
    if code != 0:
        return None
    digits = re.search(r"\d+", out or "")
    if not digits:
        return None
    count = int(digits.group())
    if count == 0:
        return "Your inbox is spotless, by the way."
    return f"And {count} unread message(s) await your attention."


def _collect_parts(location: str | None) -> list[str]:
    """Assemble whichever ingredients survived, in speaking order."""
    parts = []
    for piece in (_ing_datetime(), _ing_weather(location),
                  _ing_events(), _ing_mail()):
        if piece:
            parts.append(piece)
    return parts


# ==========================================================================
# Shared executor
# ==========================================================================

_OFFLINE_LINE = ("My feed lines are all dark right now - I'll deliver "
                 "your briefing the moment systems answer, sir.")


def _e_brief(app, ctx) -> str:
    # Spoken city wins; otherwise the user-editable default (main.py asks
    # interactively for a city - a briefing cannot, so it falls back).
    location = ctx.get("loc") or DEFAULT_LOCATION or None
    parts = _collect_parts(location)
    if not parts:
        return _OFFLINE_LINE
    return " ".join(parts) + " That's the lay of the land, sir."


# ==========================================================================
# Detectors - briefing-specific phrases only; case-insensitive, tolerant
# of extra words, but blind to bare "weather"/"calendar"/"mail" talk.
# ==========================================================================

_BRIEF_RE = re.compile(
    r"\bbrief\s+(?:me|up)\b"
    r"|\bbriefings?\b"
    r"|\bgood\s+morning\b"
    r"|\bstart\s+(?:my|the)\s+day\b"
    r"|\bcatch\s+me\s+up\b", re.I)

_DIGEST_RE = re.compile(
    r"\bsummar(?:ize|ise)\s+my\s+day\b"
    r"|\bwhat'?s\s+my\s+agenda\b"
    r"|\bmy\s+agenda\b"
    r"|\bhow'?s\s+my\s+day\b"
    r"|\bmy\s+day\s+(?:ahead|look)", re.I)

# "brief me for today" must not mistake "today" for a city.
_LOC_RE = re.compile(
    r"\b(?:in|for)\s+(?P<loc>[A-Za-z][A-Za-z .'-]*?)\s*[?.!]*\s*$")
_BAD_LOC_WORDS = {
    "today", "tonight", "tomorrow", "tmrw", "morning", "afternoon",
    "evening", "day", "week", "weekend", "month", "year",
    "weather", "forecast", "me", "us", "him", "her", "them", "jarvis",
}


def _extract_loc(cmd: str) -> str | None:
    """Pull a trailing 'in/for <city>' location, rejecting time words."""
    m = _LOC_RE.search((cmd or "").strip())
    if not m:
        return None
    raw = m.group("loc")
    if set(re.findall(r"[a-z']+", raw.lower())) & _BAD_LOC_WORDS:
        return None
    loc = raw.strip(" .'-").title()
    return loc or None


def _d_briefing(cmd: str):
    if not IS_DARWIN:
        return None
    if _BRIEF_RE.search(cmd):
        return {"cmd": cmd, "loc": _extract_loc(cmd)}
    return None


def _d_digest(cmd: str):
    if not IS_DARWIN:
        return None
    if _DIGEST_RE.search(cmd):
        return {"cmd": cmd, "loc": _extract_loc(cmd)}
    return None


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("br_briefing", _d_briefing, _e_brief, True),
    ("br_day_digest", _d_digest, _e_brief, True),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register the briefing skills with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("briefing skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my briefing module "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
