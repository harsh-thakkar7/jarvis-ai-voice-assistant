"""JARVIS HABIT & STREAK TRACKER SKILLS: recurring daily habits over time.

Unlike the one-shot todo_* items, this pack tracks REPETITION: each habit
keeps a per-day ledger of ``done`` / ``skip`` marks and derives streaks,
weekly grids and monthly completion reports from it.

Skills (all require the word "habit(s)" so they can never shadow the
existing todo_/goal_/checklist/journal detectors):

    - hb_add     : "add habit meditate" / "new habit called read 20 pages"
                   / "track habit gym" -> starts tracking today.
    - hb_done    : "habit done meditate" / "mark habit meditate done"
                   / "completed habit read" -> logs today; idempotent, a
                   second mark the same day never double-counts.
    - hb_skip    : "skip habit gym" / "habit skip gym" -> excused absence.
    - hb_undo    : "undo habit meditate" -> erases today's mark.
    - hb_remove  : "remove habit smoke" / "delete habit X" -> deletes the
                   habit and its whole history.
    - hb_list    : "show my habits" / "list habits" -> ledger with today's
                   status and current/best streaks per habit.
    - hb_streak  : "habit streak" (all) / "habit streak for meditate"
                   -> current + best streak.
    - hb_week    : "habit week" / "habit grid" -> ASCII grid of the last
                   7 days per habit.
    - hb_report  : "habit report" / "monthly habit report" -> completion %
                   month-to-date plus best/worst habits.

Streak semantics (documented contract):
    * "done" extends a streak.
    * "skip" is an EXCUSED absence: it neither extends nor breaks a
      streak - the walk bridges over it.
    * An unmarked past day BREAKS the streak. Today itself gets a grace
      pass while it is still pending, so a streak is never shown as dead
      before midnight just because you have not checked in yet.

Storage: ``.jarvis_habits.json`` in the project dir, loaded lazily,
written ATOMICALLY (temp file + os.replace) after every mutation under a
lock. A corrupt or wrong-typed file starts fresh rather than crashing.
Dates are timezone-stable LOCAL ISO dates (``YYYY-MM-DD``) derived from
the patchable seam ``_clock`` that tests freeze.

This module never imports main and needs only the standard library.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)


log = get_logger("skills_habits")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
HABITS_FILE = os.path.join(PROJECT_DIR, ".jarvis_habits.json")

MAX_HABITS = 64          # sane ceiling on tracked habits
NAME_CAP = 40            # longest habit name we will store
WALK_CAP = 730           # hard cap on day-walks (~2 years of history)
STREAK_MILESTONES = (3, 7, 14, 21, 30, 50, 100, 365)

_lock = threading.RLock()
_state: dict | None = None


# ==========================================================================
# Clock seam + date helpers
# ==========================================================================

_clock = datetime.now   # seam: tests freeze the clock


def _today_str() -> str:
    """Local, timezone-stable ISO date for 'today'."""
    return _clock().strftime("%Y-%m-%d")


def _shift(iso_date: str, days: int) -> str:
    """ISO date shifted by N days (negative goes back)."""
    d = datetime.strptime(iso_date, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def _month_start(iso_date: str) -> str:
    return iso_date[:8] + "01"


# ==========================================================================
# Storage plumbing (lazy load, atomic save, corrupt-safe)
# ==========================================================================

_DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load() -> dict:
    """Return shared state, loading lazily; corrupt input starts fresh."""
    global _state
    with _lock:
        if _state is not None:
            return _state
        try:
            with open(HABITS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        habits = data.get("habits")
        clean: dict = {}
        if isinstance(habits, dict):
            for name, entry in habits.items():
                if not isinstance(entry, dict):
                    continue
                days = entry.get("days")
                if not isinstance(days, dict):
                    continue
                kept = {d: m for d, m in days.items()
                        if _DATE_OK.match(str(d)) and m in ("done", "skip")}
                created = str(entry.get("created") or _today_str())[:10]
                if not _DATE_OK.match(created):
                    created = _today_str()
                clean[str(name)[:NAME_CAP]] = {"created": created,
                                               "days": kept}
        data["habits"] = clean
        _state = data
        return _state


def _save() -> None:
    """Atomically persist state; a failed write never takes the app down."""
    tmp = HABITS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state or {}, fh)
        os.replace(tmp, HABITS_FILE)
    except Exception as exc:
        log.warning("habit save failed: %s", exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def reset_for_tests() -> None:
    """Test seam: drop cached state (HABITS_FILE is re-pointed by tests)."""
    global _state
    with _lock:
        _state = None


def get_habits() -> dict:
    """Read-only snapshot of the habit ledger."""
    with _lock:
        return dict(_load()["habits"])


# ==========================================================================
# Name handling: cleaning, normalizing, fuzzy resolution
# ==========================================================================

_FILLER = {"daily", "everyday", "regularly", "please", "today", "tonight",
           "now", "again", "each", "every", "morning", "evening", "night",
           "day", "days"}


def _clean_name(raw: str | None) -> str:
    """Tidy a captured habit name: drop filler tails and punctuation."""
    words = re.sub(r"[^0-9A-Za-z' \-]", " ", raw or "").split()
    while words and words[-1].lower() in _FILLER:
        words.pop()
    name = " ".join(words).strip(" -:,-'\"")
    return name[:NAME_CAP].strip()


def _norm(name: str) -> str:
    """Case/space-insensitive identity used for matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                                      (name or "").lower())).strip()


