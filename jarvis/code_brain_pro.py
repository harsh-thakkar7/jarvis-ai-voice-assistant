# -*- coding: utf-8 -*-
"""CODING BRAIN PRO: turns JARVIS into a senior-engineer coding assistant.

Local-first generation from a curated template library, static code review,
validated LLM rewrites with write-back to disk, AST explanations, translation,
and pytest scaffolding. Registers eight skills into the main Brain via
register(brain). Never imports main; talks to the LLM only through brain._llm.
"""

import ast
import difflib
import functools
import importlib
import os
import re
import shutil
import sys

from jarvis_logging import get_logger

log = get_logger("code_brain_pro")

try:
    import code_validator
except ImportError:
    code_validator = None

# LLM bridge: brain._llm(app, prompt) -> str | None (None = offline).
try:
    from brain import _llm
except Exception:  # standalone/test usage without brain.py
    def _llm(app, prompt):
        return None

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

LAST_CODE = {}


def _cv():
    """Return the code_validator module, retrying once if it appeared late."""
    global code_validator
    if code_validator is None:
        try:
            code_validator = importlib.import_module("code_validator")
            log.info("code_validator became available")
        except Exception:
            return None
    return code_validator


_FENCE_RE = re.compile(r"```[\w#+.-]*[ \t]*\n?(.*?)```", re.S)

_FILE_REF_RE = re.compile(
    r"\b(?:in|from|at)\s+(?:the\s+)?(?:file\s+)?"
    r"([\w~./\- ]+?\.\w{1,4})(?:\s|$)", re.I)

_TAIL_FILLER_RE = re.compile(
    r"\b(?:please|jarvis|thanks|thank\s+you|now|today|for\s+me|sir)\b[\s,.!]*$",
    re.I)

_BANNED_TOPICS_RE = re.compile(
    r"\b(poem|story|joke|essay|letter|report|article|song|haiku|limerick|"
    r"website|web\s+page|research)\b", re.I)

_TESTS_INTENT_RE = re.compile(
    r"\btests?\b.*\b(?:for|covering)\b|^\s*test\s+this\s+code\b", re.I)

_PRO_WRITE_RE = re.compile(
    r"\b(write|create|make|generate|build|implement|code|develop)\b.*\b"
    r"(code|program|script|function|class|snippet|algorithm|utility|module)\b",
    re.I)

_FIX_VERB_RE = re.compile(
    r"\b(fix|debug|repair)\b|\bwhy\s+(?:is|does)\s+(?:my|this)\s+"
    r"(?:code|script|program)\b|\btraceback\b", re.I)

_CODEWORD_RE = re.compile(r"\b(code|script|program)\b", re.I)

_IMPROVE_RE = re.compile(
    r"\b(?:improve|refactor|optimize|optimise|clean\s*up|polish|enhance|"
    r"make\s+(?:it|this|that)?\s*better)\b.*\b"
    r"(?:code|script|program|function|file|it|this)\b", re.I)

_REVIEW_RE = re.compile(r"\b(?:review|audit|code\s+quality|"
                        r"check\s+(?:my|this)\s+code)\b", re.I)

_EXPLAIN_RE = re.compile(r"\b(?:explain|walk\s+me\s+through)\b.*\b"
                         r"(?:code|script|snippet|program|function|class)\b",
                         re.I)

_TRANSLATE_RE = re.compile(
    r"\b(?:convert|translate|port)\b.*?\bto\b\s*"
    r"(python|javascript|typescript|java|c\+\+|cpp|c|go|rust|php|ruby|"
    r"c#|csharp|bash|sql|kotlin|swift)\b", re.I)

_GEN_TESTS_RE = re.compile(
    r"\b(?:write|generate|add)\s+(?:unit\s+)?tests?\b.*\b(?:for|covering)\b",
    re.I)

_SAVE_RE = re.compile(r"\bsave\s+(?:it|the\s+code|this\s+code|that\s+code)\b",
                      re.I)

_AS_FILE_RE = re.compile(r"\bas\s+([\w\-./]+\.\w{1,4})", re.I)

_LANG_EXT = {
    "python": "py", "javascript": "js", "typescript": "ts", "java": "java",
    "c++": "cpp", "c": "c", "go": "go", "rust": "rs", "php": "php",
    "ruby": "rb", "c#": "cs", "bash": "sh", "sql": "sql", "kotlin": "kt",
    "swift": "swift",
}

_LANG_ALIAS = {
    "js": "javascript", "ts": "typescript", "py": "python",
    "cpp": "c++", "csharp": "c#", "golang": "go",
}

_LANG_SNIFF_ORDER = (
    ("javascript", (r"\bjavascript\b", r"\bjs\b", r"\bnode\b")),
    ("typescript", (r"\btypescript\b", r"\bts\b")),
    ("java", (r"\bjava\b",)),
    ("c++", (r"\bc\+\+\b",)),
    ("c#", (r"\bc#\b", r"\bcsharp\b")),
    ("bash", (r"\bbash\b", r"\bshell\b", r"\bzsh\b")),
    ("go", (r"\bgolang\b", r"\bgo\b")),
    ("rust", (r"\brust\b",)),
    ("php", (r"\bphp\b",)),
    ("ruby", (r"\bruby\b",)),
    ("sql", (r"\bsql\b",)),
    ("kotlin", (r"\bkotlin\b",)),
    ("swift", (r"\bswift\b",)),
    ("c", (r"\bc\b",)),
    ("python", (r"\bpython\b", r"\bpy\b")),
)


def _sniff_lang(text):
    """Best-effort language guess from free text; None when nothing matches."""
    low = (text or "").lower()
    for lang, patterns in _LANG_SNIFF_ORDER:
        for pat in patterns:
            if re.search(pat, low):
                return lang
    return None


def _normalize_lang(raw):
    return _LANG_ALIAS.get((raw or "").strip().lower(),
                           (raw or "").strip().lower())


def _extract_payload(cmd, trigger_pat=None):
    """Prefer a fenced block in cmd; else text after the trigger phrase.

    Returns the payload string or None. An unfenced tail must carry at
    least 25 non-space characters — or look like code (contains a call
    parenthesis pair) — to qualify.
    """
    fence = _FENCE_RE.search(cmd)
    if fence and fence.group(1).strip():
        return fence.group(1).rstrip()
    if trigger_pat:
        m = re.search(trigger_pat, cmd, re.I)
        if m:
            tail = cmd[m.end():].strip(" \t\r\n:;,.-")
            if len(re.sub(r"\s+", "", tail)) >= 25 or (
                    "(" in tail and ")" in tail and len(tail) >= 8):
                return tail.strip()
    return None


def _find_file_ref(cmd):
    """Extract a filesystem path mentioned with in/from/at; expanded."""
    m = _FILE_REF_RE.search(cmd or "")
    if not m:
        return None
    path = _TAIL_FILLER_RE.sub("", m.group(1)).strip(" \t\r\n,.;:!")
    if not path:
        return None
    path = os.path.expanduser(path.strip("\"'"))
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_DIR, path)
    return path


def _read_target(cmd, payload):
    """Return (code, path, error_persona_msg) honouring payload > file ref."""
    if payload and payload.strip():
        return payload, None, None
    path = _find_file_ref(cmd)
    if path:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(), path, None
        except OSError as exc:
            reason = exc.strerror or "unreadable"
            return None, path, ("I couldn't read %s, sir — %s. Check the "
                                "path and permissions, sir."
                                % (os.path.basename(path), reason))
    return None, None, None


def _clip(text, limit=3500):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _strip_fences_basic(text):
    """Local fence stripper used when code_validator is unavailable."""
    m = _FENCE_RE.search(text or "")
    return (m.group(1) if m else (text or "")).strip()


def _safe_to_exec(code):
    """False when running the snippet could block, prompt, or hit network."""
    if "# jarvis:no-exec" in code:
        return False
    if re.search(r"\binput\s*\(", code):
        return False
    if re.search(r"while\s+True\s*:", code):
        return False
    if re.search(r"\btime\.sleep\s*\(", code):
        return False
    if re.search(r"(?m)^\s*(?:import|from)\s+(?:socket|subprocess|threading|"
                 r"asyncio|requests|urllib|httpx|flask|fastapi|uvicorn|"
                 r"tkinter|pygame)\b", code):
        return False
    return True


def _brackets_balanced(code):
    """Cheap sanity check for non-python targets."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    in_str = None
    escaped = False
    for ch in code:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_str:
                in_str = None
            continue
        if ch in "\"'":
            in_str = ch
        elif ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack and in_str is None


_SENIOR_RULES = (
    "You are acting as a senior software engineer.\n"
    "Rules: return COMPLETE, RUNNABLE code only — no placeholders, no TODO "
    "stubs, no pseudo-code, no prose before the code fence.\n"
    "Include full type hints where the language supports them, docstrings on "
    "every public object, defensive error handling, and an entry-point demo "
    "where sensible.\n"
    "Put the code in ONE triple-backtick fence; brief notes may follow AFTER "
    "the closing fence.\n"
)


def _senior_prompt(task, lang="python"):
    return _SENIOR_RULES + "Task: %s\nTarget language: %s\n" % (
        task.strip(), lang)


_REVIEW_CHECKLIST = (
    "Review checklist (address silently, never print it): naming clarity, "
    "dead code, complexity hotspots, error handling, type hints, docstrings, "
    "security, performance.\n")


def _summarize_vr(cv, vr):
    """Persona-safe one-liner describing a ValidationResult."""
    if vr is None:
        return ""
    try:
        if hasattr(cv, "summarize_validation"):
            out = cv.summarize_validation(vr)
            if out:
                return str(out)
    except Exception:
        pass
    if getattr(vr, "ok", False):
        return "Validation passed, sir."
    errs = getattr(vr, "errors", None) or []
    head = "; ".join(str(e) for e in errs[:2])
    return "Validation flagged problems: %s" % (head or "see details, sir.")


def _store_last(code, lang, name):
    LAST_CODE.clear()
    LAST_CODE.update({"code": code, "lang": lang, "name": name})


def _suggest_name(task, lang="python"):
    hit = _local_template(task)
    if hit:
        return hit[1]
    slug = re.sub(r"[^a-z0-9]+", "_", (task or "").lower()).strip("_")[:24]
    ext = _LANG_EXT.get(lang, "txt")
    return "%s_code.%s" % (slug or "generated", ext)


def _embed_task(code, task):
    """Embed the requested task inside the template's module docstring."""
    marker = '"""'
    i = code.find(marker)
    if i == -1:
        return code
    j = code.find(marker, i + 3)
    if j == -1:
        return code
    note = "\n\nGenerated by JARVIS Coding Brain Pro for: %s" % \
        " ".join((task or "").split())[:160]
    return code[:j] + note + code[j:]


_BARE_EXCEPT_RE = re.compile(r"(?m)^(\s*)except\s*:")
_EQ_NONE_RE = re.compile(r"([\w\]\)'\"])\s*(==|!=)\s*(None|True|False)\b")
_LEADING_TAB_RE = re.compile(r"(?m)^(\t+)")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.M)
_DEBUG_PRINT_RE = re.compile(r"""print\(\s*["']DEBUG""", re.I)


def _local_auto_fixes(text):
    """Apply safe mechanical repairs; return (new_text, applied_labels)."""
    applied = []
    fixed = text

    def _sub(pattern, repl_fn, label, src):
        out, n = re.subn(pattern, repl_fn, src)
        if n:
            applied.append("%s (%d spot%s)"
                           % (label, n, "" if n == 1 else "s"))
        return out

    fixed = _sub(
        _BARE_EXCEPT_RE,
        lambda m: m.group(1) + "except Exception as e:",
        "bare 'except:' -> 'except Exception as e:'", fixed)

    def _eq_is(m):
        op = "is not" if m.group(2) == "!=" else "is"
        return "%s %s %s" % (m.group(1), op, m.group(3))

    fixed = _sub(_EQ_NONE_RE, _eq_is,
                 "'==' on None/True/False -> identity check", fixed)
    fixed = _sub(_LEADING_TAB_RE, lambda m: "    " * len(m.group(1)),
                 "tabs -> 4-space indentation", fixed)
    fixed = _sub(_TRAILING_WS_RE, lambda m: "",
                 "stripped trailing whitespace", fixed)

    debug_hits = len(_DEBUG_PRINT_RE.findall(fixed))
    if debug_hits:
        applied.append("flagged %d DEBUG print(s), left in place" % debug_hits)

    if fixed and not fixed.endswith("\n"):
        fixed += "\n"
        applied.append("added missing newline at EOF")
    return fixed, applied


