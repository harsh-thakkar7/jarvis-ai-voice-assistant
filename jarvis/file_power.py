"""FILE POWER TOOLS: deep file surgery anywhere on disk, safely."""

import difflib
import os
import re
import shutil
import sys
import time

from jarvis_logging import get_logger

log = get_logger("file_power")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
PROTECTED_PREFIXES = (
    "/System",
    "/bin",
    "/sbin",
    "/usr",
    "/etc",
    # macOS symlink targets: /etc -> /private/etc, /tmp -> /private/tmp, ...
    "/private/etc",
    "/private/bin",
    "/private/sbin",
    "/private/usr",
    "/private/var",
    "/Library/System",
)
SKIP_DIRS = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    "node_modules",
    ".idea",
    ".Trash",
}

MAX_SEARCH_HITS = 40
MAX_TREE_ENTRIES = 120
HEAD_TAIL_CAP = 60
FULL_READ_CAP = 200
DIFF_CAP = 80
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024


def _err(skill, e):
    return "I'm terribly sorry, sir — %s stumbled: %s" % (skill, e)


def _missing(path):
    return "I couldn't find %s, sir." % _disp(path)


def _protected_msg(path):
    return (
        "I'm afraid I can't touch %s, sir — it sits in a protected "
        "system area and I won't modify it." % _disp(path)
    )


def _disp(path):
    path = os.path.abspath(path)
    home = os.path.expanduser("~")
    proj = os.path.abspath(PROJECT_DIR)
    if path == proj or path.startswith(proj.rstrip(os.sep) + os.sep):
        rel = os.path.relpath(path, proj)
        return "." if rel == "." else rel.replace(os.sep, "/")
    if path == home or path.startswith(home.rstrip(os.sep) + os.sep):
        return "~" + path[len(home):].replace(os.sep, "/")
    return path.replace(os.sep, "/")


def _unquote(s):
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"`":
        q = s[0]
        inner = s[1:-1]
        inner = inner.replace("\\" + q, q).replace("\\\\", "\\")
        return inner.strip()
    return s


def _resolve(raw):
    s = (raw or "").strip().strip("`").strip()
    s = _unquote(s)
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.I).strip()
    s = re.sub(r"^at\s+", "", s, flags=re.I).strip()
    s = s.strip("'\"`").strip()
    s = os.path.expanduser(s)
    if not os.path.isabs(s):
        s = os.path.join(PROJECT_DIR, s)
    return os.path.normpath(s)


def _protected(path):
    try:
        rp = os.path.realpath(path)
    except Exception:
        return False
    proj = os.path.realpath(PROJECT_DIR)
    if rp == proj or rp.startswith(proj.rstrip(os.sep) + os.sep):
        return False
    for p in PROTECTED_PREFIXES:
        p = p.rstrip("/")
        if rp == p or rp.startswith(p + "/"):
            return True
    return False


def _backup(path):
    if not os.path.exists(path):
        return None
    cand = path + ".bak"
    i = 2
    while os.path.exists(cand):
        cand = "%s.bak.%d" % (path, i)
        i += 1
    try:
        shutil.copy2(path, cand)
        log.info("backup %s -> %s", path, cand)
        return cand
    except Exception as e:
        log.warning("backup failed for %s: %s", path, e)
        return None


def _line_numbered(lines, start=1):
    return "\n".join("%4d | %s" % (i, ln) for i, ln in enumerate(lines, start))


def _cap(text, n=80, label="lines"):
    lines = text.splitlines() if isinstance(text, str) else list(text)
    if len(lines) <= n:
        return "\n".join(lines)
    extra = len(lines) - n
    return "\n".join(lines[:n]) + (
        "\n… trimmed to the first %d %s, sir — %d more remain unshown." % (n, label, extra)
    )


def _is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except OSError:
        return False


