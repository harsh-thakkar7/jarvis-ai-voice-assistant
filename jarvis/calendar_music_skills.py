"""JARVIS CALENDAR & MUSIC SKILLS: Apple Calendar + Spotify control.

Two families, both Darwin-only and EventKit-less (pure AppleScript):

* Apple Calendar (Calendar.app)
    - cm_events_today : list today's events (start time + summary)
    - cm_create_event : natural-date creation ("add event X tomorrow at 3pm")

* Spotify transport (falls back to Music.app when Spotify is asleep)
    - cm_play_artist  : search a playlist for ARTIST and press play
    - cm_pause        : pause / next track / previous track
    - cm_resume       : resume playback
    - cm_now_playing  : what song is playing (name + artist)

Every skill follows the Brain protocol:
    detect(cmd_lower) -> ctx dict | None
    execute(app, ctx) -> persona reply string ("..., sir.")

The only OS touchpoint is the ``_run_osascript`` seam, which tests
monkeypatch. This module never imports main.
"""

from __future__ import annotations

import platform
import re
import subprocess
from datetime import datetime, timedelta, time as dtime

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("calendar_music_skills")

IS_DARWIN = platform.system() == "Darwin"

DEFAULT_EVENT_HOUR = 9          # "add event lunch" with no time -> 09:00
TONIGHT_DEFAULT_HOUR = 19       # "tonight" with no time -> 19:00
EVENT_DURATION = timedelta(hours=1)
OSA_TIMEOUT = 15.0


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _run_osascript(script: str, timeout: float = OSA_TIMEOUT) -> tuple[int, str]:
    """Execute an AppleScript through osascript; return (code, output).

    Never raises: failures come back as a non-zero code with the stderr
    text attached, mirroring the sibling modules' subprocess seams.
    """
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
# Shared AppleScript helpers
# ==========================================================================

def _osa_quote(value: str) -> str:
    """Escape a Python string into a double-quoted AppleScript literal."""
    escaped = (str(value)
               .replace("\\", "\\\\")
               .replace('"', '\\"')
               .replace("\r", " ")
               .replace("\n", " "))
    return f'"{escaped}"'


_APP_RUNNING_MARKERS = (
    "not running",
    "can't be seen",
    "cant be seen",
    "connection is invalid",
    "invalid index",
    "-1728",
    "-600",
    "-1712",
)


def _app_not_running(code: int, out: str) -> bool:
    """True when osascript failed because the target app is unavailable."""
    if code == 0:
        return False
    low = (out or "").lower()
    return any(marker in low for marker in _APP_RUNNING_MARKERS)


def _swap_target_app(script: str, from_app: str, to_app: str) -> str:
    """Retarget an AppleScript from one music app to its twin."""
    return script.replace(f'application "{from_app}"',
                          f'application "{to_app}"')


# ==========================================================================
# Natural date/time parsing (Part A)
# ==========================================================================

_WEEKDAY_IDX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

_WHEN_RE = re.compile(
    r"\b((?:on\s+|this\s+|next\s+week|next\s+)?"
    r"(today|tonight|tomorrow|tmrw|next week|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday))\b",
    re.I,
)

_TIME_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", re.I)


def _parse_when(phrase: str, tail: str = "",
                now: datetime | None = None) -> tuple[datetime, str]:
    """Resolve a date phrase (+ optional trailing time text) to a datetime.

    Returns ``(when, relative_phrase)`` where the second element is a
    human-friendly relative label such as "today", "tomorrow" or
    "on Friday". Deterministic: pass ``now`` in tests.
    """
    now = now or datetime.now()
    p = (phrase or "").lower()

    if "tomorrow" in p or "tmrw" in p:
        day = now + timedelta(days=1)
        rel = "tomorrow"
    elif "next week" in p:
        day = now + timedelta(days=7)
        rel = f"on {day.strftime('%A')}"
    else:
        weekday = next((idx for name, idx in _WEEKDAY_IDX.items()
                        if name in p), None)
        if weekday is not None:
            delta = (weekday - now.weekday()) % 7
            if delta == 0:
                delta = 7          # "on Friday" said on a Friday => next week
            day = now + timedelta(days=delta)
            rel = f"on {day.strftime('%A')}"
        else:
            day = now
            rel = "tonight" if "tonight" in p else "today"

    hour, minute = DEFAULT_EVENT_HOUR, 0
    tm = _TIME_RE.search(tail or "")
    if tm and (tm.group(1) or tm.group(2)):
        hour = int(tm.group(1))
        minute = int(tm.group(2) or 0)
        meridiem = (tm.group(3) or "").lower().replace(".", "").strip()
        if meridiem.startswith("p"):
            hour = hour % 12 + 12
        elif meridiem.startswith("a"):
            hour = hour % 12
    elif rel == "tonight":
        hour = TONIGHT_DEFAULT_HOUR

    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    when = datetime.combine(day.date(), dtime(hour, minute))
    return when, rel


