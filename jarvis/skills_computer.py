"""JARVIS COMPUTER-CONTROL SKILL PACK: hands on the user's own Mac.

Sixteen fail-soft skills that let JARVIS actually drive the machine it
runs on: launch any installed app by fuzzy name, open bare URLs, click,
type and press keys, capture the screen, run (rail-guarded) shell
commands, and read back volume, brightness, window focus, Trash moves
and display bounds. Skills prefixed ``cp_``:

    - cp_open_url      : "open example.com" / "go to docs.python.org" /
                         a bare "example.com" -> LaunchServices ``open``
                         (no AppleEvent permission needed). Only fires on
                         bare domains/URLs, never search phrases.
    - cp_open_app      : "open slack" / "launch discord" / "start spotify"
                         -> ANY app, resolved by fuzzy name via Spotlight
                         (``mdfind "kMDItemKind == 'Application'"``) with
                         an /Applications walk as fallback, ranked with
                         difflib, launched with ``open -a``. Not-found is
                         reported honestly. Registered with priority=False
                         so main.py's static APP_MAP open handler (which
                         runs at app level, before the brain) is never
                         shadowed; brain.py's priority open_folder skill
                         keeps folders.
    - cp_click         : "click at 500 400" / "click center" ->
                         pyautogui when importable, else osascript
                         "click at {x, y}". Words like "center" / "top
                         left" map to screen-size fractions (never the
                         exact corners: pyautogui's failsafe lives there).
    - cp_double_click  : "double click 120 80" / bare "double click".
    - cp_right_click   : "right click 300 200" / bare "right click".
    - cp_drag          : "drag from 100 200 to 300 400" / "drag 50 100"
                         (a relative nudge from the pointer) ->
                         pyautogui press-drag via mouseDown / moveTo /
                         mouseUp; same-point and off-screen drags refused
                         honestly. osascript cannot drag the mouse, so
                         pyautogui is required.
    - cp_type          : "type hello world" -> pyautogui.write with an
                         interval, fallback osascript keystroke. Capped
                         at ~500 chars with an honest message beyond.
    - cp_press         : "press enter", "press cmd+s", "press shift tab"
                         -> pyautogui.hotkey/press, fallback osascript
                         key codes. Unknown key names never match.
    - cp_screenshot    : "take a screenshot", "screenshot to /tmp/x.png"
                         -> ``screencapture -x`` or pyautogui; reports the
                         saved path and never uploads anything. This pack
                         supersedes brain_extra's legacy unanchored
                         "screenshot" skill (it claimed ANY message
                         containing the word and ignored explicit paths)
                         via brain.py's documented ``supersedes`` lane.
    - cp_run           : "run shell command <cmd>" / "run <cmd>" (the
                         bare form must pass a shell-ish whitelist).
                         subprocess, timeout=15, output truncated to
                         ~1200 chars, exit code reported honestly.
                         HARD SAFETY RAIL refuses sudo, rm -rf on / or
                         $HOME, diskutil erase, mkfs, shutdown/reboot,
                         killall of system processes / force kills and
                         raw /dev writes with a one-line refusal;
                         override only via JARVIS_ALLOW_DESTRUCTIVE=1.
    - cp_volume        : "set volume to 40", "volume up", "mute the
                         volume" -> osascript volume settings. Stands
                         down on "volume of a cylinder" math talk.
    - cp_brightness    : "brightness 70", "brightness up" -> absolute
                         level via guarded Quartz (pyobjc), relative
                         nudges via the brightness key codes; honest
                         refusal when the Mac locks absolute control.
    - cp_frontmost     : "what window is focused", "what am i looking
                         at" -> frontmost app + window title via the
                         osascript System Events idiom.
    - cp_quit          : "quit slack" / "close spotify" -> osascript
                         tell-app-to-quit. brain.py's quit_app (cached
                         QUIT_MAP, registered first) normally answers
                         these first; this is the standalone / fallback
                         lane and checks the app is running before
                         touching it.
    - cp_trash_file    : "trash /path" / "move X to the trash" -> move to
                         ~/.Trash with collision-safe naming; refuses
                         paths outside $HOME unless
                         JARVIS_ALLOW_DESTRUCTIVE=1. file_power's delete
                         skill (loaded earlier) owns "trash <path>" in
                         the full brain; this adds the move-to-trash
                         phrasing and the home-containment rail.
    - cp_screen_size   : "screen size", "what is my screen resolution"
                         -> display bounds via pyautogui or Finder.

Collisions: every detector is anchored and demands command-shaped input
(mirroring skills_games.gm_move's discipline): ordinary sentences like
"type 2 diabetes", "run 5 miles", "click on the submit button", "volume
of a cylinder" or "open it" simply do not match. No persistent state is
required, so there is deliberately no state file. Pure stdlib plus
optional pyautogui/pyobjc imports guarded at call time. No UI code, no
network uploads, this module never imports main.
"""

from __future__ import annotations

import difflib
import os
import platform
import re
import shutil
import subprocess
import threading
import time

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("skills_computer")

# ==========================================================================
# Tunables
# ==========================================================================

TYPE_MAX_CHARS = 500            # cp_type cap; beyond -> honest message
TYPE_INTERVAL = 0.01            # seconds between typed keys
RUN_TIMEOUT_S = 15              # cp_run hard timeout
RUN_OUTPUT_CAP = 1200           # combined stdout+stderr truncation
APP_MATCH_CUTOFF = 0.42         # min fuzzy score before "not found"
APP_CACHE_TTL = 120.0           # seconds to trust the Spotlight listing
MAX_REL_BRIGHTNESS_STEPS = 16   # cap for brightness nudges

_ACCESS_MSG = ("I need Accessibility permission for that, sir. System "
               "Settings, Privacy and Security, Accessibility.")
_AUTOMATION_MSG = ("I need Automation permission for System Events, sir. "
                   "System Settings, Privacy and Security, Automation.")
_SCREEN_MSG = ("I could not capture the screen, sir. If it stays dark, "
               "grant Screen Recording under System Settings, Privacy and "
               "Security, Screen Recording.")

# ==========================================================================
# Shared plumbing: osascript / pyautogui with fail-soft permission hints
# ==========================================================================

def _is_mac() -> bool:
    return platform.system() == "Darwin"


def _run_osascript(script: str, timeout: int = 10) -> tuple[bool, str]:
    """Run one osascript line. Returns (ok, stdout-or-stderr)."""
    if not _is_mac():
        return False, "macOS only"
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=timeout)
    except Exception as exc:                      # timeout, missing binary
        log.debug("osascript failed: %s", exc)
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stderr or "").strip()
    return True, (r.stdout or "").strip()


