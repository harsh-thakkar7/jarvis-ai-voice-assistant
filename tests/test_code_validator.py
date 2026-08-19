"""Offline tests for the JARVIS code_validator module.

Covers fence/prose extraction, language detection, the Python and
JavaScript validators, the unified dispatch, and the generate-and-verify
loop driven by a fake LLM callable. No network access is required; total
runtime stays well under 30 seconds.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import code_validator as cv

NODE_MISSING = shutil.which("node") is None

GOOD_PY = "value = 21\nprint(value * 2)"


# ---------------------------------------------------------------------------
# Fence / prose extraction
# ---------------------------------------------------------------------------

def test_strip_single_untagged_block():
    assert cv.strip_fences("```\nprint('hi')\n```") == "print('hi')"


def test_strip_lang_tagged_block_case_insensitive():
    text = "```PYTHON\nx = 1\n```"
    assert cv.strip_fences(text) == "x = 1"


def test_multiple_blocks_joined_with_blank_line():
    text = (
        "```python\na = 1\n```\n"
        "some commentary in between\n"
        "```python\nb = 2\n```"
    )
    assert cv.strip_fences(text) == "a = 1\n\nb = 2"


def test_prose_prefix_and_suffix_stripped():
    text = (
        "Here's a snippet:\n"
        "```python\nprint('x')\n```\n"
        "Let me know if you need changes!"
    )
    assert cv.strip_fences(text) == "print('x')"


def test_no_fence_pure_code_untouched():
    code = "def f():\n    return 42"
    assert cv.strip_fences(code) == code


def test_extract_blocks_preserves_order_and_tags():
    text = (
        "```python\nA\n```\nmid\n```\nB\n```\nend\n```Js\nC\n```"
    )
    assert cv.extract_code_blocks(text) == [("python", "A"), ("", "B"), ("js", "C")]


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("py", "python"),
        ("Python3", "python"),
        ("js", "javascript"),
        ("node", "javascript"),
        ("ts", "typescript"),
        ("golang", "go"),
        ("c++", "cpp"),
        ("SQL", "sql"),
        ("bash", "bash"),
        ("klingon", "unknown"),
    ],
)
def test_detect_language_hint_normalization(hint, expected):
    assert cv.detect_language("whatever text", hint=hint) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ('def greet(name):\n    return f"Hi {name}"', "python"),
        ("const add = (a, b) => a + b;", "javascript"),
        ("<!DOCTYPE html>\n<html><body></body></html>", "html"),
        ("SELECT id, name FROM users WHERE active = 1;", "sql"),
        ("#!/bin/bash\necho 'hi'", "bash"),
    ],
)
def test_detect_language_sniffing(code, expected):
    assert cv.detect_language(code) == expected


# ---------------------------------------------------------------------------
# validate_python
# ---------------------------------------------------------------------------

def test_validate_python_good_reaches_compile_stage():
    vr = cv.validate_python("def square(x):\n    return x * x\n\nprint(square(4))")
    assert vr.ok
    assert vr.stage == "compile"
    assert vr.errors == []


def test_validate_python_syntax_error_reports_line():
    vr = cv.validate_python("def broken(:\n    pass")
    assert not vr.ok
    assert vr.stage == "ast"
    assert any(err.startswith("line 1:") for err in vr.errors)


def test_validate_python_exec_catches_nameerror():
    vr = cv.validate_python("print(this_is_undefined_xyz)", exec_simple=True)
    assert not vr.ok
    assert vr.stage == "exec"
    assert any("NameError" in err for err in vr.errors)


def test_validate_python_input_guard_skips_exec():
    vr = cv.validate_python("name = input('name: ')\nprint(name)", exec_simple=True)
    assert vr.ok
    assert vr.stage == "compile"
    assert any("stdin" in warning for warning in vr.warnings)


def test_validate_python_infinite_loop_guard_skips_exec():
    vr = cv.validate_python("while True:\n    x = 1\n", exec_simple=True)
    assert vr.ok
    assert any("infinite loop" in warning.lower() for warning in vr.warnings)


def test_validate_python_empty_code_is_no_code_stage():
    vr = cv.validate_python("   \n\t")
    assert not vr.ok
    assert vr.stage == "no-code"
    assert vr.errors == ["empty code"]


# ---------------------------------------------------------------------------
# Unified validate() dispatch
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE_MISSING, reason="node executable not installed")
def test_validate_js_valid_passes_node_check():
    code = "function add(a, b) { return a + b; }\nconsole.log(add(1, 2));"
    vr = cv.validate(code, lang="javascript")
    assert vr.ok
    assert vr.stage == "node-check"
    assert vr.errors == []
    assert vr.warnings == []


@pytest.mark.skipif(NODE_MISSING, reason="node executable not installed")
def test_validate_js_syntax_error_fails():
    vr = cv.validate("function broken( { return 1; }", lang="js")
    assert not vr.ok
    assert vr.stage == "node-check"
    assert vr.errors


def test_validate_unknown_lang_warning_path():
    vr = cv.validate("just some random prose words here", lang="klingon")
    assert vr.ok
    assert vr.stage == "unknown-lang"
    assert any("unknown language" in warning for warning in vr.warnings)


def test_validate_cpp_unbalanced_brace_warning_only():
    code = '#include <iostream>\nint main() {\n    std::cout << "hi";\n    return 0;'
    vr = cv.validate(code, lang="cpp")
    assert vr.ok
    assert any("unbalanced" in warning.lower() for warning in vr.warnings)


def test_validate_typescript_gets_js_level_warning():
    vr = cv.validate("const n = 41;\nconsole.log(n + 1);", lang="typescript")
    assert vr.ok
    assert any("TypeScript" in warning for warning in vr.warnings)


# ---------------------------------------------------------------------------
# generate_validated with a fake LLM
# ---------------------------------------------------------------------------

class FakeLLM:
    """Scripted LLM double recording every prompt it receives."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) <= len(self.replies):
            return self.replies[len(self.prompts) - 1]
        return None


def test_generate_first_reply_ok_single_call():
    llm = FakeLLM([f"```python\n{GOOD_PY}\n```"])
    code, vr = cv.generate_validated(llm, "make code", lang_hint="python")
    assert vr.ok
    assert code == GOOD_PY
    assert len(llm.prompts) == 1


def test_generate_retry_prompt_contains_failure_report():
    bad = f"```python\ndef oops(:\n    return 1\n```"
    llm = FakeLLM([bad, f"```python\n{GOOD_PY}\n```"])
    code, vr = cv.generate_validated(llm, "make code", lang_hint="python")
    assert len(llm.prompts) == 2
    assert "FAILED validation" in llm.prompts[1]
    assert vr.ok
    assert code == GOOD_PY


def test_generate_llm_unavailable_returns_no_code_failure():
    llm = FakeLLM([])
    code, vr = cv.generate_validated(llm, "prompt")
    assert code == ""
    assert not vr.ok
    assert "language model unavailable" in vr.errors
    assert vr.stage == "no-code"


def test_generate_all_bad_returns_best_candidate():
    one_error = "x = (1 +"
    two_part = "y = (2 +\nz = ]"
    llm = FakeLLM(
        [f"```python\n{one_error}\n```", f"```python\n{two_part}\n```"]
    )
    code, vr = cv.generate_validated(llm, "prompt", lang_hint="python")
    assert not vr.ok
    assert code == one_error