def _resolve(query: str | None) -> str | None:
    """Map a spoken/typed fragment to a stored habit key, fuzzily."""
    if not query:
        return None
    q = _norm(query)
    if not q:
        return None
    with _lock:
        keys = list(_load()["habits"].keys())
    normed = {k: _norm(k) for k in keys}
    for key, n in normed.items():
        if q == n:
            return key
    match = difflib.get_close_matches(q, list(normed.values()), n=1,
                                      cutoff=0.55)
    if match:
        for key, n in normed.items():
            if n == match[0]:
                return key
    return None


def _suggest(query: str | None, limit: int = 3) -> list[str]:
    """Nearest known habit names for honest miss messages."""
    q = _norm(query or "")
    with _lock:
        keys = list(_load()["habits"].keys())
    ranked = (difflib.get_close_matches(q, [_norm(k) for k in keys],
                                        n=limit, cutoff=0.4)
              if q else [])
    out = [k for k in keys if _norm(k) in ranked]
    return out or sorted(keys)[:limit]


def _solo_habit() -> str | None:
    """The single tracked habit, when exactly one exists."""
    with _lock:
        keys = list(_load()["habits"].keys())
    return keys[0] if len(keys) == 1 else None


# ==========================================================================
# Core API: add / remove / mark / undo
# ==========================================================================

def add_habit(name: str) -> tuple[bool, str]:
    """Register a new habit starting today; returns (ok, canonical_name)."""
    canon = _clean_name(name)
    if not canon:
        return False, ""
    with _lock:
        state = _load()
        habits = state["habits"]
        if any(_norm(canon) == _norm(k) for k in habits):
            return False, canon
        if len(habits) >= MAX_HABITS:
            return False, canon
        habits[canon] = {"created": _today_str(), "days": {}}
        _save()
    log.info("habit added: %s", canon)
    return True, canon


def remove_habit(name: str) -> str | None:
    """Delete a habit and its history; returns the removed key or None."""
    key = _resolve(name)
    if not key:
        return None
    with _lock:
        state = _load()
        if key not in state["habits"]:
            return None
        del state["habits"][key]
        _save()
    log.info("habit removed: %s", key)
    return key


def mark_habit(name: str, mark: str) -> tuple[str | None, str | None, int]:
    """Apply today's mark ('done'|'skip'); returns (key, prev_mark, streak).

    Same-day double-marking is idempotent at the storage layer because
    the ledger is keyed by date; ``prev`` tells callers what changed.
    """
    key = _resolve(name)
    if not key:
        return None, None, 0
    today = _today_str()
    with _lock:
        entry = _load()["habits"][key]
        prev = entry["days"].get(today)
        entry["days"][today] = mark
        _save()
    streak = current_streak(entry["days"], today)
    return key, prev, streak