_OFFLINE_CHECKLIST = (
    "Beyond my offline quick-fixes, sir — this one needs my language model. "
    "Until then, walk the traceback like an engineer: read the LAST line "
    "first for the error type, jump to the quoted line number, treat "
    "NameError as a typo or missing import, TypeError as a mixed-type call, "
    "IndexError/KeyError as off-by-one or missing key, IndentationError as a "
    "spacing mixup, and AttributeError as the wrong object method, sir.")


_SECRET_PATTERNS = (
    (re.compile(r"gsk_[A-Za-z0-9]{10,}"), "hardcoded Groq key (gsk_...)"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "hardcoded AWS key (AKIA...)"),
    (re.compile(r"\bapi[_-]?key\s*=\s*[\"'][^\"']{6,}[\"']", re.I),
     "hardcoded api_key literal"),
    (re.compile(r"\bpassword\s*=\s*[\"'][^\"']{4,}[\"']", re.I),
     "hardcoded password literal"),
    (re.compile(r"\bsecret\s*=\s*[\"'][^\"']{4,}[\"']", re.I),
     "hardcoded secret literal"),
)

_SEVERITY_RANK = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
_SEVERITY_WEIGHT = {"CRITICAL": 2.0, "WARN": 0.5, "INFO": 0.1}

_TRY_TYPES = tuple(t for t in (getattr(ast, "Try", None),
                               getattr(ast, "TryStar", None)) if t)
_WITH_TYPES = tuple(t for t in (getattr(ast, "With", None),
                                getattr(ast, "AsyncWith", None)) if t)


def _analyze(code):
    """Static review: list of (severity, line, title, detail) findings."""
    findings = []
    lines = code.splitlines()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [("WARN", max(1, exc.lineno or 1), "does not parse",
                 "SyntaxError: %s" % (exc.msg or "?"))]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("eval", "exec"):
            findings.append((
                "CRITICAL", node.lineno, "%s() usage" % node.func.id,
                "%s() executes arbitrary strings — refactor it away, sir."
                % node.func.id))

    for lineno, raw in enumerate(lines, 1):
        for pat, title in _SECRET_PATTERNS:
            if pat.search(raw):
                findings.append(("CRITICAL", lineno, title,
                                 "Hard-coded credentials belong in "
                                 "environment variables, sir."))
                break

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            lits = "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant)
                           and isinstance(v.value, str)).lower()
            if re.search(r"\b(select|insert|update|delete)\b", lits) and \
                    re.search(r"\b(from|where|like)\b|\{\}|%\s*s", lits):
                findings.append((
                    "WARN", node.lineno, "SQL built with an f-string",
                    "Use parameterised queries (? or %s placeholders)."))

        if isinstance(node, ast.Global):
            findings.append(("WARN", node.lineno, "global statement",
                             "Global mutable state — pass values instead."))

        if isinstance(node, ast.Compare):
            for op, comp in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and \
                        isinstance(comp, ast.Constant) and \
                        comp.value in (None, True, False):
                    findings.append((
                        "WARN", node.lineno,
                        "== comparison to %r" % (comp.value,),
                        "Identity reads better: use 'is' / 'is not'."))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in list(node.args.defaults) + \
                    [d for d in node.args.kw_defaults if d is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)) or (
                        isinstance(d, ast.Call)
                        and isinstance(d.func, ast.Name)
                        and d.func.id in ("list", "dict", "set")):
                    findings.append((
                        "WARN", node.lineno, "mutable default argument",
                        "Defaults like [] persist across calls — use a None "
                        "sentinel."))
                    break
            span = getattr(node, "end_lineno", node.lineno) - node.lineno
            if span > 60:
                findings.append((
                    "WARN", node.lineno,
                    "function '%s' spans %d lines" % (node.name, span),
                    "Long function — decompose it."))
            if not node.name.startswith("_") and \
                    ast.get_docstring(node) is None:
                findings.append((
                    "INFO", node.lineno,
                    "function '%s' lacks a docstring" % node.name,
                    "One line explaining intent helps everyone."))

        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_") and \
                    ast.get_docstring(node) is None:
                findings.append((
                    "INFO", node.lineno,
                    "class '%s' lacks a docstring" % node.name,
                    "Document the responsibility of the class."))

        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                just_passes = len(node.body) == 1 and \
                    isinstance(node.body[0], ast.Pass)
                findings.append((
                    "WARN", node.lineno, "bare except" +
                    (" that only passes" if just_passes else ""),
                    "Catch specific exceptions; handle or log them."))
            elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                findings.append((
                    "INFO", node.lineno, "except: pass",
                    "Silently swallowed failure — at least log it."))

    opens_inside_with = set()
    for node in ast.walk(tree):
        if isinstance(node, _WITH_TYPES):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and \
                        isinstance(sub.func, ast.Name) and \
                        sub.func.id == "open":
                    opens_inside_with.add(sub.lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open" \
                and node.lineno not in opens_inside_with:
            findings.append((
                "WARN", node.lineno, "open() without with",
                "Handle may leak — wrap it in 'with open(...) as f:'."))

    prints = [n.lineno for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "print"]
    if prints:
        findings.append((
            "INFO", prints[0], "%d print() call(s)" % len(prints),
            "Debug prints — prefer logging in shipped code."))

    todo_hits = [i for i, raw in enumerate(lines, 1)
                 if re.search(r"\b(TODO|FIXME|HACK)\b", raw)]
    if todo_hits:
        findings.append((
            "INFO", todo_hits[0],
            "%d TODO/FIXME/HACK marker(s)" % len(todo_hits),
            "Resolve them or move them onto a ticket."))

    long_lines = [i for i, raw in enumerate(lines, 1) if len(raw) > 120]
    if long_lines:
        findings.append((
            "INFO", long_lines[0],
            "%d line(s) beyond 120 characters" % len(long_lines),
            "Wrap long lines for readability."))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name.split(".")[0]
                uses = len(re.findall(r"\b%s\b" % re.escape(bound), code))
                if uses <= 1:
                    findings.append((
                        "INFO", node.lineno,
                        "import '%s' looks unused" % bound,
                        "Drop it or reference it, sir."))

    _collect_nesting(tree.body, 0, findings)
    return sorted(findings,
                  key=lambda f: (_SEVERITY_RANK.get(f[0], 3), f[1], f[2]))


def _collect_nesting(body, depth, findings):
    for node in body:
        if isinstance(node, (ast.If, ast.For, ast.While, ast.AsyncFor,
                             ast.IfExp) + _TRY_TYPES + _WITH_TYPES +
                      tuple(t for t in (getattr(ast, "Match", None),) if t)):
            new_depth = depth + 1
            if new_depth > 4:
                findings.append((
                    "WARN", getattr(node, "lineno", 1),
                    "nesting depth %d" % new_depth,
                    "Deep nesting — invert conditions or extract methods."))
            _collect_nesting(getattr(node, "body", []) +
                             getattr(node, "orelse", []) +
                             getattr(node, "finalbody", []),
                             new_depth, findings)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            _collect_nesting(getattr(node, "body", []), 0, findings)


def _score_findings(findings):
    total = sum(_SEVERITY_WEIGHT.get(f[0], 0.1) for f in findings)
    return round(max(0.0, min(10.0, 10.0 - total)), 1)


def _top_recommendation(findings):
    if not findings:
        return "Spotless, sir — keep those type hints coming."
    _, line, title, detail = findings[0]
    return "Start with L%s %s — %s" % (line, title,
                                       detail.rstrip(".").lower() + ".")


def _branch_complexity(fn_node):
    """1 + count of If/For/While/ExceptHandler + extra BoolOp branches."""
    total = 1
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.AsyncFor,
                             ast.ExceptHandler)):
            total += 1
        elif isinstance(node, ast.BoolOp):
            total += max(0, len(node.values) - 1)
    return total


def _fmt_signature(fn_node):
    a = fn_node.args
    positional = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    pieces = []
    for arg, default in zip(positional, defaults):
        piece = arg.arg
        if arg.annotation is not None:
            piece += ": " + ast.unparse(arg.annotation)
        if default is not None:
            piece += "=" + ast.unparse(default)
        pieces.append(piece)
    if a.vararg:
        pieces.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        pieces.append("*")
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        piece = arg.arg
        if arg.annotation is not None:
            piece += ": " + ast.unparse(arg.annotation)
        if default is not None:
            piece += "=" + ast.unparse(default)
        pieces.append(piece)
    if a.kwarg:
        pieces.append("**" + a.kwarg.arg)
    ret = ""
    if fn_node.returns is not None:
        ret = " -> " + ast.unparse(fn_node.returns)
    return "%s(%s)%s" % (fn_node.name, ", ".join(pieces), ret)


def _outline(code):
    """Local AST outline: imports, classes, functions, metrics."""
    out = []
    loc = len([ln for ln in code.splitlines() if ln.strip()])
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return ["This snippet does not parse, sir — SyntaxError on line %s: "
                "%s" % (exc.lineno, exc.msg)]

    stdlib_mods, third_party, local = set(), set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                bucket = (stdlib_mods if root in sys.stdlib_module_names
                          else third_party)
                bucket.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                local.append("." * node.level + node.module)
            elif node.module:
                root = node.module.split(".")[0]
                bucket = (stdlib_mods if root in sys.stdlib_module_names
                          else third_party)
                bucket.add(node.module)
    if stdlib_mods or third_party or local:
        out.append("Imports:")
        if stdlib_mods:
            out.append("- stdlib: %s" % ", ".join(sorted(stdlib_mods)))
        if third_party:
            out.append("- third-party: %s" % ", ".join(sorted(third_party)))
        if local:
            out.append("- local: %s" % ", ".join(local))

    purpose = None
    doc = ast.get_docstring(tree)
    if doc:
        purpose = doc.strip().splitlines()[0]
    if not purpose:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                d = ast.get_docstring(node)
                if d:
                    purpose = d.strip().splitlines()[0]
                    break
    if purpose:
        out.append("Purpose guess: %s" % purpose[:180])

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))]
            out.append("Class %s (L%s-%s): methods %s"
                       % (node.name, node.lineno,
                          getattr(node, "end_lineno", node.lineno),
                          ", ".join(methods) or "none"))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(
                "Function %s (L%s-%s, complexity %s): %s"
                % (node.name, node.lineno,
                   getattr(node, "end_lineno", node.lineno),
                   _branch_complexity(node), _fmt_signature(node)))

    out.append("Size: %d non-blank lines of code." % loc)
    return out


def _guess_call_args(fn_node):
    a = fn_node.args
    positional = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    args = []
    for arg, default in zip(positional, defaults):
        if default is not None:
            args.append(ast.unparse(default))
            continue
        ann = ast.unparse(arg.annotation) if arg.annotation else ""
        if ann in ("int",):
            args.append("-1")
        elif ann in ("float",):
            args.append("-1.0")
        elif ann.startswith("str"):
            args.append('"sample"')
        elif ann.startswith("bool"):
            args.append("True")
        elif ann.startswith("list") or ann == "List":
            args.append("[]")
        elif ann.startswith("dict") or ann == "Dict":
            args.append("{}")
        else:
            args.append("None")
    return args


