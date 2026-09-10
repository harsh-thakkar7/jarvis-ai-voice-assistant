"""JARVIS DEVELOPER-TOOLS SKILL PACK: local, offline coding helpers.

Ten fail-soft skills for day-to-day development chores. Everything is
local and offline: AST parsing, regex scanning and plain file I/O only -
no LLM calls inside any execute(). Skills prefixed ``dv_``:

    - dv_git_msg       : "git commit message [in <dir>]" / "commit message
                         for <dir>" / "write a commit message in <dir>" ->
                         reads ``git status --porcelain``, ``git diff`` and
                         ``git diff --cached`` (READ-ONLY: never stages or
                         commits) and synthesizes a conventional-commits
                         one-liner plus a short bullet body. Honest error
                         when the folder is not a repo or has no changes.
    - dv_git_summary   : "git summary [in <dir>]" / "git repo summary" ->
                         branch, last commit, ``git log --oneline -5`` and
                         working-tree state in one speakable block. Fail-
                         soft one-liner when git itself is missing.
    - dv_code_explain  : "explain this code: <snippet>" (colon-anchored) or
                         "explain code in <file>" -> Python via ``ast``
                         (functions/classes/args/line counts); other
                         languages get an imports/includes listing plus a
                         structural sketch. File reads capped at 400 lines.
    - dv_test_scaffold : "generate tests for <py file>" / "test scaffold
                         for <file>" / "pytest skeleton for <file>" -> AST-
                         parsed pytest skeleton with one placeholder test
                         per public function. Printed unless the command
                         says "save" (then tests/test_<name>_scaffold.py
                         next to the source, .bak first).
    - dv_docstring     : "add docstrings to <py file>" -> AST-located defs
                         without docstrings, stubs printed; writes only on
                         "save[ to <path>]", always after a .bak backup.
    - dv_todo_scan     : "scan for todos in <dir>" / "find todos in <dir>"
                         -> TODO/FIXME/HACK/XXX across *.py/*.js/*.ts/
                         *.html/*.css/*.md, grouped per file with line
                         numbers, capped output. Skips .venv, node_modules,
                         __pycache__, hidden dirs.
    - dv_deps_check    : "check dependencies in <dir>" -> AST-parses all
                         *.py imports versus requirements.txt; reports
                         missing and unused candidates with an import-name
                         alias map to keep the honest mistakes down.
    - dv_json_tool     : "validate json <file>" / "check json <file>" ->
                         json.loads with line/column errors; "format json
                         <file>" (or "pretty print json <file>") pretty-
                         prints indent=2, writing only when the command
                         says save/write/overwrite, .bak backup first.
    - dv_regex         : "regex <pattern> against <text>" -> finditer with
                         match spans and groups (capped); "explain regex
                         <pattern>" / "break down regex <pattern>" -> pure
                         token-by-token heuristic breakdown, no LLM.
    - dv_loc           : "count lines in <dir/file>" / "count lines of
                         <path>" / "lines of code in <path>" -> per-
                         extension line counts plus a total, skipping junk
                         directories.

Collisions (checked against brain.py, brain_extra.py, code_brain_pro.py,
power_skills.py, data_file_tools.py, file_power.py and main.py before
designing - skill packs register LAST, so earlier packs win any phrase
they also claim):

    - power_skills.git_commit owns "git commit <actual message>" (it
      commits!). It does NOT claim "git commit message [in <dir>]": its
      dir-hint strip plus its "message" flag strip leave nothing to
      commit. dv_git_msg only claims the noun phrase "commit message"
      followed by nothing or a path-ish "in/for <dir>" tail, so real
      commits still belong to power_skills.
    - brain_extra.git_help (a cheatsheet, "git ... how/help/commit/...")
      still wins "git commit message ..." in the full brain because it
      registers earlier; the git-less phrasings ("commit message for
      <dir>") reach dv_git_msg reliably. Same story for the other lanes
      marked (shadowed): they behave correctly here, but an earlier pack
      may answer first in the full brain.
    - code_brain_pro.pro_explain / pro_gen_tests (LLM hybrids) own the
      broad "explain ... code" / "generate tests for" space when loaded;
      dv_code_explain and dv_test_scaffold are the offline AST lanes, and
      the scaffold/skeleton phrasings are exclusive to this pack.
    - data_file_tools.dt_json_validate / dt_json_format already cover
      "validate (the) json (file) <path>" and "format (the) json (file)
      <path>" (always writing a .bak); dv_json_tool keeps the spec'd
      triggers plus print-only and save-worded lanes, and avoids dt's
      "prettify" phrase entirely.
    - brain_extra.line_count claims bare "lines in" anywhere (it counts
      the tail as inline text, which is nonsense for paths); the
      "count lines of <path>" and "lines of code in <path>" phrasings
      are exclusive lanes here.
    - brain_extra's personal to-do list (show/list/add todos) and
      main.py's task-list handler are untouched: dv_todo_scan only fires
      on scan/find/search-for phrasings with a directory.
    - cp_run already covers generic shell execution; this pack never runs
      arbitrary shell. All git access goes through argument-list
      subprocess calls, read-only for dv_git_msg.

Writes are doubly gated: the command must say save/format/write, the
target must sit under $HOME, and a .bak backup (collision-safe suffix)
is made first. Reads are capped; failures answer with one honest
sentence. No persistent state, no network, no UI, never imports main.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("skills_dev")

# ==========================================================================
# Tunables
# ==========================================================================

HOME = os.path.expanduser("~")

READ_LINE_CAP = 400            # dv_code_explain / dv_docstring file cap
READ_BYTE_CAP = 60000          # stop reading a single file past this
SNIPPET_MAX_CHARS = 5000       # dv_code_explain pasted-snippet cap
SCAN_MAX_FILE_BYTES = 1_000_000    # skip huge files in scans
SCAN_MAX_FILES = 600           # dv_todo_scan file cap
SCAN_FINDINGS_CAP = 200        # stop scanning after this many markers
SCAN_FILES_SHOWN = 15          # files listed in the reply
SCAN_PER_FILE_SHOWN = 4        # findings listed per file
LOC_MAX_FILES = 800            # dv_loc file cap
LOC_EXT_ROWS_SHOWN = 12        # per-extension rows in the reply
DEPS_MAX_FILES = 600           # dv_deps_check file cap
DEPS_MAX_LISTED = 15           # names listed per bucket
JSON_MAX_BYTES = 5_000_000     # dv_json_tool read cap
JSON_SHOW_CAP = 2000           # pretty-print preview cap
GIT_TIMEOUT_S = 10             # per git subprocess call
GIT_DIFF_LINE_CAP = 500        # diff lines mined for identifiers
MSG_BULLET_CAP = 6             # bullets in the proposed commit body
DOCSTRING_PROPOSAL_CAP = 10    # stubs shown in one reply
TEST_SHOW_CAP = 2400           # printed pytest scaffold cap
REGEX_MATCH_CAP = 12           # matches shown by dv_regex
REGEX_TOKEN_CAP = 30           # tokens explained by dv_regex

JUNK_DIRS = frozenset({
    ".venv", "venv", "env", "node_modules", "__pycache__", ".git", ".hg",
    ".svn", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", "dist", "build", ".eggs", "htmlcov",
})
SCAN_EXTS = (".py", ".js", ".ts", ".html", ".css", ".md")
LOC_EXTS = (".py", ".js", ".ts", ".html", ".css", ".md", ".json", ".yml",
            ".yaml", ".sh", ".sql", ".c", ".h", ".cpp", ".java", ".go",
            ".rb", ".rs", ".php")

# import name -> likely distribution name, to cut false "missing" reports.
_IMPORT_ALIASES = {
    "pil": "pillow", "pil.Image": "pillow", "cv2": "opencv-python",
    "bs4": "beautifulsoup4", "yaml": "pyyaml", "sklearn": "scikit-learn",
    "dotenv": "python-dotenv", "serial": "pyserial", "fitz": "pymupdf",
    "crypto": "pycryptodome", "dateutil": "python-dateutil",
    "jwt": "pyjwt", "git": "gitpython", "attr": "attrs",
    "docx": "python-docx", "pptx": "python-pptx",
}

# Politeness prefix shared by the anchored detectors (same discipline as
# skills_computer): hey/ok/okay/please/jarvis only, so ordinary sentences
# never pre-match.
_POLITE = r"(?:hey\s+|ok\s+|okay\s+|please\s+|jarvis\s*[,.:]\s*)*"


# ==========================================================================
# Shared plumbing
# ==========================================================================

def _disp(path: str) -> str:
    """Shorten a path for speech: ~ for home, when possible."""
    try:
        full = os.path.abspath(path)
    except Exception:
        return str(path)
    if full == HOME or full.startswith(HOME.rstrip(os.sep) + os.sep):
        return "~" + full[len(HOME):].replace(os.sep, "/")
    return full.replace(os.sep, "/")


def _resolve_path(raw: str) -> str | None:
    """Expand and clean a user-typed path; None when empty."""
    text = (raw or "").strip().strip("`").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.I).strip()
    text = re.sub(r"^(?:at|in|of|from)\s+", "", text, flags=re.I).strip()
    text = text.strip("\"'`").strip()
    if not text or len(text) > 300:
        return None
    return os.path.normpath(os.path.expanduser(text))


def _pathish(tail: str) -> bool:
    """Does a detector tail look like a path (and not ordinary prose)?"""
    text = (tail or "").strip().strip("\"'`").strip()
    if not text or len(text) > 300:
        return False
    if "/" in text or text.startswith("~"):
        return True
    if os.path.exists(os.path.expanduser(text)):
        return True
    return bool(re.fullmatch(r"[\w.-]+\.[A-Za-z0-9]{1,12}", text))


def _dirish(tail: str) -> bool:
    """Directory hints accepted by the git skills: paths or known words."""
    text = (tail or "").strip().strip("\"'`").rstrip(".").strip()
    if not text or len(text) > 300:
        return False
    if _pathish(text):
        return True
    return text.lower() in (
        "repo", "the repo", "this repo", "project", "the project",
        "this project", "here", "cwd", "this dir", "the dir",
        "this directory", "the directory", "this folder", "the folder",
        ".", "..",
    )


def _under_home(path: str) -> bool:
    """True when path sits inside the user's home directory."""
    try:
        return os.path.realpath(path).startswith(
            os.path.realpath(HOME) + os.sep)
    except Exception:
        return False


