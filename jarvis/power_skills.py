"""JARVIS POWER SKILLS: developer & intelligence tools.

Adds Phase 1-3 capabilities from the upgrade roadmap:

* git operations          - status / add / commit / log / branches / diff
* docker operations       - ps / images / version
* clipboard history       - background capture + recall (macOS)
* system report           - CPU / RAM / disk / uptime / battery in one shot
* wikipedia summaries     - REST API, network-guarded
* dictionary / thesaurus  - dictionaryapi.dev, network-guarded
* news headlines          - Hacker News front page, network-guarded
* math solver             - linear/quadratic equations with steps,
                            polynomial derivatives and integrals
* api testing             - GET a URL, report status/timing/body
* sqlite queries          - read-only SELECTs against any .db file

Every skill follows the Brain protocol:
    detect(cmd_lower) -> ctx dict | None
    execute(app, ctx) -> persona reply string ("..., sir.")
Network operations degrade to honest offline messages instead of raising.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from fractions import Fraction
from typing import Optional

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


log = get_logger("power_skills")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
CLIPBOARD_FILE = os.path.join(PROJECT_DIR, "jarvis_clipboard.json")
CLIPBOARD_MAX = 50
CLIPBOARD_POLL_SECONDS = 5.0

_UA = {"User-Agent": "JarvisAssistant/2.1 (personal assistant)"}


# ==========================================================================
# Shared helpers
# ==========================================================================

def _run(cmd: list[str], cwd: str | None = None,
         timeout: float = 12.0) -> tuple[int, str]:
    """Run a subprocess; return (returncode, combined output tail)."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd or PROJECT_DIR, capture_output=True, text=True,
            timeout=timeout)
        out = ((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return proc.returncode, out.strip()
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:  # defensive
        return 1, str(exc)[:200]


def _clip_text() -> str:
    """Read the macOS clipboard via pbpaste ('' when unavailable)."""
    code, out = _run(["pbpaste"], timeout=4.0)
    return out if code == 0 else ""


def _copy_text(text: str) -> bool:
    if shutil.which("pbcopy") is None:
        return False
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE,
                                text=True)
        proc.communicate(text, timeout=4)
        return proc.returncode == 0
    except Exception:
        return False


def _net_get(url: str, timeout: float = 6.0, **kw) -> "requests.Response":
    if requests is None:
        raise ConnectionError("requests library unavailable")
    return requests.get(url, timeout=timeout, headers=_UA, **kw)


# ==========================================================================
# Clipboard history (lazy daemon thread)
# ==========================================================================

_clip_lock = threading.Lock()
_clip_history: deque = deque(maxlen=CLIPBOARD_MAX)
_clip_thread_started = False


def _load_clip_history() -> None:
    try:
        with open(CLIPBOARD_FILE, "r", encoding="utf-8") as fh:
            items = json.load(fh)
        if isinstance(items, list):
            for item in items[-CLIPBOARD_MAX:]:
                _clip_history.append(str(item))
    except Exception:
        pass


def _save_clip_history() -> None:
    tmp = CLIPBOARD_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(list(_clip_history), fh)
        os.replace(tmp, CLIPBOARD_FILE)
    except Exception as exc:
        log.debug("clipboard save failed: %s", exc)


def _record_clipboard(text: str) -> bool:
    if not text or not text.strip():
        return False
    with _clip_lock:
        if _clip_history and _clip_history[-1] == text:
            return False
        if text in _clip_history:
            _clip_history.remove(text)
        _clip_history.append(text)
        _save_clip_history()
    return True


def ensure_clipboard_thread() -> bool:
    """Start the clipboard poller once (skipped under JARVIS_TEST)."""
    global _clip_thread_started
    if os.environ.get("JARVIS_TEST") == "1":
        return False
    if not sys_platform_darwin():
        return False
    if _clip_thread_started:
        return True
    with _clip_lock:
        if _clip_thread_started:
            return True
        _load_clip_history()
        thread = threading.Thread(target=_clipboard_loop, name="jarvis-clip",
                                  daemon=True)
        thread.start()
        _clip_thread_started = True
    return True


def sys_platform_darwin() -> bool:
    return shutil.which("pbpaste") is not None


def _clipboard_loop() -> None:
    while True:
        try:
            _record_clipboard(_clip_text())
        except Exception as exc:  # keep the poller alive
            log.debug("clipboard poll error: %s", exc)
        time.sleep(CLIPBOARD_POLL_SECONDS)


_CLIP_HIST_RE = re.compile(r"\b(?:clipboard|copy)\s+(?:history|past)\b|"
                           r"\bwhat.{0,8}\bon my clipboard\b", re.I)
_CLIP_PASTE_RE = re.compile(r"\bpaste\s+(?:item\s+)?#?(\d{1,2})\b", re.I)
_CLIP_CLEAR_RE = re.compile(r"\bclear\s+clipboard\b", re.I)
_CLIP_COPY_RE = re.compile(r"\bcopy\s+(?:this\s+)?(.{1,400}?)\s+to\s+"
                           r"(?:my\s+)?clipboard\b", re.I)


def _e_clip_history(app, ctx) -> str:
    ensure_clipboard_thread()
    with _clip_lock:
        items = list(_clip_history)
    if not items:
        _record_clipboard(_clip_text())
        with _clip_lock:
            items = list(_clip_history)
    if not items:
        return ("My clipboard history is empty so far, sir - copy "
                "something and I will remember it, sir.")
    lines = []
    for i, item in enumerate(reversed(items), 1):
        preview = item.replace("\n", " ")[:90]
        lines.append(f"{i}. {preview}")
    return f"Clipboard history, most recent first, sir:\n" + \
        "\n".join(lines[:15])


def _d_clip_history(cmd):
    return {"cmd": cmd} if _CLIP_HIST_RE.search(cmd) else None


def _e_clip_paste(app, ctx) -> str:
    ensure_clipboard_thread()
    idx = int(ctx["n"])
    with _clip_lock:
        items = list(reversed(_clip_history))
    if idx < 1 or idx > len(items):
        return (f"I only have {len(items)} clipboard item(s) stored, sir."
                if items else
                "Nothing in my clipboard history yet, sir.")
    chosen = items[idx - 1]
    ok = _copy_text(chosen)
    if ok:
        preview = chosen.replace("\n", " ")[:120]
        return (f"Pasted clipboard item {idx} back onto your clipboard, "
                f"sir: \"{preview}\"")
    return "I could not reach the system clipboard, sir."


def _d_clip_paste(cmd):
    m = _CLIP_PASTE_RE.search(cmd)
    if m:
        return {"cmd": cmd, "n": m.group(1)}
    return None


def _e_clip_clear(app, ctx) -> str:
    with _clip_lock:
        _clip_history.clear()
        _save_clip_history()
    return "Clipboard history wiped clean, sir."


def _d_clip_clear(cmd):
    return {"cmd": cmd} if _CLIP_CLEAR_RE.search(cmd) else None


def _e_clip_copy(app, ctx) -> str:
    text = ctx["text"]
    if _copy_text(text):
        _record_clipboard(text)
        return f"Copied to your clipboard, sir ({len(text)} characters)."
    return "I could not reach the system clipboard, sir."


def _d_clip_copy(cmd):
    m = _CLIP_COPY_RE.search(cmd)
    if m:
        return {"cmd": cmd, "text": m.group(1)}
    return None


# ==========================================================================
# System report
# ==========================================================================

_SYS_REPORT_RE = re.compile(
    r"\b(system|machine)\s+(report|status|stats|health)\b|"
    r"\bhow\s+is\s+my\s+system\b|\bsystem\s+monitor(ing)?\b", re.I)


def _cpu_percent_psutil() -> Optional[float]:
    try:
        import psutil
        return float(psutil.cpu_percent(interval=0.35))
    except Exception:
        return None


def _mem_stats() -> tuple[Optional[float], Optional[float]]:
    try:
        import psutil
        mem = psutil.virtual_memory()
        used_gb = (mem.total - mem.available) / 1024 ** 3
        total_gb = mem.total / 1024 ** 3
        return round(used_gb, 1), round(total_gb, 1)
    except Exception:
        return None, None


def _disk_stats() -> tuple[Optional[float], Optional[float]]:
    usage = shutil.disk_usage("/")
    total_gb = usage.total / 1024 ** 3
    free_gb = usage.free / 1024 ** 3
    return round(total_gb, 1), round(free_gb, 1)


def _uptime_days() -> Optional[str]:
    try:
        import psutil
        secs = time.time() - psutil.boot_time()
        return f"{secs / 86400:.1f}"
    except Exception:
        pass
    code, out = _run(["sysctl", "-n", "kern.boottime"], timeout=5)
    m = re.search(r"sec\s*=\s*(\d+)", out)
    if code == 0 and m:
        return f"{(time.time() - int(m.group(1))) / 86400:.1f}"
    return None


def _battery_line() -> str:
    try:
        import psutil
        bat = psutil.sensors_battery()
        if bat:
            state = "charging" if bat.power_plugged else "on battery"
            return f"battery {bat.percent:.0f}% ({state})"
    except Exception:
        pass
    return ""


def _top_process() -> str:
    cmd = ["ps", "-Ao", "%cpu,comm", "-r"]
    code, out = _run(cmd, timeout=6)
    if code == 0:
        rows = [ln for ln in out.splitlines()[1:] if ln.strip()]
        if rows:
            parts = rows[0].split(None, 1)
            if len(parts) == 2:
                name = os.path.basename(parts[1])[:30]
                return f"top process: {name} at {float(parts[0]):.0f}% CPU"
    return ""


def _e_system_report(app, ctx) -> str:
    lines = ["System report, sir:"]
    cpu = _cpu_percent_psutil()
    if cpu is not None:
        lines.append(f"- CPU: {cpu:.0f}% in use")
    used, total = _mem_stats()
    if total:
        pct = used / total * 100 if used else 0.0
        lines.append(f"- Memory: {used} of {total} GB ({pct:.0f}%)")
    try:
        total_d, free_d = _disk_stats()
        lines.append(f"- Disk: {free_d:.0f} GB free of {total_d:.0f} GB")
    except Exception:
        pass
    up = _uptime_days()
    if up:
        lines.append(f"- Uptime: {up} days")
    bat = _battery_line()
    if bat:
        lines.append(f"- {bat.capitalize()}")
    top = _top_process()
    if top:
        lines.append(f"- {top}")
    if len(lines) == 1:
        return "I could not read the telemetry sensors, sir."
    return "\n".join(lines)


def _d_system_report(cmd):
    return {"cmd": cmd} if _SYS_REPORT_RE.search(cmd) else None


# ==========================================================================
# Git operations
# ==========================================================================

_GIT_STATUS_RE = re.compile(r"\bgit\s+(repo(sitory)?\s+)?status\b", re.I)
_GIT_ADD_RE = re.compile(r"\bgit\s+add\b\s*(.*)$", re.I)
_DIR_HINT_RE = re.compile(r"\bin\s+([\w~./\-]+)\s*$")


def _strip_dir_hint(cmd: str) -> str:
    return _DIR_HINT_RE.sub("", cmd).strip()


def _git_dir(ctx_cmd: str) -> str:
    m = _DIR_HINT_RE.search(ctx_cmd)
    if m:
        path = os.path.expanduser(m.group(1))
        if os.path.isdir(path):
            return path
    return PROJECT_DIR


_GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b(.*)$", re.I | re.S)
_COMMIT_FLAG_RE = re.compile(
    r"(?:^|\s)(?:-m\b|--message=?|-message\b|\bwith\s+message\b|"
    r"\bmessage\b|\bmsg\b)\s*", re.I)


def _extract_commit_msg(rest: str) -> Optional[str]:
    """Two-stage commit-message extraction tolerant of real phrasings."""
    rest = _COMMIT_FLAG_RE.sub(" ", rest, count=1).strip()
    if not rest:
        return None
    for q in ("\"", "'", "\u201c"):
        if rest.startswith(q):
            close = "\u201d" if q == "\u201c" else q
            end = rest.find(close, 1)
            msg = rest[1:end] if end != -1 else rest[1:]
            break
    else:
        msg = rest
    msg = msg.strip().strip("'\"").strip()
    return msg or None
_GIT_LOG_RE = re.compile(r"\bgit\s+(show\s+)?log\b", re.I)
_GIT_BRANCH_RE = re.compile(r"\bgit\s+(?:branch(es)?|current\s+branch)\b",
                            re.I)
_GIT_DIFF_RE = re.compile(r"\bgit\s+diff\b", re.I)
_DIR_HINT_RE = re.compile(r"\bin\s+([\w~./\-]+)\s*$")


def _git_dir(ctx_cmd: str) -> str:
    m = _DIR_HINT_RE.search(ctx_cmd)
    if m:
        path = os.path.expanduser(m.group(1))
        if os.path.isdir(path):
            return path
    return PROJECT_DIR


def _git_guard(path: str) -> Optional[str]:
    code, out = _run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                     timeout=6)
    if code != 0 or out.strip() != "true":
        return (f"That folder is not a git repository, sir"
                f"{' (' + path + ')' if path != PROJECT_DIR else ''}.")
    return None