def undo_habit(name: str) -> bool:
    """Erase today's mark for a habit."""
    key = _resolve(name)
    if not key:
        return False
    today = _today_str()
    with _lock:
        entry = _load()["habits"][key]
        if today not in entry["days"]:
            return False
        del entry["days"][today]
        _save()
    return True


# ==========================================================================
# Streak math (pure functions - heavily tested)
# ==========================================================================

def current_streak(days: dict, today_iso: str) -> int:
    """Walk backwards from today counting consecutive done days.

    Skips are bridged (excused); ONE grace pass absorbs an unmarked
    today; any other unmarked day stops the walk. Bounded by WALK_CAP.
    """
    d = today_iso
    streak = 0
    grace_used = False
    for i in range(WALK_CAP):
        mark = days.get(d)
        if mark == "done":
            streak += 1
        elif mark == "skip":
            pass                      # excused absence: bridge it
        else:
            if i == 0 and not grace_used:
                grace_used = True     # today still pending: fine
            else:
                break                 # genuinely missed day: streak dies
        d = _shift(d, -1)
    return streak


def best_streak(days: dict, created_iso: str, today_iso: str) -> int:
    """Longest done-run between creation and today (skips bridged).

    Scans from whichever is earlier - the recorded creation date or the
    oldest mark - so backfilled history is never silently ignored.
    """
    best = run = 0
    start = created_iso
    if days:
        start = min(start, min(days))
    start = max(start, _shift(today_iso, -(WALK_CAP - 1)))
    d = start
    while d <= today_iso:
        mark = days.get(d)
        if mark == "done":
            run += 1
            best = max(best, run)
        elif mark == "skip":
            pass                      # bridge
        else:
            run = 0
        d = _shift(d, 1)
    return best


def total_done(days: dict) -> int:
    return sum(1 for m in days.values() if m == "done")


def month_stats(days: dict, created_iso: str, today_iso: str) -> dict:
    """Completion percentage month-to-date for one habit."""
    start = _month_start(today_iso)
    effective = created_iso
    if days:
        effective = min(effective, min(days))
    start = max(start, effective)
    eligible = done = skipped = 0
    d = start
    while d <= today_iso:
        eligible += 1
        mark = days.get(d)
        if mark == "done":
            done += 1
        elif mark == "skip":
            skipped += 1
        d = _shift(d, 1)
    pct = round(done * 100.0 / eligible) if eligible else 0
    return {"eligible": eligible, "done": done, "skipped": skipped,
            "pct": pct}


# ==========================================================================
# Detectors - every pattern anchored on the word "habit(s)"
# ==========================================================================

_ADD_RE = re.compile(
    r"\b(?:add|create|make|new|track|start(?:\s+tracking)?)\s+(?:a\s+|an\s+)?"
    r"(?:new\s+)?habits?\s*:?\s+(?:called\s+|named\s+)?"
    r"(?P<name>[a-z0-9][a-z0-9' \-]{1,38})", re.I)

_DONE_NAMED = (
    re.compile(r"\bhabits?\s+done\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
    re.compile(r"\b(?:did|do)\s+(?:my\s+)?habits?\b\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
    re.compile(r"\b(?:completed?|finished?)\s+(?:my\s+)?habits?\b\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
    re.compile(r"\bmarks?\s+(?:my\s+|the\s+)?habits?\s+"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38}?)\s+(?:as\s+)?done\b",
               re.I),
    re.compile(r"\bcheck(?:ed)?\s+off\s+(?:my\s+)?habits?\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
)
_DONE_BARE = (
    re.compile(r"\bhabits?\s+done\s*$", re.I),
    re.compile(r"\bdid\s+(?:my\s+)?habits?\s*$", re.I),
    re.compile(r"\bmarks?\s+(?:my\s+|the\s+)?habits?\s+(?:as\s+)?done\s*$",
               re.I),
    re.compile(r"\b(?:completed?|finished?)\s+(?:my\s+)?habits?\s*$", re.I),
    re.compile(r"\bcheck(?:ed)?\s+off\s+(?:my\s+)?habits?\s*$", re.I),
)

_SKIP_NAMED = (
    re.compile(r"\bskips?\s+(?:my\s+|the\s+|off\s+)?habits?\b\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
    re.compile(r"\bhabits?\s+skips?\b\s*[:\-]?\s*"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I),
    re.compile(r"\bmarks?\s+(?:my\s+)?habits?\s+"
               r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38}?)\s+"
               r"(?:as\s+)?skipp?ed\b", re.I),
)
_SKIP_BARE = (
    re.compile(r"\bskips?\s+(?:my\s+|the\s+)?habits?\s*(?:today)?\s*$",
               re.I),
    re.compile(r"\bhabits?\s+skips?\s*(?:today)?\s*$", re.I),
)

_UNDO_RE = re.compile(
    r"\bundos?\s+(?:my\s+|the\s+)?habits?\b\s*[:\-]?\s*"
    r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})?\s*$"
    r"|\bhabits?\s+undos?\b", re.I)