def _backup(path: str) -> str | None:
    """Copy path to a collision-safe .bak sibling; None on failure."""
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
    except Exception as exc:
        log.warning("backup failed for %s: %s", path, exc)
        return None


def _read_head(path: str, line_cap: int = READ_LINE_CAP,
               byte_cap: int = READ_BYTE_CAP) -> tuple[str | None, str]:
    """Read up to line_cap lines / byte_cap bytes. (text, error-message)."""
    try:
        if os.path.getsize(path) > byte_cap * 4:
            return None, ("%s is %d megabytes, sir - too large for me to "
                          "read comfortably." % (_disp(path),
                          os.path.getsize(path) // (1024 * 1024) + 1))
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = []
            for i, line in enumerate(fh):
                if i >= line_cap:
                    break
                lines.append(line)
        text = "".join(lines)
        note = ""
        if len(text) >= byte_cap:
            text = text[:byte_cap]
            note = " (read truncated at %d bytes)" % byte_cap
        return text, note
    except FileNotFoundError:
        return None, "I cannot find %s, sir." % _disp(path)
    except IsADirectoryError:
        return None, "%s is a directory, not a file, sir." % _disp(path)
    except Exception as exc:
        return None, ("I could not read %s, sir (%s)."
                      % (_disp(path), str(exc)[:100]))


def _iter_files(root: str, exts: tuple[str, ...],
                max_files: int) -> list[str]:
    """Walk root for the given extensions, skipping junk and hidden dirs."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d not in JUNK_DIRS)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in exts:
                found.append(os.path.join(dirpath, name))
                if len(found) >= max_files:
                    return found
    return found


def _clip(text: str, cap: int) -> str:
    text = text.rstrip()
    if len(text) <= cap:
        return text
    return text[:cap] + " ..."


def _plural(n: int, word: str) -> str:
    if n == 1:
        return "1 %s" % word
    if word.endswith(("s", "x", "ch", "sh")):
        return "%d %ses" % (n, word)
    return "%d %ss" % (n, word)


# ---- git plumbing (argument-list subprocess, read-only in this pack) ----

def _git_missing() -> str | None:
    if shutil.which("git") is None:
        return "git is not installed on this machine, sir."
    return None


def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    """Run one read-only git command. Returns (returncode, output)."""
    try:
        r = subprocess.run(["git", "-C", cwd] + args, capture_output=True,
                           text=True, timeout=GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    except Exception as exc:
        return -1, str(exc)[:120]
    out = (r.stdout or "").strip("\n")   # keep leading spaces: porcelain's
    if r.returncode != 0:                # first column is meaningful
        out = (r.stderr or out or "unknown git error").strip()
    return r.returncode, out


def _repo_guard(directory: str) -> str | None:
    """One honest sentence when directory is not a git work tree."""
    rc, out = _run_git(["rev-parse", "--is-inside-work-tree"], directory)
    if rc != 0 or out.strip().lower() != "true":
        return ("%s is not a git repository, sir." % _disp(directory))
    return None


def _resolve_dir(raw: str | None) -> tuple[str | None, str]:
    """Resolve an optional 'in <dir>' hint to a directory."""
    if raw is None or not raw.strip():
        return os.getcwd(), ""
    path = _resolve_path(raw)
    if path is None:
        return None, "I could not make sense of that directory, sir."
    if not os.path.isdir(path):
        return None, "I cannot find a directory at %s, sir." % _disp(path)
    return path, ""


# ==========================================================================
# dv_git_msg - synthesize a conventional commit message (read-only)
# ==========================================================================

_COMMIT_MSG_RE = re.compile(
    r"^" + _POLITE
    + r"(?:(?:write|draft|generate|create|make|give\s+me)\s+(?:me\s+)?"
      r"(?:a\s+|the\s+)?)?"
    r"(?:git\s+)?commit\s+message"
    r"(?:\s+(?:in|for|of)\s+(?P<dir>\S.*?))?\s*[.!?]?$", re.I)

_DIR_HINT_WORDS = re.compile(r"^(?:this|the|that)\s+(?:repo|project|"
                             r"directory|dir|folder)$", re.I)
_IDENT_RE = re.compile(
    r"(?:def|class|function|func|const|let|var)\s+([A-Za-z_]\w*)")


def _d_git_msg(cmd: str):
    m = _COMMIT_MSG_RE.match((cmd or "").strip())
    if not m:
        return None
    tail = m.group("dir")
    if tail is not None:
        text = tail.strip().strip("\"'`").rstrip(".").strip()
        # Preserve power_skills' ground: "commit message for the release"
        # is a commit instruction, not a message request.
        if not (_pathish(text) or _DIR_HINT_WORDS.match(text)
                or text.lower() in ("repo", "project", "here", "cwd")):
            return None
    return {"dir": tail}


def _porcelain_entries(status_out: str):
    """Split `git status --porcelain` into (XY, path) pairs.

    XY keeps both raw status columns (X = index/staged, Y = worktree);
    "?" placeholders stay in place because the leading space is a real
    status, never decoration.
    """
    entries: list[tuple[str, str]] = []
    for line in status_out.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:].strip()
        if " -> " in path:                       # renames
            path = path.split(" -> ", 1)[1].strip() or path
        entries.append((xy, path))
    return entries


def _mine_identifiers(diffs: str) -> list[str]:
    """Pull candidate function/class names out of added diff lines."""
    ids: list[str] = []
    for line in diffs.splitlines()[:GIT_DIFF_LINE_CAP * 2]:
        if line.startswith("+") and not line.startswith("+++"):
            ids.extend(_IDENT_RE.findall(line))
    seen: set[str] = set()
    unique = []
    for name in ids:
        low = name.lower()
        if low not in seen and not low.startswith("_"):
            seen.add(low)
            unique.append(name)
    return unique


def _scope_of(paths: list[str]) -> str:
    """Most common top-level directory of the changed files, if any."""
    tops: dict[str, int] = {}
    for path in paths:
        head = os.path.dirname(path).replace("\\", "/").split("/", 1)[0]
        if head and head != "." and not head.startswith("."):
            tops[head] = tops.get(head, 0) + 1
    if not tops:
        return ""
    return max(tops.items(), key=lambda kv: kv[1])[0]


def _e_git_msg(app, ctx) -> str:
    missing = _git_missing()
    if missing:
        return missing
    directory, err = _resolve_dir(ctx.get("dir"))
    if directory is None:
        return err
    guard = _repo_guard(directory)
    if guard:
        return guard
    rc, status_out = _run_git(["status", "--porcelain"], directory)
    if rc != 0:
        return "git status failed, sir (%s)." % status_out[:100]
    entries = _porcelain_entries(status_out)
    if not entries:
        return ("The working tree in %s is clean, sir - nothing to "
                "commit, so no message is needed." % _disp(directory))

    added, deleted, modified, renamed = [], [], [], []
    staged = unstaged = untracked = 0
    for xy, path in entries:
        x, y = (xy + "  ")[:2]
        if xy == "??":
            untracked += 1
            added.append(path)
            continue
        if x != " ":
            staged += 1
        if y != " ":
            unstaged += 1
        if "A" in xy:
            added.append(path)
        elif "D" in xy:
            deleted.append(path)
        elif "R" in xy or "C" in xy:
            renamed.append(path)
        else:
            modified.append(path)

    # Mine added lines from both diffs for candidate identifiers.
    mined: list[str] = []
    for args in (["diff"], ["diff", "--cached"]):
        rc, out = _run_git(args, directory)
        if rc == 0 and out:
            mined.extend(_mine_identifiers(out))
    mined = list(dict.fromkeys(mined))

    if added and not deleted:
        kind, verb = "feat", "add"
    elif deleted and not added:
        kind, verb = "chore", "remove"
    elif added and deleted:
        kind, verb = "refactor", "rework"
    else:
        kind, verb = "fix", "update"

    scope = _scope_of([p for _, p in entries])
    detail = (mined[0] if mined else
              os.path.splitext(os.path.basename(
                  (added or modified or deleted or renamed or [""])[0]))[0]
              or "%d files" % len(entries))
    subject = "%s: %s %s" % (kind, verb, detail)
    if scope and scope not in subject:
        subject = "%s(%s): %s %s" % (kind, scope, verb, detail)

    bullets: list[str] = []
    for path in added[:3]:
        bullets.append("- add %s" % path)
    for path in modified[:2]:
        bullets.append("- update %s" % path)
    for path in deleted[:2]:
        bullets.append("- remove %s" % path)
    for path in renamed[:1]:
        bullets.append("- rename into %s" % path)
    if mined[1:4]:
        bullets.append("- touch %s" % ", ".join(mined[1:4]))
    bullets = bullets[:MSG_BULLET_CAP]

    counts = "staged %s, unstaged %s, untracked %s" % (
        _plural(staged, "file"), _plural(unstaged, "file"),
        _plural(untracked, "file"))
    body = "\n".join(bullets)
    return ("Here is my proposal, sir:\n\n%s\n\n%s\n\n(%s across %s)"
            % (subject, body, counts, _disp(directory)))


# ==========================================================================
# dv_git_summary - branch, last commit, recent log, working-tree state
# ==========================================================================

_GIT_SUMMARY_RE = re.compile(
    r"^" + _POLITE + r"git\s+(?:repo(?:sitory)?\s+)?summary"
    r"(?:\s+(?:in|for|of)\s+(?P<dir>\S.*?))?\s*[.!?]?$", re.I)


def _d_git_summary(cmd: str):
    m = _GIT_SUMMARY_RE.match((cmd or "").strip())
    if not m:
        return None
    tail = m.group("dir")
    if tail is not None and not _dirish(tail):
        return None
    return {"dir": tail}


def _e_git_summary(app, ctx) -> str:
    missing = _git_missing()
    if missing:
        return missing
    directory, err = _resolve_dir(ctx.get("dir"))
    if directory is None:
        return err
    guard = _repo_guard(directory)
    if guard:
        return guard

    rc, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], directory)
    if rc != 0:
        branch = "detached/unknown"
    rc, last = _run_git(
        ["log", "-1", "--format=%h %s (%ar)"], directory)
    last_line = last if rc == 0 and last else "no commits yet"
    rc, log5 = _run_git(["log", "--oneline", "-5"], directory)
    recent = [ln for ln in log5.splitlines() if ln.strip()][:5] \
        if rc == 0 else []
    rc, status_out = _run_git(["status", "--porcelain"], directory)
    dirty = [ln for ln in status_out.splitlines() if ln.strip()] \
        if rc == 0 else []

    parts = ["On branch %s, sir. Last commit: %s." % (branch, last_line)]
    if recent:
        parts.append("Recent commits: " + " | ".join(recent))
    if dirty:
        parts.append("Working tree: %s not yet committed."
                     % _plural(len(dirty), "change"))
    else:
        parts.append("Working tree: clean.")
    return "\n".join(parts)


# ==========================================================================
# dv_code_explain - offline structural walkthrough
# ==========================================================================

_EXPLAIN_SNIPPET_RE = re.compile(
    r"^" + _POLITE + r"explain\s+(?:this\s+|that\s+|the\s+|the\s+following"
    r"\s+)?code\s*[:\uFF1A]\s*(?P<code>.+)$", re.I | re.S)
_EXPLAIN_FILE_RE = re.compile(
    r"^" + _POLITE + r"explain\s+(?:the\s+|this\s+|that\s+)?"
    r"code\s+(?:in|at|from|of)\s+(?P<path>.+?)\s*[.!?]?$", re.I)


def _d_code_explain(cmd: str):
    text = (cmd or "").strip()
    m = _EXPLAIN_SNIPPET_RE.match(text)
    if m:
        code = m.group("code").strip()
        if code and len(code) <= SNIPPET_MAX_CHARS:
            return {"code": code}
        return None
    m = _EXPLAIN_FILE_RE.match(text)
    if m:
        raw = m.group("path").strip().strip("\"'`")
        if not _pathish(raw):
            return None
        return {"path": raw}
    return None


def _py_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    names = [a.arg for a in node.args.args]
    if node.args.vararg:
        names.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        names.append("**" + node.args.kwarg.arg)
    return ", ".join(names)


def _py_structure(code: str) -> list[str] | None:
    """AST outline for Python; None when the snippet does not parse."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    lines_out: list[str] = []
    n_lines = len(code.splitlines())
    doc = ast.get_docstring(tree)
    imports: list[str] = []
    funcs: list[str] = []
    classes: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and \
                node.level == 0:
            imports.append(node.module)
    for node in tree.body:                     # top level only, in order
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) \
                else ""
            has_doc = "documented" if ast.get_docstring(node) else \
                "no docstring"
            funcs.append("- %sdef %s(%s) at line %d (%s)"
                         % (prefix, node.name, _py_args(node),
                            node.lineno, has_doc))
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(getattr(b, "id", "?") for b in node.bases)
            methods = [n.name for n in node.body
                       if isinstance(n, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))
                       and not n.name.startswith("_")][:6]
            classes.append("- class %s(%s) at line %d, methods: %s"
                           % (node.name, bases or "object", node.lineno,
                              ", ".join(methods) or "none public"))
    summary = ("This module runs %d lines and defines %s and %s, sir."
               % (n_lines, _plural(len(funcs), "function"),
                  _plural(len(classes), "class")))
    lines_out.append(summary)
    if doc:
        lines_out.append("- module docstring: %s" % _clip(
            doc.splitlines()[0], 100))
    if imports:
        lines_out.append("- imports: %s"
                         % ", ".join(list(dict.fromkeys(imports))[:8]))
    lines_out.extend(funcs[:10])
    lines_out.extend(classes[:6])
    return lines_out