def _read_lines(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def _looks_like_path(s):
    s = (s or "").strip()
    if not s:
        return False
    if "/" in s or s.startswith("~"):
        return True
    return bool(re.search(r"[A-Za-z0-9_.\-]+\.[A-Za-z0-9]{1,12}(\s|$)", s))


def _detector(fn):
    def detect(cmd):
        try:
            return fn(cmd or "")
        except Exception:
            log.exception("detector %s crashed", getattr(fn, "__name__", fn))
            return None

    detect.__name__ = "detect_" + getattr(fn, "__name__", "skill")
    return detect


def _executor(skill_name, fn):
    def execute(app, ctx):
        try:
            return fn(app, ctx)
        except Exception as e:
            log.exception("skill %s failed", skill_name)
            return _err(skill_name, e)

    execute.__name__ = "execute_" + skill_name
    return execute


def _scan_top_level(s):
    seps = []
    i, n = 0, len(s)
    quote = None
    while i < n:
        ch = s[i]
        if quote:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            i += 1
            continue
        matched = False
        for sep, tag in ((" with ", "with"), (" in ", "in")):
            if s.startswith(sep, i):
                seps.append((i, tag))
                i += len(sep)
                matched = True
                break
        if not matched:
            i += 1
    return seps


def _parse_replace_args(s):
    seps = _scan_top_level(s)
    wpos = next((p for p, tag in seps if tag == "with"), None)
    if wpos is not None:
        ins = [p for p, tag in seps if tag == "in" and p > wpos]
        if ins:
            ipos = ins[-1]
            old = _unquote(s[:wpos])
            new = _unquote(s[wpos + 6:ipos])
            path = s[ipos + 4:].strip()
            if old and path:
                return old, new, path
    if " with " in s:
        left, right = s.split(" with ", 1)
        if " in " in right:
            new, path = right.rsplit(" in ", 1)
            old = left.strip()
            new = new.strip()
            path = path.strip()
            if old and path:
                return _unquote(old), _unquote(new), path
    return None


def _iter_search_files(base):
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
        )
        for fn in sorted(files):
            yield os.path.join(root, fn)


def _tree_rows(base, depth=3, cap=MAX_TREE_ENTRIES):
    rows = []
    counts = [0, 0]
    truncated = [False]

    def rec(d, prefix, level):
        if truncated[0]:
            return
        try:
            names = sorted(os.listdir(d), key=str.lower)
        except OSError:
            return
        names = [n for n in names if n not in SKIP_DIRS]
        items = [(n, os.path.isdir(os.path.join(d, n))) for n in names]
        items.sort(key=lambda t: (not t[1], t[0].lower()))
        for idx, (name, is_dir) in enumerate(items):
            if len(rows) >= cap:
                truncated[0] = True
                return
            last = idx == len(items) - 1
            conn = "`-- " if last else "|-- "
            rows.append(prefix + conn + name + ("/" if is_dir else ""))
            if is_dir:
                counts[1] += 1
                if level < depth:
                    rec(
                        os.path.join(d, name),
                        prefix + ("    " if last else "|   "),
                        level + 1,
                    )
            else:
                counts[0] += 1

    rows.append(os.path.basename(os.path.abspath(base)).rstrip("/") + "/")
    rec(base, "", 1)
    return rows, counts, truncated[0]