_REMOVE_RE = re.compile(
    r"\b(?:remove|delete|drop|retire)\s+(?:my\s+|the\s+)?habits?\s*[:\-]?\s*"
    r"(?P<name>[a-z0-9][a-z0-9' \-]{0,38})\s*$", re.I)

_STREAK_RE = re.compile(
    r"\bhabits?\s+streaks?\s*(?:for\s+|of\s+)?[:\-]?\s*"
    r"(?P<name2>[a-z0-9][a-z0-9' \-]{0,38})?\s*$"
    r"|\bstreaks?\s+(?:of\s+|for\s+)(?:the\s+|my\s+)?habits?\b\s*[:\-]?\s*"
    r"(?P<name3>[a-z0-9][a-z0-9' \-]{0,38})?\s*$"
    r"|(?:(?<=[^a-z0-9'])|^)"
    r"(?!(?:my|the|our|a|an|is|whats|what's|how)\b)"
    r"(?P<name4>[a-z0-9][a-z0-9' \-]{0,38}?)\s+habits?\s+streaks?\b"
    r"|\bhow\s+(?:long|many\s+days?)\s+(?:is\s+|have\s+i\s+kept\s+)?"
    r"(?:my\s+)?habits?\b\s*[:\-]?\s*"
    r"(?P<name5>[a-z0-9][a-z0-9' \-]{0,38})?\s*$", re.I)

_REPORT_RE = re.compile(
    r"\bhabits?\s+(?:reports?|summary|recap)\b"
    r"|\breports?\s+(?:on\s+|for\s+)?(?:my\s+)?habits?\b"
    r"|\bmonthly\s+habits?\b"
    r"|\bhabits?\s+(?:this\s+month|monthly|stats|statistics|progress)\b"
    r"|\bhow\s+am\s+i\s+doing\s+(?:with\s+|on\s+)?(?:my\s+)?habits?\b",
    re.I)

_WEEK_RE = re.compile(
    r"\bhabits?\s+(?:week|weekly|grid|overview|last\s+seven\s+days|"
    r"last\s+7\s+days)\b"
    r"|\bweeks?\s+(?:view|of)\s+(?:my\s+)?habits?\b"
    r"|\bshow\s+(?:my\s+)?habits?\s+weeks?\b", re.I)

_LIST_RE = re.compile(
    r"\b(?:list|show|view|see|display)\s+(?:all\s+|my\s+|the\s+)*habits?\b"
    r"|\bwhat\s+(?:are|about)\s+my\s+habits\b"
    r"|\bmy\s+habits\b"
    r"|\bhabits?\s+(?:status|today|ledger)\b", re.I)

_RESERVED = re.compile(
    r"\b(streaks?|reports?|grids?|weeks?|weekly|months?|monthly|stats|"
    r"statistics|progress|summary|best|worst|history)\b", re.I)


def _clean_det(m: "re.Match") -> str | None:
    raw = m.groupdict().get("name")
    if not raw:
        return None
    cleaned = _clean_name(raw)
    return cleaned or None


def _d_add(cmd: str):
    if re.search(r"\b(?:remove|delete|drop)\b", cmd, re.I):
        return None
    m = _ADD_RE.search(cmd)
    if not m:
        return None
    name = _clean_det(m)
    if not name:
        return None
    return {"cmd": cmd, "name": name}