_CREATE_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"(?:please\s+)?(?:add|create|make|new)\s+(?:me\s+)?(?:an?\s+)?event"
    r"|schedule"
    r")\s+(?P<body>.+?)\s*$",
    re.I,
)


def _d_create(cmd: str):
    """Detect 'add event TITLE tomorrow at 3pm' / 'schedule X on Friday...'."""
    if not IS_DARWIN:
        return None
    m = _CREATE_PREFIX_RE.match(cmd)
    if not m:
        return None
    body = m.group("body").strip()
    wm = _WHEN_RE.search(body)
    if not wm:
        return None
    title = body[:wm.start()].strip().rstrip(",.;:- ").strip()
    if not title:
        return None
    when, rel = _parse_when(wm.group(1), body[wm.end():])
    return {"cmd": cmd, "title": title, "when": when, "rel": rel}


# ==========================================================================
# Part A - Apple Calendar (Calendar.app, EventKit-less)
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


def _d_events_today(cmd: str):
    if not IS_DARWIN:
        return None
    if re.search(r"\bwhat'?s on my calendar\b|\bmy schedule\b"
                 r"|\btoday'?s schedule\b|\bcalendar (?:for )?today\b"
                 r"|\bshow (?:my )?(?:calendar|schedule)\b", cmd, re.I):
        return {"cmd": cmd}
    return None


def _e_events_today(app, ctx) -> str:
    code, out = _run_osascript(_EVENTS_TODAY_SCRIPT)
    if code != 0:
        return f"Calendar.app refused to answer, sir: {out.splitlines()[0][:120]}"
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if "|" in line:
            stamp, _, summary = line.partition("|")
            rows.append((stamp.strip(), summary.strip()))
    if not rows:
        return "Nothing at all on your calendar today - enjoy the quiet, sir."
    rows.sort(key=lambda pair: pair[0])
    listing = "\n".join(f"\u2022 {stamp} \u2014 {summary}"
                        for stamp, summary in rows)
    return (f"You have {len(rows)} event(s) today:\n{listing}"
            f"\nA full plate indeed, sir.")


def _mkdate_handler(dt: datetime) -> str:
    """AppleScript handler args building a locale-proof date value."""
    return (f"my mkdate({dt.year}, {dt.month}, {dt.day}, "
            f"{dt.hour}, {dt.minute})")


def _create_event_script(title: str, start: datetime,
                         end: datetime) -> str:
    return f'''
on mkdate(y, mo, dy, h, mi)
\tset dt to current date
\tset day of dt to 1
\tset year of dt to y
\tset month of dt to mo as integer
\tset day of dt to dy
\tset time of dt to h * 3600 + mi * 60
\treturn dt
end mkdate
tell application "Calendar"
\tset targetCal to missing value
\trepeat with c in calendars
\t\tif writable of c is true then
\t\t\tset targetCal to c
\t\t\texit repeat
\t\tend if
\tend repeat
\tif targetCal is equal to missing value then set targetCal to first calendar
\tmake new event at end of events of targetCal with properties {{summary:{_osa_quote(title)}, start date:{_mkdate_handler(start)}, end date:{_mkdate_handler(end)}}}
\treturn "created"
end tell
'''.strip()


def _e_create(app, ctx) -> str:
    title = ctx["title"]
    when: datetime = ctx["when"]
    rel = ctx.get("rel", "today")
    code, out = _run_osascript(
        _create_event_script(title, when, when + EVENT_DURATION))
    if code != 0:
        return (f"I couldn't reach Calendar.app to book \"{title}\", sir: "
                f"{out.splitlines()[0][:120]}")
    phrase = f"{rel} ({when.strftime('%a %d %b')} at {when.strftime('%I:%M %p').lstrip('0')})"
    return f"Done \u2014 \"{title}\" is booked for {phrase}, sir."


# ==========================================================================
# Part B - Spotify control (with Music.app fallback)
# ==========================================================================

_PLAY_ARTIST_RE = re.compile(r"\bplay\s+(?P<artist>.+?)\s+on\s+spotify\b",
                             re.I)
_PAUSE_RESUME_RE = {
    "pause": re.compile(r"\b(?:pause|hold)\s+(?:the\s+)?"
                        r"(?:music|spotify|playback|song)\b", re.I),
    "next track": re.compile(
        r"\b(?:next track|skip\s+(?:this\s+|the\s+)?(?:track|song)|"
        r"play the next\s+(?:track|song))\b", re.I),
    "previous track": re.compile(
        r"\b(?:previous track|go back(?:\s+to)?\s+(?:the\s+)?"
        r"(?:last|previous)\s+(?:track|song))\b", re.I),
}
_RESUME_RE = re.compile(r"\b(?:resume|unpause)\s+(?:the\s+)?"
                        r"(?:music|spotify|playback|song)\b", re.I)