def _d_head(cmd):
    c = cmd.lower().strip()
    m = re.search(r"\bfirst\s+(\d+)\s+lines?\s+(?:of|from|in)\s+(.+)", c)
    if m:
        return {"cmd": cmd, "n": int(m.group(1)), "raw": m.group(2)}
    m = re.match(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?head\s+(?:of\s+)?(?:the\s+)?"
        r"(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "n": HEAD_TAIL_CAP, "raw": m.group(1)}
    m = re.match(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?top\s+of\s+(?:the\s+)?"
        r"(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "n": HEAD_TAIL_CAP, "raw": m.group(1)}
    m = re.match(r"^peek\s+at\s+(?:the\s+)?(?:file\s+)?(.+)$", c)
    if m:
        return {"cmd": cmd, "n": HEAD_TAIL_CAP, "raw": m.group(1)}
    return None


def _e_head(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    n = max(1, int(ctx.get("n", HEAD_TAIL_CAP)))
    lines = _read_lines(p)
    take = lines[:n]
    numbered = _line_numbered(take, 1).splitlines()
    out = "\n".join(numbered)
    if extra := (len(lines) - len(take)):
        out += "\n… trimmed, sir — %d more line(s) remain unshown." % extra
    return "Top of %s, sir:\n%s" % (_disp(p), out)


def _d_tail(cmd):
    c = cmd.lower().strip()
    m = re.search(r"\blast\s+(\d+)\s+lines?\s+(?:of|from|in)\s+(.+)", c)
    if m:
        return {"cmd": cmd, "n": int(m.group(1)), "raw": m.group(2)}
    m = re.match(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?tail\s+(?:of\s+)?(?:the\s+)?"
        r"(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "n": HEAD_TAIL_CAP, "raw": m.group(1)}
    m = re.match(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?end\s+of\s+(?:the\s+)?"
        r"(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "n": HEAD_TAIL_CAP, "raw": m.group(1)}
    return None


def _e_tail(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    n = max(1, int(ctx.get("n", HEAD_TAIL_CAP)))
    lines = _read_lines(p)
    take = lines[-n:]
    start = max(1, len(lines) - len(take) + 1)
    numbered = _line_numbered(take, start).splitlines()
    out = "\n".join(numbered)
    if len(lines) > len(take):
        out += "\n… trimmed, sir — %d earlier line(s) remain unshown." % (
            len(lines) - len(take)
        )
    return "End of %s, sir:\n%s" % (_disp(p), out)


def _d_range(cmd):
    c = cmd.lower().strip()
    m = re.search(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?lines?\s+(\d+)\s*"
        r"(?:to|-|\u2013|\u2014)\s*(\d+)\s+(?:of|in|from)\s+"
        r"(?:the\s+)?(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {
            "cmd": cmd,
            "a": int(m.group(1)),
            "b": int(m.group(2)),
            "raw": m.group(3),
        }
    return None


def _e_range(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    a, b = int(ctx["a"]), int(ctx["b"])
    lines = _read_lines(p)
    if a < 1 or a > b:
        return (
            "I'm afraid that range is upside down, sir — %d to %d won't do; "
            "line numbers start at 1 and ascend." % (a, b)
        )
    if b > len(lines):
        return (
            "Those lines lie beyond the end of %s (%d lines), sir — "
            "I can't show what isn't there." % (_disp(p), len(lines))
        )
    seg = lines[a - 1:b]
    numbered = _line_numbered(seg, a).splitlines()
    return "Lines %d–%d of %s, sir:\n%s" % (
        a,
        b,
        _disp(p),
        _cap(numbered, HEAD_TAIL_CAP, "lines"),
    )


def _d_full(cmd):
    c = cmd.lower().strip()
    m = re.match(
        r"^(?:please\s+)?(?:show\s+(?:me\s+)?)?(?:the\s+)?"
        r"(?:entire\s+|whole\s+|full\s+)?contents?\s+of\s+(?:the\s+)?"
        r"(?:file\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(r"^(?:please\s+)?(?:dump|cat)\s+(?:the\s+)?(?:file\s+)?(.+)$", c)
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(r"^(?:please\s+)?read\s+(?:the\s+)?(?:file\s+)?(.+)$", c)
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_full(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    if _is_binary(p):
        size = os.path.getsize(p)
        return (
            "That appears to be a binary file, sir — %s holds %s bytes of "
            "non-text data; I shan't pour gibberish into your eyes."
            % (_disp(p), format(size, ","))
        )
    lines = _read_lines(p)
    numbered = _line_numbered(lines, 1).splitlines()
    return "Contents of %s, sir:\n%s" % (
        _disp(p),
        _cap(numbered, FULL_READ_CAP, "lines"),
    )


_WRITE_PATTERNS = (
    r"^write\s+(?:a\s+)?(?:new\s+)?file\s+(.+?)\s+(?:with|containing)\s*:?\s*(.+)$",
    r"^create\s+(?:a\s+)?(?:new\s+)?file\s+(.+?)\s+(?:with|containing)\s*:?\s*(.+)$",
    r"^overwrite\s+(?:the\s+)?(?:file\s+)?(.+?)\s+with\s*:?\s*(.+)$",
    r"^put\s+this\s+in\s+(?:the\s+)?(?:file\s+)?(.+?)\s*:\s*(.+)$",
)


def _d_write(cmd):
    s = cmd.strip()
    for pat in _WRITE_PATTERNS:
        m = re.match(pat, s, re.I | re.S)
        if m:
            content = m.group(2).replace("\\n", "\n")
            return {"cmd": cmd, "raw": m.group(1), "content": content}
    return None


def _e_write(app, ctx):
    p = _resolve(ctx["raw"])
    if _protected(p):
        return _protected_msg(p)
    content = ctx["content"]
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    bk = _backup(p)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    nbytes = len(content.encode("utf-8"))
    nlines = len(content.splitlines())
    reply = "Done, sir — %s bytes across %d line(s) written to %s." % (
        format(nbytes, ","),
        nlines,
        _disp(p),
    )
    if bk:
        reply += " A backup of the previous version is at %s." % _disp(bk)
    log.info("wrote %s (%d bytes)", p, nbytes)
    return reply


def _d_append(cmd):
    s = cmd.strip()
    m = re.match(
        r"^append\s+(.+?)\s+to\s+(?:the\s+)?(?:file\s+)?(.+)$", s, re.I | re.S
    )
    if m:
        return {"cmd": cmd, "raw": m.group(2), "text": m.group(1)}
    m = re.match(
        r"^add\s+(?:a\s+)?line\s+(.+?)\s+to\s+(?:the\s+)?(?:file\s+)?(.+)$",
        s,
        re.I | re.S,
    )
    if m:
        return {"cmd": cmd, "raw": m.group(2), "text": m.group(1)}
    return None


def _e_append(app, ctx):
    p = _resolve(ctx["raw"])
    if _protected(p):
        return _protected_msg(p)
    text = ctx["text"].replace("\\n", "\n")
    existed = os.path.exists(p)
    if existed:
        bk = _backup(p)
    else:
        bk = None
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
    prefix = ""
    if existed and os.path.getsize(p) > 0:
        with open(p, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                prefix = "\n"
    with open(p, "a", encoding="utf-8", newline="") as f:
        f.write(prefix + text + "\n")
    verb = "Appended" if existed else "Created %s and appended" % _disp(p)
    reply = "%s to %s, sir." % (verb, _disp(p)) if existed else (
        "The file did not exist, so I created it and appended your text, sir — %s."
        % _disp(p)
    )
    if bk:
        reply += " Backup of the prior version: %s." % _disp(bk)
    return reply


def _d_replace(cmd):
    m = re.match(r"^replace\s+(.+)$", cmd.strip(), re.I | re.S)
    if not m:
        return None
    parsed = _parse_replace_args(m.group(1))
    if not parsed:
        return None
    old, new, path = parsed
    return {"cmd": cmd, "old": old, "new": new, "raw": path}


def _e_replace(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    if _protected(p):
        return _protected_msg(p)
    old, new = ctx["old"], ctx["new"]
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    count = content.count(old)
    if count == 0:
        return "nothing matched, sir — 0 replacements made in %s." % _disp(p)
    bk = _backup(p)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content.replace(old, new))
    reply = "Made %d replacement(s) in %s, sir." % (count, _disp(p))
    if bk:
        reply += " Backup: %s." % _disp(bk)
    log.info("replaced %d occurrence(s) in %s", count, p)
    return reply


def _d_insert(cmd):
    s = cmd.strip()
    m = re.search(
        r"\binsert\s+(.+?)\s+at\s+line\s+(\d+)\s+in\s+(.+)$", s, re.I | re.S
    )
    if m:
        return {
            "cmd": cmd,
            "text": _unquote(m.group(1)),
            "pos": int(m.group(2)),
            "raw": m.group(3),
            "mode": "at",
        }
    m = re.search(
        r"\badd\s+(.+?)\s+after\s+line\s+(\d+)\s+in\s+(.+)$", s, re.I | re.S
    )
    if m:
        return {
            "cmd": cmd,
            "text": _unquote(m.group(1)),
            "pos": int(m.group(2)),
            "raw": m.group(3),
            "mode": "after",
        }
    return None


def _e_insert(app, ctx):
    p = _resolve(ctx["raw"])
    if _protected(p):
        return _protected_msg(p)
    mode = ctx["mode"]
    pos = int(ctx["pos"])
    if mode == "after":
        pos += 1
    lines = _read_lines(p) if os.path.exists(p) else []
    if pos < 1 or pos > len(lines) + 1:
        return (
            "That line number is out of bounds, sir — %s holds %d line(s), "
            "so I can only place text between 1 and %d."
            % (_disp(p), len(lines), len(lines) + 1)
        )
    bk = _backup(p) if os.path.exists(p) else None
    lines.insert(pos - 1, ctx["text"])
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write("".join(ln + "\n" for ln in lines))
    reply = "Inserted your text at line %d of %s, sir." % (pos, _disp(p))
    if bk:
        reply += " Backup: %s." % _disp(bk)
    return reply


def _d_delete_lines(cmd):
    c = cmd.lower().strip()
    m = re.search(
        r"\bdelete\s+lines?\s+(\d+)(?:\s*(?:to|-|\u2013|\u2014)\s*(\d+))?\s+"
        r"(?:in|of|from)\s+(?:the\s+)?(?:file\s+)?(.+)$",
        c,
    )
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a:
            a, b = b, a
        return {"cmd": cmd, "a": a, "b": b, "raw": m.group(3)}
    return None


def _e_delete_lines(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    if _protected(p):
        return _protected_msg(p)
    a, b = int(ctx["a"]), int(ctx["b"])
    lines = _read_lines(p)
    if a < 1 or b > len(lines) or a > b:
        return (
            "That span is out of bounds, sir — %s holds %d line(s); "
            "valid deletions run from line 1 to %d."
            % (_disp(p), len(lines), len(lines))
        )
    bk = _backup(p)
    removed = lines[a - 1:b]
    kept = lines[:a - 1] + lines[b:]
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write("".join(ln + "\n" for ln in kept))
    snippet = "; ".join(removed[:3]) + ("…" if len(removed) > 3 else "")
    reply = "Removed %d line(s) (%d–%d) from %s, sir — gone: %s." % (
        len(removed),
        a,
        b,
        _disp(p),
        snippet,
    )
    if bk:
        reply += " Backup: %s." % _disp(bk)
    log.info("deleted lines %d-%d from %s", a, b, p)
    return reply


def _d_delete_file(cmd):
    c = cmd.lower().strip()
    m = re.match(
        r"^(?:please\s+)?(?:delete|remove)\s+(?:the\s+)?file\s+(?:at\s+)?(.+)$", c
    )
    if m:
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(r"^(?:please\s+)?trash\s+(?:the\s+)?(?:file\s+)?(?:at\s+)?(.+)$", c)
    if m:
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_delete_file(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.exists(p):
        return _missing(p)
    if os.path.isdir(p):
        return (
            "That's a folder, sir — 'delete folder' is unsupported here; "
            "directories are beyond my delicate touch. Please use the shell "
            "skill (rm -r) for %s." % _disp(p)
        )
    if _protected(p):
        return _protected_msg(p)
    if sys.platform == "darwin":
        trash = os.path.expanduser("~/.Trash")
        try:
            os.makedirs(trash, exist_ok=True)
            target = os.path.join(trash, os.path.basename(p))
            if os.path.lexists(target):
                stamp = time.strftime("%Y%m%d-%H%M%S")
                target = "%s.%s" % (target, stamp)
                while os.path.lexists(target):
                    target += "x"
            shutil.move(p, target)
            log.info("trashed %s -> %s", p, target)
            return "Sent %s to the Trash, sir — recoverable should you repent." % (
                _disp(p)
            )
        except OSError as e:
            # Safety mechanism failed: never fall through to an
            # irreversible delete — surface the failure instead.
            log.warning("Trash move failed for %s: %s", p, e)
            return ("I could not move %s to the Trash, sir (%s). "
                    "Nothing was deleted — delete it manually once you "
                    "have checked the volume." % (_disp(p), e))
    try:
        os.unlink(p)
        log.info("deleted %s", p)
        return "Deleted %s, sir." % _disp(p)
    except OSError as e:
        return _err("fp_delete_file", e)


def _d_copy(cmd):
    c = cmd.lower().strip()
    # Clipboard intents belong to the clipboard skills, not file copy.
    if "clipboard" in c:
        return None
    m = re.match(r"^(?:please\s+)?(?:copy|clone)\s+(.+?)\s+to\s+(.+)$", c, re.S)
    if m:
        return {"cmd": cmd, "src": m.group(1), "dst": m.group(2), "verb": "copy"}
    return None


def _d_move(cmd):
    c = cmd.lower().strip()
    m = re.match(
        r"^(?:please\s+)?(?:move|rename)\s+(?:the\s+)?(?:file\s+)?(.+?)\s+to\s+(.+)$",
        c,
        re.S,
    )
    if m:
        return {"cmd": cmd, "src": m.group(1), "dst": m.group(2), "verb": "move"}
    return None


def _e_copy_or_move(app, ctx):
    verb = ctx["verb"]
    src = _resolve(ctx["src"])
    dst = _resolve(ctx["dst"])
    if not os.path.exists(src):
        return _missing(src)
    if os.path.isdir(src):
        return (
            "%s is a folder, sir — I only ferry individual files; "
            "please use the shell skill for directories." % _disp(src)
        )
    if _protected(src):
        return _protected_msg(src)
    if _protected(dst):
        return _protected_msg(dst)
    if os.path.isdir(dst):
        return (
            "The destination %s is a folder, sir — give me a full file path "
            "instead." % _disp(dst)
        )
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    bk = _backup(dst)
    if verb == "copy":
        shutil.copy2(src, dst)
        reply = "Copied %s to %s, sir." % (_disp(src), _disp(dst))
    else:
        shutil.move(src, dst)
        reply = "Moved %s to %s, sir." % (_disp(src), _disp(dst))
    if bk:
        reply += " The previous destination was preserved at %s." % _disp(bk)
    log.info("%sd %s -> %s", verb, src, dst)
    return reply


def _d_search(cmd):
    c = cmd.lower().strip()
    m = re.search(r"\b(?:search\s+for|grep|find\s+files\s+containing)\s+", c)
    if not m:
        return None
    low = c[m.end():]
    if not low:
        return None
    regex = False
    pattern = None
    consumed = 0
    if low[0] == "/":
        end = low.find("/", 1)
        if end > 1:
            pattern = low[1:end]
            regex = True
            consumed = end + 1
    elif low and low[0] in "'\"":
        q = low[0]
        end = 1
        while end < len(low):
            if low[end] == "\\" and end + 1 < len(low):
                end += 2
                continue
            if low[end] == q:
                break
            end += 1
        pattern = _unquote(low[:end + 1])
        consumed = end + 1
    else:
        parts = low.split(None, 1)
        pattern = parts[0]
        consumed = len(parts[0])
    if not pattern:
        return None
    tail = low[consumed:]
    base_raw = PROJECT_DIR
    bm = re.search(r"\bin\s+(\S+)", tail)
    if bm:
        base_raw = bm.group(1)
    ext = None
    em = re.search(r"\bfor\s+(?:\*\s*)?\.?([A-Za-z0-9]{1,10})\b", tail)
    if em:
        ext = "." + em.group(1).lower()
    return {
        "cmd": cmd,
        "pattern": pattern,
        "regex": regex,
        "base": base_raw,
        "ext": ext,
    }


def _e_search(app, ctx):
    pattern = ctx["pattern"]
    base = _resolve(ctx["base"]) if ctx["base"] else PROJECT_DIR
    ext = ctx["ext"]
    if ctx["regex"]:
        try:
            cre = re.compile(pattern, re.I)
        except re.error as e:
            return "That regex won't compile, sir: %s" % e

        def match(line):
            return cre.search(line) is not None

    else:
        needle = pattern.lower()

        def match(line):
            return needle in line.lower()

    if not os.path.isdir(base):
        return _missing(base)
    hits = []
    total = 0
    nfiles = 0
    for path in _iter_search_files(base):
        if total >= 400 or len(hits) >= MAX_SEARCH_HITS:
            break
        fn = os.path.basename(path)
        if fn.startswith("."):
            continue
        if ext and not fn.lower().endswith(ext):
            continue
        try:
            if os.path.getsize(path) > MAX_SEARCH_FILE_BYTES:
                continue
            with open(path, "rb") as f:
                if b"\x00" in f.read(8192):
                    continue
            matched_here = False
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if match(line):
                        total += 1
                        matched_here = True
                        if len(hits) < MAX_SEARCH_HITS:
                            hits.append(
                                "%s:%d: %s"
                                % (
                                    os.path.relpath(path, base).replace(os.sep, "/"),
                                    i,
                                    line.strip()[:160],
                                )
                            )
                        if total >= 400:
                            break
            if matched_here:
                nfiles += 1
        except OSError:
            continue
    if total == 0:
        return (
            "No matches for '%s'%s under %s, sir — I looked high and low."
            % (pattern, " for %s files" % ext if ext else "", _disp(base))
        )
    shown = len(hits)
    head = "Found %d match(es) in %d file(s) under %s, sir" % (
        total,
        nfiles,
        _disp(base),
    )
    if total > shown:
        head += " — showing the first %d" % shown
    return head + ":\n" + "\n".join(hits)


def _d_tree(cmd):
    c = cmd.lower().strip()
    m = re.match(
        r"^(?:please\s+)?(?:show\s+)?(?:me\s+)?(?:the\s+)?"
        r"(?:folder|directory)\s+tree\s+(?:of|for)?\s*(?:the\s+)?(.+)$",
        c,
    )
    if m and m.group(1).strip():
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(r"^(?:please\s+)?tree\s+(?:of\s+)?(.+)$", c)
    if m and m.group(1).strip():
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_tree(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isdir(p):
        return _missing(p)
    rows, counts, truncated = _tree_rows(p)
    footer = "%d files, %d dirs" % (counts[0], counts[1])
    out = "\n".join(rows)
    if truncated:
        out += "\n… pruned at %d entries, sir — the garden grows deeper." % (
            MAX_TREE_ENTRIES
        )
    return "Tree of %s, sir:\n%s\n(%s)" % (_disp(p), out, footer)


def _d_diff(cmd):
    c = cmd.lower().strip()
    m = re.search(
        r"\bdiff\s+(?:between\s+)?(.+?)\s+and\s+(?:the\s+)?(.+)$", c, re.S
    )
    if m:
        return {"cmd": cmd, "a": m.group(1), "b": m.group(2)}
    m = re.search(r"\bcompare\s+(.+?)\s+with\s+(?:the\s+)?(.+)$", c, re.S)
    if m:
        return {"cmd": cmd, "a": m.group(1), "b": m.group(2)}
    return None


def _e_diff(app, ctx):
    pa = _resolve(ctx["a"])
    pb = _resolve(ctx["b"])
    for p in (pa, pb):
        if not os.path.isfile(p):
            return _missing(p)
    la = _read_lines(pa)
    lb = _read_lines(pb)
    diff = list(
        difflib.unified_diff(
            la,
            lb,
            fromfile=_disp(pa),
            tofile=_disp(pb),
            lineterm="",
        )
    )
    added = sum(
        1 for l in diff if l.startswith("+") and not l.startswith("+++")
    )
    removed = sum(
        1 for l in diff if l.startswith("-") and not l.startswith("---")
    )
    header = "Comparing %s with %s, sir — %d added, %d removed:" % (
        _disp(pa),
        _disp(pb),
        added,
        removed,
    )
    body = _cap(diff, DIFF_CAP, "diff lines")
    return header + "\n" + (body if body else "(identical, sir)")


def _d_mkdir(cmd):
    c = cmd.lower().strip()
    m = re.match(
        r"^(?:please\s+)?(?:make|create)\s+(?:a\s+)?(?:new\s+)?"
        r"(?:folder|directory)(?:\s+called)?\s+(?:named\s+)?(.+)$",
        c,
    )
    if m:
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(r"^(?:please\s+)?new\s+(?:folder|directory)\s+(?:at\s+)?(.+)$", c)
    if m:
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_mkdir(app, ctx):
    p = _resolve(ctx["raw"])
    if _protected(p):
        return _protected_msg(p)
    existed = os.path.isdir(p)
    os.makedirs(p, exist_ok=True)
    if existed:
        return "%s is already there, sir — nothing to do." % _disp(p)
    log.info("mkdir %s", p)
    return "Created folder %s, sir." % _disp(p)


SKILLS = [
    ("fp_read_head", _detector(_d_head), _executor("fp_read_head", _e_head), True),
    ("fp_read_tail", _detector(_d_tail), _executor("fp_read_tail", _e_tail), False),
    ("fp_read_range", _detector(_d_range), _executor("fp_read_range", _e_range), False),
    ("fp_read_full", _detector(_d_full), _executor("fp_read_full", _e_full), True),
    ("fp_write_file", _detector(_d_write), _executor("fp_write_file", _e_write), True),
    (
        "fp_append_file",
        _detector(_d_append),
        _executor("fp_append_file", _e_append),
        False,
    ),
    (
        "fp_replace_in_file",
        _detector(_d_replace),
        _executor("fp_replace_in_file", _e_replace),
        True,
    ),
    (
        "fp_insert_line",
        _detector(_d_insert),
        _executor("fp_insert_line", _e_insert),
        False,
    ),
    (
        "fp_delete_lines",
        _detector(_d_delete_lines),
        _executor("fp_delete_lines", _e_delete_lines),
        False,
    ),
    (
        "fp_delete_file",
        _detector(_d_delete_file),
        _executor("fp_delete_file", _e_delete_file),
        True,
    ),
    (
        "fp_copy_file",
        _detector(_d_copy),
        _executor("fp_copy_file", _e_copy_or_move),
        False,
    ),
    (
        "fp_move_file",
        _detector(_d_move),
        _executor("fp_move_file", _e_copy_or_move),
        False,
    ),
    (
        "fp_search_content",
        _detector(_d_search),
        _executor("fp_search_content", _e_search),
        False,
    ),
    ("fp_tree", _detector(_d_tree), _executor("fp_tree", _e_tree), False),
    ("fp_diff_files", _detector(_d_diff), _executor("fp_diff_files", _e_diff), False),
    ("fp_mkdir", _detector(_d_mkdir), _executor("fp_mkdir", _e_mkdir), False),
]


def register(brain):
    for name, detect, execute, priority in SKILLS:
        brain.register(name, detect, execute, priority=priority)


register_extra = register