def _pick(cmd: str, named, bare):
    """Shared detector body for done/skip: named forms first, then bare."""
    if _RESERVED.search(cmd):
        return None
    for rx in named:
        m = rx.search(cmd)
        if m:
            return {"cmd": cmd, "name": _clean_det(m)}
    for rx in bare:
        if rx.search(cmd):
            return {"cmd": cmd, "name": None}
    return None


def _d_done(cmd: str):
    return _pick(cmd, _DONE_NAMED, _DONE_BARE)


def _d_skip(cmd: str):
    return _pick(cmd, _SKIP_NAMED, _SKIP_BARE)


def _d_undo(cmd: str):
    if _RESERVED.search(cmd):
        return None
    m = _UNDO_RE.search(cmd)
    if not m:
        return None
    return {"cmd": cmd, "name": _clean_det(m)}


def _d_remove(cmd: str):
    m = _REMOVE_RE.search(cmd)
    if not m:
        return None
    name = _clean_det(m)
    if not name:
        return None
    return {"cmd": cmd, "name": name}


_STREAK_STOP = {"my", "the", "our", "a", "an", "is", "whats", "what",
                "how", "s", "me", "of", "for", "streak", "streaks",
                "habit", "habits"}


def _d_streak(cmd: str):
    m = _STREAK_RE.search(cmd)
    if not m:
        return None
    gd = m.groupdict()
    raw = next((v for v in (gd.get("name2"), gd.get("name3"),
                            gd.get("name4"), gd.get("name5")) if v), None)
    if not raw:
        return {"cmd": cmd, "name": None}
    words = [w for w in _clean_name(raw).split()
             if w.lower() not in _STREAK_STOP]
    return {"cmd": cmd, "name": " ".join(words) or None}


def _d_report(cmd: str):
    return {"cmd": cmd} if _REPORT_RE.search(cmd) else None


def _d_week(cmd: str):
    if re.search(r"\breports?\b", cmd, re.I):
        return None                       # "weekly report" belongs elsewhere
    return {"cmd": cmd} if _WEEK_RE.search(cmd) else None


def _d_list(cmd: str):
    if _RESERVED.search(cmd):
        return None
    return {"cmd": cmd} if _LIST_RE.search(cmd) else None


# ==========================================================================
# Executors - Iron-Man persona, fail-soft via register-time _wrap
# ==========================================================================

def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _streak_flair(name: str, streak: int) -> str:
    if streak >= 100:
        return f"One hundred days of '{name}', sir. Legendary."
    if streak in STREAK_MILESTONES:
        return (_plural(streak, "day") + f" straight on '{name}' - "
                f"a milestone worth noting, sir.")
    return ""


def _need_name(ctx_name: str | None, verb: str) -> tuple[str | None,
                                                          str | None]:
    """Resolve a possibly-missing habit name.

    Returns ``(key, None)`` on success or ``(None, persona_reply)`` when
    the habit cannot be pinned down (unknown, ambiguous, or empty ledger).
    """
    if ctx_name:
        key = _resolve(ctx_name)
        if key:
            return key, None
        near = _suggest(ctx_name)
        if near:
            return None, (f"I track no habit like '{ctx_name}', sir. "
                          f"Nearest matches: " + ", ".join(near) + ".")
        return None, (f"I have no habit called '{ctx_name}' on record, "
                      f"sir - add one first with 'add habit {ctx_name}'.")
    solo = _solo_habit()
    if solo:
        return solo, None
    with _lock:
        count = len(_load()["habits"])
    if count == 0:
        return None, ("Your habit ledger is empty, sir - tell me "
                      "'add habit <name>' and I shall start tracking.")
    return None, (f"Which habit shall I {verb}, sir? You are tracking "
                  f"{count} of them - name one, or say 'list habits'.")


def _e_add(app, ctx) -> str:
    ok, canon = add_habit(ctx["name"])
    if not ok:
        if not canon:
            return "What shall I call this habit, sir?"
        with _lock:
            dup = any(_norm(canon) == _norm(k) for k in _load()["habits"])
        if dup:
            return (f"'{canon}' is already on your habit ledger, sir - "
                    f"I shall keep counting it rather than duplicate it.")
        return (f"The ledger is full at {MAX_HABITS} habits, sir - even "
                f"I cannot watch everything at once. Remove one first.")
    low = canon.lower()
    return (f"Habit registered, sir: '{canon}'. Day one begins now - when "
            f"you have done it, tell me 'habit done {low}' and I shall "
            f"keep the streak honest.")