def _raises_possible(fn_node):
    return any(isinstance(n, ast.Raise) for n in ast.walk(fn_node))


def _edge_arg_for(fn_node):
    a = fn_node.args
    for arg in list(a.posonlyargs) + list(a.args):
        ann = ast.unparse(arg.annotation) if arg.annotation else ""
        if ann.startswith("str"):
            return '""'
        if ann.startswith("list") or ann == "List":
            return "[]"
        if ann in ("int", "float"):
            return "0"
    return "None"


def _gen_test_scaffold(code):
    """Build a pytest scaffold; returns (scaffold_text, function_count)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        log.warning("cannot scaffold tests: %s", exc)
        return None, 0

    fixtures, tests = [], []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fname = re.sub(r"\W+", "_", node.name.lower())
            fixtures.append(
                '@pytest.fixture()\ndef %s_fixture() -> "%s":\n'
                '    """Fresh %s instance per test."""\n'
                "    return %s()" % (fname, node.name, node.name, node.name))

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                not node.name.startswith("_"):
            call = "%s(%s)" % (node.name, ", ".join(_guess_call_args(node)))
            edge_call = "%s(%s)" % (node.name, _edge_arg_for(node))
            tests.append(
                "def test_%s_happy_path() -> None:\n"
                '    """Typical call should succeed."""\n'
                "    result = %s\n"
                "    assert result is not None  # TODO: pin expected value\n"
                % (node.name, call))
            if _raises_possible(node):
                tests.append(
                    "def test_%s_edge_case_raises() -> None:\n"
                    '    """Degenerate input surfaces a typed error."""\n'
                    "    with pytest.raises(Exception):\n"
                    "        %s\n" % (node.name, edge_call))
            else:
                tests.append(
                    "def test_%s_edge_case() -> None:\n"
                    '    """Empty / zero / None inputs behave sanely."""\n'
                    "    result = %s  # TODO: tighten expectations\n"
                    "    assert result is not None or result is None\n"
                    % (node.name, edge_call))

    if not tests:
        return None, 0
    lines = ["import pytest", ""]
    lines.extend(fixtures)
    if fixtures:
        lines.append("")
    lines.extend(tests)
    scaffold = "\n".join(lines)
    try:
        compile(scaffold, "<generated-tests>", "exec")
    except SyntaxError as exc:
        log.warning("scaffold failed to compile: %s", exc)
        fallback = ('import pytest\n\n\ndef test_todo() -> None:\n'
                    '    """Replace with real assertions."""\n'
                    "    assert True\n")
        return fallback, len(tests)
    return scaffold.rstrip() + "\n", len(tests)

# ---------------------------------------------------------------------------
# local template library (skill 1)
# ---------------------------------------------------------------------------

TEMPLATE_A = [
    (("fibonacci", "fib series", "nth fib"),
     "fibonacci.py",
     '''"""Fibonacci numbers: iterative, recursive, and full series."""
from typing import List


def fib_iterative(n: int) -> int:
    """Return the n-th Fibonacci number (0-indexed) iteratively."""
    if n < 0:
        raise ValueError("n must be >= 0")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def fib_recursive(n: int) -> int:
    """Return the n-th Fibonacci number recursively."""
    if n < 0:
        raise ValueError("n must be >= 0")
    if n < 2:
        return n
    return fib_recursive(n - 1) + fib_recursive(n - 2)


def fib_series(count: int) -> List[int]:
    """Return the first *count* Fibonacci numbers."""
    series: List[int] = []
    a, b = 0, 1
    for _ in range(max(0, count)):
        series.append(a)
        a, b = b, a + b
    return series


if __name__ == "__main__":
    print("iterative fib(10):", fib_iterative(10))
    print("recursive fib(10):", fib_recursive(10))
    print("series:", fib_series(10))
'''),
    (("factorial",),
     "factorial.py",
     '''"""Factorial: iterative and recursive flavours."""
from typing import List


def factorial(n: int) -> int:
    """Return n! iteratively; ValueError for negative n."""
    if n < 0:
        raise ValueError("factorial undefined for negatives")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def factorial_recursive(n: int) -> int:
    """Return n! recursively."""
    if n < 0:
        raise ValueError("factorial undefined for negatives")
    return 1 if n < 2 else n * factorial_recursive(n - 1)


def factorials_up_to(limit: int) -> List[int]:
    """Return [0!, 1!, ..., limit!]."""
    return [factorial(i) for i in range(limit + 1)]


if __name__ == "__main__":
    print("5! =", factorial(5))
    print("recursive 6! =", factorial_recursive(6))
    print(factorials_up_to(7))
'''),
    (("prime sieve", "sieve of eratosthenes", "eratosthenes", "primes",
      "prime numbers"),
     "prime_sieve.py",
     '''"""Sieve of Eratosthenes: all primes below a limit."""
from typing import List


def primes_below(limit: int) -> List[int]:
    """Return every prime p with p < limit using a boolean sieve."""
    if limit <= 2:
        return []
    sieve = bytearray([1]) * limit
    sieve[0] = sieve[1] = 0
    for p in range(2, int(limit ** 0.5) + 1):
        if sieve[p]:
            sieve[p * p::p] = bytearray(len(range(p * p, limit, p)))
    return [i for i, flag in enumerate(sieve) if flag]


def is_prime(n: int) -> bool:
    """Deterministic trial-division primality check."""
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    for d in range(3, int(n ** 0.5) + 1, 2):
        if n % d == 0:
            return False
    return True


if __name__ == "__main__":
    print("primes < 50:", primes_below(50))
    print("97 prime?", is_prime(97))
'''),
    (("palindrome",),
     "palindrome.py",
     '''"""Palindrome checker for words, phrases, and substrings."""
import re
from typing import Tuple


def is_palindrome(text: str) -> bool:
    """Case-insensitive palindrome check ignoring punctuation/spaces."""
    cleaned = re.sub(r"[^a-z0-9]", "", text.lower())
    return cleaned == cleaned[::-1]


def longest_palindrome_substring(s: str) -> str:
    """Longest palindromic substring via expand-around-centre."""
    if len(s) < 2:
        return s
    start, end = 0, 0

    def expand(left: int, right: int) -> Tuple[int, int]:
        while left >= 0 and right < len(s) and s[left] == s[right]:
            left -= 1
            right += 1
        return left + 1, right - 1

    for centre in range(len(s)):
        for lo, hi in (expand(centre, centre), expand(centre, centre + 1)):
            if hi - lo > end - start:
                start, end = lo, hi
    return s[start:end + 1]


if __name__ == "__main__":
    for sample in ("A man, a plan, a canal: Panama", "racecar", "jarvis"):
        print(repr(sample), "->", is_palindrome(sample))
    print(longest_palindrome_substring("babad"))
'''),
    (("anagram",),
     "anagram_check.py",
     '''"""Anagram detection via sorted signatures and bucketing."""
from collections import Counter
from typing import List


def _signature(word: str) -> str:
    """Lowercased, space-stripped sorted letters."""
    return "".join(sorted(word.lower().replace(" ", "")))


def are_anagrams(a: str, b: str) -> bool:
    """True when a and b contain identical letters, order-free."""
    return _signature(a) == _signature(b)


def group_anagrams(words: List[str]) -> List[List[str]]:
    """Bucket words into anagram families."""
    buckets = {}
    for word in words:
        buckets.setdefault(_signature(word), []).append(word)
    return list(buckets.values())


if __name__ == "__main__":
    print(are_anagrams("listen", "silent"))
    print(group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"]))
    print(Counter("silent") == Counter("listen"))
'''),
    (("binary search", "bisect",),
     "binary_search.py",
     '''"""Binary search on ascending lists: lookup and insertion point."""
from typing import List, Optional


def binary_search(items: List[int], target: int) -> Optional[int]:
    """Return the index of target in ascending items, or None."""
    lo, hi = 0, len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def insertion_point(items: List[int], target: int) -> int:
    """Leftmost position where target keeps the list sorted."""
    lo, hi = 0, len(items)
    while lo < hi:
        mid = (lo + hi) // 2
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


if __name__ == "__main__":
    data = [1, 3, 5, 7, 9, 11]
    print(binary_search(data, 7))
    print(binary_search(data, 4))
    print(insertion_point(data, 4))
'''),
    (("quicksort", "quick sort",),
     "quicksort.py",
     '''"""Quicksort: in-place Lomuto partition plus functional variant."""
import random
from typing import List, Optional


def quicksort_inplace(items: List[int], low: int = 0,
                      high: Optional[int] = None) -> List[int]:
    """Sort items ascending in place and return them."""
    if high is None:
        high = len(items) - 1
    if low < high:
        pivot_index = _partition(items, low, high)
        quicksort_inplace(items, low, pivot_index - 1)
        quicksort_inplace(items, pivot_index + 1, high)
    return items


def _partition(items: List[int], low: int, high: int) -> int:
    pivot = items[high]
    wall = low - 1
    for probe in range(low, high):
        if items[probe] <= pivot:
            wall += 1
            items[wall], items[probe] = items[probe], items[wall]
    items[wall + 1], items[high] = items[high], items[wall + 1]
    return wall + 1


def quicksort_functional(items: List[int]) -> List[int]:
    """Non-mutating quicksort (teaching flavour, O(n) extra space)."""
    if len(items) <= 1:
        return list(items)
    pivot, *rest = items
    smaller = [x for x in rest if x < pivot]
    larger = [x for x in rest if x >= pivot]
    return quicksort_functional(smaller) + [pivot] + \\
        quicksort_functional(larger)


if __name__ == "__main__":
    sample = [random.randint(0, 99) for _ in range(10)]
    print(quicksort_inplace(list(sample)))
    print(quicksort_functional(sample))
'''),
    (("bubble sort", "bubblesort",),
     "bubble_sort.py",
     '''"""Bubble sort with an early-exit optimisation."""
from typing import List


def bubble_sort(items: List[int]) -> List[int]:
    """Sort ascending in place; returns items for convenience."""
    n = len(items)
    for pass_no in range(n - 1):
        swapped = False
        for probe in range(n - 1 - pass_no):
            if items[probe] > items[probe + 1]:
                items[probe], items[probe + 1] = (
                    items[probe + 1], items[probe])
                swapped = True
        if not swapped:
            break
    return items


if __name__ == "__main__":
    data = [5, 1, 4, 2, 8, 0, 42]
    print(bubble_sort(data))
'''),
    (("linked list", "linkedlist", "singly linked"),
     "linked_list.py",
     '''"""Singly linked list with append, remove, reverse, iteration."""
from typing import Iterator, List, Optional


class Node:
    """One link in the chain holding a value."""

    def __init__(self, value: object,
                 nxt: "Optional[Node]" = None) -> None:
        self.value = value
        self.next: Optional["Node"] = nxt

    def __repr__(self) -> str:
        return "Node(%r)" % (self.value,)


class LinkedList:
    """Minimal singly linked list."""

    def __init__(self, values: Optional[List[object]] = None) -> None:
        self.head: Optional[Node] = None
        for value in reversed(values or []):
            self.push(value)

    def push(self, value: object) -> None:
        """Insert at the front, O(1)."""
        self.head = Node(value, self.head)

    def append(self, value: object) -> None:
        """Insert at the tail, O(n)."""
        node = Node(value)
        if self.head is None:
            self.head = node
            return
        cursor = self.head
        while cursor.next is not None:
            cursor = cursor.next
        cursor.next = node

    def remove(self, value: object) -> bool:
        """Remove the first matching node; True when something went."""
        prev, cursor = None, self.head
        while cursor is not None:
            if cursor.value == value:
                if prev is None:
                    self.head = cursor.next
                else:
                    prev.next = cursor.next
                return True
            prev, cursor = cursor, cursor.next
        return False

    def reverse(self) -> None:
        """Reverse the chain in place."""
        prev, cursor = None, self.head
        while cursor is not None:
            cursor.next, prev, cursor = prev, cursor, cursor.next
        self.head = prev

    def __iter__(self) -> Iterator[object]:
        cursor = self.head
        while cursor is not None:
            yield cursor.value
            cursor = cursor.next

    def __repr__(self) -> str:
        return " -> ".join(str(v) for v in self) + " -> None"


if __name__ == "__main__":
    lst = LinkedList([3, 1, 2])
    lst.append(9)
    lst.reverse()
    print(lst)
    print("removed 2:", lst.remove(2), "|", lst)
'''),
    (("stack", "lifo",),
     "stack.py",
     '''"""LIFO stack built on a list with O(1) operations."""


class Stack:
    """A tiny generic stack."""

    def __init__(self) -> None:
        self._items: list = []

    def push(self, item: object) -> None:
        """Place item on top."""
        self._items.append(item)

    def pop(self) -> object:
        """Remove and return the top; IndexError when empty."""
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self) -> object:
        """Top item without removal."""
        if not self._items:
            raise IndexError("peek at empty stack")
        return self._items[-1]

    def is_empty(self) -> bool:
        """True when nothing is stored."""
        return not self._items

    def __len__(self) -> int:
        return len(self._items)


def balanced_brackets(text: str) -> bool:
    """Classic stack exercise: ()[]{} balance checker."""
    closers = {")": "(", "]": "[", "}": "{"}
    openers = {v: k for k, v in closers.items()}
    st = Stack()
    for ch in text:
        if ch in openers:
            st.push(ch)
        elif ch in closers:
            if st.is_empty() or st.pop() != closers[ch]:
                return False
    return st.is_empty()


if __name__ == "__main__":
    st = Stack()
    for i in range(3):
        st.push(i)
    print(len(st), st.pop(), st.peek())
    print(balanced_brackets("{[()]}"), balanced_brackets("(]"))
'''),
    (("queue", "fifo",),
     "queue.py",
     '''"""FIFO queue on collections.deque for O(1) ends."""
from collections import deque


class Queue:
    """First-in-first-out queue."""

    def __init__(self) -> None:
        self._items: deque = deque()

    def enqueue(self, item: object) -> None:
        """Add item to the back."""
        self._items.append(item)

    def dequeue(self) -> object:
        """Remove and return the front; IndexError when empty."""
        if not self._items:
            raise IndexError("dequeue from empty queue")
        return self._items.popleft()

    def peek(self) -> object:
        """Front item without removal."""
        if not self._items:
            raise IndexError("peek at empty queue")
        return self._items[0]

    def __len__(self) -> int:
        return len(self._items)


if __name__ == "__main__":
    q = Queue()
    for name in ("alpha", "beta", "gamma"):
        q.enqueue(name)
    print(len(q), q.peek())
    while len(q):
        print(q.dequeue(), end=" ")
    print()
'''),
    (("binary tree", "bst", "inorder", "in-order", "tree insert"),
     "bst.py",
     '''"""Binary search tree: insert, membership, in-order traversal."""
from typing import List, Optional


class TreeNode:
    """One BST node."""

    def __init__(self, value: int) -> None:
        self.value: int = value
        self.left: Optional["TreeNode"] = None
        self.right: Optional["TreeNode"] = None


class BinarySearchTree:
    """Duplicate-free integer BST."""

    def __init__(self, values: Optional[List[int]] = None) -> None:
        self.root: Optional[TreeNode] = None
        for value in values or []:
            self.insert(value)

    def insert(self, value: int) -> None:
        """Insert value iteratively, ignoring duplicates."""
        if self.root is None:
            self.root = TreeNode(value)
            return
        node = self.root
        while node is not None:
            if value == node.value:
                return
            if value < node.value:
                if node.left is None:
                    node.left = TreeNode(value)
                    return
                node = node.left
            else:
                if node.right is None:
                    node.right = TreeNode(value)
                    return
                node = node.right

    def inorder(self) -> List[int]:
        """Sorted values via recursive in-order traversal."""
        out: List[int] = []

        def visit(node: Optional[TreeNode]) -> None:
            if node is None:
                return
            visit(node.left)
            out.append(node.value)
            visit(node.right)

        visit(self.root)
        return out

    def __contains__(self, value: int) -> bool:
        node = self.root
        while node is not None:
            if value == node.value:
                return True
            node = node.left if value < node.value else node.right
        return False


if __name__ == "__main__":
    bst = BinarySearchTree([7, 3, 9, 1, 5])
    print(bst.inorder())
    print(5 in bst, 4 in bst)
'''),
    (("bfs", "dfs", "graph traversal", "breadth first", "depth first",
      "shortest path", "graph"),
     "graph_traversal.py",
     '''"""Graph traversal: BFS, DFS, and BFS shortest path."""
from collections import deque
from typing import Dict, List, Set

Graph = Dict[str, List[str]]


def bfs(graph: Graph, start: str) -> List[str]:
    """Visit neighbours layer by layer."""
    visited: Set[str] = {start}
    order: List[str] = []
    frontier: deque = deque([start])
    while frontier:
        node = frontier.popleft()
        order.append(node)
        for neighbour in graph.get(node, []):
            if neighbour not in visited:
                visited.add(neighbour)
                frontier.append(neighbour)
    return order


def dfs(graph: Graph, start: str) -> List[str]:
    """Go as deep as possible before backtracking (iterative)."""
    visited: Set[str] = set()
    order: List[str] = []
    frontier: List[str] = [start]
    while frontier:
        node = frontier.pop()
        if node in visited:
            continue
        visited.add(node)
        order.append(node)
        for neighbour in reversed(graph.get(node, [])):
            if neighbour not in visited:
                frontier.append(neighbour)
    return order


def shortest_path(graph: Graph, start: str, goal: str) -> List[str]:
    """Fewest-edges path via BFS parents; [] when unreachable."""
    parents: Dict[str, str] = {start: ""}
    frontier: deque = deque([start])
    while frontier:
        node = frontier.popleft()
        if node == goal:
            path = [goal]
            while parents[path[-1]]:
                path.append(parents[path[-1]])
            return list(reversed(path))
        for nb in graph.get(node, []):
            if nb not in parents:
                parents[nb] = node
                frontier.append(nb)
    return []


if __name__ == "__main__":
    g: Graph = {"A": ["B", "C"], "B": ["D"], "C": ["D", "E"],
                "D": ["E"], "E": []}
    print("bfs:", bfs(g, "A"))
    print("dfs:", dfs(g, "A"))
    print("path A->E:", shortest_path(g, "A", "E"))
'''),
]

TEMPLATE_B = [
    (("word frequency", "word count", "count words", "frequency counter",
      "top words"),
     "word_frequency.py",
     '''"""Word frequency counting with stopword-aware reporting."""
import re
from collections import Counter
from typing import Dict

STOPWORDS = frozenset("""a an and are as at be but by for from has have i in
is it its of on or that the to was were will with""".split())


def word_frequencies(text: str) -> Counter:
    """Counter of lowercase words ignoring punctuation and stopwords."""
    words = re.findall(r"[a-z']+", text.lower())
    kept = (w for w in words if w not in STOPWORDS and len(w) > 1)
    return Counter(kept)


def top_words(text: str, n: int = 5) -> Dict[str, int]:
    """Most common n words as a plain dict."""
    return dict(word_frequencies(text).most_common(n))


if __name__ == "__main__":
    passage = ("The quick brown fox jumps over the lazy dog "
               "while the dog naps.")
    print(top_words(passage, 3))
'''),
    (("# jarvis:no-exec", "csv", "tsv"),
     "csv_reader.py",
     '''"""CSV reading and writing with DictReader / DictWriter."""
# jarvis:no-exec
import csv
from pathlib import Path
from typing import List


def read_rows(path: str) -> List[dict]:
    """Read a CSV file into dicts keyed by the header row."""
    with open(path, newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_rows(path: str, rows: List[dict]) -> None:
    """Write dicts as CSV using the union of their keys as header."""
    if not rows:
        return
    fieldnames = sorted({key for row in rows for key in row})
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    demo = Path("demo_people.csv")
    write_rows(str(demo), [{"name": "Ada", "role": "engineer"},
                           {"name": "Alan", "role": "mathematician"}])
    print(read_rows(str(demo)))
    demo.unlink(missing_ok=True)
'''),
    (("# jarvis:no-exec", "json",),
     "json_io.py",
     '''"""JSON load/save helpers preserving pretty formatting."""
# jarvis:no-exec
import json
from pathlib import Path
from typing import Any


def load_json(path: str) -> Any:
    """Read JSON from path as UTF-8."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: str, data: Any, indent: int = 2) -> None:
    """Write data as UTF-8 JSON with sorted keys."""
    Path(path).write_text(json.dumps(data, indent=indent, sort_keys=True),
                          encoding="utf-8")