_GENERIC_PATTERNS = {
    ".js": (r"^\s*(?:import\s.+|export\s+(?:default\s+)?|const\s+\w+\s*=\s*"
            r"require\()", re.I),
    ".ts": (r"^\s*(?:import\s.+|export\s+(?:interface|type|class|function)"
            r"\b)", re.I),
    ".c": (r"^\s*#\s*include\b", 0),
    ".h": (r"^\s*#\s*include\b", 0),
    ".cpp": (r"^\s*#\s*include\b", 0),
    ".html": (r"<\s*([a-zA-Z][a-zA-Z0-9]*)", 0),
    ".css": (r"^\s*[.#\w][^{]*\{", 0),
    ".md": (r"^#{1,6}\s+\S", 0),
}


def _generic_structure(code: str, ext: str) -> list[str]:
    """Fallback outline for non-Python (or unparseable) sources."""
    lines = code.splitlines()
    non_blank = [ln for ln in lines if ln.strip()]
    out = ["This %s source runs %d lines (%d non-blank), sir."
           % (ext.lstrip(".") or "text", len(lines), len(non_blank))]
    spec = _GENERIC_PATTERNS.get(ext)
    if spec:
        pattern, _flags = spec
        hits: list[str] = []
        for ln in lines:
            if len(hits) >= 8:
                break
            m = re.search(pattern, ln)
            if m:
                hits.append((m.group(1) if m.groups() else
                             ln.strip())[:60])
        label = {".html": "tags", ".md": "headings", ".css": "selectors"}.\
            get(ext, "imports/includes")
        if hits:
            out.append("- %s spotted: %s" % (label,
                                             ", ".join(dict.fromkeys(hits))))
    funcs = [ln.strip()[:70] for ln in lines
             if re.search(r"\b(function|def|fn|func)\s+\w+", ln)][:6]
    if funcs:
        out.append("- routine definitions:")
        out.extend("  " + f for f in funcs)
    return out


