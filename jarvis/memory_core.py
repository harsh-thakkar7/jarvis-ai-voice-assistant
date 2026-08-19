"""JARVIS MEMORY CORE: persistent conversation memory across restarts.

The biggest gap versus any real assistant product: Jarvis used to wake
up amnesiac every session. This module gives it durable recall:

* facts      - "remember that my laptop is a MacBook Pro"  -> topic store
* prefs      - learned preferences
* turn log   - rolling transcript of recent conversation turns

Storage is a single JSON file written atomically after every mutation,
loaded lazily on first access and shared across instances, so both the
HUD app and the orb see the same memory.

Public API:
    remember(topic, text) / recall(topic) / forget(topic)
    all_facts() / log_turn(role, text) / recent_turns(n) / export_digest()

Skills registered: mm_remember / mm_recall / mm_forget_fact /
mm_about_me / mm_recent.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import re
import threading
import time
from typing import Optional

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    logging.basicConfig(level=logging.WARNING)

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("memory_core")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
MEMORY_FILE = os.path.join(PROJECT_DIR, "jarvis_memory_core.json")

FACTS_CAP = 200
LOG_CAP = 200

_lock = threading.RLock()
_state: Optional[dict] = None


# --------------------------------------------------------------------------
# Storage plumbing
# --------------------------------------------------------------------------

def _now() -> float:
    return time.time()


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data.setdefault("facts", {})
    data.setdefault("prefs", {})
    data.setdefault("log", [])
    _state = data
    return _state


def _save() -> None:
    tmp = MEMORY_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state or {}, fh)
        os.replace(tmp, MEMORY_FILE)
    except Exception as exc:
        log.warning("memory save failed: %s", exc)


def reset_for_tests() -> None:
    """Test seam: drop cached state and point at a fresh file."""
    global _state, MEMORY_FILE
    _state = None


def _evict_oldest(facts: dict) -> None:
    while len(facts) >= FACTS_CAP:
        oldest_key = min(facts, key=lambda k: facts[k].get("ts", 0))
        del facts[oldest_key]


# --------------------------------------------------------------------------
# Core API
# --------------------------------------------------------------------------

def remember(topic: str, text: str) -> str:
    """Upsert a fact under a normalized topic; returns stored topic."""
    topic_n = re.sub(r"\s+", " ", (topic or "").strip().lower())[:60]
    text = (text or "").strip()[:500]
    if not topic_n or not text:
        return ""
    with _lock:
        state = _load()
        _evict_oldest(state["facts"])
        state["facts"][topic_n] = {"text": text, "ts": _now()}
        _save()
    log.info("remembered %s", topic_n)
    return topic_n


def recall(topic: str) -> Optional[str]:
    topic_n = re.sub(r"\s+", " ", (topic or "").strip().lower())
    with _lock:
        fact = _load()["facts"].get(topic_n)
    return fact["text"] if fact else None


def forget(topic: str) -> bool:
    topic_n = re.sub(r"\s+", " ", (topic or "").strip().lower())
    with _lock:
        state = _load()
        if topic_n in state["facts"]:
            del state["facts"][topic_n]
            _save()
            return True
    return False


def all_facts() -> dict:
    with _lock:
        return dict(_load()["facts"])


def suggest_topics(query: str, limit: int = 3) -> list[str]:
    """Nearest known topics for honest miss messages."""
    q = (query or "").strip().lower()
    topics = list(all_facts().keys())
    ranked = difflib.get_close_matches(q, topics, n=limit, cutoff=0.4)
    if not ranked:
        ranked = sorted(topics)[:limit]
    return ranked


def log_turn(role: str, text: str) -> None:
    with _lock:
        state = _load()
        state["log"].append({"role": role[:12], "text": text[:400],
                             "ts": _now()})
        del state["log"][:-LOG_CAP]
        _save()


def recent_turns(n: int = 5) -> list[dict]:
    with _lock:
        return list(_load()["log"])[-max(1, n):]


def export_digest(limit: int = 10) -> str:
    facts = all_facts()
    ordered = sorted(facts.items(), key=lambda kv: kv[1].get("ts", 0),
                     reverse=True)[:limit]
    if not ordered:
        return ""
    return "\n".join(f"- {t}: {v['text']}" for t, v in ordered)


# --------------------------------------------------------------------------
# Skill wiring
# --------------------------------------------------------------------------

_MM_REMEMBER_RE = re.compile(
    r"\bremember(?:\s+that)?\s*[:,-]?\s+(.+)$", re.I)
_MM_TOPIC_IS = re.compile(r"^(.{1,40}?)\s+(?:is|are|means|was)\s+(.+)$", re.I)
_MM_RECALL_RE = re.compile(
    r"\bwhat\s+(?:do\s+you\s+remember\s+about|did\s+i\s+say\s+about)\s+"
    r"(.{2,50})\b|\brecall\s+(.{2,50})\b", re.I)
_MM_FORGET_RE = re.compile(r"\bforget\s+(?:about\s+)?(.{2,50})\b", re.I)
_MM_ABOUT_ME_RE = re.compile(
    r"\bwhat\s+do\s+you\s+know\s+about\s+me\b|\bmy\s+preferences\b", re.I)
_MM_RECENT_RE = re.compile(
    r"\brecent\s+conversation\b|\bwhat\s+did\s+we\s+discuss\b", re.I)


def _e_mm_remember(app, ctx) -> str:
    body = ctx["body"]
    m = _MM_TOPIC_IS.match(body)
    if m:
        topic = remember(m.group(1), m.group(2))
    else:
        words = body.split()
        topic = remember(" ".join(words[:3]) or "note", body)
    if not topic:
        return ("I need a little more than that to remember, sir - "
                "try 'remember that my wifi password is hunter2'.")
    return f"Committed to long-term memory, sir: {topic}."


def _d_mm_remember(cmd):
    # Recall questions contain "remember" too - never let the store
    # skill capture "what do you remember about X".
    if re.match(r"^\s*(?:what|did|do)\b", cmd, re.I) or \
            re.search(r"\bremember\s+about\b", cmd, re.I):
        return None
    m = _MM_REMEMBER_RE.search(cmd)
    if m and len(m.group(1).strip()) >= 6:
        return {"cmd": cmd, "body": m.group(1).strip()}
    return None


def _e_mm_recall(app, ctx) -> str:
    query = ctx["query"]
    fact = recall(query)
    if fact:
        return f"From memory, sir - {query}: {fact}"
    near = suggest_topics(query)
    if near:
        return (f"I hold nothing on '{query}', sir. Nearest memories: "
                + ", ".join(near) + ".")
    return (f"I keep no memory of '{query}' yet, sir - teach me with "
            "'remember that ...'.")


def _d_mm_recall(cmd):
    m = _MM_RECALL_RE.search(cmd)
    if m:
        return {"cmd": cmd, "query": (m.group(1) or m.group(2)).strip()}
    return None


def _e_mm_forget(app, ctx) -> str:
    topic = ctx["topic"]
    if forget(topic):
        return f"Erased '{topic}' from memory, sir."
    return f"I never had a memory called '{topic}', sir."


def _d_mm_forget(cmd):
    m = _MM_FORGET_RE.search(cmd)
    if m:
        return {"cmd": cmd, "topic": m.group(1).strip()}
    return None


def _e_mm_about_me(app, ctx) -> str:
    digest = export_digest(10)
    if not digest:
        return ("My memory book about you is blank so far, sir - tell me "
                "'remember that ...' and I will never forget it.")
    return "What I know about you, sir:\n" + digest


def _d_mm_about_me(cmd):
    return {"cmd": cmd} if _MM_ABOUT_ME_RE.search(cmd) else None


def _e_mm_recent(app, ctx) -> str:
    turns = recent_turns(5)
    if not turns:
        return "Our current conversation just began, sir."
    lines = [f"{t['role']}: {t['text'][:80]}" for t in turns]
    return "Recently discussed, sir:\n" + "\n".join(lines)


def _d_mm_recent(cmd):
    return {"cmd": cmd} if _MM_RECENT_RE.search(cmd) else None


_SKILLS = (
    ("mm_remember", _d_mm_remember, _e_mm_remember),
    ("mm_recall", _d_mm_recall, _e_mm_recall),
    ("mm_forget_fact", _d_mm_forget, _e_mm_forget),
    ("mm_about_me", _d_mm_about_me, _e_mm_about_me),
    ("mm_recent", _d_mm_recent, _e_mm_recent),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    # Explicit supersede relationships: the persistent store replaces
    # brain_extra's session-only remember/recall pair.
    supersede_map = {
        "mm_remember": ("remember",),
        "mm_recall": ("recall",),
    }
    for name, detect, execute in _SKILLS:
        def wrapped(app, ctx, _fn=execute):
            try:
                return _fn(app, ctx)
            except Exception as exc:
                log.exception("memory skill failed")
                return f"My memory module misfired, sir: {exc}"
        brain.register(name, detect, wrapped, priority=False,
                       supersedes=supersede_map.get(name, ()))
    log.info("memory core registered (%d skills)", len(_SKILLS))


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, d, e, priority=False):
            print("would register", name)

    register(_B())