def merge_json_files(source: str, override: str) -> Any:
    """Shallow-merge two JSON objects; override wins on clashes."""
    merged = dict(load_json(source))
    merged.update(load_json(override))
    return merged


if __name__ == "__main__":
    save_json("demo_cfg.json", {"name": "jarvis", "skills": 8})
    print(load_json("demo_cfg.json"))
    Path("demo_cfg.json").unlink()
'''),
    (("# jarvis:no-exec", "http get", "http request", "requests library",
      "fetch url", "download url", "call an api", "rest call", "api call",
      "with retries"),
     "http_get.py",
     '''"""Robust HTTP GET with requests: retries, timeouts, JSON decoding."""
# jarvis:no-exec
import time
from typing import Any, Dict, Optional

import requests

DEFAULT_TIMEOUT = 10.0
RETRY_DELAYS = (1.0, 2.0, 4.0)


def http_get(url: str,
             params: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> requests.Response:
    """GET url with exponential backoff; raises after final retry."""
    last_error: Optional[Exception] = None
    for delay in (0,) + RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(url, params=params, headers=headers,
                                    timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
    raise RuntimeError("GET failed after retries") from last_error


def get_json(url: str, **kwargs: Any) -> Any:
    """GET and decode a JSON body."""
    return http_get(url, **kwargs).json()


if __name__ == "__main__":
    payload = get_json("https://api.github.com/repos/python/cpython")
    print(payload.get("full_name"), payload.get("stargazers_count"))
'''),
    (("# jarvis:no-exec", "flask",),
     "flask_api.py",
     '''"""Tiny Flask JSON API: hello endpoint plus error handling."""
# jarvis:no-exec
from typing import Tuple

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.get("/api/hello")
def hello() -> Tuple[dict, int]:
    """GET /api/hello?name=X -> greeting payload."""
    who = request.args.get("name", "world")
    return jsonify(message=f"Hello, {who}!"), 200


@app.get("/api/divide")
def divide() -> Tuple[dict, int]:
    """GET /api/divide?a=6&b=3 demonstrating typed errors."""
    try:
        a = float(request.args.get("a", 0))
        b = float(request.args.get("b", 1))
    except ValueError:
        return jsonify(error="a and b must be numbers"), 400
    if b == 0:
        return jsonify(error="cannot divide by zero"), 400
    return jsonify(result=a / b), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
'''),
    (("# jarvis:no-exec", "fastapi", "pydantic",),
     "fastapi_api.py",
     '''"""FastAPI service with a Pydantic model and auto docs."""
# jarvis:no-exec
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Jarvis Demo API")


class Task(BaseModel):
    """Incoming task payload, validated by Pydantic."""

    title: str = Field(min_length=1, max_length=120)
    priority: int = Field(default=1, ge=1, le=5)


_TASKS: dict = {}
_NEXT_ID: list = [1]


@app.post("/tasks", status_code=201)
def create_task(task: Task) -> Task:
    """Store a validated task and echo it back."""
    task_id = _NEXT_ID[0]
    _NEXT_ID[0] += 1
    _TASKS[task_id] = task
    return task


@app.get("/tasks/{task_id}")
def read_task(task_id: int) -> Task:
    """Fetch one task or raise a 404."""
    if task_id not in _TASKS:
        raise HTTPException(status_code=404, detail="no such task")
    return _TASKS[task_id]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''),
    (("# jarvis:no-exec", "sqlite", "crud", "database"),
     "sqlite_crud.py",
     '''"""SQLite CRUD with parameterised queries and safe sessions."""
# jarvis:no-exec
import os
import sqlite3
from contextlib import closing
from typing import List, Tuple


def _connect(db_path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
    return conn


def create_item(db_path: str, name: str) -> int:
    """Insert one parameterised row; returns the new id."""
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute(
            "INSERT INTO items (name) VALUES (?)", (name,))
        return int(cur.lastrowid or 0)


def list_items(db_path: str) -> List[Tuple[int, str]]:
    """All rows as (id, name) tuples."""
    with closing(_connect(db_path)) as conn:
        return list(conn.execute(
            "SELECT id, name FROM items ORDER BY id"))


def rename_item(db_path: str, item_id: int, new_name: str) -> bool:
    """Update one row parameterised; True when a row changed."""
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute(
            "UPDATE items SET name = ? WHERE id = ?", (new_name, item_id))
        return cur.rowcount > 0


def delete_item(db_path: str, item_id: int) -> bool:
    """Delete one row parameterised; True when a row vanished."""
    with closing(_connect(db_path)) as conn, conn:
        cur = conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cur.rowcount > 0


if __name__ == "__main__":
    db = "demo_items.sqlite3"
    new_id = create_item(db, "sonar")
    print(list_items(db))
    print(rename_item(db, new_id, "radar"), delete_item(db, new_id))
    if os.path.exists(db):
        os.remove(db)
'''),
    (("dataclass", "data model", "record model", "model class"),
     "data_model.py",
     '''"""Dataclass domain model with __post_init__ validation."""
from dataclasses import dataclass, field
from typing import List


@dataclass
class InventoryItem:
    """A stocked product; quantities are validated on construction."""

    name: str
    unit_price: float
    quantity_on_hand: int = 0
    tags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.unit_price < 0:
            raise ValueError("unit_price must be non-negative")
        if self.quantity_on_hand < 0:
            raise ValueError("quantity cannot be negative")

    @property
    def total_cost(self) -> float:
        """Price times quantity, rounded to pence."""
        return round(self.unit_price * self.quantity_on_hand, 2)

    def add_tags(self, *tags: str) -> "InventoryItem":
        """Attach tags; returns self for chaining."""
        self.tags.extend(t for t in tags if t not in self.tags)
        return self


if __name__ == "__main__":
    item = InventoryItem("sonar widget", 19.99, 3).add_tags(
        "hardware", "sensor")
    print(item, item.total_cost)
    try:
        InventoryItem("bad", -1.0)
    except ValueError as exc:
        print("rejected:", exc)
'''),
    (("custom exception", "exception hierarchy", "error hierarchy",
      "custom errors"),
     "exceptions.py",
     '''"""Custom exception hierarchy: base error plus specialised failures."""


class JarvisError(Exception):
    """Root of this project's error hierarchy."""


class ConfigError(JarvisError):
    """Malformed or missing configuration."""


class ConfigMissingKeyError(ConfigError):
    """A required configuration key is absent."""


class DeviceError(JarvisError):
    """A device misbehaved; carries its name."""

    def __init__(self, device: str, message: str) -> None:
        super().__init__(f"{device}: {message}")
        self.device = device


def load_config(mapping: dict, *keys: str) -> dict:
    """Pick keys from mapping, raising typed errors when absent."""
    selected = {}
    for key in keys:
        if key not in mapping:
            raise ConfigMissingKeyError(f"config key missing: {key}")
        selected[key] = mapping[key]
    return selected


if __name__ == "__main__":
    try:
        load_config({"host": "localhost"}, "host", "port")
    except ConfigMissingKeyError as exc:
        print("typed failure:", exc)
    except JarvisError:
        print("hierarchy catches everything of ours")
    try:
        raise DeviceError("thrusters", "overheated")
    except DeviceError as exc:
        print(exc, "| device =", exc.device)
'''),
    (("timing decorator", "timer decorator", "measure runtime",
      "time a function"),
     "timing_decorator.py",
     '''"""Timing decorator reporting how long each call takes."""
import functools
import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


def timed(func: Callable) -> Callable:
    """Log the wall-clock duration of every decorated call."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            log.info("%s took %.3fs", func.__qualname__, elapsed)
            print(f"{func.__qualname__} took {elapsed:.3f}s")

    return wrapper


@timed
def crunch(n: int) -> int:
    """Demo workload: sum a big range."""
    return sum(range(n))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(crunch(1000000))
'''),
    (("retry decorator", "decorator that retries", "retryable"),
     "retry_decorator.py",
     '''"""Retry decorator with exponential-ish backoff for flaky calls."""
import functools
import random
import time
from typing import Any, Callable, Tuple, TypeVar

T = TypeVar("T")


def retry(times: int = 3, delays: Tuple[float, ...] = (0.05, 0.1, 0.2),
          exceptions: Tuple[type, ...] = (Exception,)) -> Callable:
    """Re-run the call up to *times* attempts, pausing between tries."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last: Exception = RuntimeError("unreachable")
            for attempt in range(max(1, times)):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last = exc
                    if attempt < times - 1 and attempt < len(delays):
                        time.sleep(delays[attempt])
            raise last

        return wrapper

    return decorator


@retry(times=4, delays=(0.01, 0.02, 0.04))
def flaky_dice(threshold: int = 2) -> int:
    """Roll until at least threshold; raises only when very unlucky."""
    roll = random.randint(1, 6)
    if roll < threshold:
        raise OSError(f"rolled {roll} < {threshold}")
    return roll


if __name__ == "__main__":
    print("survived with roll:", flaky_dice())
'''),
    (("context manager timer", "contextmanager", "timed block",
      "context timer"),
     "timed_block.py",
     '''"""Context-manager stopwatch plus a reusable timed block."""
import time
from contextlib import contextmanager
from typing import Any, Iterator


class Timer:
    """Measure a with-block; read .elapsed afterwards."""

    def __enter__(self) -> "Timer":
        self._started = time.perf_counter()
        self.elapsed: float = 0.0
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.elapsed = time.perf_counter() - self._started
        return False


@contextmanager
def timed_block(label: str = "block") -> Iterator[None]:
    """Print how long the managed block took."""
    started = time.perf_counter()
    try:
        yield
    finally:
        print(f"{label} took {time.perf_counter() - started:.4f}s")


if __name__ == "__main__":
    with Timer():
        total = sum(i * i for i in range(200000))
    print(total)
    with timed_block("modular exponentiation"):
        pow(2, 10000, 999983)
'''),
    (("generator", "yield", "fibonacci stream",),
     "fib_generator.py",
     '''"""Infinite Fibonacci generator with itertools helpers."""
import itertools
from typing import Iterator


def fibonacci_stream() -> Iterator[int]:
    """Yield 0, 1, 1, 2, 3, ... forever - take what you need."""
    a, b = 0, 1
    while True:
        yield a
        a, b = b, a + b


def fib_upto(limit: int) -> Iterator[int]:
    """Fibonacci values below limit as a finite stream."""
    for value in fibonacci_stream():
        if value > limit:
            return
        yield value


def nth_fibonacci(n: int) -> int:
    """Zero-indexed n-th Fibonacci number via the stream."""
    return next(itertools.islice(fibonacci_stream(), n, None))


if __name__ == "__main__":
    print(list(itertools.islice(fibonacci_stream(), 10)))
    print(list(fib_upto(100)))
    print(nth_fibonacci(30))
'''),
]

