"""DATA FILE TOOLS: JSON & CSV surgery plus light image work, safely."""

import csv
import json
import os
import re
import shutil
import statistics

from jarvis_logging import get_logger

log = get_logger("data_file_tools")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE

try:
    from PIL import Image as _Image

    HAVE_PIL = True
except Exception:
    _Image = None
    HAVE_PIL = False

FILTER_ROWS_SHOWN = 5


def _err(skill, e):
    return "I'm terribly sorry, sir — %s stumbled: %s" % (skill, e)


def _missing(path):
    return "I couldn't find %s, sir." % _disp(path)


def _offline():
    return (
        "I'm afraid Pillow isn't installed, sir — the image skills stay "
        "offline until you add it (pip install pillow)."
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


def _looks_like_path(s):
    s = (s or "").strip()
    if not s:
        return False
    if "/" in s or s.startswith("~"):
        return True
    return bool(
        re.search(r"[A-Za-z0-9_.\-]+\.[A-Za-z0-9]{1,12}(\s|$)", s)
    )


def _resolve(raw):
    s = (raw or "").strip().strip("`").strip()
    s = _unquote(s)
    s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.I).strip()
    s = re.sub(r"^(?:at|in)\s+", "", s, flags=re.I).strip()
    s = s.strip("'\"`").strip()
    s = os.path.expanduser(s)
    if not os.path.isabs(s):
        s = os.path.join(PROJECT_DIR, s)
    return os.path.normpath(s)


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


def _bk_note(bk):
    return " A backup rests at %s." % _disp(bk) if bk else ""


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