def _e_code_explain(app, ctx) -> str:
    if "code" in ctx:
        code = ctx["code"][:SNIPPET_MAX_CHARS]
        name = "the pasted snippet"
    else:
        path = _resolve_path(ctx.get("path") or "")
        if path is None:
            return "I could not make sense of that file path, sir."
        code, err = _read_head(path, READ_LINE_CAP, READ_BYTE_CAP)
        if code is None:
            return err
        name = os.path.basename(path)
    outline = _py_structure(code)
    if outline is not None:
        body = outline
    else:
        ext = os.path.splitext(name)[1].lower() if "." in name else ""
        body = _generic_structure(code, ext)
        body.append("(It did not parse as Python, sir, so that is a "
                    "structural sketch rather than an AST walkthrough.)")
    return ("Here is the walkthrough of %s, sir:\n%s"
            % (name, "\n".join(_clip(ln, 160) for ln in body[:20])))


# ==========================================================================
# dv_test_scaffold - AST pytest skeleton (print, or save under $HOME)
# ==========================================================================

_TEST_SCAFFOLD_RE = re.compile(
    r"^" + _POLITE
    + r"(?:(?:generate|write|create|scaffold)\s+(?:unit\s+)?tests?\s+for"
      r"|(?:pytest|test)\s+(?:scaffold|skeleton)\s+for"
      r"|scaffold\s+(?:a\s+)?pytest\s+(?:scaffold|skeleton)\s+for)"
    r"\s+(?P<path>.+?)"
    r"(?:\s+(?:and\s+)?save(?:\s+it)?)?\s*[.!?]?$", re.I)


def _d_test_scaffold(cmd: str):
    m = _TEST_SCAFFOLD_RE.match((cmd or "").strip())
    if not m:
        return None
    raw = m.group("path").strip().strip("\"'`")
    if not raw.lower().endswith(".py") or not _pathish(raw):
        return None                      # non-Python targets are not mine
    return {"path": raw, "save": bool(re.search(r"\bsave\b", cmd, re.I))}


def _scaffold_module(code: str, stem: str) -> tuple[str | None, int]:
    """Build a pytest skeleton; (source, test-count) or (None, 0)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, 0
    names: list[str] = []
    tests: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                not node.name.startswith("_"):
            args = _py_args(node)
            names.append(node.name)
            tests.append(
                "def test_%s():\n"
                "    \"\"\"TODO: exercise %s(%s) with real inputs.\"\"\"\n"
                "    # result = %s(...)  # TODO: call it, then assert\n"
                "    assert True  # placeholder\n"
                % (node.name, node.name, args or "...", node.name))
    if not names:
        return None, 0
    if stem.isidentifier():
        import_block = "from %s import (\n%s\n)" % (
            stem, "\n".join("    %s," % n for n in names))
    else:
        import_block = "# import %r manually, then call its functions" % stem
    header = ('"""Pytest scaffold for %s.py, generated by JARVIS.\n\n'
              "Fill in the placeholders, sir - every assert is a stub.\n"
              '"""\n\n%s\n\n\n' % (stem, import_block))
    return header + "\n\n".join(tests), len(tests)