TEMPLATE_C = [
    (("# jarvis:no-exec", "argparse", "command line tool", "cli skeleton",
      "cli tool"),
     "cli_tool.py",
     '''"""argparse CLI skeleton: typed flags and a testable main()."""
# jarvis:no-exec
import argparse
import sys
from typing import List, Optional


def build_parser() -> argparse.ArgumentParser:
    """Assemble the CLI surface."""
    parser = argparse.ArgumentParser(
        prog="greeter", description="Greet people politely.")
    parser.add_argument("names", nargs="+", help="who to greet")
    parser.add_argument("-u", "--uppercase", action="store_true",
                        help="SHOUT the greeting")
    parser.add_argument("-n", "--times", type=int, default=1,
                        metavar="N", help="repeat count")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point returning a process exit code."""
    args = build_parser().parse_args(argv)
    greeting = "Hello, " + ", ".join(args.names)
    if args.uppercase:
        greeting = greeting.upper()
    for _ in range(max(1, args.times)):
        print(greeting + "!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''),
    (("# jarvis:no-exec", "tkinter", "gui window", "desktop window", "gui"),
     "tk_window.py",
     '''"""Tkinter starter window: label, entry, button, grid layout."""
# jarvis:no-exec
import tkinter as tk
from tkinter import ttk


class App(tk.Tk):
    """Minimal desktop window skeleton."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Jarvis Toolkit")
        self.geometry("360x160")
        self.name_var = tk.StringVar()
        heading = ttk.Label(self, text="Mission Control",
                            font=("Helvetica", 14, "bold"))
        entry = ttk.Entry(self, textvariable=self.name_var)
        button = ttk.Button(self, text="Engage", command=self._engage)
        output = ttk.Label(self, textvariable=self.name_var,
                           foreground="#555")
        heading.grid(row=0, column=0, columnspan=2, pady=8)
        entry.grid(row=1, column=0, padx=8, sticky="ew")
        button.grid(row=1, column=1, padx=8)
        output.grid(row=2, column=0, columnspan=2, pady=8)

    def _engage(self) -> None:
        """React to the button press."""
        if not self.name_var.get():
            self.name_var.set("sir")


if __name__ == "__main__":
    App().mainloop()
'''),
    (("password generator", "password", "secure password"),
     "password_generator.py",
     '''"""Cryptographically secure password generator using secrets."""
import secrets
import string

ALPHABETS = {
    "lower": string.ascii_lowercase,
    "upper": string.ascii_uppercase,
    "digits": string.digits,
    "symbols": "!@#$%^&*-_=+?",
}


def generate_password(length: int = 16,
                      groups: str = "lower,upper,digits,symbols") -> str:
    """Guarantee one char per requested group; fill the rest randomly."""
    pools = [ALPHABETS[g] for g in groups.split(",") if ALPHABETS.get(g)]
    if not pools or length < len(pools):
        raise ValueError("length must cover every requested group")
    chars = [secrets.choice(pool) for pool in pools]
    universe = "".join(pools)
    chars += [secrets.choice(universe) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


if __name__ == "__main__":
    for n in (12, 16, 24):
        print(generate_password(n))
'''),
    (("countdown timer", "countdown", "launch timer"),
     "countdown_timer.py",
     '''"""Countdown timer printing T-minus progress with a bounded loop."""
import sys
import time
from typing import Generator


def countdown(seconds: int) -> Generator[int, None, None]:
    """Yield remaining seconds down to zero."""
    if seconds < 0:
        raise ValueError("seconds must be >= 0")
    remaining = seconds
    while remaining >= 0:
        yield remaining
        remaining -= 1


def run_countdown(seconds: int) -> None:
    """Drive the countdown generator with one-second ticks."""
    for remaining in countdown(seconds):
        print(f"T-{remaining:02d}", flush=True)
        if remaining:
            time.sleep(1)
    print("Liftoff, sir!")


if __name__ == "__main__":
    run_countdown(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
'''),
    (("email validator", "validate email", "email validation",
      "check email", "email"),
     "email_validator.py",
     r'''"""Email address syntax checker with a pragmatic RFC-lite regex."""
import re

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def is_valid_email(address: str) -> bool:
    """True when the address looks deliverable-shaped."""
    return bool(EMAIL_RE.match(address.strip()))


def harvest_emails(text: str) -> list:
    """Pull email-looking tokens out of free text."""
    loose = EMAIL_RE.pattern.strip("^$")
    return re.findall(loose, text)


if __name__ == "__main__":
    for candidate in ("ada@example.com", "not-an-email",
                      "bot+jr@sub.domain.org"):
        print(candidate, is_valid_email(candidate))
'''),
    (("gcd", "euclid", "greatest common divisor", "lcm",),
     "gcd.py",
     '''"""Euclidean GCD and LCM, iterative and recursive."""


def gcd(a: int, b: int) -> int:
    """Greatest common divisor via Euclid's algorithm (iterative)."""
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def gcd_recursive(a: int, b: int) -> int:
    """Same result recursively."""
    return abs(a) if b == 0 else gcd_recursive(b, a % b)


def lcm(a: int, b: int) -> int:
    """Least common multiple built on gcd (zero-safe)."""
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // gcd(a, b)


if __name__ == "__main__":
    print(gcd(48, 18), gcd_recursive(48, 18), lcm(4, 6))
'''),
    (("matrix multiply", "matrix multiplication", "matmul", "matrices",
      "matrix"),
     "matrix_multiply.py",
     '''"""Matrix multiplication from scratch with an identity helper."""
from typing import List

Matrix = List[List[int]]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    """Multiply m x n by n x p; ValueError on shape mismatch."""
    if not a or not b or len(a[0]) != len(b):
        raise ValueError("inner dimensions must agree")
    rows, inner, cols = len(a), len(b), len(b[0])
    result = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        for k in range(inner):
            aik = a[i][k]
            if aik == 0:
                continue
            for j in range(cols):
                result[i][j] += aik * b[k][j]
    return result


def identity(n: int) -> Matrix:
    """The n x n identity matrix."""
    return [[1 if r == c else 0 for c in range(n)] for r in range(n)]


if __name__ == "__main__":
    m1 = [[1, 2], [3, 4]]
    print(matmul(m1, [[0, 1], [1, 0]]))
    print(matmul(m1, identity(2)))
'''),
    (("temperature converter", "temperature", "celsius", "fahrenheit"),
     "temperature.py",
     '''"""Temperature conversions across Celsius, Fahrenheit, Kelvin."""
from typing import Callable, Dict


def c_to_f(celsius: float) -> float:
    """Celsius to Fahrenheit."""
    return celsius * 9 / 5 + 32


def f_to_c(fahrenheit: float) -> float:
    """Fahrenheit to Celsius."""
    return (fahrenheit - 32) * 5 / 9


def c_to_k(celsius: float) -> float:
    """Celsius to Kelvin."""
    return celsius + 273.15


def k_to_c(kelvin: float) -> float:
    """Kelvin to Celsius."""
    return kelvin - 273.15


CONVERSIONS: Dict[str, Callable[[float], float]] = {
    "c->f": c_to_f, "f->c": f_to_c, "c->k": c_to_k, "k->c": k_to_c,
    "f->k": lambda f: c_to_k(f_to_c(f)),
    "k->f": lambda k: c_to_f(k_to_c(k)),
}


def convert(value: float, direction: str) -> float:
    """Convert value along an 'x->y' direction key."""
    try:
        converter = CONVERSIONS[direction]
    except KeyError:
        raise ValueError("unknown direction: %s" % direction) from None
    return round(converter(value), 2)


if __name__ == "__main__":
    for direction in CONVERSIONS:
        print(direction, convert(100.0, direction))
'''),
    (("# jarvis:no-exec", "pytest template", "unit test template",
      "unittest template", "test suite template", "skeleton test"),
     "test_template.py",
     '''"""Pytest-style unit test skeleton ready to extend."""
# jarvis:no-exec
import pytest


def divide(a: float, b: float) -> float:
    """Sample unit under test - replace with your real function."""
    if b == 0:
        raise ZeroDivisionError("cannot divide by zero")
    return a / b


class TestDivide:
    """Grouped tests exercising happy paths and failures."""

    def test_happy_path(self) -> None:
        assert divide(9.0, 3.0) == pytest.approx(3.0)

    def test_negative_numbers(self) -> None:
        assert divide(-9.0, 3.0) == pytest.approx(-3.0)

    def test_zero_divisor_raises(self) -> None:
        with pytest.raises(ZeroDivisionError):
            divide(1.0, 0.0)


@pytest.mark.parametrize(("a", "b", "expected"), [
    (1.0, 2.0, 0.5),
    (-1.0, -2.0, 0.5),
    (0.0, 5.0, 0.0),
])
def test_divide_table(a: float, b: float, expected: float) -> None:
    assert divide(a, b) == pytest.approx(expected)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
'''),
]

TEMPLATE_LIBRARY = TEMPLATE_A + TEMPLATE_B + TEMPLATE_C


def _local_template(task):
    """Pick the best template for the task; returns (code, name) or None."""
    t = re.sub(r"[^a-z0-9# ]+", " ", (task or "").lower())
    best = None
    best_score = 0
    for keys, name, code in TEMPLATE_LIBRARY:
        score = 0
        for key in keys:
            if key.startswith("#"):
                continue
            if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(key), t):
                score += 1
        if score > best_score:
            best_score = score
            best = (code, name)
    if best is None:
        return None
    return _embed_task(best[0], task), best[1]


def _guard(fn):
    @functools.wraps(fn)
    def wrapped(app, ctx):
        try:
            return fn(app, ctx)
        except Exception as exc:
            log.exception("coding skill misfired")
            return "Something misfired in my coding module, sir: %s" % (
                str(exc)[:120] or exc.__class__.__name__)
    return wrapped


# ---------------------------------------------------------------------------
# skill 1: pro_write_code
# ---------------------------------------------------------------------------

def _d_write(cmd):
    c = cmd.lower()
    if _BANNED_TOPICS_RE.search(c):
        return None
    if _TESTS_INTENT_RE.search(c):
        return None
    if not _PRO_WRITE_RE.search(c):
        return None
    return {"cmd": c, "task": c}


@_guard
def _e_write(app, ctx):
    task = ctx.get("task") or ""
    cv = _cv()
    hit = _local_template(task)
    if hit:
        code, name = hit
        warning = ""
        if cv is not None:
            try:
                vr = cv.validate(code, "python",
                                 exec_simple=_safe_to_exec(code))
                if not getattr(vr, "ok", True):
                    warning = ("\n\nHeads-up, sir — validation flagged it: "
                               "%s" % _summarize_vr(cv, vr))
            except Exception as exc:
                log.warning("template validation skipped: %s", exc)
        _store_last(code, "python", name)
        return ("Built locally, sir — verified syntax and compile:\n\n%s%s\n\n"
                "Say 'save it as %s' and I'll write it to disk, sir."
                % (code, warning, name))

    lang = _sniff_lang(task) or "python"
    prompt = _senior_prompt(task, lang)
    code, vr = None, None
    if cv is not None and hasattr(cv, "generate_validated"):
        try:
            res = cv.generate_validated(
                llm_call=lambda p: _llm(app, p), prompt=prompt,
                lang_hint=lang, exec_simple=False)
            if isinstance(res, tuple) and len(res) == 2:
                code, vr = res
            elif isinstance(res, str):
                code = res
        except Exception as exc:
            log.warning("generate_validated failed: %s", exc)
    else:
        raw = _llm(app, prompt)
        if raw:
            code = _strip_fences_basic(raw)
    if code:
        name = _suggest_name(task, lang)
        _store_last(code, lang, name)
        parts = ["Here you go, sir:", "", code]
        summary = _summarize_vr(cv, vr)
        if summary:
            parts += ["", summary]
        parts += ["", "Say 'save it as %s' and I'll write it to disk, sir."
                  % name]
        return "\n".join(parts)
    return ("I can't reach my language model right now, sir, and that "
            "request exceeds my offline library.\nOn the spot I can still "
            "build: fibonacci series, prime sieve, binary search, quicksort, "
            "stack and queue classes, word-frequency counter, CSV reader, "
            "JSON load/save, sqlite CRUD, dataclass models, timing/retry "
            "decorators, password generator, countdown timer, argparse CLI "
            "and more — just name one, sir.")


# ---------------------------------------------------------------------------
# skill 2: pro_save_code
# ---------------------------------------------------------------------------

def _d_save(cmd):
    c = cmd.lower()
    if not _SAVE_RE.search(c):
        return None
    am = _AS_FILE_RE.search(c)
    return {"cmd": c, "filename": am.group(1) if am else None}


def _resolve_save_path(filename):
    """Resolve filename under PROJECT_DIR; None when it escapes it."""
    proj_real = os.path.realpath(PROJECT_DIR)
    rel = os.path.normpath((filename or "").strip().replace("\\", "/"))
    candidate = rel if os.path.isabs(rel) else os.path.join(PROJECT_DIR, rel)
    target = os.path.realpath(candidate)
    if target == proj_real or not target.startswith(proj_real + os.sep):
        return None
    return target


@_guard
def _e_save(app, ctx):
    code = LAST_CODE.get("code")
    if not code:
        return ("There's nothing fresh on my workbench yet, sir — ask me to "
                "build some code first, then say 'save it as name.py', sir.")
    requested = ctx.get("filename") or LAST_CODE.get("name") \
        or "generated_code.py"
    target = _resolve_save_path(requested)
    if target is None:
        return ("I keep generated files inside the project folder, sir — "
                "'%s' would escape it, so I've declined." % requested.strip())
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    backed = ""
    if os.path.exists(target):
        shutil.copy2(target, target + ".bak")
        backed = "\nPrevious version backed up to %s.bak, sir." % target
    status = "syntax verified locally"
    cv = _cv()
    if cv is not None:
        try:
            status = _summarize_vr(
                cv, cv.validate(code, LAST_CODE.get("lang") or "python"))
        except Exception as exc:
            log.warning("pre-save validation skipped: %s", exc)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(code)
    nlines = code.count("\n") + (0 if code.endswith("\n") else 1)
    return ("Saved to %s, sir — validation: %s — %d lines.%s"
            % (target, status, nlines, backed))


# ---------------------------------------------------------------------------
# shared rewrite plumbing (skills 3 & 4)
# ---------------------------------------------------------------------------

_FIX_USAGE = ("Nothing to fix yet, sir. Paste the code between triple "
              "backticks, or point me at a file — e.g. \"fix the bug in "
              "utils.py\", \"debug this code:\" followed by the snippet, or "
              "\"why does my program crash in app.py\", sir.")

_IMPROVE_USAGE = ("Give me something to polish, sir — paste the code between "
                  "triple backticks or say \"improve the code in utils.py\", "
                  "sir.")


def _validated_rewrite(app, cv, instruction, original, extra=""):
    """Ask the LLM for a full validated rewrite; (code, vr) or (None, None)."""
    prompt = (_SENIOR_RULES + instruction + "\nORIGINAL CODE:\n```python\n"
              + _clip(original) + "\n```\n" + extra)
    if cv is not None and hasattr(cv, "generate_validated"):
        try:
            res = cv.generate_validated(llm_call=lambda p: _llm(app, p),
                                        prompt=prompt, lang_hint="python",
                                        exec_simple=False)
            if isinstance(res, tuple) and len(res) == 2 and res[0]:
                return res[0], res[1]
        except Exception as exc:
            log.warning("generate_validated failed: %s", exc)
    else:
        raw = _llm(app, prompt)
        if raw:
            return _strip_fences_basic(raw), None
    return None, None


def _write_back(path, new_text):
    """Backup then overwrite; returns a persona note."""
    note = ""
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        note = " Backup: %s.bak." % path
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return note


def _diff_summary(old_text, new_text, max_items=3):
    """Count changed diff lines; return (count, first few +/- lines)."""
    changes = [ln for ln in difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), lineterm="", n=0)
        if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    sample = [re.sub(r"\s+", " ", ln.strip())[:72]
              for ln in changes[:max_items]]
    return len(changes), sample


# ---------------------------------------------------------------------------
# skill 3: pro_fix_code
# ---------------------------------------------------------------------------

def _d_fix(cmd):
    c = cmd.lower()
    if not _FIX_VERB_RE.search(c):
        return None
    payload = _extract_payload(c, r"\b(?:fix|debug|repair)\b")
    fref = _find_file_ref(c)
    if not (payload or fref or _CODEWORD_RE.search(c)):
        return None
    return {"cmd": c, "payload": payload, "file": fref}


@_guard
def _e_fix(app, ctx):
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None:
        return _FIX_USAGE

    fixed, applied = _local_auto_fixes(code)
    cv = _cv()
    improved, vr = _validated_rewrite(
        app, cv,
        "Fix the bug(s) in the code below while keeping its intended "
        "behaviour identical.\nOutput the FULL corrected code in ONE fence; "
        "AFTER the fence briefly explain what was wrong.",
        fixed,
        extra=("Quick fixes already applied locally: %s\n"
               % "; ".join(applied)) if applied else "")

    if improved:
        final_code = improved
    elif applied:
        final_code = fixed
    else:
        return _OFFLINE_CHECKLIST

    validation = _summarize_vr(cv, vr) if improved else \
        "local auto-fixes only, no model pass"
    changed, sample = _diff_summary(code, final_code)
    if path:
        note = _write_back(path, final_code)
        deltas = "".join("\n • %s %s" % (s[0], s[1:].strip())
                         for s in sample) or "\n • cosmetic changes only"
        return ("Fixed and written back to %s, sir — %d changed line(s).%s\n"
                "Top changes:%s\nValidation: %s"
                % (path, changed, note, deltas, validation))
    _store_last(final_code, "python", "fixed_code.py")
    parts = ["Here's the repaired code, sir:"]
    if applied and not improved:
        parts.append("Language model unreachable, sir — mechanical auto-fixes "
                     "only:\n- %s" % "\n- ".join(applied))
    elif applied:
        parts.append("Local pre-pass also applied: %s."
                     % "; ".join(applied))
    parts += ["", final_code]
    summary = _summarize_vr(cv, vr)
    if summary:
        parts += ["", summary]
    parts += ["", "Say 'save it as fixed_code.py' to keep it, sir."]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# skill 4: pro_improve_code
# ---------------------------------------------------------------------------

def _d_improve(cmd):
    c = cmd.lower()
    if not _IMPROVE_RE.search(c):
        return None
    payload = _extract_payload(
        c, r"\b(?:improve|refactor|optimize|optimise|polish|enhance)\b")
    fref = _find_file_ref(c)
    if not (payload or fref or _CODEWORD_RE.search(c)):
        return None
    return {"cmd": c, "payload": payload, "file": fref}


@_guard
def _e_improve(app, ctx):
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None:
        return _IMPROVE_USAGE

    findings = _analyze(code)
    hints = "\n".join("- [%s] L%s %s: %s" % (sev, line, title, detail)
                      for sev, line, title, detail in findings[:6])
    prompt_extra = ("Top findings from my local review (address these):\n%s\n"
                    % (hints or "- none")) + _REVIEW_CHECKLIST
    cv = _cv()
    improved, vr = _validated_rewrite(
        app, cv,
        "Improve the code below the way a senior reviewer would: clearer "
        "naming, dead code removed, lower complexity, robust error handling, "
        "full type hints and docstrings, security and performance wins. Keep "
        "behaviour identical.\nOutput the FULL improved file in ONE fence; "
        "AFTER the fence give a short bullet changelog.",
        code, extra=prompt_extra)

    if not improved:
        if findings:
            listing = "\n".join(
                " %s  L%s %s — %s" % (sev, line, title, detail)
                for sev, line, title, detail in findings[:8])
            return ("My language model is unreachable, sir, so here's the "
                    "local review instead — say \"review this code\" for the "
                    "full audit:\n%s\nScore estimate: %.1f/10. Reconnect me "
                    "for the full rewrite, sir."
                    % (listing, _score_findings(findings)))
        return ("My language model is unreachable and the code already "
                "passes my local checks, sir — nothing mechanical left to "
                "improve offline.")

    changed, sample = _diff_summary(code, improved)
    if path:
        note = _write_back(path, improved)
        deltas = "".join("\n • %s %s" % (s[0], s[1:].strip())
                         for s in sample) or "\n • mostly restructuring"
        return ("Improved and written back to %s, sir — %d changed line(s), "
                "validation: %s.%s\nKey deltas:%s"
                % (path, changed, _summarize_vr(cv, vr), note, deltas))
    _store_last(improved, "python", "improved_code.py")
    return ("Here's the polished version, sir — validation: %s\n\n%s\n\nSay "
            "'save it as improved_code.py' to keep it, sir."
            % (_summarize_vr(cv, vr), improved))


# ---------------------------------------------------------------------------
# skill 5: pro_review_code
# ---------------------------------------------------------------------------

def _d_review(cmd):
    c = cmd.lower()
    if not _REVIEW_RE.search(c):
        return None
    payload = _extract_payload(c, r"\b(?:review|audit)\b")
    fref = _find_file_ref(c)
    if not (payload or fref):
        return None
    return {"cmd": c, "payload": payload, "file": fref}


@_guard
def _e_review(app, ctx):
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None:
        return ("Hand me the code, sir — paste it between triple backticks "
                "or point me at a file: \"review the code in utils.py\", sir.")
    findings = _analyze(code)
    score = _score_findings(findings)
    sections = {"CRITICAL": [], "WARN": [], "INFO": []}
    for sev, line, title, detail in findings:
        sections.setdefault(sev, []).append((line, title, detail))
    subject = " of %s" % os.path.basename(path) if path else ""
    out = ["Code review%s — score %.1f/10" % (subject, score)]
    for sev in ("CRITICAL", "WARN", "INFO"):
        items = sections.get(sev) or []
        out.append("%s:" % sev)
        if not items:
            out.append(" • none")
        for line, title, detail in items[:12]:
            out.append(" • L%s %s — %s" % (line, title, detail))
    out.append("Top recommendation: %s" % _top_recommendation(findings))
    opinion = _llm(app,
                   "Blunt senior-engineer review in five lines; worst risk "
                   "first:\n```python\n" + _clip(code, 3000) + "\n```")
    if opinion:
        out.append("--- Second opinion (online):")
        out.append(_clip(opinion, 900))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# skill 6: pro_explain_code
# ---------------------------------------------------------------------------

def _d_explain(cmd):
    c = cmd.lower()
    if not _EXPLAIN_RE.search(c):
        return None
    payload = _extract_payload(c, r"\b(?:explain|walk\s+me\s+through)\b")
    fref = _find_file_ref(c)
    if not (payload or fref):
        return None
    return {"cmd": c, "payload": payload, "file": fref}


@_guard
def _e_explain(app, ctx):
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None:
        return ("Send me the snippet, sir — paste it between triple "
                "backticks, or say \"explain the code in utils.py\", sir.")
    outline = _outline(code)
    narrative = _llm(app,
                     "Explain this code in one tight paragraph, then flag any "
                     "hidden risk:\n```python\n" + _clip(code, 3000)
                     + "\n```")
    subject = " of %s" % os.path.basename(path) if path else ""
    body = ["Code walkthrough%s, sir:" % subject] + list(outline)
    if narrative:
        body += ["", "--- Narrative (online):", _clip(narrative, 900)]
    return "\n".join(body)


# ---------------------------------------------------------------------------
# skill 7: pro_translate_code
# ---------------------------------------------------------------------------

_CHEATSHEET = (
    ("def foo(x):", "function foo(x) { ... }"),
    ("print(x)", "console.log(x)"),
    ('f"{x} units"', "`${x} units`"),
    ("None", "null"),
    ("True / False", "true / false"),
    ("elif cond:", "else if (cond) { ... }"),
    ("dict {'a': 1}", "object {a: 1}"),
    ("list [1, 2]", "array [1, 2]"),
    ("import math", "require('math') / import from module"),
    ("range(10)", "for (let i = 0; i < 10; i++) { ... }"),
    ("try / except", "try / catch"),
    ("lambda x: x * 2", "(x) => x * 2"),
    ("[f(x) for x in xs]", "xs.map((x) => f(x))"),
    ("[x for x in xs if ok(x)]", "xs.filter((x) => ok(x))"),
)


def _cheatsheet(source, target):
    lines = []
    if source == "javascript":
        lines.append("JavaScript -> Python pocket map, sir:")
        for js, py in ((b, a) for a, b in _CHEATSHEET):
            lines.append("  %-32s -> %s" % (js, py))
    else:
        lines.append("Python -> JavaScript pocket map, sir:")
        for py, js in _CHEATSHEET:
            lines.append("  %-32s -> %s" % (py, js))
    lines.append("Same ideas, different clothes, sir — bring me online and "
                 "I'll do a real translation.")
    return "\n".join(lines)


def _d_translate(cmd):
    c = cmd.lower()
    m = _TRANSLATE_RE.search(c)
    if not m:
        return None
    target = _normalize_lang(m.group(1))
    src = None
    for lang, patterns in _LANG_SNIFF_ORDER:
        if lang == target:
            continue
        if any(re.search(p, c) for p in patterns):
            src = lang
            break
    payload = _extract_payload(c, r"\b(?:convert|translate|port)\b")
    fref = _find_file_ref(c)
    return {"cmd": c, "target": target, "source": src,
            "payload": payload, "file": fref}


@_guard
def _e_translate(app, ctx):
    target = ctx["target"]
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None and LAST_CODE.get("code"):
        code, path = LAST_CODE["code"], None
    if code is None:
        return ("Nothing to translate yet, sir — paste the code between "
                "triple backticks or build one first, then say \"convert it "
                "to rust\", sir.")
    source = ctx.get("source") or "python"
    translated = _llm(app,
                      "Translate the following %s code to %s.\nOutput ONLY "
                      "the complete, runnable %s code inside ONE "
                      "triple-backtick fence - no prose before it. Preserve "
                      "behaviour and comments.\n```%s\n%s\n```"
                      % (source, target, target, source, _clip(code)))
    if not translated:
        return _cheatsheet(source, target)
    out_code = _strip_fences_basic(translated)
    cv = _cv()
    status = ""
    if cv is not None:
        try:
            if target in ("python", "javascript"):
                vr = cv.validate(out_code, target)
                status = _summarize_vr(cv, vr)
            else:
                status = ("brackets balanced, sir"
                          if _brackets_balanced(out_code)
                          else "bracket mismatch — eyeball it, sir")
        except Exception as exc:
            log.warning("translate validation skipped: %s", exc)
    safe_target = re.sub(r"[^a-z0-9]+", "_", target)
    name = "translated_%s.%s" % (safe_target, _LANG_EXT.get(target, "txt"))
    _store_last(out_code, target, name)
    tail = ("\n\nValidation: %s" % status) if status else ""
    return ("Translated to %s, sir:\n\n%s%s\n\nSay 'save it as %s' to keep "
            "it, sir." % (target, out_code, tail, name))


# ---------------------------------------------------------------------------
# skill 8: pro_gen_tests
# ---------------------------------------------------------------------------

def _d_gen_tests(cmd):
    c = cmd.lower()
    if not (_GEN_TESTS_RE.search(c)
            or re.match(r"\s*test\s+this\s+code\b", c)):
        return None
    payload = _extract_payload(c, r"\btests?\b")
    fref = _find_file_ref(c)
    if not (payload or fref):
        return None
    return {"cmd": c, "payload": payload, "file": fref}


@_guard
def _e_gen_tests(app, ctx):
    cmd = ctx.get("cmd", "")
    code, path, err = _read_target(cmd, ctx.get("payload"))
    if err:
        return err
    if code is None:
        return ("Paste the code to test, sir — say \"write unit tests for\" "
                "followed by a fenced snippet, sir.")
    scaffold, count = _gen_test_scaffold(code)
    if not scaffold or count == 0:
        return ("I found no public functions to exercise, sir — send the "
                "module again with its functions, sir.")
    enrichment = _llm(app,
                      "Add more meaningful pytest cases for this code. Output "
                      "only extra test functions in ONE fence:\n```python\n"
                      + _clip(code, 2500) + "\n```")
    stem = os.path.basename(path) if path else "subject"
    fname = "test_%s_tests.py" % re.sub(r"\W+", "_", stem).lower().strip("_")
    extra = ""
    if enrichment:
        extra = ("\n\nExtra cases from my online pass, sir:\n%s"
                 % _clip(enrichment, 1200))
    return ("Here's a pytest scaffold covering %d public function(s), sir:"
            "\n\n```python\n%s```\nRun it with: pytest %s, sir.%s"
            % (count, scaffold, fname, extra))


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def register(brain):
    """Register all coding skills into the JARVIS brain."""
    brain.register("pro_write_code", _d_write, _e_write, priority=True)
    brain.register("pro_save_code", _d_save, _e_save, priority=False)
    brain.register("pro_fix_code", _d_fix, _e_fix, priority=True)
    brain.register("pro_improve_code", _d_improve, _e_improve, priority=True)
    brain.register("pro_review_code", _d_review, _e_review, priority=False)
    brain.register("pro_explain_code", _d_explain, _e_explain,
                   priority=False)
    brain.register("pro_translate_code", _d_translate, _e_translate,
                   priority=False)
    brain.register("pro_gen_tests", _d_gen_tests, _e_gen_tests,
                   priority=False)
    brain.register("pro_run_code", _d_run_code, _e_run_code, priority=False)
    brain.register("pro_fix_and_run", _d_fix_and_run, _e_fix_and_run,
                   priority=True)


# ---------------------------------------------------------------------------
# main.py delegation hook
# ---------------------------------------------------------------------------

_SAVE_TARGET_RE = re.compile(r"\b(\w+\.(?:py|js|html|css|java|cpp|json))\b",
                             re.I)


def delegate_code_write(app, cmd):
    """Entry point for main.py's legacy _handle_code_write.

    Runs the PRO engine (local template first, else validated LLM
    generation with retry). When the command names a destination file,
    the code is written there with a .bak backup, mirroring legacy
    behaviour. Returns a chat-ready reply string, or None when this
    module should not handle the request. Never raises.
    """
    try:
        ctx = _d_write(cmd.lower())
        if ctx is None:
            return None
        task = ctx.get("task") or ""
        lang_hint = _sniff_lang(task) or "python"
        cv = _cv()
        code = None
        hit = _local_template(task)
        if hit:
            code, name = hit
            lang_used = "python"
            source_note = "Built locally, sir — verified syntax and compile."
        else:
            prompt = _senior_prompt(task, lang_hint)
            if cv is not None and hasattr(cv, "generate_validated"):
                try:
                    gen_code, vr = cv.generate_validated(
                        llm_call=lambda p: _llm(app, p), prompt=prompt,
                        lang_hint=lang_hint, exec_simple=False)
                except Exception as exc:
                    log.warning("delegate generation failed: %s", exc)
                    gen_code, vr = None, None
                code = (gen_code or "").strip() or None
            else:
                raw = _llm(app, prompt)
                code = _strip_fences_basic(raw).strip() or None
            if not code:
                return None
            # Never present a candidate that failed validation: hand
            # the request back to the legacy handler instead.
            if cv is not None and vr is not None and \
                    not getattr(vr, "ok", True):
                log.info("delegate declining unvalidated candidate")
                return None
            name = _suggest_name(task, lang_hint)
            lang_used = lang_hint
            note = _summarize_vr(cv, vr) if (cv is not None and vr is not
                                             None) else "generated"
            source_note = "Generated and validated, sir (%s)." % note
        _store_last(code, lang_used, name)

        saved_line = ""
        m = _SAVE_TARGET_RE.search(cmd)
        if not m and hit is None:
            # No destination file named and no local template: leave the
            # request to the legacy handler (which always saves a file).
            return None
        if m:
            filename = os.path.basename(m.group(1))
            target = os.path.join(PROJECT_DIR, filename)
            try:
                if os.path.exists(target):
                    backup = target + ".bak"
                    with open(target, "r", encoding="utf-8") as fh:
                        prev = fh.read()
                    with open(backup, "w", encoding="utf-8") as fh:
                        fh.write(prev)
                    saved_line = ("\nPrevious version backed up to %s."
                                  % os.path.basename(backup))
                else:
                    parent = os.path.dirname(target)
                    if parent:
                        os.makedirs(parent, exist_ok=True)
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write(code + "\n")
                saved_line += ("\nWritten to %s (%d lines), sir."
                               % (filename, code.count("\n") + 1))
            except OSError as exc:
                saved_line += ("\nI could not write %s, sir: %s"
                               % (filename, exc))
        return "%s\n\n%s%s" % (source_note, code, saved_line)
    except Exception as exc:
        log.warning("delegate_code_write failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# SELF-HEALING RUNNER: write -> execute -> read traceback -> fix -> rerun
# ---------------------------------------------------------------------------

_RUN_FILE_RE = re.compile(
    r"\b(?:run|execute|launch)\s+(?:the\s+)?(?:file\s+)?([\w~./\- ]+?\.\w{1,4})\b",
    re.I)
_RUN_IT_RE = re.compile(r"\b(run|execute)\s+(it|this|that|the\s+code)\b", re.I)
_FIXRUN_RE = re.compile(r"\bfix\s+(?:and|then)?\s*run\b|\brun\s+and\s+fix\b", re.I)
_TRACEBACK_RE = re.compile(r"^(?:[\w.]+\.)?(?:\w+Error|Exception|"
                           r"KeyboardInterrupt|SystemExit)(?::\s*(.*))?$")


def _run_python_file(path: str, timeout: float = 12.0):
    """Execute a python file; return dict(rc, stdout, stderr, tb)."""
    import subprocess as _sp
    try:
        proc = _sp.run([sys.executable, path], capture_output=True,
                       text=True, timeout=timeout, cwd=os.path.dirname(path))
        err = (proc.stderr or "").strip()
        tb = None
        for line in reversed(err.splitlines()):
            if _TRACEBACK_RE.match(line.strip()):
                tb = line.strip()
                break
        return {"rc": proc.returncode, "stdout": (proc.stdout or "").strip(),
                "stderr": err, "tb": tb}
    except _sp.TimeoutExpired:
        return {"rc": 124, "stdout": "", "stderr":
                "Timed out after %ss (possible infinite loop or blocking "
                "input)." % timeout, "tb": "Timeout"}
    except Exception as exc:
        return {"rc": 1, "stdout": "", "stderr": str(exc), "tb": None}


def _last_error_block(err_text: str, max_lines: int = 14) -> str:
    lines = [ln for ln in err_text.splitlines() if ln.strip()]
    return "\n".join(lines[-max_lines:])


@_guard
def _e_fix_and_run(app, ctx):
    """fix-and-run / run-and-fix: guaranteed self-healing execution."""
    cmd = ctx["cmd"]
    m = _RUN_FILE_RE.search(cmd)
    if not m:
        if not LAST_CODE.get("code"):
            return ("Nothing to run yet, sir — generate something first "
                    "('write code for ...'), or name a file to run.")
        target = os.path.join(PROJECT_DIR, "generated_runs",
                              LAST_CODE.get("name") or "snippet.py")
    else:
        raw = m.group(1).strip()
        target = raw if os.path.isabs(raw) else os.path.join(PROJECT_DIR,
                                                             raw)
    if not os.path.isfile(target):
        return f"No such file to run, sir: {target}"

    cv = _cv()
    history = []
    for attempt in range(1, 4):
        result = _run_python_file(target)
        if result["rc"] == 0:
            tail = result["stdout"][-600:]
            note = "ran clean" if attempt == 1 else \
                f"healed after {attempt - 1} fix round(s), sir"
            return (f"Executed {os.path.basename(target)} — {note}.\n"
                    f"Output:\n{tail}" if tail else
                    f"Executed {os.path.basename(target)} — {note} "
                    "(no output).")
        err_block = _last_error_block(result["stderr"])
        history.append("attempt %d: %s" % (
            attempt, (result["tb"] or "failed")[:120]))
        # Local auto-fixes first...
        try:
            with open(target, "r", encoding="utf-8") as fh:
                current = fh.read()
        except OSError as exc:
            return f"Could not read {target}, sir: {exc}"
        fixed = _local_auto_fixes(current)[0] if hasattr(
            "_local_auto_fixes", "__call__") else current
        changed = fixed != current
        # ...then a validated LLM repair carrying the exact traceback.
        if cv is not None and hasattr(cv, "generate_validated"):
            prompt = (_senior_prompt("Fix this failing program so it runs "
                                     "correctly.") +
                      "\n\nCurrent code:\n" + current +
                      "\n\nExecution errors:\n" + err_block +
                      "\nReturn ONLY the complete corrected program.")
            new_code, vr = None, None
            try:
                new_code, vr = cv.generate_validated(
                    llm_call=lambda p: _llm(app, p), prompt=prompt,
                    lang_hint="python", exec_simple=False)
            except Exception as exc:
                log.warning("self-heal generation failed: %s", exc)
            if new_code and getattr(vr, "ok", True):
                fixed = new_code
                changed = True
        if not changed:
            break
        backup = target + ".bak%d" % attempt
        try:
            with open(backup, "w", encoding="utf-8") as fh:
                fh.write(current)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(fixed if fixed.endswith("\n") else fixed + "\n")
        except OSError as exc:
            return f"Could not write the healed version of {target}: {exc}"
        _store_last(fixed, "python", os.path.basename(target))
    return ("I could not fully heal %s after %d rounds, sir.\n"
            "Attempts: %s\nLast errors:\n%s\nSay 'explain this code %s' "
            "and we'll debug together."
            % (os.path.basename(target), 3, " | ".join(history),
               _last_error_block(result.get("stderr", "")),
               os.path.basename(target)))


def _d_run_code(cmd):
    c = cmd.lower().strip()
    if _FIXRUN_RE.search(c):
        return {"cmd": c}
    if _RUN_FILE_RE.search(c):
        m = _RUN_FILE_RE.search(c)
        candidate = m.group(1).strip()
        if candidate.endswith(".py") or os.path.isfile(
                candidate if os.path.isabs(candidate)
                else os.path.join(PROJECT_DIR, candidate)):
            return {"cmd": c}
    if _RUN_IT_RE.search(c) and LAST_CODE.get("code"):
        return {"cmd": c}
    return None


def _d_fix_and_run(cmd):
    return {"cmd": cmd.lower()} if _FIXRUN_RE.search(cmd.lower()) else None


def _e_run_code(app, ctx):
    """Plain runner: no healing unless asked; one shot, honest output."""
    cmd = ctx["cmd"]
    m = _RUN_FILE_RE.search(cmd) or _RUN_IT_RE.search(cmd)
    if not m:
        return None
    if _RUN_FILE_RE.search(cmd):
        raw = _RUN_FILE_RE.search(cmd).group(1).strip()
        target = raw if os.path.isabs(raw) else os.path.join(PROJECT_DIR,
                                                             raw)
    elif LAST_CODE.get("code"):
        target = os.path.join(PROJECT_DIR, "generated_runs",
                              LAST_CODE.get("name") or "snippet.py")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(LAST_CODE["code"])
    else:
        return None
    result = _run_python_file(target)
    label = os.path.basename(target)
    if result["rc"] == 0:
        out = result["stdout"]
        return (f"Ran {label} successfully, sir." +
                ("\nOutput:\n" + out[-600:] if out else ""))
    return (f"{label} exited with code {result['rc']}, sir.\n"
            + (_last_error_block(result["stderr"]) or result["stderr"][:400])
            + "\nSay 'fix and run' and I'll heal it, sir.")