def _e_git_status(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    code, branch = _run(["git", "-C", d, "rev-parse", "--abbrev-ref", "HEAD"],
                        timeout=6)
    code2, st = _run(["git", "-C", d, "status", "--porcelain"], timeout=8)
    if code != 0 or code2 != 0:
        return "git status failed, sir."
    dirty = [ln for ln in st.splitlines() if ln.strip()]
    summary = f"{len(dirty)} change(s)" if dirty else "clean working tree"
    return f"On branch {branch.strip()}: {summary}, sir." + \
        ("\n" + "\n".join(dirty[:10]) if dirty else "")


def _d_git_status(cmd):
    return {"cmd": cmd} if _GIT_STATUS_RE.search(cmd) else None


def _e_git_add(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    target = (ctx.get("rest") or "").strip() or "-A"
    code, out = _run(["git", "-C", d, "add"] + target.split(), timeout=10)
    if code != 0:
        return f"git add failed, sir: {out.splitlines()[0][:120]}"
    return f"Staged '{target}', sir."


def _d_git_add(cmd):
    stripped = _strip_dir_hint(cmd)
    m = _GIT_ADD_RE.search(stripped)
    if m:
        rest = (m.group(1) or "").strip()
        return {"cmd": cmd, "rest": rest}
    return None


def _e_git_commit(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    msg = ctx["msg"].strip().strip("'\"")
    if len(msg) < 3:
        return "Give me a proper commit message, sir - three characters minimum."
    code, out = _run(["git", "-C", d, "commit", "-m", msg], timeout=15)
    if code != 0:
        if "nothing to commit" in out:
            return "Nothing to commit - the working tree is clean, sir."
        first = out.splitlines()[0][:140] if out else "unknown error"
        return f"The commit was refused, sir: {first}"
    m = re.search(r"\[.*?\]\s*(.+)", out)
    head = m.group(1).strip() if m else msg[:60]
    files = re.findall(r"\d+ files? changed", out)
    extra = f" ({files[0]})" if files else ""
    return f"Committed: {head}{extra}, sir."


def _d_git_commit(cmd):
    m = _GIT_COMMIT_RE.search(_strip_dir_hint(cmd))
    if m:
        msg = _extract_commit_msg(m.group(1))
        if msg:
            return {"cmd": cmd, "msg": msg}
    return None


def _e_git_log(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    code, out = _run(["git", "-C", d, "log", "--oneline", "-7"], timeout=8)
    if code != 0:
        return "No commits yet, sir - this repository is brand new."
    return "Recent commits, newest first, sir:\n" + "\n".join(
        out.splitlines()[:7])


def _d_git_log(cmd):
    return {"cmd": cmd} if _GIT_LOG_RE.search(cmd) else None


def _e_git_branches(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    code, out = _run(["git", "-C", d, "branch", "--list"], timeout=6)
    if code != 0:
        return "Could not list branches, sir."
    branches = [ln.strip() for ln in out.splitlines() if ln.strip()]
    current = next((b.lstrip("* ") for b in branches if b.startswith("*")),
                   "?")
    others = [b.lstrip("* ").strip() for b in branches if
              not b.startswith("*")]
    reply = f"You are on '{current}'"
    if others:
        reply += "; other branches: " + ", ".join(others[:8])
    return reply + ", sir."


def _d_git_branches(cmd):
    return {"cmd": cmd} if _GIT_BRANCH_RE.search(cmd) else None


def _e_git_diff(app, ctx) -> str:
    d = _git_dir(ctx["cmd"])
    fail = _git_guard(d)
    if fail:
        return fail
    code, stat = _run(["git", "-C", d, "diff", "--stat"], timeout=8)
    if code != 0:
        return "git diff failed, sir."
    if not stat.strip():
        return "No unstaged changes to diff, sir."
    lines = stat.strip().splitlines()
    return "Unstaged changes, sir:\n" + "\n".join(lines[-6:])


def _d_git_diff(cmd):
    return {"cmd": cmd} if _GIT_DIFF_RE.search(cmd) else None


# ==========================================================================
# Docker operations
# ==========================================================================

_DOCKER_PS_RE = re.compile(r"\bdocker\s+(?:containers?\s+)?(ps|running)\b|^docker ps$",
                           re.I)
_DOCKER_IMG_RE = re.compile(r"\bdocker\s+images?\b", re.I)
_DOCKER_VER_RE = re.compile(r"\bdocker\s+version\b|\bis\s+docker\s+running\b",
                            re.I)


def _docker_missing() -> Optional[str]:
    if shutil.which("docker") is None:
        return ("Docker is not installed on this machine, sir - I can "
                "install it with 'brew install --cask docker' if you wish.")
    return None


def _e_docker_ps(app, ctx) -> str:
    miss = _docker_missing()
    if miss:
        return miss
    code, out = _run(["docker", "ps", "--format",
                      "{{.Names}}\t{{.Image}}\t{{.Status}}"], timeout=15)
    if code != 0:
        return "Docker did not respond - is Docker Desktop running, sir?"
    rows = [ln for ln in out.splitlines() if ln.strip()]
    if not rows:
        return "Docker is up but no containers are running, sir."
    listing = "\n".join(f"- {ln.replace(chr(9), ' | ')}" for ln in rows[:10])
    return f"{len(rows)} container(s) running, sir:\n{listing}"


def _d_docker_ps(cmd):
    return {"cmd": cmd} if (_DOCKER_PS_RE.search(cmd)) else None


def _e_docker_images(app, ctx) -> str:
    miss = _docker_missing()
    if miss:
        return miss
    code, out = _run(["docker", "images", "--format",
                      "{{.Repository}}:{{.Tag}}\t{{.Size}}"], timeout=15)
    if code != 0:
        return "Could not read the local image cache, sir."
    rows = [ln for ln in out.splitlines() if ln.strip()]
    if not rows:
        return "No docker images pulled yet, sir."
    listing = "\n".join(f"- {ln.replace(chr(9), ' (')})" for ln in rows[:10])
    return f"{len(rows)} image(s) cached locally, sir:\n{listing}"


def _d_docker_images(cmd):
    return {"cmd": cmd} if _DOCKER_IMG_RE.search(cmd) else None


def _e_docker_version(app, ctx) -> str:
    miss = _docker_missing()
    if miss:
        return miss
    code, out = _run(["docker", "version", "--format",
                      "{{.Server.Version}}"], timeout=12)
    if code != 0:
        return "Docker CLI exists but the daemon is unreachable, sir."
    return f"Docker daemon is running, version {out.strip()}, sir."


def _d_docker_version(cmd):
    return {"cmd": cmd} if _DOCKER_VER_RE.search(cmd) else None


# ==========================================================================
# Wikipedia
# ==========================================================================

_WIKI_RE = re.compile(r"\bwikipedia\s+(?:search\s+for\s+|on\s+)?(.{2,80})\b|"
                      r"\bwiki\s+(.{2,80})\b", re.I)


def _e_wiki(app, ctx) -> str:
    topic = ctx["topic"]
    if requests is None:
        return "My network layer is unavailable offline, sir."
    try:
        resp = _net_get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + topic.strip().replace(" ", "_"),
            timeout=6)
        if resp.status_code == 404:
            search = _net_get("https://en.wikipedia.org/w/api.php",
                              params={"action": "opensearch", "search":
                                      topic, "limit": 1, "format": "json"},
                              timeout=6)
            results = search.json()
            if results and len(results) > 1 and results[1]:
                return _wiki_reply(results[1][0])
            return (f"Wikipedia has no article titled '{topic}', sir.")
        resp.raise_for_status()
        title = resp.json().get("title", topic)
        extract = resp.json().get("extract", "")
        return _wiki_reply_from(title, extract)
    except Exception as exc:
        log.debug("wiki error: %s", exc)
        return ("I could not reach Wikipedia just now, sir - the network "
                "may be down. Try 'define <term>' for the local dictionary.")


def _wiki_reply(topic: str) -> str:
    try:
        resp = _net_get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + topic.strip().replace(" ", "_"), timeout=6)
        resp.raise_for_status()
        return _wiki_reply_from(resp.json().get("title", topic),
                                resp.json().get("extract", ""))
    except Exception:
        return _GENERIC_OFFLINE_NET


def _wiki_reply_from(title: str, extract: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", extract.strip())
    body = " ".join(sentences[:3]).strip()
    if not body:
        return (f"Wikipedia returned an empty summary for '{title}', sir.")
    return f"From Wikipedia, sir - {title}: {body}"


_GENERIC_OFFLINE_NET = ("The network request failed, sir - I cannot "
                        "reach that source right now.")


def _d_wiki(cmd):
    m = _WIKI_RE.search(cmd)
    if m:
        return {"cmd": cmd, "topic": (m.group(1) or m.group(2)).strip()}
    return None


# ==========================================================================
# Dictionary / thesaurus
# ==========================================================================

_DICT_DEFINE_RE = re.compile(
    r"\b(?:define|definition\s+of|meaning\s+of|dictionary)\s+([a-zA-Z\-']{2,30})\b",
    re.I)
_DICT_SYN_RE = re.compile(
    r"\b(?:synonyms?\s+(?:of|for)|thesaurus)\s+([a-zA-Z\-']{2,30})\b", re.I)
_DICT_ANT_RE = re.compile(r"\bantonyms?\s+(?:of|for)\s+([a-zA-Z\-']{2,30})\b",
                          re.I)


def _fetch_dict(word: str):
    resp = _net_get(
        f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}",
        timeout=6)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    return data[0] if isinstance(data, list) and data else None


def _e_define(app, ctx) -> str:
    word = ctx["word"]
    if requests is None:
        return _GENERIC_OFFLINE_NET
    try:
        entry = _fetch_dict(word)
    except Exception:
        return _GENERIC_OFFLINE_NET
    if not entry:
        return f"'{word}' is not in my online dictionary, sir."
    phon = ""
    meanings = entry.get("meanings", [])
    for ph in entry.get("phonetics", []):
        if ph.get("text"):
            phon = f" ({ph['text']})"
            break
    lines = [f"'{entry.get('word', word)}'{phon}, sir:"]
    for meaning in meanings[:2]:
        pos = meaning.get("partOfSpeech", "?")
        defs = meaning.get("definitions", [])
        if defs:
            line = f"- as a {pos}: {defs[0].get('definition', '')}"
            example = defs[0].get("example")
            if example:
                line += f" e.g. \"{example}\""
            lines.append(line)
    if len(lines) == 1:
        return f"No definitions found for '{word}', sir."
    return "\n".join(lines)


def _kb_thesaurus(word: str, mode: str) -> Optional[str]:
    """Offline fallback into brain_extra's curated synonym/antonym KB."""
    try:
        import brain_extra as _be
        table = getattr(_be, "SYNONYMS" if mode == "syn" else "ANTONYMS",
                        None)
        words = (table or {}).get(word.lower())
        if words:
            return f"{words[0].capitalize()} and {', '.join(words[1:4])}"
    except Exception:
        pass
    return None


def _e_thesaurus(app, ctx) -> str:
    word = ctx["word"]
    mode = ctx["mode"]
    label = "Synonyms" if mode == "syn" else "Antonyms"
    if requests is None:
        kb = _kb_thesaurus(word, mode)
        return (f"{label} for '{word}', sir - {kb}." if kb
                else _GENERIC_OFFLINE_NET)
    try:
        entry = _fetch_dict(word)
    except Exception:
        kb = _kb_thesaurus(word, mode)
        return (f"{label} for '{word}', sir - {kb}." if kb
                else _GENERIC_OFFLINE_NET)
    if not entry:
        return f"'{word}' is not in my online thesaurus, sir."
    collected: dict[str, list[str]] = {}
    for meaning in entry.get("meanings", []):
        for item in meaning.get(mode + "onyms", []) or []:
            w = item if isinstance(item, str) else item.get("word")
            if w and w.lower() != word.lower():
                bucket = meaning.get("partOfSpeech", "other")
                collected.setdefault(bucket, [])
                if w not in collected[bucket]:
                    collected[bucket].append(w)
    flat = [w for ws in collected.values() for w in ws]
    best = max(collected.values(), key=len) if collected else []
    # Curated-KB words lead each bucket so common senses survive the
    # display slice (dictionaryapi can bury "joyful" past position 6).
    try:
        import brain_extra as _be
        table = getattr(_be, "SYNONYMS" if mode == "syn" else "ANTONYMS",
                        None)
        kb_words = [w.lower() for w in
                    (table or {}).get(word.lower(), [])]
        if kb_words:
            for bucket in collected:
                collected[bucket].sort(
                    key=lambda w: w.lower() not in kb_words)
    except Exception:
        pass
    if len(best) < 2:
        kb_first = _kb_thesaurus(word, mode)
        if kb_first:
            return f"{label} for '{word}', sir - {kb_first}."
    if not flat:
        return (f"My thesaurus lists no {label.lower()} for '{word}', sir.")
    groups = "; ".join(f"{pos}: {', '.join(ws[:6])}"
                       for pos, ws in collected.items())
    return f"{label} for '{word}', sir - {groups}"


def _d_define(cmd):
    m = _DICT_DEFINE_RE.search(cmd)
    if m:
        return {"cmd": cmd, "word": m.group(1)}
    return None


def _d_synonyms(cmd):
    m = _DICT_SYN_RE.search(cmd)
    if m:
        return {"cmd": cmd, "word": m.group(1), "mode": "syn"}
    return None


def _d_antonyms(cmd):
    m = _DICT_ANT_RE.search(cmd)
    if m:
        return {"cmd": cmd, "word": m.group(1), "mode": "ant"}
    return None


# ==========================================================================
# News headlines (Hacker News front page)
# ==========================================================================

_NEWS_RE = re.compile(r"\b(news\s+headlines?|top\s+news|hacker\s+news|"
                      r"tech\s+news|latest\s+headlines?)\b", re.I)


def _e_news(app, ctx) -> str:
    if requests is None:
        return _GENERIC_OFFLINE_NET
    try:
        ids = _net_get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=6).json()[:6]
        lines = []
        for rank, story_id in enumerate(ids, 1):
            item = _net_get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json",
                timeout=6).json() or {}
            title = item.get("title", "?")
            score = item.get("score", 0)
            url = item.get("url", "")
            host = re.sub(r"^www\.", "", url.split("/")[2]) if url.count("/") >= 2 else ""
            lines.append(f"{rank}. {title} [{host}] ({score} pts)")
        if not lines:
            return "The news feed came back empty, sir."
        return "Front-page tech headlines, sir:\n" + "\n".join(lines)
    except Exception:
        return _GENERIC_OFFLINE_NET


def _d_news(cmd):
    return {"cmd": cmd} if _NEWS_RE.search(cmd) else None


# ==========================================================================
# Math solver: equations with steps, derivatives, integrals
# ==========================================================================

_SOLVE_LIN_RE = re.compile(r"\bsolve\s+(?:for\s+\w+\s*:?\s*)?([^=]+)=([^=]+)$",
                           re.I)
_DERIV_RE = re.compile(
    r"\b(?:derivative|differentiate)\s+of\s+(.+)$", re.I)
_INTEGRAL_RE = re.compile(
    r"\b(?:integral|integrate)\s+(?:of\s+)(.+)$", re.I)

_TERM_RE = re.compile(
    r"([+-]?)\s*(\d*\.\d+|\d+)?\s*\*?\s*x(?:\^\s*(-?\d+))?", re.I)


def _parse_poly(expr: str) -> Optional[dict[int, Fraction]]:
    """Parse a polynomial in x into {degree: coefficient}."""
    expr = expr.replace("-", "+-").replace(" ", "")
    if not expr:
        return None
    coeffs: dict[int, Fraction] = {}
    for raw in expr.split("+"):
        if not raw:
            continue
        m = re.fullmatch(
            r"([+-]?)(\d*\.\d+|\d+)?\*?(?:x(?:\^\s*(-?\d+))?)?", raw, re.I)
        if not m:
            return None
        sign = -1 if m.group(1) == "-" else 1
        num = m.group(2)
        power_s = m.group(3)
        has_x = "x" in raw.lower()
        if has_x:
            power = int(power_s) if power_s else 1
        else:
            if num is None:
                return None
            power = 0
        coeff = Fraction(num) if num else Fraction(1)
        coeffs[power] = coeffs.get(power, Fraction(0)) + sign * coeff
    return {k: v for k, v in coeffs.items() if v != 0}


def _fmt_frac(fr: Fraction) -> str:
    if fr.denominator == 1:
        return str(fr.numerator)
    return f"{fr.numerator}/{fr.denominator}"


def _poly_str(coeffs: dict[int, Fraction]) -> str:
    if not coeffs:
        return "0"
    parts = []
    for deg in sorted(coeffs, reverse=True):
        c = coeffs[deg]
        sign = "-" if c < 0 else "+"
        mag = abs(c)
        mag_s = _fmt_frac(mag)
        if deg == 0:
            term = mag_s
        elif deg == 1:
            term = f"{mag_s}x" if mag != 1 else "x"
        else:
            term = f"{mag_s}x^{deg}" if mag != 1 else f"x^{deg}"
        parts.append((sign, term))
    first_sign, first_term = parts[0]
    out = ("" if first_sign == "+" else "-") + first_term
    for sign, term in parts[1:]:
        out += f" {sign} {term}"
    return out


def _solve_linear(a: Fraction, b: Fraction,
                  c: Fraction, d: Fraction) -> Optional[str]:
    """Solve ax+b = cx+d."""
    A = a - c
    D = d - b
    if A == 0:
        if D == 0:
            return ("Both sides are identical, sir - every value of x "
                    "is a solution (infinite solutions).")
        return "The equation reduces to a contradiction, sir - no solution exists."
    x = D / A
    check_left = a * x + b
    check_right = c * x + d
    if check_left != check_right:
        log.warning("linear verify mismatch")
        return None
    lhs_terms = f"{_fmt_frac(a)}x" + (_pm(-c) if c else "")
    rhs_terms = f"{_fmt_frac(d)}" + (_pm(-b) if b else "")
    return ("Solving the linear equation, sir:\n"
            f"Step 1: collect terms - {lhs_terms} = {rhs_terms}\n"
            f"Step 2: {_fmt_frac(A)}x = {_fmt_frac(D)}\n"
            f"Step 3: divide both sides by {_fmt_frac(A)}\n"
            f"=> x = {_fmt_frac(x)}, sir.\n"
            f"Check: left = right = {_fmt_frac(check_left)}.")


def _pm(v: Fraction) -> str:
    v = -v
    return f" {'+' if v >= 0 else '-'} {_fmt_frac(abs(v))}"


def _solve_quadratic(a: Fraction, b: Fraction, c: Fraction) -> Optional[str]:
    disc = b * b - 4 * a * c
    two_a = 2 * a
    steps = [
        "Recognised the quadratic form ax^2 + bx + c = 0.",
        f"Discriminant = b^2 - 4ac = {_fmt_frac(b*b)} - "
        f"{_fmt_frac(4*a*c)} = {_fmt_frac(disc)}.",
    ]
    if disc > 0:
        root_disc = _isqrt_fraction(disc)
        steps.append("Discriminant is positive: two distinct real roots.")
        if root_disc is not None:
            x1 = (-b + root_disc) / two_a
            x2 = (-b - root_disc) / two_a
            for xv in (x1, x2):
                if a * xv * xv + b * xv + c != 0:
                    log.warning("quadratic verify mismatch")
                    return None
            steps += [
                f"x = (-b +/- sqrt(D)) / 2a = "
                f"({_fmt_frac(-b)} +/- {_fmt_frac(root_disc)}) / "
                f"{_fmt_frac(two_a)}",
                f"=> x = {_fmt_frac(x1)} or x = {_fmt_frac(x2)}, sir.",
            ]
        else:
            steps.append("sqrt(D) is irrational - exact roots stay in "
                         f"radical form: x = ({_fmt_frac(-b)} +/- sqrt("
                         f"{_fmt_frac(disc)})) / {_fmt_frac(two_a)}, sir.")
    elif disc == 0:
        x = -b / two_a
        if a * x * x + b * x + c != 0:
            return None
        steps += [f"One repeated root: x = -b/2a = {_fmt_frac(x)}, sir."]
    else:
        real = -b / two_a
        imag_mag = (-disc) ** Fraction(1, 2) if False else None
        steps += [
            "Discriminant is negative: complex conjugate roots, sir.",
            f"x = ({_fmt_frac(-b)} +/- i*sqrt({_fmt_frac(-disc)})) / "
            f"{_fmt_frac(two_a)}.",
        ]
    return "Solving the quadratic, sir:\n" + "\n".join(steps)


def _isqrt_fraction(value: Fraction) -> Optional[Fraction]:
    """Exact integer square root of a nonneg rational square, else None."""
    num, den = value.numerator, value.denominator
    rn, rd = _isqrt(num), _isqrt(den)
    if rn is not None and rd is not None:
        return Fraction(rn, rd)
    return None


def _isqrt(n: int) -> Optional[int]:
    if n < 0:
        return None
    r = int(n ** 0.5)
    for cand in (r - 1, r, r + 1):
        if cand >= 0 and cand * cand == n:
            return cand
    return None


def _derivative(coeffs: dict[int, Fraction]) -> dict[int, Fraction]:
    out = {}
    for deg, c in coeffs.items():
        if deg >= 1:
            out[deg - 1] = out.get(deg - 1, Fraction(0)) + c * deg
    return {k: v for k, v in out.items() if v != 0}


def _integral(coeffs: dict[int, Fraction]) -> dict[int, Fraction]:
    out = {deg + 1: c / (deg + 1) for deg, c in coeffs.items()}
    return out


def _e_solve(app, ctx) -> Optional[str]:
    lhs_raw, rhs_raw = ctx["lhs"], ctx["rhs"]
    lhs = _parse_poly(lhs_raw)
    rhs = _parse_poly(rhs_raw)
    if lhs is None and rhs is None:
        # Not an equation in x at all — let other skills handle it.
        return None
    if lhs is None or rhs is None:
        return ("I can solve linear and quadratic equations in one "
                "variable, sir - e.g. 'solve 2x + 5 = 13' or "
                "'solve x^2 - 5x + 6 = 0'.")
    lmax = max(lhs, key=int) if lhs else 0
    rmax = max(rhs, key=int) if rhs else 0
    if max(lmax, rmax) > 2:
        return ("That degree exceeds my local solver, sir - I handle up "
                "to quadratics locally; give me an API key for more.")
    a = lhs.get(2, Fraction(0)) - rhs.get(2, Fraction(0))
    b = lhs.get(1, Fraction(0)) - rhs.get(1, Fraction(0))
    c = lhs.get(0, Fraction(0)) - rhs.get(0, Fraction(0))
    if a != 0:
        return _solve_quadratic(a, b, c)
    return _solve_linear(lhs.get(1, Fraction(0)), lhs.get(0, Fraction(0)),
                         rhs.get(1, Fraction(0)), rhs.get(0, Fraction(0)))


def _d_solve(cmd):
    m = _SOLVE_LIN_RE.search(cmd)
    if m:
        lhs, rhs = m.group(1), m.group(2)
        # Require at least one side to look like a polynomial in x so
        # casual "a = b" sentences never hijack the solver.
        if "x" in lhs.lower() or "x" in rhs.lower():
            return {"cmd": cmd, "lhs": lhs, "rhs": rhs}
    return None


def _e_derivative(app, ctx) -> str:
    expr = ctx["expr"].strip().rstrip("?")
    coeffs = _parse_poly(expr)
    if coeffs is None:
        return ("Give me a simple polynomial in x, sir - e.g. "
                "'derivative of 3x^3 + 2x'.")
    deriv = _derivative(coeffs)
    result = _poly_str(deriv) if deriv else "0"
    verify = _verify_derivative(coeffs, deriv)
    if not verify:
        log.warning("derivative verify mismatch")
        return None
    steps = "; ".join(
        f"d/dx({_fmt_frac(c)}·x^{d}) = {_fmt_frac(c * d)}·x^{d - 1}"
        for d, c in sorted(coeffs.items(), reverse=True) if d >= 1) or \
        "constants differentiate to zero"
    return (f"Differentiating term by term (power rule): {steps}.\n"
            f"=> d/dx [{_poly_str(coeffs)}] = {result}, sir.")


def _verify_derivative(coeffs: dict[int, Fraction],
                       deriv: dict[int, Fraction]) -> bool:
    """Exact check: symbolically re-integrate the derivative and compare
    with the original polynomial (the constant may differ)."""
    reint: dict[int, Fraction] = {}
    for deg, c in deriv.items():
        reint[deg + 1] = reint.get(deg + 1, Fraction(0)) + c / (deg + 1)
    if set(reint) - set(coeffs):
        return False
    return all(reint.get(deg, Fraction(0)) == c
               for deg, c in coeffs.items() if deg != 0)


def _d_derivative(cmd):
    m = _DERIV_RE.search(cmd)
    if m:
        return {"cmd": cmd, "expr": m.group(1)}
    return None


def _e_integral(app, ctx) -> str:
    expr = ctx["expr"].strip().rstrip("?")
    coeffs = _parse_poly(expr)
    if coeffs is None:
        return ("Give me a simple polynomial in x, sir - e.g. "
                "'integral of 3x^2 + 4x'.")
    anti = _integral(coeffs)
    body = _poly_str(anti) if any(v != 0 for v in anti.values()) else "0"
    return (f"Integrating term by term (power rule, +C implied):\n"
            f"=> ∫ [{_poly_str(coeffs)}] dx = {body} + C, sir.")


def _d_integral(cmd):
    m = _INTEGRAL_RE.search(cmd)
    if m:
        return {"cmd": cmd, "expr": m.group(1)}
    return None


# ==========================================================================
# API testing
# ==========================================================================

_API_TEST_RE = re.compile(
    r"\b(?:test|check|hit|ping|call)\s+(?:the\s+)?(?:api\s+)?"
    r"(https?://[^\s\"']+)", re.I)


def _e_api_test(app, ctx) -> str:
    url = ctx["url"]
    if requests is None:
        return _GENERIC_OFFLINE_NET
    started = time.perf_counter()
    try:
        resp = _net_get(url, timeout=8)
    except Exception:
        return f"The endpoint at {url} did not respond, sir."
    elapsed_ms = (time.perf_counter() - started) * 1000
    ctype = resp.headers.get("content-type", "unknown")
    size = len(resp.content)
    verdict = "healthy" if resp.status_code == 200 else \
        f"responding with status {resp.status_code}"
    body_note = ""
    if "application/json" in ctype:
        try:
            resp.json()
            body_note = " valid JSON confirmed."
        except ValueError:
            body_note = " but the JSON body failed to parse, sir!"
    return (f"API probe complete, sir: {verdict} in {elapsed_ms:.0f} ms - "
            f"{ctype.split(';')[0]}, {size:,} bytes.{body_note}")


def _d_api_test(cmd):
    m = _API_TEST_RE.search(cmd)
    if m:
        return {"cmd": cmd, "url": m.group(1)}
    return None


# ==========================================================================
# SQLite read-only queries
# ==========================================================================

_SQL_RE = re.compile(
    r"\bsqlite\s+(?:query\s+)?(\S+\.db(?:sqlite3?)?)\s+(.+)$", re.I)


def _e_sqlite(app, ctx) -> str:
    import sqlite3
    raw = ctx["dbfile"]
    db_path = raw if os.path.isabs(raw) else os.path.join(PROJECT_DIR, raw)
    query = ctx["query"].strip().rstrip(";")
    if not re.match(r"(?is)^(\s*)(select|with)\b", query):
        return ("Read-only SELECT/WITH queries only, sir - I will not "
                "mutate databases by voice.")
    if not os.path.isfile(db_path):
        return f"No database file at {db_path}, sir."
    uri = "file:" + db_path + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            cur = conn.execute(query)
            rows = cur.fetchmany(21)
            cols = [d[0] for d in cur.description] or []
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return f"The query failed, sir: {exc}"
    if not rows:
        return "Query executed fine - zero rows returned, sir."
    truncated = len(rows) > 20
    shown = rows[:20]
    header = " | ".join(cols) if cols else "(no columns)"
    lines = [header, "-" * min(len(header), 60)]
    for row in shown:
        cells = [("NULL" if v is None else str(v)[:28]) for v in row]
        lines.append(" | ".join(cells))
    note = f"\n(showing 20 of {len(rows)}+ rows)" if truncated else ""
    return f"{len(rows)} row(s), sir:\n" + "\n".join(lines) + note


def _d_sqlite(cmd):
    m = _SQL_RE.search(cmd)
    if m:
        return {"cmd": cmd, "dbfile": m.group(1), "query": m.group(2)}
    return None


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("ps_clipboard_history", _d_clip_history, _e_clip_history, False),
    ("ps_clipboard_paste", _d_clip_paste, _e_clip_paste, False),
    ("ps_clipboard_clear", _d_clip_clear, _e_clip_clear, False),
    ("ps_clipboard_copy", _d_clip_copy, _e_clip_copy, False),
    ("ps_system_report", _d_system_report, _e_system_report, False),
    ("ps_git_status", _d_git_status, _e_git_status, False),
    ("ps_git_add", _d_git_add, _e_git_add, False),
    ("ps_git_commit", _d_git_commit, _e_git_commit, False),
    ("ps_git_log", _d_git_log, _e_git_log, False),
    ("ps_git_branches", _d_git_branches, _e_git_branches, False),
    ("ps_git_diff", _d_git_diff, _e_git_diff, False),
    ("ps_docker_ps", _d_docker_ps, _e_docker_ps, False),
    ("ps_docker_images", _d_docker_images, _e_docker_images, False),
    ("ps_docker_version", _d_docker_version, _e_docker_version, False),
    ("ps_wikipedia", _d_wiki, _e_wiki, False),
    ("ps_define", _d_define, _e_define, False),
    ("ps_synonyms", _d_synonyms, _e_thesaurus, False),
    ("ps_antonyms", _d_antonyms, _e_thesaurus, False),
    ("ps_news", _d_news, _e_news, False),
    ("ps_solve_equation", _d_solve, _e_solve, False),
    ("ps_derivative", _d_derivative, _e_derivative, False),
    ("ps_integral", _d_integral, _e_integral, False),
    ("ps_api_test", _d_api_test, _e_api_test, False),
    ("ps_sqlite_query", _d_sqlite, _e_sqlite, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all power skills with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        wrapped = _wrap(execute, name)
        brain.register(name, detect, wrapped, priority=priority)
    log.info("power skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return f"Something misfired in my {name.replace('ps_', '')} module, sir: {exc}"
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