def _e_test_scaffold(app, ctx) -> str:
    path = _resolve_path(ctx.get("path") or "")
    if path is None:
        return "I could not make sense of that file path, sir."
    code, err = _read_head(path, READ_LINE_CAP, READ_BYTE_CAP)
    if code is None:
        return err
    stem = os.path.splitext(os.path.basename(path))[0]
    scaffold, count = _scaffold_module(code, stem)
    if scaffold is None:
        return ("I found no public functions in %s to test, sir."
                % _disp(path))
    if not ctx.get("save"):
        return ("Here is a pytest scaffold covering %s in %s, sir:\n\n%s"
                "\nSay 'generate tests for %s and save' and I shall write "
                "it into tests/, sir."
                % (_plural(count, "public function"), _disp(path),
                   _clip(scaffold, TEST_SHOW_CAP), _disp(path)))
    target_dir = os.path.join(os.path.dirname(path) or ".", "tests")
    target = os.path.join(target_dir, "test_%s_scaffold.py" % stem)
    if not _under_home(target):
        return ("%s sits outside your home folder, sir, so I will not "
                "write there." % _disp(target))
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as exc:
        return ("I could not create the tests folder, sir (%s)."
                % str(exc)[:100])
    backup = _backup(target)
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(scaffold)
    except Exception as exc:
        return ("I could not write the scaffold, sir (%s)."
                % str(exc)[:100])
    note = " The previous version rests at %s." % _disp(backup) if backup \
        else ""
    return ("Scaffold saved to %s, sir - %s with placeholder asserts."
            % (_disp(target), _plural(count, "test")) + note)


# ==========================================================================
# dv_docstring - locate defs without docstrings, propose stubs
# ==========================================================================

_DOCSTRING_RE = re.compile(
    r"^" + _POLITE
    + r"(?:add|propose|suggest|write|draft)\s+docstrings?\s+(?:to|for)\s+"
      r"(?P<path>.+?)"
      r"(?:\s+and\s+save(?:\s+to\s+(?P<target>\S.*?))?)?\s*[.!?]?$", re.I)


def _d_docstring(cmd: str):
    m = _DOCSTRING_RE.match((cmd or "").strip())
    if not m:
        return None
    raw = m.group("path").strip().strip("\"'`")
    if not raw.lower().endswith(".py") or not _pathish(raw):
        return None
    return {"path": raw, "target": m.group("target"),
            "save": bool(m.group("target"))
            or bool(re.search(r"\bsave\b", cmd, re.I))}


def _doc_stub(node, kind: str) -> str:
    """Build the proposed docstring text (without indentation)."""
    if kind == "class":
        return '"""TODO: describe the %s class."""' % node.name
    params = [a.arg for a in node.args.args if a.arg not in ("self", "cls")]
    lines = ['"""TODO: describe %s.' % node.name, ""]
    for param in params:
        lines.append(":param %s: TODO" % param)
    lines.append(":returns: TODO")
    lines.append('"""')
    return "\n".join(lines)