def _e_done(app, ctx) -> str:
    key, miss = _need_name(ctx.get("name"), "credit")
    if miss:
        return miss
    logged, prev, streak = mark_habit(key, "done")
    disp = logged or "?"
    flair = _streak_flair(disp, streak)
    if prev == "done":
        return (f"Already chalked up for today, sir - '{disp}' stands at "
                f"{_plural(streak, 'day')}. Double credit is not my style.")
    if prev == "skip":
        base = (f"Upgraded today from skip to done, sir - '{disp}' now "
                f"sits at {_plural(streak, 'day')}.")
    else:
        base = (f"Logged, sir - '{disp}' is done for today. Streak: "
                f"{_plural(streak, 'day')}.")
    return base + (" " + flair if flair else "")


def _e_skip(app, ctx) -> str:
    key, miss = _need_name(ctx.get("name"), "excuse")
    if miss:
        return miss
    logged, prev, streak = mark_habit(key, "skip")
    disp = logged or "?"
    if prev == "skip":
        return (f"Today was already marked as an excused skip for "
                f"'{disp}', sir. Nothing further needed.")
    if prev == "done":
        return (f"Very well, sir - today's done mark on '{disp}' is now "
                f"an excused skip. The streak reads "
                f"{_plural(streak, 'day')}.")
    return (f"Noted, sir - '{disp}' is marked as an excused skip today. "
            f"It will neither extend nor break your "
            f"{_plural(streak, 'day')} streak.")


def _e_undo(app, ctx) -> str:
    key, miss = _need_name(ctx.get("name"), "wipe")
    if miss:
        return miss
    if undo_habit(key):
        return f"Today's mark for '{key}' erased, sir. Clean slate."
    return f"There is nothing logged for '{key}' today, sir."


def _e_remove(app, ctx) -> str:
    name = ctx.get("name")
    key = _resolve(name) if name else None
    if not key:
        near = _suggest(name) if name else []
        if near:
            return (f"No habit precisely named '{name}', sir. Nearest: "
                    + ", ".join(near) + ".")
        return (f"I track no habit called '{name}', sir - nothing to "
                f"remove.")
    if remove_habit(key):
        return (f"Habit '{key}' deleted along with its full history, sir. "
                f"If it returns, we start from day one again.")
    return "That habit slipped away before I could delete it, sir."


def _fmt_status(mark: str | None) -> str:
    return {"done": "done today", "skip": "skipped today"}.get(
        mark, "pending today")


def _e_list(app, ctx) -> str:
    with _lock:
        habits = dict(_load()["habits"])
    if not habits:
        return ("Your habit ledger is empty, sir. Say 'add habit <name>' "
                "and I shall hold you to it daily.")
    today = _today_str()
    lines = ["Your habit ledger, sir:"]
    for i, (name, entry) in enumerate(sorted(habits.items()), 1):
        cur = current_streak(entry["days"], today)
        best = best_streak(entry["days"], entry.get("created", today),
                           today)
        status = _fmt_status(entry["days"].get(today))
        lines.append(f"  {i}. {name[:22]:<24} [{status}]  "
                     f"streak {cur} (best {best}, "
                     f"{total_done(entry['days'])} total)")
    lines.append("Say 'habit done <name>' when you check in, sir.")
    return "\n".join(lines)