def _d_json_format(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?format\s+(?:the\s+)?json\s+(?:file\s+)?(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(
        r"^\s*(?:please\s+)?prettify\s+(?:the\s+)?(.+?)\s*$", cmd, re.I
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _e_json_format(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        data = _load_json(p)
    except Exception as e:
        return (
            "I'm terribly sorry, sir — dt_json_format couldn't parse that "
            "JSON: %s" % e
        )
    bk = _backup(p)
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if isinstance(data, dict):
        n, kind = len(data), "top-level key(s)"
    elif isinstance(data, list):
        n, kind = len(data), "top-level item(s)"
    else:
        n, kind = 1, "value"
    return "I've reformatted %s with indent=2, sir — %d %s.%s" % (
        _disp(p),
        n,
        kind,
        _bk_note(bk),
    )


def _d_json_query(cmd):
    m = re.match(
        r"^\s*get\s+(?:the\s+)?(?:key\s+)?([A-Za-z0-9_.\-]+)\s+from\s+(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(2)):
        return {"cmd": cmd, "path": m.group(1), "raw": m.group(2)}
    m = re.match(
        r"^\s*json\s+(.+?)\s+key\s+([A-Za-z0-9_.\-]+)\s*$", cmd, re.I
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "path": m.group(2), "raw": m.group(1)}
    return None


def _dotted_lookup(data, path):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
            else:
                raise KeyError(part)
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except ValueError:
                raise KeyError(part)
            cur = cur[idx]
        else:
            raise KeyError(part)
    return cur


def _summary_of(value):
    if isinstance(value, dict):
        return "a dict holding %d key(s): %s" % (
            len(value),
            ", ".join(sorted(map(str, value.keys()))[:20]),
        )
    if isinstance(value, list):
        return "a list holding %d item(s)" % len(value)
    return repr(value)


def _e_json_query(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        data = _load_json(p)
    except Exception as e:
        return (
            "I'm terribly sorry, sir — dt_json_query couldn't parse that "
            "JSON: %s" % e
        )
    try:
        value = _dotted_lookup(data, ctx["path"])
    except KeyError:
        return (
            "I'm afraid there's no “%s” along that path in %s, sir."
            % (ctx["path"], _disp(p))
        )
    except IndexError:
        return (
            "That index runs past the end of the array in %s, sir."
            % _disp(p)
        )
    return "%s is %s, sir." % (ctx["path"], _summary_of(value))


def _d_json_validate(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?validate\s+(?:the\s+)?(?:json\s+)?"
        r"(?:file\s+)?(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_json_validate(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        with open(p, "r", encoding="utf-8") as f:
            json.load(f)
    except json.JSONDecodeError as e:
        return (
            "I'm afraid %s isn't valid JSON, sir — error on line %d, "
            "column %d: %s" % (_disp(p), e.lineno, e.colno, e.msg)
        )
    except Exception as e:
        return _err("dt_json_validate", e)
    return "%s checks out — valid JSON, sir." % _disp(p)


def _read_rows(path):
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    while rows and not any(cell.strip() for cell in rows[-1]):
        rows.pop()
    return rows


def _guess_type(values):
    vals = [v.strip() for v in values if v.strip() != ""]
    if not vals:
        return "empty"
    try:
        [int(v) for v in vals]
        return "int"
    except ValueError:
        pass
    try:
        [float(v) for v in vals]
        return "float"
    except ValueError:
        pass
    return "text"


def _fmt_num(x):
    r = round(float(x), 2)
    return ("%g" % r)


def _d_csv_summarize(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?summarize\s+(?:the\s+)?(?:csv\s+)?"
        r"(?:file\s+)?(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    m = re.match(
        r"^\s*csv\s+stats?(?:istics)?\s+(?:on\s+|of\s+|for\s+)?(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_csv_summarize(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        rows = _read_rows(p)
    except Exception as e:
        return _err("dt_csv_summarize", e)
    if not rows:
        return "%s is an empty CSV, sir — nothing to summarize." % _disp(p)
    header = [h.strip() for h in rows[0]]
    data = rows[1:]
    lines = [
        "Here's the lay of the land for %s, sir — %d data row(s) × %d "
        "column(s):" % (_disp(p), len(data), len(header))
    ]
    for i, col in enumerate(header):
        cells = [r[i].strip() if i < len(r) else "" for r in data]
        missing = sum(1 for v in cells if v == "")
        kind = _guess_type(cells)
        desc = "- %s: %s, %d missing" % (col, kind, missing)
        if kind in ("int", "float"):
            nums = []
            for v in cells:
                if v != "":
                    nums.append(float(v))
            if nums:
                desc += ", min=%s max=%s mean=%s" % (
                    _fmt_num(min(nums)),
                    _fmt_num(max(nums)),
                    _fmt_num(statistics.mean(nums)),
                )
        lines.append(desc)
    return "\n".join(lines)


def _d_csv_filter(cmd):
    m = re.match(
        r"^\s*csv\s+(.+?)\s+where\s+(.+?)\s+(?:equals|=|==|is)\s+(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {
            "cmd": cmd,
            "raw": m.group(1),
            "column": m.group(2).strip(),
            "value": m.group(3).strip(),
        }
    return None


def _e_csv_filter(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        rows = _read_rows(p)
    except Exception as e:
        return _err("dt_csv_filter", e)
    if not rows:
        return "%s has no header row, sir — nothing to filter." % _disp(p)
    header = [h.strip().lower() for h in rows[0]]
    col = ctx["column"].strip().lower()
    if col not in header:
        return (
            "I can't find a “%s” column in %s, sir — available columns: %s."
            % (ctx["column"], _disp(p), ", ".join(rows[0]))
        )
    idx = header.index(col)
    want = _unquote(ctx["value"]).strip().lower()
    hits = [r for r in rows[1:] if idx < len(r) and r[idx].strip().lower() == want]
    if not hits:
        return (
            "No rows in %s have %s equal to “%s”, sir — zero matches."
            % (_disp(p), ctx["column"], ctx["value"])
        )
    shown = hits[:FILTER_ROWS_SHOWN]
    body = "\n".join("|".join(r) for r in shown)
    out = (
        "I found %d matching row(s) in %s, sir — showing the first %d:"
        "\n%s" % (len(hits), _disp(p), len(shown), body)
    )
    if len(hits) > FILTER_ROWS_SHOWN:
        out += "\n… %d more remain unshown, sir." % (
            len(hits) - FILTER_ROWS_SHOWN
        )
    return out


def _d_csv_to_json(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?convert\s+(.+?\.csv)\s+to\s+json\s*$", cmd, re.I
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_csv_to_json(app, ctx):
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        with open(p, "r", newline="", encoding="utf-8-sig") as f:
            records = list(csv.DictReader(f))
    except Exception as e:
        return _err("dt_csv_to_json", e)
    target = os.path.splitext(p)[0] + ".json"
    bk = _backup(target)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return "I've converted %s to %s, sir — %d record(s).%s" % (
        _disp(p),
        _disp(target),
        len(records),
        _bk_note(bk),
    )


def _d_img_info(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?image\s+info\s+(?:for\s+|of\s+|about\s+)?(.+?)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {"cmd": cmd, "raw": m.group(1)}
    return None


def _e_img_info(app, ctx):
    if not HAVE_PIL:
        return _offline()
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    try:
        with _Image.open(p) as im:
            size = "%dx%d" % im.size
            mode, fmt = im.mode, im.format
        filesize = os.path.getsize(p)
    except Exception as e:
        return _err("dt_img_info", e)
    return (
        "%s is a %s image, %s pixels (%s mode), %s bytes, sir."
        % (_disp(p), fmt or "?", size, mode, filesize)
    )


def _d_img_resize(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?resize\s+(?:image\s+)?(.+?)\s+to\s+"
        r"(\d+)\s*[xX*×]\s*(\d+)\s*$",
        cmd,
        re.I,
    )
    if m and _looks_like_path(m.group(1)):
        return {
            "cmd": cmd,
            "raw": m.group(1),
            "w": int(m.group(2)),
            "h": int(m.group(3)),
        }
    return None


def _save_image(im, path, fmt_key):
    if fmt_key in ("jpg", "jpeg") and im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.save(path)


def _e_img_resize(app, ctx):
    if not HAVE_PIL:
        return _offline()
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    w, h = int(ctx["w"]), int(ctx["h"])
    if w < 1 or h < 1:
        return (
            "I'm afraid those dimensions are nonsensical, sir — width and "
            "height must be positive integers."
        )
    try:
        bk = _backup(p)
        with _Image.open(p) as im:
            resized = im.resize((w, h))
            fmt_key = os.path.splitext(p)[1].lstrip(".").lower()
            _save_image(resized, p, fmt_key)
    except Exception as e:
        return _err("dt_img_resize", e)
    return "I've resized %s to %dx%d pixels, sir.%s" % (
        _disp(p),
        w,
        h,
        _bk_note(bk),
    )


def _d_img_convert(cmd):
    m = re.match(
        r"^\s*(?:please\s+)?convert\s+(.+?)\s+to\s+(png|jpe?g)\s*$", cmd, re.I
    )
    if m and _looks_like_path(m.group(1)):
        fmt = m.group(2).lower()
        return {"cmd": cmd, "raw": m.group(1), "fmt": "jpg" if fmt == "jpeg" else fmt}
    return None


def _e_img_convert(app, ctx):
    if not HAVE_PIL:
        return _offline()
    p = _resolve(ctx["raw"])
    if not os.path.isfile(p):
        return _missing(p)
    fmt = ctx["fmt"]
    target = os.path.splitext(p)[0] + "." + fmt
    if os.path.realpath(target) == os.path.realpath(p):
        return "%s is already a %s file, sir — nothing to do." % (
            _disp(p),
            fmt.upper(),
        )
    try:
        with _Image.open(p) as im:
            bk = _backup(target)
            _save_image(im, target, fmt)
    except Exception as e:
        return _err("dt_img_convert", e)
    return "I've converted %s to %s (%s), sir.%s" % (
        _disp(p),
        _disp(target),
        fmt.upper(),
        _bk_note(bk),
    )


SKILLS = [
    (
        "dt_json_format",
        _detector(_d_json_format),
        _executor("dt_json_format", _e_json_format),
        False,
    ),
    (
        "dt_json_query",
        _detector(_d_json_query),
        _executor("dt_json_query", _e_json_query),
        False,
    ),
    (
        "dt_json_validate",
        _detector(_d_json_validate),
        _executor("dt_json_validate", _e_json_validate),
        False,
    ),
    (
        "dt_csv_summarize",
        _detector(_d_csv_summarize),
        _executor("dt_csv_summarize", _e_csv_summarize),
        False,
    ),
    (
        "dt_csv_filter",
        _detector(_d_csv_filter),
        _executor("dt_csv_filter", _e_csv_filter),
        False,
    ),
    (
        "dt_csv_to_json",
        _detector(_d_csv_to_json),
        _executor("dt_csv_to_json", _e_csv_to_json),
        False,
    ),
    (
        "dt_img_info",
        _detector(_d_img_info),
        _executor("dt_img_info", _e_img_info),
        False,
    ),
    (
        "dt_img_resize",
        _detector(_d_img_resize),
        _executor("dt_img_resize", _e_img_resize),
        False,
    ),
    (
        "dt_img_convert",
        _detector(_d_img_convert),
        _executor("dt_img_convert", _e_img_convert),
        False,
    ),
]


def register(brain):
    for name, detect, execute, priority in SKILLS:
        brain.register(name, detect, execute, priority=priority)


register_extra = register