def _missing_docstrings(code: str):
    """[(node, kind)] for defs/classes lacking a docstring, source order."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and \
                ast.get_docstring(node) is None:
            found.append((node, "class" if isinstance(node, ast.ClassDef)
                          else "def"))
    found.sort(key=lambda pair: pair[0].lineno)
    return found


def _e_docstring(app, ctx) -> str:
    path = _resolve_path(ctx.get("path") or "")
    if path is None:
        return "I could not make sense of that file path, sir."
    code, err = _read_head(path, READ_LINE_CAP, READ_BYTE_CAP)
    if code is None:
        return err
    missing = _missing_docstrings(code)
    if missing is None:
        return ("%s does not parse as Python, sir, so I cannot place its "
                "docstrings." % _disp(path))
    if not missing:
        return ("Every def and class in %s already carries a docstring, "
                "sir." % _disp(path))

    src_lines = code.splitlines()
    proposals: list[str] = []
    for node, kind in missing[:DOCSTRING_PROPOSAL_CAP]:
        line = src_lines[node.lineno - 1].strip()[:70] \
            if node.lineno - 1 < len(src_lines) else "?"
        proposals.append("line %d  %s\n    %s"
                         % (node.lineno, line,
                            _doc_stub(node, kind).replace(
                                "\n", "\n    ")))
    extra = ("" if len(missing) <= DOCSTRING_PROPOSAL_CAP
             else "\n... and %d more." % (len(missing) -
                                          DOCSTRING_PROPOSAL_CAP))

    target_raw = ctx.get("target")
    if not ctx.get("save"):
        return ("I found %s without docstrings in %s, sir. Proposed "
                "stubs:\n%s%s\nSay 'and save' and I shall insert them "
                "(.bak first)."
                % (_plural(len(missing), "def/class"), _disp(path),
                   "\n".join(proposals), extra))

    target = _resolve_path(target_raw) if target_raw else path
    if target is None:
        return "I could not make sense of the save destination, sir."
    if not _under_home(target):
        return ("%s sits outside your home folder, sir, so I will not "
                "write there." % _disp(target))
    # Insert docstrings bottom-up so earlier line numbers stay valid.
    insertions: list[tuple[int, int, str]] = []
    skipped = 0
    for node, kind in missing:
        first = node.body[0]
        if first.lineno == node.lineno or first.col_offset is None:
            skipped += 1                # one-liner or odd layout: skip
            continue
        indent = " " * first.col_offset
        stub = "\n".join(indent + ln if ln else ln
                         for ln in _doc_stub(node, kind).splitlines())
        insertions.append((first.lineno, first.col_offset, stub))
    insertions.sort(key=lambda item: item[0], reverse=True)
    for lineno, _col, stub in insertions:
        src_lines.insert(lineno - 1, stub)
    backup = _backup(target)
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("\n".join(src_lines) + "\n")
    except Exception as exc:
        return ("I could not write the docstrings, sir (%s)."
                % str(exc)[:100])
    note = " Backup at %s." % _disp(backup) if backup else ""
    skipped_note = (" (%d one-liner defs were left alone.)" % skipped) \
        if skipped else ""
    return ("Inserted %s and saved to %s, sir.%s%s"
            % (_plural(len(insertions), "docstring"), _disp(target),
               note, skipped_note))


# ==========================================================================
# dv_todo_scan - TODO/FIXME/HACK/XXX across a source tree
# ==========================================================================

_TODO_SCAN_RE = re.compile(
    r"^" + _POLITE
    + r"(?:scan|search|find|look|grep)\s+(?:for\s+)?"
      r"(?:todos?|to-dos?|fixmes?|hacks?|code\s+markers?)"
    r"(?:\s+(?:in|across|under|through)\s+(?P<dir>.+?))?\s*[.!?]?$", re.I)
_TODO_SCAN_REV_RE = re.compile(
    r"^" + _POLITE + r"scan\s+(?P<dir>\S.*?)\s+for\s+"
    r"(?:todos?|to-dos?|fixmes?|hacks?)\s*[.!?]?$", re.I)
_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b\s*[:#-]?\s*(.*)")


def _d_todo_scan(cmd: str):
    text = (cmd or "").strip()
    m = _TODO_SCAN_RE.match(text) or _TODO_SCAN_REV_RE.match(text)
    if not m:
        return None
    tail = m.group("dir")
    if tail is not None:
        raw = tail.strip().strip("\"'`").rstrip(".").strip()
        if not _pathish(raw) and not _dirish(raw):
            return None
    return {"dir": tail}


def _e_todo_scan(app, ctx) -> str:
    directory, err = _resolve_dir(ctx.get("dir"))
    if directory is None:
        return err
    files = _iter_files(directory, SCAN_EXTS, SCAN_MAX_FILES)
    if not files:
        return ("No %s sources under %s, sir - nothing to scan."
                % ("/".join(e.lstrip(".") for e in SCAN_EXTS),
                   _disp(directory)))
    hits: list[tuple[str, int, str, str]] = []   # (file, line, tag, text)
    scanned = 0
    for path in files:
        try:
            if os.path.getsize(path) > SCAN_MAX_FILE_BYTES:
                continue
            with open(path, "r", encoding="utf-8",
                      errors="replace") as fh:
                for lineno, line in enumerate(fh, 1):
                    m = _MARKER_RE.search(line)
                    if m:
                        hits.append((path, lineno, m.group(1),
                                     m.group(2).strip()[:90]))
                        if len(hits) >= SCAN_FINDINGS_CAP:
                            break
        except Exception:
            continue
        scanned += 1
        if len(hits) >= SCAN_FINDINGS_CAP:
            break
    if not hits:
        return ("No TODO, FIXME, HACK or XXX markers in the %s I scanned "
                "under %s, sir."
                % (_plural(scanned, "file"), _disp(directory)))
    by_file: dict[str, list[tuple[int, str, str]]] = {}
    for path, lineno, tag, text in hits:
        by_file.setdefault(path, []).append((lineno, tag, text))
    shown_files = sorted(by_file)[:SCAN_FILES_SHOWN]
    blocks = []
    shown_count = 0
    for path in shown_files:
        entries = by_file[path][:SCAN_PER_FILE_SHOWN]
        shown_count += len(entries)
        rel = os.path.relpath(path, directory).replace(os.sep, "/")
        lines = ["%s (%s):" % (rel, _plural(len(by_file[path]), "marker"))]
        lines.extend("  line %d  %s  %s" % (lineno, tag, text or "-")
                     for lineno, tag, text in entries)
        if len(by_file[path]) > SCAN_PER_FILE_SHOWN:
            lines.append("  ... %d more here."
                         % (len(by_file[path]) - SCAN_PER_FILE_SHOWN))
        blocks.append("\n".join(lines))
    hidden = len(hits) - shown_count
    tail_note = ("\n... %d further marker(s) not shown, sir." % hidden) \
        if hidden > 0 else ""
    return ("I found %s across %s in %s, sir:\n%s%s"
            % (_plural(len(hits), "marker"),
               _plural(len(by_file), "file"), _disp(directory),
               "\n".join(blocks), tail_note))


# ==========================================================================
# dv_deps_check - imports versus requirements.txt
# ==========================================================================

_DEPS_CHECK_RE = re.compile(
    r"^" + _POLITE
    + r"(?:check\s+(?:the\s+)?(?:project\s+)?(?:dependencies|deps|imports)"
      r"\s+(?:in|for|of)|dependency\s+check\s+(?:for|in|of)|deps\s+check"
      r"\s+(?:for|in|of))\s+(?P<dir>.+?)\s*[.!?]?$", re.I)


def _d_deps_check(cmd: str):
    m = _DEPS_CHECK_RE.match((cmd or "").strip())
    if not m:
        return None
    raw = m.group("dir").strip().strip("\"'`").rstrip(".").strip()
    if not _pathish(raw) and not _dirish(raw):
        return None
    return {"dir": raw}


def _root_module(name: str) -> str:
    return name.split(".", 1)[0]


def _py_imports(code: str) -> list[str]:
    roots: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return roots
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(_root_module(a.name) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue                  # relative import: local by birth
            if node.module:
                roots.append(_root_module(node.module))
    return roots


def _norm_dist(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).strip().lower()


def _requirements(path: str) -> tuple[list[str], str | None]:
    """Parse requirements.txt into normalized distribution names."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except Exception as exc:
        return [], str(exc)[:100]
    names: list[str] = []
    for line in lines:
        entry = line.split(";", 1)[0].strip()      # drop markers
        if not entry or entry.startswith(("#", "-", "--")):
            continue
        entry = re.split(r"[\[><=!~]", entry, 1)[0].strip()
        if entry:
            names.append(_norm_dist(entry))
    return names, None


def _e_deps_check(app, ctx) -> str:
    directory, err = _resolve_dir(ctx.get("dir"))
    if directory is None:
        return err
    files = _iter_files(directory, (".py",), DEPS_MAX_FILES)
    if not files:
        return "I found no Python files under %s, sir." % _disp(directory)
    local = {os.path.splitext(os.path.basename(p))[0] for p in files}
    for name in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, name)) and \
                not name.startswith(".") and name not in JUNK_DIRS:
            local.add(name)
    imported: dict[str, str] = {}      # root -> first file that used it
    parse_errors = 0
    for path in files:
        code, io_err = _read_head(path, READ_LINE_CAP, READ_BYTE_CAP)
        if code is None:
            parse_errors += 1
            continue
        try:
            for root in _py_imports(code):
                imported.setdefault(root, path)
        except Exception:
            parse_errors += 1
    req_path = os.path.join(directory, "requirements.txt")
    required, req_err = _requirements(req_path)
    stdlib = {n.lower() for n in getattr(sys, "stdlib_module_names", ())}

    def declared(root: str) -> bool:
        guess = _IMPORT_ALIASES.get(root.lower(), root.lower())
        return _norm_dist(guess) in required or _norm_dist(root) in required

    def imported_name(dist: str) -> bool:
        rev = {v: k for k, v in _IMPORT_ALIASES.items()}
        candidates = {dist, rev.get(dist, dist)}
        return any(_norm_dist(c) in { _norm_dist(r) for r in imported }
                   for c in candidates)

    missing = sorted(r for r in imported
                     if r.lower() not in stdlib and r not in local
                     and not declared(r))
    unused = sorted(d for d in dict.fromkeys(required)
                    if not imported_name(d))

    parts = ["Dependencies for %s, sir: %s parsed (%d unreadable)."
             % (_disp(directory), _plural(len(files), "py file"),
                parse_errors)]
    if req_err is not None:
        parts.append("No readable requirements.txt found there, sir.")
    else:
        parts.append("requirements.txt declares %s."
                     % _plural(len(required), "distribution"))
    if missing:
        parts.append("Imported but not declared: %s."
                     % ", ".join(missing[:DEPS_MAX_LISTED])
                     + (" (%d more.)" % (len(missing) - DEPS_MAX_LISTED)
                        if len(missing) > DEPS_MAX_LISTED else ""))
    elif required or imported:
        parts.append("Nothing imported is missing from the declaration, "
                     "sir.")
    if unused:
        parts.append("Declared but never imported (candidates, not "
                     "verdicts): %s."
                     % ", ".join(unused[:DEPS_MAX_LISTED]))
    return "\n".join(parts)