def _permission_hint(err_text: str) -> str:
    """Map a raw AppleScript error to one helpful line, or ''."""
    low = (err_text or "").lower()
    if "assistive access" in low or "accessibility" in low:
        return " " + _ACCESS_MSG
    if "not allowed to send apple events" in low or "authorized" in low:
        return " " + _AUTOMATION_MSG
    return ""


def _pyautogui():
    """Import pyautogui lazily; None when unavailable (fail-soft)."""
    try:
        import pyautogui
        return pyautogui
    except Exception as exc:
        log.debug("pyautogui unavailable: %s", exc)
        return None


def _screen_size() -> tuple[int, int] | None:
    """(width, height) of the main display, best-effort."""
    pg = _pyautogui()
    if pg is not None:
        try:
            size = pg.size()
            w, h = int(size.width), int(size.height)
            if w > 0 and h > 0:
                return w, h
        except Exception as exc:
            log.debug("pyautogui.size failed: %s", exc)
    ok, out = _run_osascript(
        'tell application "Finder" to get bounds of window of desktop')
    if ok:
        nums = re.findall(r"-?\d+", out)
        if len(nums) >= 4:
            w, h = int(nums[2]), int(nums[3])
            if w > 0 and h > 0:
                return w, h
    return None


def _as_str(s: str) -> str:
    """Escape a Python string into an AppleScript double-quoted literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Politeness prefix shared by the anchored detectors. Deliberately narrow:
# "hey/ok/okay/please/jarvis" only, so ordinary sentences never pre-match.
_POLITE = r"(?:hey\s+|ok\s+|okay\s+|please\s+|jarvis\s*[,.:]\s*)*"


# ==========================================================================
# cp_open_url - bare domains and URLs only
# ==========================================================================

_OPEN_URL_RE = re.compile(
    r"^" + _POLITE + r"(?:open|launch|go\s+to|visit|browse)\s+"
    r"(?:the\s+|my\s+)?(?:website\s+|web\s+site\s+|site\s+|url\s+)?"
    r"(?P<url>\S+)\s*$", re.I)
_DOMAIN_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+"
    r"(?::\d{2,5})?(?:/\S*)?$", re.I)
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


def _d_open_url(cmd: str):
    c = (cmd or "").strip().rstrip(".!?").strip()
    if not c or len(c) > 300:
        return None
    m = _OPEN_URL_RE.match(c)
    if m:
        url = m.group("url").strip(".,")
    elif re.fullmatch(r"\S+", c):
        url = c.strip(".,")          # bare domain typed on its own
    else:
        return None
    if not url or " " in url:
        return None
    if _SCHEME_RE.match(url):
        return {"url": url}
    if _DOMAIN_RE.match(url) and re.search(r"[a-z]", url.rsplit(".", 1)[-1]):
        # TLD must contain a letter: "5.5" is arithmetic, not a host.
        return {"url": "https://" + url}
    return None


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).netloc or url
    except Exception:
        return url


def _e_open_url(app, ctx) -> str:
    url = str(ctx["url"])[:2048]
    if _is_mac():
        # LaunchServices `open` honors the default browser and needs no
        # per-app AppleEvent permission (same idiom as main.py).
        try:
            r = subprocess.run(["open", url], capture_output=True,
                               timeout=15)
            if r.returncode == 0:
                return "Opening %s in your browser, sir." % _host_of(url)
        except Exception as exc:
            log.debug("open url failed: %s", exc)
        return "I could not open %s, sir." % _host_of(url)
    try:
        import webbrowser
        webbrowser.open(url)
        return "Opening %s, sir." % _host_of(url)
    except Exception:
        return "I could not open %s, sir." % _host_of(url)


# ==========================================================================
# cp_open_app - fuzzy ANY-app launch via Spotlight
# ==========================================================================

_OPEN_APP_RE = re.compile(
    r"^" + _POLITE + r"(?:open|launch|start|fire\s+up)\s+"
    r"(?:the\s+|my\s+)?"
    r"(?P<target>[a-z0-9][a-z0-9 .,'+&!-]{0,39}?)\s*[.!?]?$", re.I)

# Words that are never app names: ordinary chat or other skills' ground.
_OPEN_STOP = {"it", "this", "that", "them", "there", "here", "up", "over",
              "again", "now", "today", "me", "you", "us", "one", "thing",
              "window", "door", "gate", "book", "file", "files", "folder",
              "document", "documents", "link", "page", "site", "website",
              "url", "app", "the app"}
_FOLDER_WORDS_RE = re.compile(
    r"^(?:downloads|documents|desktop|pictures|movies|music|applications|"
    r"apps|library)$", re.I)
_TIMER_WORDS_RE = re.compile(
    r"^(?:a\s+|an\s+|the\s+)?(?:timer|alarm|reminder|stopwatch|countdown)\b",
    re.I)
_DOMAIN_ONLY_RE = re.compile(
    r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d+)?(?:/\S*)?$", re.I)

_app_cache: dict = {"when": 0.0, "apps": []}
_app_cache_lock = threading.Lock()


def _installed_apps() -> list[tuple[str, str]]:
    """[(display_name, path)] for every .app Spotlight knows (cached)."""
    now = time.time()
    with _app_cache_lock:
        if _app_cache["apps"] and now - _app_cache["when"] < APP_CACHE_TTL:
            return list(_app_cache["apps"])
    paths: list[str] = []
    if _is_mac():
        try:
            r = subprocess.run(
                ["mdfind", "kMDItemKind == 'Application'"],
                capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                paths = [ln.strip() for ln in r.stdout.splitlines()
                         if ln.strip().endswith(".app")]
        except Exception as exc:
            log.debug("mdfind failed: %s", exc)
    if not paths:                     # fail-soft fallback: walk the roots
        for root in ("/Applications", "/System/Applications",
                     os.path.expanduser("~/Applications")):
            try:
                for name in os.listdir(root):
                    if name.endswith(".app"):
                        paths.append(os.path.join(root, name))
            except Exception:
                continue
    apps: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        name = os.path.basename(path)[:-4]
        if name and path not in seen:
            seen.add(path)
            apps.append((name, path))
    with _app_cache_lock:
        _app_cache["apps"] = apps
        _app_cache["when"] = now
    return apps


def _rank_apps(query: str) -> list[tuple[float, str, str]]:
    """Rank installed apps against a spoken name, best first."""
    q_compact = re.sub(r"[^a-z0-9]", "", query.lower())
    q_tokens = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if t}
    scored: list[tuple[float, str, str]] = []
    for name, path in _installed_apps():
        n_compact = re.sub(r"[^a-z0-9]", "", name.lower())
        score = difflib.SequenceMatcher(None, q_compact, n_compact).ratio()
        if q_compact and q_compact == n_compact:
            score += 0.35
        elif q_compact and q_compact in n_compact:
            score += 0.20
        n_tokens = {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}
        if q_tokens and q_tokens <= n_tokens:
            score = max(score, 0.0) + 0.25
        scored.append((score, name, path))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored


def _d_open_app(cmd: str):
    m = _OPEN_APP_RE.match((cmd or "").strip())
    if not m:
        return None
    target = m.group("target").strip(" .,")
    low = target.lower()
    if not target or low in _OPEN_STOP:
        return None
    if _FOLDER_WORDS_RE.match(low):
        return None                    # brain.py open_folder owns folders
    if _TIMER_WORDS_RE.match(low):
        return None                    # timers/alarm packs own those
    if _DOMAIN_ONLY_RE.match(low):
        return None                    # cp_open_url owns bare domains
    return {"target": target}


def _e_open_app(app, ctx) -> str:
    target = ctx["target"]
    ranked = _rank_apps(target)
    if not ranked:
        return ("I could not scan the installed applications, sir - "
                "Spotlight returned nothing.")
    score, name, path = ranked[0]
    if score < APP_MATCH_CUTOFF:
        near = ", ".join(n for _, n, _ in ranked[:3])
        return ("I could not find an application called '%s', sir. "
                "Closest I have: %s." % (target, near))
    try:
        # `open -a <name-or-path>` goes through LaunchServices, exactly
        # like main.py's static-map handler - no AppleEvent permission.
        args = ["open", "-a", path if path.startswith("/") else name]
        r = subprocess.run(args, capture_output=True, timeout=15)
        ok = r.returncode == 0
    except Exception as exc:
        log.debug("open -a failed: %s", exc)
        ok = False
    if ok:
        return "Opening %s, sir." % name
    return "I found %s but could not launch it, sir." % name


# ==========================================================================
# cp_click / cp_double_click / cp_right_click - pointer control
# ==========================================================================

# Position words -> screen-size fractions. Never the exact corners:
# pyautogui's failsafe trips at (0, 0) style coordinates.
_POSITION_WORDS: dict[str, tuple[float, float]] = {
    "center": (0.50, 0.50), "centre": (0.50, 0.50), "middle": (0.50, 0.50),
    "top": (0.50, 0.20), "bottom": (0.50, 0.80),
    "left": (0.20, 0.50), "right": (0.80, 0.50),
    "top left": (0.20, 0.20), "top center": (0.50, 0.20),
    "top centre": (0.50, 0.20), "top right": (0.80, 0.20),
    "bottom left": (0.20, 0.80), "bottom center": (0.50, 0.80),
    "bottom centre": (0.50, 0.80), "bottom right": (0.80, 0.80),
    "upper left": (0.20, 0.20), "upper right": (0.80, 0.20),
    "lower left": (0.20, 0.80), "lower right": (0.80, 0.80),
}

_CLICK_POLITE = r"^(?:please\s+|jarvis\s*[,.:]\s*)*"
_DBLCLICK_RE = re.compile(
    _CLICK_POLITE + r"double[ -]?click(?:\s+at|\s+on)?"
    r"(?:\s+(?P<pos>.+?))?\s*$", re.I)
_RCLICK_RE = re.compile(
    _CLICK_POLITE + r"right[ -]?click(?:\s+at|\s+on)?"
    r"(?:\s+(?P<pos>.+?))?\s*$", re.I)
_CLICK_RE = re.compile(
    _CLICK_POLITE + r"(?:left\s+|single\s+)?click(?:\s+at)?"
    r"(?:\s+(?P<pos>.+?))?\s*$", re.I)
_COORDS_RE = re.compile(r"^(-?\d{1,5})\s*[,\s]\s*(-?\d{1,5})$")


def _parse_position(raw: str | None) -> tuple[int, int] | None:
    """'500 400' | '500, 400' | 'center' | 'top left' -> (x, y), or None."""
    if not raw:
        return None
    screen = _screen_size()
    if not screen:
        return None
    w, h = screen
    text = re.sub(r"[-_]+", " ", raw.strip().lower()).strip(" .,")
    text = re.sub(r"^(?:the\s+|at\s+|on\s+)", "", text)
    m = _COORDS_RE.match(text)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        return max(0, min(w - 1, x)), max(0, min(h - 1, y))
    if text in _POSITION_WORDS:
        fx, fy = _POSITION_WORDS[text]
        return int(w * fx), int(h * fy)
    return None


def _d_click_generic(cmd: str, pattern, kind: str, require_pos: bool):
    m = pattern.match((cmd or "").strip())
    if not m:
        return None
    raw = m.group("pos")
    if raw:
        pos = _parse_position(raw)
        if pos is None:
            return None                # "click on the submit button" etc.
    elif require_pos:
        return None                    # bare "click" stays ambiguous
    else:
        pos = None                     # bare double/right click: in place
    return {"kind": kind, "pos": pos}


def _d_double_click(cmd: str):
    return _d_click_generic(cmd, _DBLCLICK_RE, "double", require_pos=False)


def _d_right_click(cmd: str):
    return _d_click_generic(cmd, _RCLICK_RE, "right", require_pos=False)


def _d_click(cmd: str):
    return _d_click_generic(cmd, _CLICK_RE, "left", require_pos=True)


def _osascript_click(x: int, y: int) -> tuple[bool, str]:
    ok, out = _run_osascript(
        'tell application "System Events" to click at {%d, %d}' % (x, y))
    if not ok:
        hint = _permission_hint(out)
        return False, hint or (" I could not click there, sir (%s)."
                               % out[:100])
    return True, ""


def _e_click(app, ctx) -> str:
    kind, pos = ctx["kind"], ctx.get("pos")
    pg = _pyautogui()
    if pos is None and pg is None:
        return ("I need a position like 'click at 500 400' for that, sir - "
                "my fallback layer cannot find the mouse without "
                "pyautogui.")
    try:
        if pg is not None:
            if pos is None:
                if kind == "double":
                    pg.doubleClick()
                elif kind == "right":
                    pg.rightClick()
                else:
                    pg.click()
            else:
                x, y = pos
                if kind == "double":
                    pg.click(x=x, y=y, clicks=2, interval=0.08)
                elif kind == "right":
                    pg.click(x=x, y=y, button="right")
                else:
                    pg.click(x=x, y=y)
            label = {"left": "Clicked", "double": "Double-clicked",
                     "right": "Right-clicked"}[kind]
            where = "at %d, %d" % pos if pos else "at the pointer"
            return "%s %s, sir." % (label, where)
        if pos is None:
            return ("I need pyautogui for pointer-relative clicks, sir - "
                    "it is not importable right now.")
        x, y = pos
        if kind != "left":
            return ("My osascript fallback can only single-click, sir - "
                    "install pyautogui for %s clicks." % kind)
        ok, extra = _osascript_click(x, y)
        if not ok:
            return extra.lstrip()
        return "Clicked at %d, %d, sir." % (x, y)
    except Exception as exc:
        if type(exc).__name__ == "FailSafeException":
            return ("I pulled up short at the screen corner, sir - "
                    "pyautogui's failsafe refuses clicks there. Pick a "
                    "point away from the very edges.")
        log.exception("click failed")
        hint = _permission_hint(str(exc))
        return (hint.lstrip() if hint else
                "The click did not land, sir (%s)." % str(exc)[:100])


# ==========================================================================
# cp_drag - press-and-drag the pointer via pyautogui
# ==========================================================================

_DRAG_REL_RE = re.compile(
    _CLICK_POLITE + r"drag\s+(?P<rel>\d{1,5}\s*[,\s]\s*\d{1,5})\s*[.!?]?$",
    re.I)
_DRAG_ABS_RE = re.compile(
    _CLICK_POLITE + r"drag\s+"
    r"(?:(?:the|my|this|that|some)\s+(?:icon|file|window|folder|item|"
    r"thing|object|element|selection|card|widget|app)s?\s+)?"
    r"(?:from\s+)?(?P<from_pos>.+?)\s+to\s+(?P<to_pos>.+?)\s*[.!?]?$",
    re.I)


def _drag_point(raw: str) -> tuple[int, int, bool] | None:
    """(x, y, within_bounds) for one drag endpoint.

    Same clamping discipline as _parse_position, but also reports whether
    the given numbers lived inside the screen so _e_drag can refuse an
    off-screen drag honestly instead of silently pinning the pointer.
    """
    if not raw:
        return None
    screen = _screen_size()
    if not screen:
        return None
    w, h = screen
    text = re.sub(r"[-_]+", " ", raw.strip().lower()).strip(" .,")
    text = re.sub(r"^(?:from\s+|the\s+|at\s+|on\s+)", "", text)
    m = _COORDS_RE.match(text)
    if m:
        x, y = int(m.group(1)), int(m.group(2))
        ok = 0 <= x < w and 0 <= y < h
        return max(0, min(w - 1, x)), max(0, min(h - 1, y)), ok
    if text in _POSITION_WORDS:
        fx, fy = _POSITION_WORDS[text]
        return int(w * fx), int(h * fy), True
    return None


def _d_drag(cmd: str):
    c = (cmd or "").strip()
    m = _DRAG_REL_RE.match(c)
    if m:
        r = _COORDS_RE.match(m.group("rel"))
        if r:
            # "drag 50 100": move +50 x +100 from the current pointer.
            return {"kind": "drag", "from": None,
                    "to": (int(r.group(1)), int(r.group(2)))}
        return None
    m = _DRAG_ABS_RE.match(c)
    if not m:
        return None
    fp = _drag_point(m.group("from_pos"))
    tp = _drag_point(m.group("to_pos"))
    if fp is None or tp is None:
        return None                    # no coordinates in the right shape
    x1, y1, inb1 = fp
    x2, y2, inb2 = tp
    if not inb1 or not inb2:
        return {"kind": "drag", "from": (x1, y1), "to": (x2, y2),
                "refuse": "off_screen"}
    if (x1, y1) == (x2, y2):
        return {"kind": "drag", "from": (x1, y1), "to": (x2, y2),
                "refuse": "same_point"}
    return {"kind": "drag", "from": (x1, y1), "to": (x2, y2)}


def _e_drag(app, ctx) -> str:
    refuse = ctx.get("refuse")
    if refuse == "same_point":
        return ("Those two points are the same spot, sir - a drag needs "
                "a start and a finish somewhere else.")
    if refuse == "off_screen":
        return ("That drag leaves the display, sir - I only press-and-"
                "drag within your screen bounds.")
    rel = ctx.get("from") is None
    pg = _pyautogui()
    if pg is None:
        return ("I need pyautogui to press-and-drag the mouse, sir - "
                "osascript cannot drag, and it is not importable right "
                "now.")
    try:
        if rel:
            x, y = pg.position()
            dx, dy = ctx["to"]
            x2, y2 = int(x + dx), int(y + dy)
        else:
            x, y = ctx["from"]
            x2, y2 = ctx["to"]
            pg.moveTo(x, y, duration=0.2)
        pg.mouseDown()
        pg.moveTo(x2, y2, duration=0.3)
        pg.mouseUp()
        return "Dragged from %d, %d to %d, %d, sir." % (x, y, x2, y2)
    except Exception as exc:
        if type(exc).__name__ == "FailSafeException":
            return ("I pulled up short at the screen corner, sir - "
                    "pyautogui's failsafe refuses drags there. Pick "
                    "points away from the very edges.")
        log.exception("drag failed")
        hint = _permission_hint(str(exc))
        return (hint.lstrip() if hint else
                "The drag did not land, sir (%s)." % str(exc)[:100])


# ==========================================================================
# cp_type - type text into the frontmost app
# ==========================================================================

_TYPE_RE = re.compile(
    r"^(?:please\s+|jarvis\s*[,.:]\s*)*type\s+(?P<text>.+?)\s*$", re.I)
_TYPE_MEDICAL_RE = re.compile(r"^type\s+[12]\s+diabet", re.I)


def _d_type(cmd: str):
    c = (cmd or "").strip()
    if _TYPE_MEDICAL_RE.match(c):
        return None                    # "type 2 diabetes" is chat, not keys
    m = _TYPE_RE.match(c)
    if not m:
        return None
    text = re.sub(r"\s*[.!?]+$", "", m.group("text")).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if not text:
        return None
    return {"text": text, "too_long": len(text) > TYPE_MAX_CHARS}


def _e_type(app, ctx) -> str:
    if ctx.get("too_long"):
        return ("That passage is %d characters, sir - I cap typing at %d. "
                "Send it in pieces, or paste it yourself."
                % (len(ctx["text"]), TYPE_MAX_CHARS))
    text = ctx["text"][:TYPE_MAX_CHARS]
    pg = _pyautogui()
    if pg is not None:
        try:
            pg.write(text, interval=TYPE_INTERVAL)
            return "Typed, sir. Mind where the cursor lives."
        except Exception as exc:
            hint = _permission_hint(str(exc))
            if hint:
                return hint.lstrip()
            log.debug("pyautogui.write failed: %s", exc)
    lines = text.split("\n")
    steps = []
    for i, line in enumerate(lines):
        if i:
            steps.append('key code 36')           # return between lines
        if line:
            steps.append("keystroke %s" % _as_str(line))
    ok, out = _run_osascript("tell application \"System Events\"\n"
                             + "\n".join(steps) + "\nend tell")
    if ok:
        return "Typed, sir. Mind where the cursor lives."
    hint = _permission_hint(out)
    return (hint.lstrip() if hint else
            "I could not type that, sir (%s)." % out[:100])


# ==========================================================================
# cp_press - key presses and combos
# ==========================================================================

_PGA_KEY_ALIASES: dict[str, str] = {
    "enter": "enter", "return": "enter", "cmd": "command",
    "command": "command", "ctl": "ctrl", "ctrl": "ctrl", "control": "ctrl",
    "alt": "option", "opt": "option", "option": "option", "shift": "shift",
    "esc": "esc", "escape": "esc", "space": "space", "spacebar": "space",
    "tab": "tab", "backspace": "backspace", "delete": "delete",
    "del": "delete", "forwarddelete": "delete", "up": "up", "down": "down",
    "left": "left", "right": "right", "home": "home", "end": "end",
    "pageup": "pageup", "pagedown": "pagedown", "pgup": "pageup",
    "pgdn": "pagedown", "capslock": "capslock", "mute": "volumemute",
    "volumeup": "volumeup", "volumedown": "volumedown",
    "volumemute": "volumemute", "play": "playpause",
    "playpause": "playpause", "pause": "playpause",
    "next": "nexttrack", "nexttrack": "nexttrack",
    "previous": "previoustrack", "previoustrack": "previoustrack",
    "stop": "stop",
}
for _i in range(1, 13):
    _PGA_KEY_ALIASES["f%d" % _i] = "f%d" % _i
for _ch in "abcdefghijklmnopqrstuvwxyz0123456789":
    _PGA_KEY_ALIASES[_ch] = _ch

_AS_KEY_CODES: dict[str, int] = {
    "enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51,
    "delete": 51, "forwarddelete": 117, "esc": 53, "escape": 53,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126, "capslock": 57,
    "volumeup": 72, "volumedown": 73, "volumemute": 74,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
_AS_MOD_NAMES = {
    "command": "command down", "ctrl": "control down",
    "option": "option down", "shift": "shift down",
}

_PRESS_RE = re.compile(
    r"^(?:please\s+|jarvis\s*[,.:]\s*)*press\s+(?:the\s+|key\s+)*"
    r"(?P<combo>[a-z0-9 +\-]+?)\s*[.!?]?$", re.I)
_PRESS_FILLER = {"the", "key", "keys", "button", "and"}


def _d_press(cmd: str):
    m = _PRESS_RE.match((cmd or "").strip())
    if not m:
        return None
    tokens = [t for t in re.split(r"\s*\+\s*|\s+", m.group("combo").lower())
              if t and t not in _PRESS_FILLER]
    if not tokens or len(tokens) > 4:
        return None
    keys = [_PGA_KEY_ALIASES.get(t) for t in tokens]
    if any(k is None for k in keys):
        return None                    # "press the issue" is not a key
    return {"keys": keys}


def _e_press(app, ctx) -> str:
    keys: list[str] = ctx["keys"]
    pg = _pyautogui()
    if pg is not None:
        try:
            if len(keys) > 1:
                pg.hotkey(*keys)
            else:
                pg.press(keys[0])
            return "Pressed %s, sir." % "+".join(keys)
        except Exception as exc:
            hint = _permission_hint(str(exc))
            if hint:
                return hint.lstrip()
            log.debug("pyautogui press failed: %s", exc)
    # osascript fallback: modifiers + key code (or keystroke for chars)
    mods = [_AS_MOD_NAMES[k] for k in keys[:-1] if k in _AS_MOD_NAMES]
    main = keys[-1]
    using = " using {%s}" % ", ".join(mods) if mods else ""
    if main in _AS_KEY_CODES:
        script = 'tell application "System Events" to key code %d%s' % (
            _AS_KEY_CODES[main], using)
    elif len(main) == 1:
        script = ('tell application "System Events" to keystroke %s%s'
                  % (_as_str(main), using))
    else:
        return ("I do not know the key '%s', sir." % main)
    ok, out = _run_osascript(script)
    if ok:
        return "Pressed %s, sir." % "+".join(keys)
    hint = _permission_hint(out)
    return (hint.lstrip() if hint else
            "I could not press %s, sir (%s)." % ("+".join(keys), out[:100]))


# ==========================================================================
# cp_screenshot - local capture only, never uploaded
# ==========================================================================

_SCREENSHOT_RE = re.compile(
    r"^(?:please\s+|jarvis\s*[,.:]\s*)*"
    r"(?:(?:take|grab|capture|save|snap)\s+(?:a\s+|an\s+|the\s+)?)?"
    r"screenshot(?:\s+shot)?"
    r"(?:\s+(?:to|into|as|at)\s+(?P<path>.+?))?"
    r"(?:\s+(?:now|please|quickly?|for\s+me|of\s+(?:the|my)\s+screen))*"
    r"\s*$", re.I)
_SCREENSHOT_ALT_RE = re.compile(
    r"^(?:please\s+|jarvis\s*[,.:]\s*)*(?:(?:capture|grab|snap)\s+"
    r"(?:the\s+)?screen|screen\s+(?:capture|shot|grab))\s*[.!?]?$", re.I)


def _d_screenshot(cmd: str):
    c = (cmd or "").strip()
    m = _SCREENSHOT_RE.match(c)
    if not m:
        if _SCREENSHOT_ALT_RE.match(c):
            return {"path": None}
        return None
    raw = (m.group("path") or "").strip().strip("\"'").rstrip(" .!?")
    return {"path": raw or None}


def _e_screenshot(app, ctx) -> str:
    raw = ctx.get("path")
    if raw:
        path = os.path.expanduser(raw)
        if not os.path.isabs(path):
            path = os.path.join(os.path.expanduser("~"), path)
        root, ext = os.path.splitext(path)
        if not ext:
            path += ".png"
    else:
        path = os.path.join(
            os.path.expanduser("~/Desktop"),
            "jarvis_screenshot_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    except Exception as exc:
        log.debug("screenshot dir failed: %s", exc)
    if _is_mac():
        try:
            r = subprocess.run(["screencapture", "-x", path],
                               capture_output=True, timeout=15)
            if r.returncode == 0 and os.path.exists(path):
                return ("Screenshot saved to %s, sir. It stays on this "
                        "machine - I never upload anything." % path)
        except Exception as exc:
            log.debug("screencapture failed: %s", exc)
    pg = _pyautogui()
    if pg is not None:
        try:
            pg.screenshot(path)
            if os.path.exists(path):
                return ("Screenshot saved to %s, sir. It stays on this "
                        "machine - I never upload anything." % path)
        except Exception as exc:
            log.debug("pyautogui screenshot failed: %s", exc)
    return _SCREEN_MSG


# ==========================================================================
# cp_run - shell execution behind a hard safety rail
# ==========================================================================

_RUN_EXPLICIT_RE = re.compile(
    r"^" + _POLITE + r"run\s+(?:the\s+)?(?:(?:shell|terminal|bash|zsh)\s+)?"
    r"command\s+(?P<cmd>.+?)\s*$", re.I)
_RUN_BARE_RE = re.compile(
    r"^" + _POLITE + r"run\s+(?P<cmd>.+?)\s*$", re.I)

# Bare "run <cmd>" fires only for recognised binaries, paths or flags -
# sentences like "run 5 miles" or "run a marathon" never reach the shell.
_SAFE_BINARIES = frozenset("""
    ls cat pwd cd echo printf mkdir touch cp mv head tail grep find wc sort
    uniq diff date whoami df du ps which file stat basename dirname realpath
    sleep true false test env uname sw_vers system_profiler defaults
    readlink tar zip unzip gzip gunzip sed awk cut tr xargs shasum md5 open
    say mdfind pbcopy pbpaste osascript chmod chown git python python3 pip
    pip3 node npm npx pnpm yarn curl wget ping dig host nslookup ssh scp
    rsync brew code go cargo java javac make cmake gcc clang swift ruby
    perl php lua jq pytest
