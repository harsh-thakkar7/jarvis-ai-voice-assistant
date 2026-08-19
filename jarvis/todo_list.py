import json
import os
import re
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
_TODO_FILE = os.environ.get("JARVIS_TODO_FILE") or os.path.join(PROJECT_DIR, "jarvis_todo.json")
_LOCK = threading.Lock()


def _load():
    try:
        with open(_TODO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return data.get("tasks", [])
    except Exception:
        return []


def _save(tasks):
    try:
        with open(_TODO_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("TODO SAVE ERROR:", e)


def parse_intent(cmd):
    """Return (verb, payload) or None if not a todo command."""
    c = cmd.strip()
    m = re.match(r"^(add|create|new)\b(.*)$", c, re.I)
    if m and ("todo" in c.lower() or "task" in c.lower() or "to do" in c.lower()
              or "to-do" in c.lower()):
        body = m.group(2)
        body = re.sub(r"\b(?:the\s+)?(?:todo|to[- ]do|task|list)*\b", " ", body,
                      flags=re.I)
        body = re.sub(r"\s+", " ", body).strip()
        if not body:
            return None
        return ("add", body)
    m = re.match(r"^(list|show|read)\b.*(?:todo|to[- ]do|tasks)\b", c, re.I)
    if m:
        return ("list", "")
    m = re.match(r"^(?:clear|delete|remove|wipe)\s+(?:all\s+)?(?:my\s+)?"
                 r"(?:todo|to[- ]do|tasks?)\b", c, re.I)
    if m:
        return ("clear", "")
    m = re.match(r"^(?:done|complete|check|finish|mark\s+(?:as\s+)?done)\b(.*)$",
                 c, re.I)
    if m:
        body = m.group(1).strip(" .")
        if body:
            return ("done", body)
        return None
    m = re.match(r"^(?:remove|delete|drop)\s+(?:the\s+)?(?:todo|task)(?:\s+#?(\d+))?\b"
                 r"(.*)$", c, re.I)
    if m:
        idx = m.group(1)
        body = m.group(2).strip(" .")
        return ("delete", (idx, body))
    m = re.match(r"^(?:what(?:'s| is)?\s+)?(?:on\s+)?(?:my\s+)?(?:todo|to[- ]do|task)"
                 r"\s+list\b", c, re.I)
    if m:
        return ("list", "")
    return None


def add_task(text):
    tasks = _load()
    tasks.append({"text": text, "done": False})
    _save(tasks)
    return len(tasks)


def list_tasks():
    return _load()


def clear_tasks():
    _save([])
    return 0


def task_count_remaining(tasks=None):
    if tasks is None:
        tasks = _load()
    return sum(1 for t in tasks if not t.get("done"))


def done_task(body):
    tasks = _load()
    target = body.strip().lower()
    for t in tasks:
        if str(t.get("text", "")).strip().lower() == target:
            t["done"] = True
            _save(tasks)
            return True
    return False


def delete_task(idx_text):
    tasks = _load()
    idx = None
    if isinstance(idx_text, tuple):
        idx, body = idx_text
    else:
        body = idx_text
    if idx is not None:
        try:
            n = int(idx)
            if 1 <= n <= len(tasks):
                removed = tasks.pop(n - 1)
                _save(tasks)
                return removed
        except Exception:
            pass
    target = (body or "").strip().lower()
    for i, t in enumerate(tasks):
        if str(t.get("text", "")).strip().lower() == target:
            removed = tasks.pop(i)
            _save(tasks)
            return removed
    return None