# ==========================================================================
# dv_json_tool - validate / pretty-print / save a JSON file
# ==========================================================================

_JSON_VALIDATE_RE = re.compile(
    r"^" + _POLITE + r"(?:validate|check)\s+(?:the\s+)?json(?:\s+file)?\s+"
    r"(?P<path>.+?)\s*[.!?]?$", re.I)
_JSON_FORMAT_RE = re.compile(
    r"^" + _POLITE + r"(?:format|pretty[- ]?print|print|show)\s+"
    r"(?:the\s+)?json(?:\s+file)?\s+(?P<path>.+?)"
    r"(?:\s+(?:and\s+)?(?:save|write|overwrite)(?:\s+it)?)?\s*[.!?]?$",
    re.I)


def _d_json_tool(cmd: str):
    text = (cmd or "").strip()
    m = _JSON_VALIDATE_RE.match(text)
    if m:
        raw = m.group("path").strip().strip("\"'`")
        if _pathish(raw):
            return {"action": "validate", "path": raw}
        return None
    m = _JSON_FORMAT_RE.match(text)
    if m:
        raw = m.group("path").strip().strip("\"'`")
        if not _pathish(raw):
            return None
        action = "save" if re.search(
            r"\b(?:save|write|overwrite)\b", text, re.I) else "show"
        return {"action": action, "path": raw}
    return None