""".split())


def _looks_shellish(cmd: str) -> bool:
    first = cmd.strip().split(None, 1)[0] if cmd.strip() else ""
    if not first:
        return False
    if "/" in first or first.lower() in _SAFE_BINARIES:
        return True
    return bool(re.match(r"^\.[/\w]", first))


_SYSTEM_PROCS = ("finder", "dock", "systemuiserver", "loginwindow",
                 "windowserver", "kernel_task", "launchd", "spotlight",
                 "cfprefsd", "distnoted", "hidd", "powerd", "bluetoothd")
_ROOTISH = {"/", "/*", "~", "~/", "~/*", "$home", "$home/", "$home/*",
            "/system", "/library", "/users", "/applications", "/usr",
            "/etc", "/var", "/private", "/bin", "/sbin", "/volumes"}


def _norm_target(token: str) -> str:
    text = token.strip("\"'")
    if text.lower().startswith("$home"):
        text = os.path.expanduser("~") + text[5:]
    return os.path.normpath(os.path.expanduser(text)).rstrip("/").lower()


def _safety_rail(cmd: str) -> str:
    """Return a one-line reason to refuse, or '' to allow."""
    low = cmd.lower()
    if re.search(r"\bsudo\b", low):
        return "superuser (sudo) execution"
    if re.search(r"\bdiskutil\s+erase", low):
        return "erasing a disk (diskutil erase)"
    if re.search(r"\bmkfs\b|\bmkfs\.", low):
        return "formatting a filesystem (mkfs)"
    if re.search(r"\b(?:shutdown|reboot|halt|poweroff)\b", low):
        return "shutting down or rebooting the machine"
    m = re.search(r"\brm\s+(?P<rest>[^|;&]+)", low)
    if m:
        home = os.path.expanduser("~").rstrip("/").lower()
        targets = [t for t in m.group("rest").split()
                   if t and not t.startswith("-")]
        for t in targets:
            norm = _norm_target(t)
            if norm in ("", "/", home) or norm in _ROOTISH \
                    or norm == home + "/*":
                return "deleting '%s' (rm on the root or home system)" % t
    m = re.search(r"\bkillall\b(?P<rest>[^|;&]*)", low)
    if m:
        words = m.group("rest").split()
        flags = {re.sub(r"^-+", "", w) for w in words if w.startswith("-")}
        names = {re.sub(r"^-+", "", w) for w in words}
        if flags & {"force", "9", "sigkill"} or names & set(_SYSTEM_PROCS):
            return "force-killing system processes (killall)"
    if re.search(r"\b(?:kill|pkill)\s+[^|;&]*-9\b", low):
        return "force kills (kill -9)"
    if re.search(r"\b(?:kill|pkill)\s+(?:finder|dock|windowserver|"
                 r"loginwindow|launchd)\b", low):
        return "killing system processes"
    if re.search(r"\bdd\b[^|;&]*of=/dev/|>\s*/dev/[shv]d[a-z]", low):
        return "raw writes to a disk device"
    return ""


def _d_run(cmd: str):
    c = (cmd or "").strip()
    m = _RUN_EXPLICIT_RE.match(c)
    if m:
        payload = re.sub(r"\s*[.!?]+$", "", m.group("cmd")).strip()
        return {"cmd": payload, "explicit": True} if payload else None
    m = _RUN_BARE_RE.match(c)
    if not m:
        return None
    payload = re.sub(r"\s*[.!?]+$", "", m.group("cmd")).strip()
    if not payload or re.match(r"^(?:a|an|the|my|some)\s+", payload):
        return None                    # "run a marathon" is chat
    if not _looks_shellish(payload):
        return None
    return {"cmd": payload, "explicit": False}


def _e_run(app, ctx) -> str:
    cmd = ctx["cmd"].strip()
    reason = _safety_rail(cmd)
    override = os.environ.get("JARVIS_ALLOW_DESTRUCTIVE") == "1"
    if reason and not override:
        return ("I refuse, sir: %s. That is on my do-not-touch list; "
                "override only with JARVIS_ALLOW_DESTRUCTIVE=1." % reason)
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return ("That command ran past %d seconds, so I pulled the plug, "
                "sir." % RUN_TIMEOUT_S)
    except Exception as exc:
        return "I could not run that command, sir (%s)." % str(exc)[:120]
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    out = re.sub(r"\n{2,}", "\n", out)
    if len(out) > RUN_OUTPUT_CAP:
        out = out[:RUN_OUTPUT_CAP] + " ..."
    note = " (destructive override was active)" if reason else ""
    if r.returncode == 0:
        return "Done, sir - exit code 0.%s%s" % (
            note, ("\n" + out) if out else "")
    return "The command failed with exit code %d, sir.%s%s" % (
        r.returncode, note, ("\n" + out) if out else "")


# ==========================================================================
# cp_volume - output volume via osascript
# ==========================================================================

_VOLUME_SET_RE = re.compile(r"\bvolume\s+(?:to|at)?\s*(\d{1,3})\s*%?", re.I)
_VOLUME_PRE_RE = re.compile(r"(\d{1,3})\s*%?\s+volume\b", re.I)
_VOLUME_STEP_RE = re.compile(r"\bby\s+(\d{1,3})\b", re.I)
_VOLUME_MATH_RE = re.compile(r"\bvolume\s+of\b", re.I)


def _d_volume(cmd: str):
    c = (cmd or "").strip()
    if not re.search(r"\bvolume\b", c, re.I):
        return None
    if _VOLUME_MATH_RE.search(c):
        return None                    # "volume of a cylinder" is maths
    low = c.lower()
    if re.search(r"\b(?:unmute|turn\s+(?:the\s+)?volume\s+(?:back\s+)?on)\b",
                 low):
        return {"action": "mute", "on": False}
    if re.search(r"\b(?:mute|silence)\b", low):
        return {"action": "mute", "on": True}
    m = _VOLUME_SET_RE.search(low) or _VOLUME_PRE_RE.search(low)
    if m:
        return {"action": "level", "level": max(0, min(100, int(m.group(1))))}
    step = _VOLUME_STEP_RE.search(low)
    delta = min(50, int(step.group(1))) if step else 10
    if re.search(r"\b(?:up|increase|raise|louder|higher|crank)\b", low):
        return {"action": "relative", "delta": delta}
    if re.search(r"\b(?:down|decrease|lower|quieter|softer|reduce)\b", low):
        return {"action": "relative", "delta": -delta}
    if re.search(r"\b(?:max|maximum|full)\b", low):
        return {"action": "level", "level": 100}
    return None


def _e_volume(app, ctx) -> str:
    action = ctx["action"]
    if action == "mute":
        flag = "true" if ctx["on"] else "false"
        ok, out = _run_osascript("set volume output muted %s" % flag)
        if ok:
            return ("Muted, sir." if ctx["on"] else "Sound is back on, sir.")
        hint = _permission_hint(out)
        return (hint.lstrip() if hint else
                "I could not change the mute state, sir (%s)." % out[:100])
    if action == "level":
        level = int(ctx["level"])
        ok, out = _run_osascript("set volume output volume %d" % level)
        if ok:
            return "Volume set to %d percent, sir." % level
        hint = _permission_hint(out)
        return (hint.lstrip() if hint else
                "I could not set the volume, sir (%s)." % out[:100])
    delta = int(ctx["delta"])
    ok, out = _run_osascript("output volume of (get volume settings)")
    if not ok:
        hint = _permission_hint(out)
        return (hint.lstrip() if hint else
                "I could not read the current volume, sir (%s)." % out[:100])
    m = re.search(r"\d+", out)
    current = int(m.group(0)) if m else 50
    level = max(0, min(100, current + delta))
    ok, out = _run_osascript("set volume output volume %d" % level)
    if not ok:
        hint = _permission_hint(out)
        return (hint.lstrip() if hint else
                "I could not set the volume, sir (%s)." % out[:100])
    return "Volume %s to %d percent, sir." % (
        "raised" if delta > 0 else "lowered", level)


# ==========================================================================
# cp_brightness - Quartz for absolute levels, key codes for nudges
# ==========================================================================

_BRIGHT_LEVEL_RE = re.compile(
    r"\bbrightness\s+(?:to|at)?\s*(\d{1,3})\s*%?"
    r"|(\d{1,3})\s*%?\s+brightness\b", re.I)


def _d_brightness(cmd: str):
    c = (cmd or "").strip()
    if not re.search(r"\bbrightness\b", c, re.I):
        return None
    low = c.lower()
    m = _BRIGHT_LEVEL_RE.search(low)
    if m:
        raw = int(m.group(1) or m.group(2))
        return {"action": "level", "level": max(0, min(100, raw))}
    if re.search(r"\b(?:up|increase|raise|brighter|max|maximum|full)\b", low):
        return {"action": "relative", "delta": 1}
    if re.search(r"\b(?:down|decrease|lower|dim(?:mer)?|reduce)\b", low):
        return {"action": "relative", "delta": -1}
    return None


def _cg_set_brightness(level01: float) -> bool:
    """Absolute brightness via pyobjc Quartz; False when unsupported."""
    try:
        from Quartz.CoreGraphics import (CGDisplaySetBrightness,
                                         CGMainDisplayID)
        return CGDisplaySetBrightness(CGMainDisplayID(), level01) == 0
    except Exception as exc:
        log.debug("CGDisplaySetBrightness unavailable: %s", exc)
        return False


def _e_brightness(app, ctx) -> str:
    if ctx["action"] == "level":
        level = int(ctx["level"])
        if _cg_set_brightness(max(0.0, min(1.0, level / 100.0))):
            return "Brightness set to about %d percent, sir." % level
        return ("This Mac will not hand me absolute brightness control, "
                "sir - say 'brightness up' or 'brightness down' and I "
                "shall nudge the function keys instead.")
    delta = int(ctx["delta"])
    code = 113 if delta > 0 else 107           # brightness up / down
    presses = min(MAX_REL_BRIGHTNESS_STEPS, abs(delta))
    script = ("repeat %d times\nkey code %d\ndelay 0.05\nend repeat"
              % (presses, code))
    ok, out = _run_osascript(script)
    if ok:
        return "Nudged the brightness %s, sir." % (
            "up" if delta > 0 else "down")
    hint = _permission_hint(out)
    return (hint.lstrip() if hint else
            "I could not nudge the brightness, sir (%s)." % out[:100])


# ==========================================================================
# cp_frontmost - what the user is looking at
# ==========================================================================

_FRONTMOST_RE = re.compile(
    r"\bwhat(?:'s| is)?\s+(?:the\s+)?(?:frontmost|focused|active|current)"
    r"\s+(?:app|application|window|program)\b"
    r"|\bwhat\s+(?:app|window|program)\s+(?:am\s+i\s+|is\s+)?"
    r"(?:focused|frontmost|active|open\s+right\s+now)\b"
    r"|\bwhich\s+(?:app|window)\s+(?:is\s+)?(?:focused|frontmost|active)\b"
    r"|\bwhat(?:'s| is)?\s+in\s+focus\b"
    r"|\bwhat\s+am\s+i\s+looking\s+at\b", re.I)


def _d_frontmost(cmd: str):
    if _FRONTMOST_RE.search(cmd or ""):
        return {"cmd": cmd}
    return None


def _e_frontmost(app, ctx) -> str:
    ok1, name = _run_osascript(
        'tell application "System Events" to get name of first process '
        'whose frontmost is true', timeout=5)
    if not ok1 or not name:
        hint = _permission_hint(name)
        return (hint.lstrip() if hint else
                "I could not read the frontmost application, sir.")
    ok2, win = _run_osascript(
        'tell application "System Events" to get name of window 1 of '
        'first process whose frontmost is true', timeout=5)
    title = " - window: '%s'" % win if ok2 and win else ""
    return "You are looking at %s%s, sir." % (name, title)


# ==========================================================================
# cp_quit - tell an app to quit (standalone / fallback lane)
# ==========================================================================

_QUIT_RE = re.compile(
    r"^" + _POLITE + r"(?:quit|close|exit)\s+"
    r"(?:the\s+|my\s+)?(?P<name>[a-z0-9][a-z0-9 .'+-]{0,30}?)"
    r"(?:\s+app(?:lication)?)?\s*[.!?]?$", re.I)
_QUIT_STOP = {"window", "windows", "tab", "tabs", "it", "this", "that",
              "everything", "all", "them", "door", "laptop", "computer",
              "mac", "machine", "session", "channel", "account", "down"}

_APP_ALIASES = {
    "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
    "imessage": "Messages", "chrome": "Google Chrome",
    "word": "Microsoft Word", "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint", "settings": "System Settings",
    "text edit": "TextEdit", "voice memos": "Voice Memos",
}


def _d_quit(cmd: str):
    m = _QUIT_RE.match((cmd or "").strip())
    if not m:
        return None
    name = m.group("name").strip(" .,")
    if not name or name.lower() in _QUIT_STOP:
        return None
    return {"name": name}


def _e_quit(app, ctx) -> str:
    name = ctx["name"]
    app_name = _APP_ALIASES.get(name.lower(), name.title())
    ok, out = _run_osascript('application "%s" is running' % app_name,
                             timeout=5)
    if ok and out.strip().lower() == "false":
        return "%s is not running, sir." % app_name
    ok, out = _run_osascript('tell application "%s" to quit' % app_name)
    if ok:
        return "Closing %s, sir." % app_name
    hint = _permission_hint(out)
    return (hint.lstrip() if hint else
            "I could not quit %s; it may not be running, sir." % app_name)


# ==========================================================================
# cp_trash_file - move into ~/.Trash with a home-containment rail
# ==========================================================================

_TRASH_RE = re.compile(
    r"^" + _POLITE
    + r"(?:(?:trash|throw\s+away)\s+"
      r"(?:the\s+|my\s+)?(?:file\s+|folder\s+|directory\s+)?"
      r"(?P<path1>.+?)"
      r"|move\s+(?:the\s+|my\s+)?(?:file\s+|folder\s+|directory\s+)?"
      r"(?P<path2>.+?)\s+to\s+(?:the\s+)?trash)\s*[.!?]?$", re.I)


def _d_trash_file(cmd: str):
    m = _TRASH_RE.match((cmd or "").strip())
    if not m:
        return None
    raw = (m.group("path1") or m.group("path2") or "").strip(" .,\"'")
    if not raw or len(raw) > 300:
        return None
    return {"path": raw}


def _e_trash_file(app, ctx) -> str:
    raw = ctx["path"]
    path = os.path.realpath(os.path.expanduser(raw))
    home = os.path.realpath(os.path.expanduser("~"))
    if not os.path.exists(path):
        return "I cannot find %s, sir." % raw
    if path == home:
        return "Trashing your home directory is not happening, sir."
    if not path.startswith(home + os.sep):
        if os.environ.get("JARVIS_ALLOW_DESTRUCTIVE") != "1":
            return ("%s sits outside your home folder, sir, so I will not "
                    "trash it without the JARVIS_ALLOW_DESTRUCTIVE=1 flag."
                    % raw)
    trash = os.path.join(home, ".Trash")
    try:
        os.makedirs(trash, exist_ok=True)
        target = os.path.join(trash, os.path.basename(path) or path)
        if os.path.lexists(target):
            target = "%s.%s" % (target, time.strftime("%Y%m%d-%H%M%S"))
        shutil.move(path, target)
    except Exception as exc:
        return ("I could not move %s to the Trash, sir (%s)."
                % (raw, str(exc)[:100]))
    return "Moved %s to the Trash (%s), sir - recoverable from there." % (
        raw, target)


# ==========================================================================
# cp_screen_size - display bounds
# ==========================================================================

_SCREENSIZE_RE = re.compile(
    r"^" + _POLITE + r"(?:what(?:'s| is)?\s+(?:the\s+|my\s+)?)?"
    r"(?:screen\s+(?:size|resolution|dimensions|bounds)"
    r"|display\s+(?:size|resolution|dimensions)"
    r"|how\s+(?:big|large)\s+is\s+my\s+(?:screen|display))"
    r"\s*[.!?]?$", re.I)


def _d_screen_size(cmd: str):
    if _SCREENSIZE_RE.match((cmd or "").strip()):
        return {"cmd": cmd}
    return None


def _e_screen_size(app, ctx) -> str:
    size = _screen_size()
    if size:
        return "Your main display is %d x %d pixels, sir." % size
    return "I could not read the display bounds, sir."


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("cp_open_url", _d_open_url, _e_open_url, False),
    ("cp_open_app", _d_open_app, _e_open_app, False),
    ("cp_double_click", _d_double_click, _e_click, False),
    ("cp_right_click", _d_right_click, _e_click, False),
    ("cp_click", _d_click, _e_click, False),
    ("cp_drag", _d_drag, _e_drag, False),
    ("cp_type", _d_type, _e_type, False),
    ("cp_press", _d_press, _e_press, False),
    # brain_extra's legacy unanchored "screenshot" skill is replaced by
    # this anchored, path-aware version (brain.py's documented pattern).
    ("cp_screenshot", _d_screenshot, _e_screenshot, False,
     ("screenshot",)),
    ("cp_run", _d_run, _e_run, False),
    ("cp_volume", _d_volume, _e_volume, False),
    ("cp_brightness", _d_brightness, _e_brightness, False),
    ("cp_frontmost", _d_frontmost, _e_frontmost, False),
    ("cp_quit", _d_quit, _e_quit, False),
    ("cp_trash_file", _d_trash_file, _e_trash_file, False),
    ("cp_screen_size", _d_screen_size, _e_screen_size, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register every computer-control skill with the given Brain."""
    for entry in _SKILLS:
        name, detect, execute, priority = entry[:4]
        supersedes = entry[4] if len(entry) > 4 else ()
        brain.register(name, detect, _wrap(execute, name),
                       priority=priority, supersedes=supersedes)
    log.info("computer-control skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return ("Something jammed in my computer-control module "
                    "(%s), sir." % str(exc)[:120])
    safe.__name__ = "safe_%s" % name
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False,
                     supersedes=()):
            print("would register %s" % name)

    register(_B())