def _e_streak(app, ctx) -> str:
    name = ctx.get("name")
    today = _today_str()
    if name:
        key = _resolve(name)
        if not key:
            near = _suggest(name)
            hint = ", ".join(near) if near else "nothing yet"
            return (f"No habit matching '{name}', sir - I am tracking: "
                    f"{hint}.")
        entry = get_habits()[key]
        cur = current_streak(entry["days"], today)
        best = best_streak(entry["days"], entry.get("created", today),
                           today)
        tail = _streak_flair(key, cur)
        return (f"'{key}' stands at a {_plural(cur, 'day')} streak "
                f"(best ever: {_plural(best, 'day')}), sir."
                + (" " + tail if tail else ""))
    habits = get_habits()
    if not habits:
        return ("No habits to measure yet, sir - say 'add habit <name>' "
                "and the streak board comes alive.")
    lines = ["Streak board, sir:"]
    for name_k, entry in sorted(habits.items()):
        cur = current_streak(entry["days"], today)
        best = best_streak(entry["days"], entry.get("created", today),
                           today)
        lines.append(f"  {name_k[:22]:<24} current {_plural(cur, 'day'):>9}   "
                     f"best {_plural(best, 'day'):>9}")
    return "\n".join(lines)


_CELL = {"done": "#", "skip": "s"}
_WEEK_LEGEND = "Legend: #=done  s=skipped  .=missed  -=not tracked yet"


def _e_week(app, ctx) -> str:
    with _lock:
        habits = dict(_load()["habits"])
    if not habits:
        return ("Nothing to draw yet, sir - add a habit and I shall "
                "chart your week.")
    today = _today_str()
    dates = [_shift(today, -offset) for offset in range(6, -1, -1)]
    header = " " * 28 + "".join(
        f"{datetime.strptime(d, '%Y-%m-%d').strftime('%a')[:2].title():<4}"
        for d in dates)
    lines = ["Habit grid - last 7 days, sir:", header]
    only = _resolve(ctx.get("name")) if ctx.get("name") else None
    for name, entry in sorted(habits.items()):
        if only and _norm(name) != _norm(only):
            continue
        created = entry.get("created", today)
        cells = []
        for d in dates:
            mark = entry["days"].get(d)
            if mark in _CELL:
                cells.append(_CELL[mark])
            elif d > created:
                cells.append(".")
            else:
                cells.append("-")
        lines.append(f"  {name[:22]:<24}  " + "   ".join(cells))
    lines.append(_WEEK_LEGEND)
    return "\n".join(lines)


def _e_report(app, ctx) -> str:
    with _lock:
        habits = dict(_load()["habits"])
    if not habits:
        return ("No habit data to report yet, sir - the month is yours "
                "to start shaping with 'add habit <name>'.")
    today = _today_str()
    month_label = datetime.strptime(today, "%Y-%m-%d").strftime("%B %Y")
    rows = []
    for name, entry in sorted(habits.items()):
        st = month_stats(entry["days"], entry.get("created", today), today)
        rows.append((name, st))
    lines = [f"Monthly habit report - {month_label}, sir:"]
    for name, st in rows:
        lines.append(f"  {name[:24]:<26} {st['pct']:>3}%  "
                     f"({st['done']}/{st['eligible']} days, "
                     f"{st['skipped']} skipped)")
    scored = [(name, st) for name, st in rows if st["eligible"] > 0]
    if scored:
        best = max(scored, key=lambda kv: (kv[1]["pct"], kv[0]))
        worst = min(scored, key=lambda kv: (kv[1]["pct"], kv[0]))
        avg = round(sum(st["pct"] for _, st in scored) / len(scored))
        lines.append(f"Best: {best[0]} ({best[1]['pct']}%)  |  "
                     f"Worst: {worst[0]} ({worst[1]['pct']}%)")
        verdict = ("Outstanding discipline, sir." if avg >= 80 else
                   "Solid, sir - though there is headroom." if avg >= 50
                   else "We should tighten the schedule, sir.")
        lines.append(f"Month average: {avg}%. {verdict}")
    return "\n".join(lines)


# ==========================================================================
# Registration (fail-soft wrap, mirroring net_diagnostics_brain)
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("hb_add", _d_add, _e_add, False),
    ("hb_done", _d_done, _e_done, False),
    ("hb_skip", _d_skip, _e_skip, False),
    ("hb_undo", _d_undo, _e_undo, False),
    ("hb_remove", _d_remove, _e_remove, False),
    ("hb_streak", _d_streak, _e_streak, False),
    ("hb_report", _d_report, _e_report, False),
    ("hb_week", _d_week, _e_week, False),
    ("hb_list", _d_list, _e_list, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all habit-tracker skills with the given Brain."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("habit tracker registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something misfired in my habit tracker module "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