_NOW_PLAYING_RE = re.compile(
    r"\b(?:what song(?:'s|\s+is)?\s+(?:currently\s+)?playing"
    r"|what'?s playing|now playing|which song is this"
    r"|what is this song)\b", re.I)


def _transport_script(target_app: str, verb: str) -> str:
    return f'tell application "{target_app}"\n{verb}\nend tell'


_PLAY_ARTIST_SCRIPT = '''
tell application "Spotify"
\tset hits to (every playlist whose name contains {artist})
\tif (count of hits) > 0 then
\t\tplay item 1 of hits
\t\treturn "played"
\telse
\t\tactivate
\t\tdelay 1
\t\tplay track (item 1 of (every track whose artist contains {artist}))
\t\treturn "played"
\tend if
end tell
'''.strip()


def _d_play_artist(cmd: str):
    if not IS_DARWIN:
        return None
    m = _PLAY_ARTIST_RE.search(cmd)
    if not m:
        return None
    return {"cmd": cmd, "artist": m.group("artist").strip()}


def _e_play_artist(app, ctx) -> str:
    artist = ctx["artist"]
    script = _PLAY_ARTIST_SCRIPT.format(artist=_osa_quote(artist))
    code, out = _run_osascript(script)
    if code == 0:
        return f"Queuing {artist} on Spotify now, sir."
    if _app_not_running(code, out):
        return ("Spotify isn't running at the moment \u2014 wake it up and "
                "I'll spin your music straight away, sir.")
    return f"Spotify balked at that request, sir: {out.splitlines()[0][:120]}"


def _d_pause(cmd: str):
    if not IS_DARWIN:
        return None
    for verb, rx in _PAUSE_RESUME_RE.items():
        if rx.search(cmd):
            return {"cmd": cmd, "verb": verb,
                    "label": {"pause": "Playback paused",
                              "next track": "Skipped to the next track",
                              "previous track": "Rewound to the previous track"}[verb]}
    return None


def _e_pause(app, ctx) -> str:
    verb, label = ctx["verb"], ctx["label"]
    script = _transport_script("Spotify", verb)
    code, out = _run_osascript(script)
    if code == 0:
        return f"{label} on Spotify, sir."
    if _app_not_running(code, out):
        code2, out2 = _run_osascript(_swap_target_app(script, "Spotify", "Music"))
        if code2 == 0:
            return f"{label} \u2014 routed through Music.app instead, sir."
        return ("Spotify isn't running and Music.app wouldn't answer either "
                "- I'd suggest launching Spotify, sir.")
    return f"The transport controls jammed, sir: {out.splitlines()[0][:120]}"


def _d_resume(cmd: str):
    if not IS_DARWIN:
        return None
    if _RESUME_RE.search(cmd):
        return {"cmd": cmd, "verb": "play"}
    return None


def _e_resume(app, ctx) -> str:
    return _e_pause(app, {"verb": ctx["verb"],
                          "label": "Resuming playback"})


_NOW_PLAYING_SCRIPT = '''
tell application "Spotify"
\tif player state is stopped then return "silence"
\treturn (name of current track) & " - " & (artist of current track)
end tell
'''.strip()


def _parse_now_playing(raw: str) -> tuple[str, str]:
    """Split 'Song - Artist' (first separator wins)."""
    song, _, artist = (raw or "").strip().partition(" - ")
    return song.strip(), artist.strip()


def _d_now_playing(cmd: str):
    if not IS_DARWIN:
        return None
    if _NOW_PLAYING_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_now_playing(app, ctx) -> str:
    script = _NOW_PLAYING_SCRIPT
    code, out = _run_osascript(script)
    if _app_not_running(code, out):
        code2, out2 = _run_osascript(
            _swap_target_app(script, "Spotify", "Music"))
        if code2 == 0:
            song, artist = _parse_now_playing(out2)
            if song and song.lower() != "silence":
                return (f"Now spinning \"{song}\" by {artist} "
                        f"(via Music.app), sir.")
        return ("Spotify isn't running at the moment, sir \u2014 start it "
                "up and I'll tell you what's on the decks.")
    if code != 0:
        return f"I couldn't read Spotify's mind, sir: {out.splitlines()[0][:120]}"
    raw = out.strip()
    if raw.lower() == "silence":
        return "Spotify is sitting in silence right now, sir."
    song, artist = _parse_now_playing(raw)
    if not song:
        return "Something is playing, but the metadata came back garbled, sir."
    return f"Now spinning \"{song}\" by {artist}, sir."


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("cm_events_today", _d_events_today, _e_events_today, False),
    ("cm_create_event", _d_create, _e_create, False),
    ("cm_play_artist", _d_play_artist, _e_play_artist, True),
    ("cm_pause", _d_pause, _e_pause, False),
    ("cm_resume", _d_resume, _e_resume, False),
    ("cm_now_playing", _d_now_playing, _e_now_playing, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all calendar/music skills with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("calendar/music skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my {name.replace('cm_', '')} "
                    f"module ({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
