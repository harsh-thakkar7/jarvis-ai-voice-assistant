"""Code validation pipeline for the JARVIS AI assistant.

JARVIS frequently asks language models to produce source code. Raw model
output is unreliable: it may wrap code in markdown fences, mix in polite
prose, contain syntax errors, or reference runtime failures. This module
is the gatekeeper that sits between "model said something" and "JARVIS
shows/executes code", so only verified code ever reaches the user.

Pipeline overview:

1. :func:`strip_fences` / :func:`extract_code_blocks` recover raw code
   from a conversational reply (markdown fences, prose wrappers).
2. :func:`detect_language` resolves the language from an explicit hint
   (``py`` -> ``python``, ``js`` -> ``javascript`` ...) or heuristically
   sniffs the code itself.
3. Language validators check the code:
   - ``validate_python``: ``ast.parse`` -> ``compile()`` -> optional
     sandboxed execution in a fresh temp directory.
   - ``validate_javascript``: ``node --check`` syntax check (cached
     binary lookup).
   - Everything else gets lightweight structural sanity checks.
4. :func:`generate_validated` closes the loop: it calls an LLM-backed
   callable, validates the reply, and feeds precise validation errors
   back into the prompt for a bounded number of repair attempts.
5. :func:`summarize_validation` renders one human-readable verdict line.

Only the Python standard library is used. All public functions are
defensive: they are deterministic, typed, and never raise on malformed
input.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis_logging import get_logger

log = get_logger("code_validator")

__all__ = [
    "ValidationResult",
    "strip_fences",
    "extract_code_blocks",
    "detect_language",
    "validate_python",
    "validate_javascript",
    "validate",
    "generate_validated",
    "summarize_validation",
]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Outcome of validating one code sample.

    Attributes:
        ok: True when the code passed every applicable check.
        lang: Resolved language identifier (e.g. ``"python"``).
        code: The exact code text that was validated.
        errors: Blocking problems; non-empty means ``ok`` is False.
        warnings: Non-blocking observations worth surfacing to the user.
        stage: Pipeline stage that produced the verdict. One of
            ``fence-strip``, ``ast``, ``compile``, ``exec``,
            ``node-check``, ``unknown-lang``, ``no-code`` (or
            ``structural`` for lightweight cross-language checks).
    """

    ok: bool
    lang: str
    code: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stage: str = ""


# ---------------------------------------------------------------------------
# Fence / prose extraction
# ---------------------------------------------------------------------------

