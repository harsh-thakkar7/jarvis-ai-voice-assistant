# -*- coding: utf-8 -*-
"""KNOWLEDGE JOURNAL BRAIN: clicky-inspired notes + spaced repetition.

A persistent, fully offline memory layer for JARVIS stored as one JSON
document at PROJECT_DIR/jarvis_journal.json (module constant JOURNAL_FILE;
tests monkeypatch it):

    {"notes": [{"ts": "YYYY-MM-DD", "text": "..."}, ...],
     "cards": {"TERM": {"term": ..., "definition": ...,
                        "box": 0..4, "due": "YYYY-MM-DD"}}}

Registers six skills into the main Brain via register(brain):
    jr_note, jr_today, jr_search, jr_learn, jr_review, jr_forget

Behaviour highlights:
* notes are capped at the newest JOURNAL_MAX_NOTES (500) entries
* every save is atomic: write JOURNAL_FILE + ".tmp", then os.replace
* jr_review implements a 5-box Leitner system with intervals
  [0, 1, 3, 7, 16] days; because chat is one-shot it returns a study
  sheet (term -> definition) and reschedules the cards it showed
* jr_forget rotates the journal to ".bak" before mutating anything

The current date flows through the injectable _today() helper so tests can
freeze time. Detectors are deliberately tight: the note detector refuses to
fire whenever another journal skill claims the command, keeping routing
unambiguous. Every executor reply is persona-safe and ends with ", sir."
Never imports main.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("journal_brain")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
JOURNAL_FILE = os.path.join(PROJECT_DIR, "jarvis_journal.json")

JOURNAL_MAX_NOTES = 500
BOX_INTERVALS = (0, 1, 3, 7, 16)
MAX_BOX = 4
SEARCH_LIMIT = 8


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _today() -> dt.date:
    """Injectable clock seam: the single source of 'today'."""
    return dt.date.today()


def _load() -> dict:
    """Load the journal document; missing/corrupt files yield empty state."""
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {"notes": [], "cards": {}}
    if not isinstance(data, dict):
        return {"notes": [], "cards": {}}
    notes = [n for n in (data.get("notes") or [])
             if isinstance(n, dict) and n.get("text")]
    cards_raw = data.get("cards")
    cards = {k: v for k, v in (cards_raw or {}).items()
             if isinstance(k, str) and isinstance(v, dict)}
    return {"notes": notes, "cards": cards}


def _save(state: dict) -> None:
    """Atomically persist the journal (tmp file, then os.replace)."""
    tmp = JOURNAL_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, JOURNAL_FILE)


def _rotate_backup() -> bool:
    """Copy the current journal to '.bak' before a destructive mutation."""
    if not os.path.exists(JOURNAL_FILE):
        return False
    try:
        shutil.copyfile(JOURNAL_FILE, JOURNAL_FILE + ".bak")
        return True
    except OSError as exc:
        log.warning("could not rotate journal backup: %s", exc)
        return False


# ==========================================================================
# Shared helpers
# ==========================================================================

def _persona_safe(reply: str) -> str:
    """Guarantee the Jarvis persona: every reply ends with ', sir.'"""
    r = (reply or "").rstrip()
    if re.search(r"\bsir\b[\s.?!]*$", r, re.I):
        return r
    if r.endswith((".", "!", "?")):
        return r[:-1].rstrip() + ", sir" + r[-1:]
    return r + ", sir."


def _clean_phrase(raw: str) -> str:
    p = (raw or "").strip().strip("\"'`").strip()
    return p.rstrip(" \t.,!?;:-").strip()


def _iso(day: dt.date | None = None) -> str:
    return (day or _today()).isoformat()


def _parse_date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _add_note(text: str) -> dict:
    """Append {ts, text}, enforcing the rolling cap; returns the entry."""
    state = _load()
    entry = {"ts": _iso(), "text": text}
    state["notes"].append(entry)
    state["notes"] = state["notes"][-JOURNAL_MAX_NOTES:]
    _save(state)
    return entry


def _notes_for_day(state: dict, day: dt.date) -> list:
    stamp = _iso(day)
    return [n for n in state["notes"] if str(n.get("ts", ""))[:10] == stamp]


# ==========================================================================
# Detector regexes (tight, mutually exclusive by construction + guard)
# ==========================================================================

_NOTE_RE = re.compile(
    r"\b(?:note\s+to\s+self|journal)\b[\s:,]+(?P<text>.+)", re.I)
_TODAY_RE = re.compile(
    r"\b(?:what\s+did\s+i\s+note\s+today|my\s+journal\s+today)\b", re.I)
_SEARCH_RE = re.compile(
    r"\bsearch\s+my\s+notes?\s+for\s+(?P<query>.+)", re.I)
_LEARN_RE = re.compile(
    r"\b(?:teach\s+me\s+(?P<t1>.+?)\s*:\s*(?P<d1>.+)"
    r"|learn\s+(?P<t2>.+?)\s+means\s+(?P<d2>.+))", re.I)
_REVIEW_RE = re.compile(
    r"\b(?:review\s+session|spaced\s+repetition\s+review)\b", re.I)
_FORGET_TERM_RE = re.compile(
    r"\bforget\s+(?:the\s+)?term\s+(?P<term>.+)", re.I)
_FORGET_NOTE_RE = re.compile(
    r"\bdelete\s+(?:my\s+)?notes?\s+about\s+(?P<phrase>.+)", re.I)

_OTHER_CLAIMS = (_TODAY_RE, _SEARCH_RE, _LEARN_RE, _REVIEW_RE,
                 _FORGET_TERM_RE, _FORGET_NOTE_RE)


def _claimed_elsewhere(cmd: str) -> bool:
    """True when any sibling journal skill matches this command first."""
    return any(rx.search(cmd) for rx in _OTHER_CLAIMS)


def _detect_note(cmd: str):
    if _claimed_elsewhere(cmd):
        return None
    m = _NOTE_RE.search(cmd)
    if not m:
        return None
    text = m.group("text").strip()
    if not text:
        return None
    return {"kind": "note", "text": text}


def _detect_today(cmd: str):
    return {"kind": "today"} if _TODAY_RE.search(cmd) else None


def _detect_search(cmd: str):
    m = _SEARCH_RE.search(cmd)
    if not m:
        return None
    query = m.group("query").strip()
    return {"kind": "search", "query": query} if query else None


def _detect_learn(cmd: str):
    m = _LEARN_RE.search(cmd)
    if not m:
        return None
    term = m.group("t1") if m.group("t1") is not None else m.group("t2")
    definition = (m.group("d1") if m.group("d1") is not None
                  else m.group("d2"))
    term, definition = _clean_phrase(term), _clean_phrase(definition)
    if not term or not definition:
        return None
    return {"kind": "learn", "term": term, "definition": definition}


def _detect_review(cmd: str):
    return {"kind": "review"} if _REVIEW_RE.search(cmd) else None


def _detect_forget(cmd: str):
    m = _FORGET_TERM_RE.search(cmd)
    if m:
        term = _clean_phrase(m.group("term"))
        if term:
            return {"kind": "forget_card", "term": term}
    m = _FORGET_NOTE_RE.search(cmd)
    if m:
        phrase = _clean_phrase(m.group("phrase"))
        if phrase:
            return {"kind": "forget_note", "phrase": phrase}
    return None


# ==========================================================================
# Executors
# ==========================================================================

def _execute_note(app, ctx) -> str:
    entry = _add_note(ctx["text"])
    total = len(_load()["notes"])
    return ('Logged to the journal on %s: "%s" (%d note%s on file)'
            % (entry["ts"], entry["text"], total,
               "" if total == 1 else "s"))


def _execute_today(app, ctx) -> str:
    entries = _notes_for_day(_load(), _today())
    if not entries:
        return "Your journal has no entries for today yet."
    lines = ["Here is what you noted today (%d):" % len(entries)]
    lines += ["  %d. %s" % (i, n["text"])
              for i, n in enumerate(entries, 1)]
    return "\n".join(lines)


def _execute_search(app, ctx) -> str:
    query = ctx["query"]
    needle = query.lower()
    hits = [n for n in reversed(_load()["notes"])
            if needle in str(n.get("text", "")).lower()]
    if not hits:
        return "No notes match '%s'." % query
    shown = hits[:SEARCH_LIMIT]
    lines = ["Found %d matching note%s (showing %d):"
             % (len(hits), "" if len(hits) == 1 else "s", len(shown))]
    lines += ["  [%s] %s" % (str(n.get("ts", "?"))[:10], n.get("text", ""))
              for n in shown]
    return "\n".join(lines)


def _execute_learn(app, ctx) -> str:
    state = _load()
    term = ctx["term"]
    state["cards"][term] = {"term": term,
                            "definition": ctx["definition"],
                            "box": 0,
                            "due": _iso()}
    _save(state)
    return ("Learned '%s'. Filed in review box 0, due today - "
            "say 'review session' whenever you want to drill it."
            % term)


def _build_study_sheet(state: dict) -> tuple[list[str], list[dict]]:
    """Return (sheet_lines, reviewed_cards); reschedules as a side effect."""
    today = _today()
    due = []
    for card in state["cards"].values():
        d = _parse_date(card.get("due"))
        if d is not None and d <= today:
            due.append(card)
    due.sort(key=lambda c: str(c.get("term", "")).lower())
    lines = []
    for card in due:
        lines.append("%s -> %s" % (card.get("term", "?"),
                                   card.get("definition", "?")))
        gap = BOX_INTERVALS[min(int(card.get("box", 0)), MAX_BOX)]
        base = _parse_date(card.get("due")) or today
        new_due = base + dt.timedelta(days=gap)
        card["due"] = new_due.isoformat()
        card["box"] = min(MAX_BOX, int(card.get("box", 0)) + 1)
    return lines, due


def _next_due_date(state: dict) -> dt.date | None:
    today = _today()
    upcoming = [_parse_date(c.get("due")) for c in state["cards"].values()]
    upcoming = [d for d in upcoming if d is not None and d > today]
    return min(upcoming) if upcoming else None


def _execute_review(app, ctx) -> str:
    state = _load()
    if not state["cards"]:
        return "Your knowledge journal has no cards yet - teach me something."
    sheet, reviewed = _build_study_sheet(state)
    if not reviewed:
        nxt = _next_due_date(state)
        if nxt is None:
            return "Nothing is due in your review stack."
        return "No cards are due right now; the next one matures on %s." % (
            nxt.isoformat())
    _save(state)
    lines = ["Spaced repetition study sheet - %d card%s due:"
             % (len(reviewed), "" if len(reviewed) == 1 else "s")]
    lines += ["  " + line for line in sheet]
    lines.append("All reviewed cards moved up a box; come back tomorrow "
                 "or later.")
    return "\n".join(lines)


def _execute_forget(app, ctx) -> str:
    had_backup = _rotate_backup()
    state = _load()
    if ctx["kind"] == "forget_card":
        term = str(ctx["term"]).lower()
        victims = [k for k in state["cards"]
                   if k.strip().lower() == term
                   or str(state["cards"][k].get("term", "")).strip().lower()
                   == term]
        names = sorted({str(state["cards"][k].get("term", "")) or k
                        for k in victims})
        for k in victims:
            del state["cards"][k]
        if victims:
            _save(state)
        label = ", ".join("'%s'" % n for n in names) if names \
            else "'%s'" % ctx["term"]
        msg = "Removed %d card%s for term %s" % (
            len(victims), "" if len(victims) == 1 else "s", label)
    else:
        phrase = str(ctx["phrase"]).lower()
        kept = [n for n in state["notes"]
                if phrase not in str(n.get("text", "")).lower()]
        removed = len(state["notes"]) - len(kept)
        if removed:
            state["notes"] = kept
            _save(state)
        msg = "Deleted %d note%s containing '%s'" % (
            removed, "" if removed == 1 else "s", ctx["phrase"])
    if had_backup:
        msg += "; the earlier journal was rotated to %s.bak" % (
            os.path.basename(JOURNAL_FILE))
    else:
        msg += "; no earlier journal existed to back up"
    return msg


# ==========================================================================
# Skill table + registration
# ==========================================================================

def _executor(name: str):
    def execute(app, ctx) -> str:
        try:
            return _persona_safe(EXECUTORS[name.split("_", 1)[1]](app, ctx))
        except Exception as exc:
            log.exception("skill %s failed", name)
            return _persona_safe("My journal module misfired (%s)" % exc)
    execute.__name__ = name
    return execute


EXECUTORS = {
    "note": _execute_note,
    "today": _execute_today,
    "search": _execute_search,
    "learn": _execute_learn,
    "review": _execute_review,
    "forget": _execute_forget,
}

DETECTORS = {
    "note": _detect_note,
    "today": _detect_today,
    "search": _detect_search,
    "learn": _detect_learn,
    "review": _detect_review,
    "forget": _detect_forget,
}

SKILLS = [
    ("jr_" + key, DETECTORS[key], _executor("jr_" + key), False)
    for key in ("note", "today", "search", "learn", "review", "forget")
]


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    for name, detect, execute, priority in SKILLS:
        brain.register(name, detect, execute, priority=priority)
    log.info("journal skills registered (%d)", len(SKILLS))


register_extra = register


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print("would register", name)

    register(_B())