def _load_json_text(path: str) -> tuple[str | None, str]:
    try:
        size = os.path.getsize(path)
        if size > JSON_MAX_BYTES:
            return None, ("%s is over %d megabytes, sir - too large for "
                          "my JSON tooling." % (_disp(path),
                          JSON_MAX_BYTES // (1024 * 1024)))
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), ""
    except FileNotFoundError:
        return None, "I cannot find %s, sir." % _disp(path)
    except Exception as exc:
        return None, ("I could not read %s, sir (%s)."
                      % (_disp(path), str(exc)[:100]))


def _json_shape(data) -> str:
    if isinstance(data, dict):
        return "a dict with %s (%s)" % (
            _plural(len(data), "key"),
            ", ".join(list(map(str, data.keys()))[:6]) or "empty")
    if isinstance(data, list):
        return "a list with %s" % _plural(len(data), "item")
    return "a %s value" % type(data).__name__


def _e_json_tool(app, ctx) -> str:
    path = _resolve_path(ctx.get("path") or "")
    if path is None:
        return "I could not make sense of that file path, sir."
    text, err = _load_json_text(path)
    if text is None:
        return err
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ("%s is not valid JSON, sir - line %d, column %d: %s."
                % (_disp(path), exc.lineno, exc.colno, exc.msg))
    except Exception as exc:
        return ("I could not parse %s, sir (%s)."
                % (_disp(path), str(exc)[:100]))

    if ctx["action"] == "validate":
        return "%s checks out - valid JSON, sir: %s." % (_disp(path),
                                                         _json_shape(data))
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    if ctx["action"] == "show":
        return ("Pretty JSON for %s, sir:\n%s"
                % (_disp(path), _clip(pretty, JSON_SHOW_CAP)))
    # save lane: home-rail, .bak first, then write.
    if not _under_home(path):
        return ("%s sits outside your home folder, sir, so I will not "
                "rewrite it." % _disp(path))
    backup = _backup(path)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(pretty + "\n")
    except Exception as exc:
        return ("I could not write the formatted JSON, sir (%s)."
                % str(exc)[:100])
    note = " Backup rests at %s." % _disp(backup) if backup else ""
    return ("Reformatted %s with indent=2, sir - %s.%s"
            % (_disp(path), _json_shape(data), note))


# ==========================================================================
# dv_regex - finditer matcher plus heuristic pattern breakdown
# ==========================================================================

_REGEX_MATCH_RE = re.compile(
    r"^" + _POLITE + r"regex\s+(?P<pat>.+?)\s+against\s+(?P<text>.+)$",
    re.I | re.S)
_REGEX_EXPLAIN_RE = re.compile(
    r"^" + _POLITE + r"(?:explain|break\s+down|describe)\s+(?:the\s+)?"
    r"regex\s*[:\uFF1A]?\s*(?P<pat>.+)$", re.I | re.S)

_ESCAPE_DOCS = {
    "d": "any digit (0-9)", "D": "any non-digit",
    "w": "any word character (letters, digits, underscore)",
    "W": "any non-word character", "s": "any whitespace",
    "S": "any non-whitespace", "b": "word boundary", "B": "not a word "
    "boundary", "n": "newline", "t": "tab", "r": "carriage return",
    "A": "start of string", "Z": "end of string", ".": "a literal dot",
}


def _d_regex(cmd: str):
    text = (cmd or "").strip()
    m = _REGEX_MATCH_RE.match(text)
    if m:
        pat = m.group("pat").strip()
        subject = m.group("text").strip()
        if pat and subject:
            return {"action": "match", "pat": pat, "text": subject}
        return None
    m = _REGEX_EXPLAIN_RE.match(text)
    if m:
        pat = m.group("pat").strip().strip("`\"'")
        if pat:
            return {"action": "explain", "pat": pat}
    return None


def _e_regex(app, ctx) -> str:
    pattern = ctx["pat"]
    if ctx["action"] == "match":
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return ("That pattern will not compile, sir - %s at position "
                    "%d." % (exc.msg, exc.pos if exc.pos is not None
                             else 0))
        matches = list(rx.finditer(ctx["text"]))[:REGEX_MATCH_CAP]
        total = len(list(rx.finditer(ctx["text"])))
        if not matches:
            return ("The pattern /%s/ matches nothing in that text, sir."
                    % pattern)
        lines = []
        for i, m in enumerate(matches, 1):
            groups = [g for g in m.groups() if g is not None]
            named = ["%s=%r" % (k, v) for k, v in
                     (m.groupdict() or {}).items() if v is not None]
            desc = "groups: %s" % ", ".join(named or
                                            map(repr, groups)) \
                if (groups or named) else "no groups"
            lines.append("%d. %r at %d-%d (%s)"
                         % (i, m.group(0), m.start(), m.end(), desc))
        extra = ("" if total <= REGEX_MATCH_CAP
                 else "\n... %d more match(es), sir."
                 % (total - REGEX_MATCH_CAP))
        return ("The pattern /%s/ hits %s in that text, sir:\n%s%s"
                % (pattern, _plural(total, "match"), "\n".join(lines),
                   extra))

    tokens = _regex_tokens(pattern)
    return ("Here is the breakdown of /%s/, sir:\n%s"
            % (pattern, "\n".join("- " + t for t in tokens[:REGEX_TOKEN_CAP])))


def _regex_tokens(pattern: str) -> list[str]:
    """Purely heuristic, character-level explanation of a pattern."""
    out: list[str] = []
    i, n = 0, len(pattern)
    groups = 0
    while i < n and len(out) < REGEX_TOKEN_CAP + 5:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            doc = _ESCAPE_DOCS.get(nxt)
            if nxt.isdigit():
                out.append("\\%s - backreference to group %s"
                           % (nxt, nxt))
            elif doc:
                out.append("\\%s - %s" % (nxt, doc))
            else:
                out.append("\\%s - literal %s" % (nxt, nxt))
            i += 2
        elif ch == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append("[ - unclosed character class, sir")
                break
            body = pattern[i + 1:end]
            neg = body.startswith("^")
            out.append("[%s] - character class%s: %s"
                       % (body, " (negated)" if neg else "", body.lstrip("^")))
            i = end + 1
        elif ch == "^":
            out.append("^ - anchor: start of string")
            i += 1
        elif ch == "$":
            out.append("$ - anchor: end of string")
            i += 1
        elif ch == ".":
            out.append(". - any single character (except newline)")
            i += 1
        elif ch == "|":
            out.append("| - alternation: either side may match")
            i += 1
        elif ch == "(":
            groups += 1
            if pattern.startswith("(?P<", i):
                close = pattern.find(">", i)
                name = pattern[i + 4:close] if close != -1 else "?"
                out.append("(?P<%s>...) - named capture group %d: '%s'"
                           % (name, groups, name))
                i = (close + 1) if close != -1 else i + 4
            elif pattern.startswith("(?:", i):
                out.append("(?:...) - non-capturing group %d" % groups)
                i += 4
            elif pattern.startswith(("(?=", "(?!", "(?<=", "(?<!"), i):
                out.append("(?... ) - lookaround group %d" % groups)
                i += 3
            else:
                out.append("( ) - capturing group %d" % groups)
                i += 1
        elif ch == ")":
            out.append(") - closes a group")
            i += 1
        elif ch in "*+?":
            lazy = " (lazy)" if i + 1 < n and pattern[i + 1] == "?" else ""
            meaning = {"*": "zero or more of the previous",
                       "+": "one or more of the previous",
                       "?": "optional: zero or one of the previous"}[ch]
            out.append("%s - %s%s" % (ch, meaning, lazy))
            i += 2 if lazy else 1
        elif ch == "{":
            end = pattern.find("}", i)
            if end == -1:
                out.append("{ - literal brace")
                i += 1
            else:
                out.append("{%s} - repeated-range quantifier"
                           % pattern[i + 1:end])
                i = end + 1
        else:
            j = i
            while j < n and pattern[j] not in "^$.|*+?{}()[]\\":
                j += 1
            out.append("%r - literal text" % pattern[i:j])
            i = j
    out.append("Total: %s." % _plural(groups, "capture group"))
    return out


# ==========================================================================
# dv_loc - per-extension line counts
# ==========================================================================

_LOC_RE = re.compile(
    r"^" + _POLITE
    + r"(?:count\s+(?:the\s+)?lines\s+(?:in|of)"
      r"|lines\s+of\s+code\s+(?:in|of)"
      r"|how\s+many\s+lines\s+(?:are\s+(?:there\s+)?in|of))"
    r"\s+(?P<path>.+?)\s*[.!?]?$", re.I)


def _d_loc(cmd: str):
    m = _LOC_RE.match((cmd or "").strip())
    if not m:
        return None
    raw = m.group("path").strip().strip("\"'`").rstrip(".").strip()
    if not _pathish(raw):
        return None                      # "count lines in this sentence"
    return {"path": raw}


def _count_lines(path: str) -> tuple[int, int] | None:
    """(total, blank) lines of one file; None when unreadable."""
    try:
        if os.path.getsize(path) > SCAN_MAX_FILE_BYTES:
            return None
        total = blank = 0
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                total += 1
                if not line.strip():
                    blank += 1
        return total, blank
    except Exception:
        return None


def _e_loc(app, ctx) -> str:
    path = _resolve_path(ctx.get("path") or "")
    if path is None:
        return "I could not make sense of that path, sir."
    if os.path.isfile(path):
        counts = _count_lines(path)
        if counts is None:
            return "I could not read %s, sir." % _disp(path)
        total, blank = counts
        return ("%s runs %s (%d blank), sir."
                % (_disp(path), _plural(total, "line"), blank))
    if not os.path.isdir(path):
        return "I cannot find %s, sir." % _disp(path)
    files = _iter_files(path, LOC_EXTS, LOC_MAX_FILES)
    if not files:
        return ("No countable source files under %s, sir."
                % _disp(path))
    per_ext: dict[str, list[int]] = {}
    truncated = len(files) >= LOC_MAX_FILES
    for fpath in files:
        counts = _count_lines(fpath)
        if counts is None:
            continue
        ext = os.path.splitext(fpath)[1].lower() or ".?"
        totals = per_ext.setdefault(ext, [0, 0, 0])   # files, lines, blank
        totals[0] += 1
        totals[1] += counts[0]
        totals[2] += counts[1]
    if not per_ext:
        return ("I could not read any of the %s under %s, sir."
                % (_plural(len(files), "source file"), _disp(path)))
    grand = sum(v[1] for v in per_ext.values())
    n_files = sum(v[0] for v in per_ext.values())
    rows = sorted(per_ext.items(), key=lambda kv: -kv[1][1])
    lines = ["Line count for %s, sir - %s across %s:"
             % (_disp(path), _plural(grand, "line"),
                _plural(n_files, "file"))]
    for ext, (_nf, nl, _nb) in rows[:LOC_EXT_ROWS_SHOWN]:
        lines.append("- %s: %s" % (ext, _plural(nl, "line")))
    if len(rows) > LOC_EXT_ROWS_SHOWN:
        lines.append("- ... %d more extensions." % (len(rows) -
                                                    LOC_EXT_ROWS_SHOWN))
    if truncated:
        lines.append("(Scan stopped at the %d-file cap.)" % LOC_MAX_FILES)
    return "\n".join(lines)


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("dv_git_msg", _d_git_msg, _e_git_msg, False),
    ("dv_git_summary", _d_git_summary, _e_git_summary, False),
    ("dv_code_explain", _d_code_explain, _e_code_explain, False),
    ("dv_test_scaffold", _d_test_scaffold, _e_test_scaffold, False),
    ("dv_docstring", _d_docstring, _e_docstring, False),
    ("dv_todo_scan", _d_todo_scan, _e_todo_scan, False),
    ("dv_deps_check", _d_deps_check, _e_deps_check, False),
    ("dv_json_tool", _d_json_tool, _e_json_tool, False),
    ("dv_regex", _d_regex, _e_regex, False),
    ("dv_loc", _d_loc, _e_loc, False),
)


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return ("Something jammed in my developer-tools module "
                    "(%s), sir." % str(exc)[:120])
    safe.__name__ = "safe_%s" % name
    return safe


_SUPERSEDES: dict[str, tuple[str, ...]] = {
    # brain_extra's line_count matches "lines in <anything>" and answers
    # path requests with nonsense ("1 lines"). dv_loc owns path-shaped
    # requests with real per-extension counts; inline-text line questions
    # now fall through to chat, which is honest.
    "dv_loc": ("line_count",),
}


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register every developer-tools skill with the given Brain."""
    for entry in _SKILLS:
        name, detect, execute, priority = entry[:4]
        brain.register(name, detect, _wrap(execute, name),
                       priority=priority,
                       supersedes=_SUPERSEDES.get(name, ()))
    log.info("developer-tools skills registered (%d)", len(_SKILLS))


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False,
                     supersedes=()):
            print("would register %s" % name)

    register(_B())