_FENCE_BLOCK_RE = re.compile(
    r"^[ \t]{0,3}```([A-Za-z0-9_+#.\-]*)[ \t\r]*\n(.*?)^[ \t]{0,3}```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

_FENCE_OPEN_RE = re.compile(
    r"^[ \t]{0,3}```([A-Za-z0-9_+#.\-]*)[ \t\r]*\n",
    re.MULTILINE,
)

_LEADING_PROSE_RE = re.compile(
    r"^\s*(?:"
    r"here(?:'s|\bis\b)|sure\b|certainly\b|below\s+is\b|of\s+course\b|"
    r"absolutely\b|okay?\b|got\s+it\b|great\b|alright\b|"
    r"this\s+(?:code|script|program|snippet|function|solution|version)|"
    r"i(?:'ve|\s+have)\s+(?:created|written|made|fixed|updated|prepared)"
    r")",
    re.IGNORECASE,
)

_TRAILING_PROSE_RE = re.compile(
    r"^\s*(?:"
    r"let\s+me\s+know\b|hope\s+(?:this|that|it)\b|feel\s+free\b|i\s+hope\b|"
    r"this\s+(?:should|will|code|script|works)\b|"
    r"you\s+can\s+(?:now|run|use|copy|test)\b|"
    r"just\s+(?:copy|save|run|paste)\b|"
    r"that(?:'s|\s+is)\s+(?:it|all)\b|good\s+luck\b|enjoy\b|thanks\b|note:"
    r")",
    re.IGNORECASE,
)


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Extract every markdown-fenced code block from *text*.

    Args:
        text: Arbitrary LLM reply text, possibly containing ``````
            fences with optional language tags.

    Returns:
        Ordered ``(lang_or_empty, code)`` tuples, one per fenced block.
        Language tags are lowercased; unterminated trailing fences are
        tolerated and yield their partial content.
    """
    if not isinstance(text, str) or "```" not in text:
        return []
    blocks: list[tuple[str, str]] = []
    last_end = 0
    try:
        for match in _FENCE_BLOCK_RE.finditer(text):
            blocks.append((match.group(1).lower(), match.group(2).strip()))
            last_end = match.end()
        tail = text[last_end:]
        if "```" in tail:
            open_match = _FENCE_OPEN_RE.search(tail)
            if open_match:
                remainder = tail[open_match.end():].strip()
                if remainder:
                    blocks.append((open_match.group(1).lower(), remainder))
    except Exception as exc:  # pragma: no cover - purely defensive
        log.warning("fence extraction failed: %s", exc)
    return blocks


def strip_fences(text: str) -> str:
    """Recover pure code from a conversational LLM reply.

    Behaviour:
        - Fenced blocks win: all ````` ```lang ... ``` ```` blocks are
          extracted and joined with blank lines (language tags are
          matched case-insensitively).
        - Without fences, obvious conversational prose is trimmed:
          leading lines like ``Here's...`` / ``Sure...`` /
          ``Certainly...`` / ``Below...`` and trailing sentences such as
          ``Let me know if you need changes``.
        - Pure code with no fences and no prose is returned untouched.

    Deterministic and exception-free: on any internal failure the input
    is returned unchanged.

    Args:
        text: Raw model reply.

    Returns:
        Best-effort extraction of just the code.
    """
    if not isinstance(text, str):
        return ""
    try:
        blocks = extract_code_blocks(text)
        if blocks:
            return "\n\n".join(code for _, code in blocks)

        lines = text.splitlines()
        start = 0
        while start < len(lines) - 1 and _LEADING_PROSE_RE.match(lines[start]):
            start += 1
        end = len(lines)
        while end > start + 1 and _TRAILING_PROSE_RE.match(lines[end - 1]):
            end -= 1
        if start == 0 and end == len(lines):
            return text
        candidate = "\n".join(lines[start:end]).strip()
        return candidate if candidate else text
    except Exception as exc:  # pragma: no cover - purely defensive
        log.warning("prose stripping failed: %s", exc)
        return text


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_LANG_ALIASES: dict[str, str] = {
    "py": "python",
    "python": "python",
    "python3": "python",
    "ipython": "python",
    "js": "javascript",
    "javascript": "javascript",
    "node": "javascript",
    "nodejs": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "ecmascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "tsx": "typescript",
    "html": "html",
    "htm": "html",
    "xml": "html",
    "css": "css",
    "sql": "sql",
    "mysql": "sql",
    "postgres": "sql",
    "postgresql": "sql",
    "sqlite": "sql",
    "sh": "bash",
    "bash": "bash",
    "shell": "bash",
    "zsh": "bash",
    "console": "bash",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "rs": "rust",
    "cpp": "cpp",
    "c++": "cpp",
    "cxx": "cpp",
    "cc": "cpp",
    "c": "c",
    "java": "java",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "markdown": "markdown",
    "md": "markdown",
}

_SQL_SNIFF_RE = re.compile(
    r"\bselect\b[\s\S]+\bfrom\b|\binsert\s+into\b|\bcreate\s+table\b|"
    r"\bupdate\b[\s\S]+\bset\b|\bdelete\s+from\b",
    re.IGNORECASE,
)
_RUST_SNIFF_RE = re.compile(r"\bfn\s+main\b|\bprintln!\s*\(")
_GO_SNIFF_RE = re.compile(r"^\s*package\s+\w+", re.MULTILINE)
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+\w+\s*\(", re.MULTILINE)
_PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+[\w.]+\s+import|import\s+\w+)", re.MULTILINE)
_PY_CLASS_RE = re.compile(r"^\s*class\s+\w+[^:]*:\s*$", re.MULTILINE)
_JS_SNIFF_RE = re.compile(r"\bfunction\b|\b(?:const|let|var)\s+\w+|console\.log|=>")
_CPP_SNIFF_RE = re.compile(r"#include\b|std::|\bcout\b|\bcerr\b")
_JAVA_SNIFF_RE = re.compile(r"\bpublic\s+(?:static\s+)?(?:class|void)\b|System\.out\.print")


def _normalize_tag(tag: str) -> str:
    """Map a raw language tag/hint onto a canonical language name."""
    return _LANG_ALIASES.get(tag.strip().lower(), "") if isinstance(tag, str) else ""


def detect_language(code: str, hint: str | None = None) -> str:
    """Resolve the programming language of *code*.

    A recognised *hint* (``py``, ``Python3``, ``node``, ``c++`` ...)
    short-circuits the decision. Otherwise lightweight heuristics sniff
    the source: shebangs, DOCTYPE, SQL keywords, ``def``/``import``/
    ``class`` for Python, ``function``/``const``/``=>`` for JavaScript,
    ``#include`` for C++, ``package main`` for Go, ``fn main`` for Rust,
    and so on.

    Args:
        code: The source text to inspect.
        hint: Optional language tag supplied by the caller or model.

    Returns:
        Canonical language name, or ``"unknown"`` when nothing matches.
    """
    try:
        normalized = _normalize_tag(hint) if hint else ""
        if normalized:
            return normalized
        if not isinstance(code, str) or not code.strip():
            return "unknown"
        low = code.lstrip().lower()
        if low.startswith(("#!/bin/bash", "#!/bin/sh", "#!/usr/bin/env bash")):
            return "bash"
        if "<!doctype" in low[:200] or "<html" in low[:500]:
            return "html"
        # Python/JS before SQL: embedded queries inside real programs
        # ("cur.execute(\"SELECT ...\")") must not downgrade the file.
        if (
            _PY_DEF_RE.search(code)
            or _PY_IMPORT_RE.search(code)
            or _PY_CLASS_RE.search(code)
            or re.search(r"\bprint\s*\(", code)
        ):
            return "python"
        if _JS_SNIFF_RE.search(code):
            return "javascript"
        if _SQL_SNIFF_RE.search(code):
            return "sql"
        if _RUST_SNIFF_RE.search(code):
            return "rust"
        if _GO_SNIFF_RE.search(code) or re.search(r"\bfunc\s+\w+\s*\(", code):
            return "go"
        if _JAVA_SNIFF_RE.search(code):
            return "java"
        if _CPP_SNIFF_RE.search(code):
            return "cpp"
        return "unknown"
    except Exception:  # pragma: no cover - purely defensive
        return "unknown"


# ---------------------------------------------------------------------------
# Python validation
# ---------------------------------------------------------------------------

_STDIN_GUARD_RE = re.compile(r"\binput\s*\(")
_INFINITE_LOOP_RE = re.compile(r"\bwhile\s+True\b")
_EXC_LINE_RE = re.compile(
    r"\b(SyntaxError|NameError|TypeError|ValueError|ZeroDivisionError|"
    r"IndexError|KeyError|AttributeError|ImportError|RuntimeError|"
    r"OSError|RecursionError|MemoryError|OverflowError|StopIteration|"
    r"ArithmeticError|UnicodeError|Exception)\b"
)


def _last_meaningful_stderr(stderr: str) -> str:
    """Pick the most diagnostic line from a Python traceback."""
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for line in reversed(lines):
        if _EXC_LINE_RE.search(line):
            return line
    return lines[-1] if lines else ""


def validate_python(
    code: str, exec_simple: bool = False, timeout: float = 6.0
) -> ValidationResult:
    """Validate Python *code* through progressively deeper stages.

    Stages:
        1. ``ast.parse`` - syntax errors reported as ``line N: msg``.
        2. ``compile()`` - catches residual compilation problems.
        3. ``exec`` (only when *exec_simple* is True) - runs the code in
           a clean subprocess (``sys.executable -I -``) inside a fresh
           temporary directory; a non-zero exit surfaces the most
           meaningful stderr line.

    Safety guards skip stage 3 (with a warning) for code that reads
    ``input(...)`` or contains a ``while True`` loop without a
    ``break``. Empty code short-circuits with stage ``no-code``.

    Args:
        code: Python source to validate.
        exec_simple: Whether to additionally execute the code.
        timeout: Wall-clock budget for the execution subprocess.

    Returns:
        A :class:`ValidationResult`; never raises.
    """
    if not isinstance(code, str) or not code.strip():
        return ValidationResult(
            ok=False, lang="python", code=code or "",
            errors=["empty code"], stage="no-code",
        )

    errors: list[str] = []
    warnings: list[str] = []

    try:
        ast.parse(code)
    except SyntaxError as exc:
        errors.append(f"line {exc.lineno}: {exc.msg}")
        log.info("python syntax error: %s", errors[-1])
        return ValidationResult(
            ok=False, lang="python", code=code, errors=errors, stage="ast"
        )
    except (ValueError, RecursionError) as exc:
        errors.append(f"could not parse code: {exc}")
        return ValidationResult(
            ok=False, lang="python", code=code, errors=errors, stage="ast"
        )

    try:
        compile(code, "<jarvis-validation>", "exec")
    except Exception as exc:
        errors.append(f"compilation failed: {exc}")
        log.info("python compile error: %s", errors[-1])
        return ValidationResult(
            ok=False, lang="python", code=code, errors=errors, stage="compile"
        )

    if _STDIN_GUARD_RE.search(code):
        warnings.append("skipped execution: waits for stdin")
    elif _INFINITE_LOOP_RE.search(code) and "break" not in code:
        warnings.append("skipped execution: potential infinite loop")
    elif exec_simple:
        stage = "exec"
        try:
            with tempfile.TemporaryDirectory(prefix="jarvis_val_") as tmpdir:
                proc = subprocess.run(
                    [sys.executable, "-I", "-"],
                    input=code,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=tmpdir,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            errors.append(f"execution timed out after {timeout:.1f}s")
            log.warning("python exec timeout: %s", errors[-1])
            return ValidationResult(
                ok=False, lang="python", code=code, errors=errors,
                warnings=warnings, stage="exec",
            )
        except OSError as exc:
            errors.append(f"could not run validation subprocess: {exc}")
            return ValidationResult(
                ok=False, lang="python", code=code, errors=errors,
                warnings=warnings, stage="exec",
            )
        except Exception as exc:  # pragma: no cover - purely defensive
            errors.append(f"unexpected execution failure: {exc}")
            return ValidationResult(
                ok=False, lang="python", code=code, errors=errors,
                warnings=warnings, stage="exec",
            )
        if proc.returncode != 0:
            detail = _last_meaningful_stderr(proc.stderr or "") or (
                f"exit code {proc.returncode}"
            )
            errors.append(f"execution failed: {detail}")
            log.info("python exec failure: %s", errors[-1])
            return ValidationResult(
                ok=False, lang="python", code=code, errors=errors,
                warnings=warnings, stage="exec",
            )
        log.debug("python code executed cleanly (%.1fs budget)", timeout)
        return ValidationResult(
            ok=True, lang="python", code=code, warnings=warnings, stage="exec"
        )

    log.debug("python code passed syntax + compile")
    return ValidationResult(
        ok=True, lang="python", code=code, warnings=warnings, stage="compile"
    )


# ---------------------------------------------------------------------------
# JavaScript validation
# ---------------------------------------------------------------------------

_NODE_BIN: str | None = None
_NODE_LOOKUP_DONE: bool = False


def _node_binary() -> str | None:
    """Locate the ``node`` executable once and cache the answer."""
    global _NODE_BIN, _NODE_LOOKUP_DONE
    if not _NODE_LOOKUP_DONE:
        try:
            _NODE_BIN = shutil.which("node")
        except Exception:  # pragma: no cover - purely defensive
            _NODE_BIN = None
        _NODE_LOOKUP_DONE = True
        log.debug("node lookup resolved to %r", _NODE_BIN)
    return _NODE_BIN


def validate_javascript(code: str, timeout: float = 10.0) -> ValidationResult:
    """Syntax-check JavaScript *code* with ``node --check``.

    The code is written to a temporary ``.js`` file and checked without
    executing it. The ``which("node")`` lookup result is cached at module
    level so repeated validations stay cheap.

    Args:
        code: JavaScript source to validate.
        timeout: Wall-clock budget for the ``node`` subprocess.

    Returns:
        A :class:`ValidationResult` whose stage is ``node-check``. When
        node is not installed the result is ``ok`` with an explanatory
        warning instead of a hard failure.
    """
    node = _node_binary()
    if not node:
        return ValidationResult(
            ok=True, lang="javascript", code=code,
            warnings=["node not found; skipped JS syntax check"],
            stage="node-check",
        )

    fd: int | None = None
    path: str | None = None
    try:
        fd, path = tempfile.mkstemp(suffix=".js", prefix="jarvis_val_")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(code)
        fd = None
        proc = subprocess.run(
            [node, "--check", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("node --check timed out after %.1fs", timeout)
        return ValidationResult(
            ok=False, lang="javascript", code=code,
            errors=[f"node --check timed out after {timeout:.1f}s"],
            stage="node-check",
        )
    except OSError as exc:
        log.warning("could not run node --check: %s", exc)
        return ValidationResult(
            ok=False, lang="javascript", code=code,
            errors=[f"could not run node --check: {exc}"],
            stage="node-check",
        )
    except Exception as exc:  # pragma: no cover - purely defensive
        return ValidationResult(
            ok=False, lang="javascript", code=code,
            errors=[f"unexpected node --check failure: {exc}"],
            stage="node-check",
        )
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    if proc.returncode != 0:
        stderr_lines = [ln.strip() for ln in (proc.stderr or "").splitlines()]
        errors = [ln for ln in stderr_lines if ln][-3:] or [
            f"node --check exited with code {proc.returncode}"
        ]
        log.info("node --check rejected code: %s", errors[-1])
        return ValidationResult(
            ok=False, lang="javascript", code=code, errors=errors,
            stage="node-check",
        )
    log.debug("node --check accepted code")
    return ValidationResult(ok=True, lang="javascript", code=code, stage="node-check")


# ---------------------------------------------------------------------------
# Structural sanity for other languages
# ---------------------------------------------------------------------------

_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{"}
_BRACKET_NAMES = {"(": "parentheses", "[": "brackets", "{": "braces"}

_STRUCTURAL_LANGS = frozenset({"sql", "bash", "go", "rust", "cpp", "java", "c"})


def _bracket_problem_names(code: str) -> list[str]:
    """Detect unbalanced delimiters, ignoring strings and comments.

    Understands line comments (``#``, ``//``, ``--``), block comments
    (``/* */``) and quoted strings (``'``/``"``/`` ` ``) with escapes.

    Returns:
        Human names (``parentheses``/``brackets``/``braces``) of any
        delimiter class that is left unbalanced; empty list when clean.
    """
    problems: list[str] = []
    stack: list[str] = []
    in_str = ""
    escaped = False
    i = 0
    n = len(code)
    try:
        while i < n:
            ch = code[i]
            nxt = code[i + 1] if i + 1 < n else ""
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == in_str:
                    in_str = ""
                i += 1
                continue
            if ch in ("'", '"', "`"):
                in_str = ch
            elif ch == "#" or (ch == "/" and nxt == "/") or (ch == "-" and nxt == "-"):
                nl = code.find("\n", i)
                i = n if nl == -1 else nl
                continue
            elif ch == "/" and nxt == "*":
                close = code.find("*/", i + 2)
                i = n if close == -1 else close + 2
                continue
            elif ch in "([{":
                stack.append(ch)
            elif ch in ")]}":
                if stack and stack[-1] == _BRACKET_PAIRS[ch]:
                    stack.pop()
                else:
                    problems.append(_BRACKET_PAIRS[ch])
            i += 1
        problems.extend(stack)
    except Exception:  # pragma: no cover - purely defensive
        return []
    seen: list[str] = []
    for opener in problems:
        name = _BRACKET_NAMES[opener]
        if name not in seen:
            seen.append(name)
    return seen


def _validate_structural(lang: str, code: str) -> ValidationResult:
    """Lightweight bracket-balance sanity check for non-Python/JS code."""
    warnings: list[str] = []
    problems = _bracket_problem_names(code)
    if problems:
        joined = "/".join(problems)
        warnings.append(
            f"possible unbalanced {joined} (approximate cross-language check)"
        )
        log.debug("%s structural check flagged: %s", lang, joined)
    return ValidationResult(
        ok=True, lang=lang, code=code, warnings=warnings, stage="structural"
    )


def _validate_html(code: str) -> ValidationResult:
    """Basic HTML sanity: the text must actually contain tags."""
    if "<" in code and ">" in code:
        return ValidationResult(ok=True, lang="html", code=code, stage="structural")
    return ValidationResult(
        ok=False, lang="html", code=code,
        errors=["no HTML tags detected (missing < or >)"],
        stage="structural",
    )


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

def validate(
    code: str,
    lang: str | None = None,
    hint: str | None = None,
    exec_simple: bool = False,
) -> ValidationResult:
    """Validate *code*, dispatching on its resolved language.

    The language comes from *lang* (explicit override) else *hint*
    (normalized) else heuristic sniffing of the code itself.

    Dispatch table:
        - ``python``: full :func:`validate_python` pipeline.
        - ``javascript``: :func:`validate_javascript` (``node --check``).
        - ``typescript``: same JS-level check plus a warning that full
          TypeScript checking is not performed.
        - ``html``: basic tag-presence sanity.
        - ``sql``/``bash``/``go``/``rust``/``cpp``/``java``/``c``:
          structural bracket-balance sanity (warnings only).
        - anything else: accepted with an ``unknown language`` warning.

    Args:
        code: Source text to validate.
        lang: Explicit language override taking priority over sniffing.
        hint: Soft language hint (e.g. from the generation prompt).
        exec_simple: Passed through to :func:`validate_python`.

    Returns:
        A :class:`ValidationResult`; never raises.
    """
    try:
        if not isinstance(code, str) or not code.strip():
            return ValidationResult(
                ok=False, lang=(lang or hint or "unknown"), code=code or "",
                errors=["empty code"], stage="no-code",
            )
        resolved = detect_language(code, lang or hint)
        log.debug("validate dispatch: resolved=%s", resolved)
        if resolved == "python":
            return validate_python(code, exec_simple=exec_simple)
        if resolved == "javascript":
            return validate_javascript(code)
        if resolved == "typescript":
            result = validate_javascript(code)
            result.warnings.insert(
                0, "TypeScript checked at JavaScript level only (no full type check)"
            )
            return result
        if resolved == "html":
            return _validate_html(code)
        if resolved in _STRUCTURAL_LANGS:
            return _validate_structural(resolved, code)
        return ValidationResult(
            ok=True, lang=resolved, code=code,
            warnings=["unknown language; basic checks only"],
            stage="unknown-lang",
        )
    except Exception as exc:  # pragma: no cover - purely defensive
        log.warning("validate crashed unexpectedly: %s", exc)
        return ValidationResult(
            ok=False, lang=(lang or hint or "unknown"), code=str(code),
            errors=[f"internal validation failure: {exc}"],
            stage="unknown-lang",
        )


# ---------------------------------------------------------------------------
# Generate-and-verify loop
# ---------------------------------------------------------------------------

_RETRY_SUFFIX = (
    "\n\nYour previous output FAILED validation with these errors:\n"
)


def generate_validated(
    llm_call: Callable[[str], str | None],
    prompt: str,
    *,
    lang_hint: str | None = None,
    max_attempts: int = 2,
    exec_simple: bool = False,
) -> tuple[str, ValidationResult]:
    """Ask an LLM for code and keep trying until it validates.

    Each attempt calls ``llm_call(current_prompt)``, strips fences/prose
    and validates the result. On failure the validation errors are fed
    back verbatim into the next prompt so the model can repair its own
    output. If the callable returns ``None`` (transport/API failure) the
    loop stops immediately.

    Args:
        llm_call: Callable mapping a prompt to a reply string, or None
            when the language model is unavailable.
        prompt: The user's original coding request.
        lang_hint: Optional language hint used during validation.
        max_attempts: Maximum number of LLM calls (minimum 1).
        exec_simple: Passed through to the Python validator.

    Returns:
        ``(code, ValidationResult)`` for the first passing candidate, or
        - when every attempt fails - the best candidate seen (fewest
        validation errors; earliest wins ties) together with its result.
        An unavailable model yields ``("", result)`` with stage
        ``no-code`` and a ``language model unavailable`` error.
    """
    attempts = max(1, int(max_attempts))
    current_prompt = prompt
    best_code = ""
    best_result: ValidationResult | None = None

    for attempt in range(attempts):
        try:
            reply = llm_call(current_prompt)
        except Exception as exc:
            log.warning("llm_call raised: %s", exc)
            reply = None

        if reply is None:
            log.info("llm unavailable on attempt %d/%d", attempt + 1, attempts)
            return "", ValidationResult(
                ok=False,
                lang=detect_language("", lang_hint),
                code="",
                errors=["language model unavailable"],
                stage="no-code",
            )

        candidate = strip_fences(reply)
        result = validate(candidate, hint=lang_hint, exec_simple=exec_simple)
        log.debug(
            "attempt %d/%d ok=%s stage=%s errors=%d",
            attempt + 1, attempts, result.ok, result.stage, len(result.errors),
        )

        if result.ok:
            return candidate, result

        if best_result is None or len(result.errors) < len(best_result.errors):
            best_code, best_result = candidate, result

        if attempt < attempts - 1:
            bullet_errors = "\n".join(
                f"- {err}" for err in result.errors
            ) or "- unknown validation failure"
            current_prompt = (
                prompt
                + _RETRY_SUFFIX
                + bullet_errors
                + "\nFix EVERY issue and return ONLY the corrected complete "
                "code with no prose or markdown fences."
            )

    assert best_result is not None
    return best_code, best_result


# ---------------------------------------------------------------------------
# Human-friendly summary
# ---------------------------------------------------------------------------

_DISPLAY_LANGS = {
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "html": "HTML",
    "css": "CSS",
    "sql": "SQL",
    "bash": "Bash",
    "go": "Go",
    "rust": "Rust",
    "cpp": "C++",
    "c": "C",
    "java": "Java",
}


def _pretty_lang(lang: str) -> str:
    """Render a canonical language id for display."""
    if not lang:
        return "code"
    return _DISPLAY_LANGS.get(lang, lang.replace("+", "+").title())


def _one_line(message: str) -> str:
    """Collapse a possibly multi-line message into a single line."""
    return " ".join(str(message).split())


def summarize_validation(vr: ValidationResult) -> str:
    """Render one human-readable line describing a validation outcome.

    Examples:
        ``validated Python (syntax + compile)`` /
        ``syntax errors found: line 3: invalid syntax`` /
        ``runtime error: NameError: name 'x' is not defined``

    Args:
        vr: The result to describe.

    Returns:
        A single-line string; never raises.
    """
    try:
        lang = _pretty_lang(vr.lang)
        first_error = _one_line(vr.errors[0]) if vr.errors else ""

        if not vr.ok:
            if vr.stage == "no-code":
                return first_error or "no code to validate"
            if vr.stage == "ast":
                return f"syntax errors found: {first_error}" if first_error else (
                    "syntax errors found"
                )
            if vr.stage == "exec":
                return f"runtime error: {first_error}" if first_error else (
                    "runtime error during execution"
                )
            if first_error:
                return f"validation failed ({vr.stage}): {first_error}"
            if vr.warnings:
                return f"validation inconclusive: {_one_line('; '.join(vr.warnings))}"
            return f"validation failed ({vr.stage})"

        if vr.stage == "compile":
            return f"validated {lang} (syntax + compile)"
        if vr.stage == "exec":
            return f"validated {lang} (syntax + compile + execution)"
        if vr.stage == "node-check":
            if any("not found" in w for w in vr.warnings):
                return f"validated {lang} (node unavailable; syntax check skipped)"
            return f"validated {lang} (node --check)"
        if vr.stage == "structural":
            return f"validated {lang} (basic structure check)"
        if vr.stage == "unknown-lang":
            return f"accepted {lang}: unknown language; basic checks only"
        if vr.stage == "fence-strip":
            return f"extracted {lang} code from reply"
        return f"validated {lang}"
    except Exception:  # pragma: no cover - purely defensive
        return "validation summary unavailable"


# ---------------------------------------------------------------------------
# Smoke demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    SAMPLE_REPLY = (
        "Here's a quick utility:\n"
        "```python\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "print(add(2, 3))\n"
        "```\n"
        "Hope this helps!"
    )
    cleaned = strip_fences(SAMPLE_REPLY)
    print("cleaned code >>>")
    print(cleaned)
    print("detected lang >>>", detect_language(cleaned))

    verdict = validate(cleaned, exec_simple=True)
    print("ok/stage >>>", verdict.ok, "/", verdict.stage)
    print("errors >>>", verdict.errors)
    print("warnings >>>", verdict.warnings)
    print("summary >>>", summarize_validation(verdict))

    broken = validate("def broken(:\n    pass")
    print("broken summary >>>", summarize_validation(broken))
