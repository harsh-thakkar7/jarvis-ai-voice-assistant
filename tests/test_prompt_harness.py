"""Tests for prompt_harness: message assembly, intent routing, cleaning."""

import pytest

import prompt_harness
from prompt_harness import (PROMPT_CONTRACTS, build_messages, classify_intent,
                            clean_reply, selftest, wrap_code_prompt,
                            wrap_website_prompt)


def test_selftest_all_checks_pass():
    ok, report = selftest()
    assert ok, report


def test_build_messages_embeds_today_date():
    sys_txt = build_messages("hello")[0]["content"]
    assert "Today is" in sys_txt
    assert "not sure" in sys_txt


def test_build_messages_appends_persona_extra():
    sys_txt = build_messages("hello", persona_extra="User is testing.")[0]["content"]
    assert "User is testing." in sys_txt


def test_build_messages_code_intent_uses_full_harness_contract():
    sys_txt = build_messages("write a python function to sort a list")[0]["content"]
    assert "first line must be code" in sys_txt
    assert "Never truncate" in sys_txt
    no_code = build_messages("what is a black hole")[0]["content"]
    assert "first line must be code" not in no_code


def test_build_messages_context_block():
    m = build_messages("hello", context={
        "frontmost_app": "Safari",
        "ai_mode": "code_gen",
        "recent_commands": ["open safari", "play music"],
        "time": "12:00",
        "ignored_key": "nope",
    })
    sys_txt = m[0]["content"]
    assert "Frontmost app: Safari" in sys_txt
    assert "Recent commands: open safari; play music" in sys_txt
    assert "ignored_key" not in sys_txt


def test_build_messages_never_raises_on_garbage():
    for args in ((None,), (123,), ("x", [None, 7, "junk"])):
        m = build_messages(args[0], history=args[1] if len(args) > 1 else None)
        assert m and m[0]["role"] == "system"


def test_classify_intent_routing():
    cases = {
        "write a python function to sort a list": "code",
        "translate hello into French": "translate",
        "summarize this article for me": "summarize",
        "open chrome": "command",
        "hi": "smalltalk",
        "what is a black hole": "explain",
        "Is Paris the capital of France?": "question",
    }
    for text, want in cases.items():
        assert classify_intent(text) == want, text
    assert classify_intent("") == "question"
    assert classify_intent(None) == "question"


def test_clean_reply_strips_fences_and_chatter():
    assert clean_reply("```python\nx = 1\n```\nLet me know if you need more.",
                       intent="code") == "x = 1"
    assert clean_reply("Certainly, sir! Here is the summary:\n\nSome text.\n"
                       "I hope this helps.") == "Some text."
    assert clean_reply(None) == ""
    assert clean_reply(42) == "42"


def test_wrap_code_prompt_contract():
    sys_c, user_p = wrap_code_prompt("a snake game", "Python")
    assert "Output ONLY the requested code" in sys_c
    assert "first line must be code" in sys_c
    assert "Python" in user_p and "snake game" in user_p


def test_wrap_website_prompt_structure():
    for kind in ("web", "app"):
        p = wrap_website_prompt("a portfolio for a photographer", kind)
        for section in ("Layout", "Interactions", "Styling",
                        "Responsiveness", "Quality bar"):
            assert section in p, kind
        assert p.strip().splitlines()[-1].startswith("Spec:"), kind
    assert "HTML" in wrap_website_prompt("x", "web")
    assert "Kotlin" in wrap_website_prompt("x", "app")


def test_module_exports_expected_surface():
    for attr in ("build_messages", "classify_intent", "clean_reply",
                 "wrap_code_prompt", "wrap_website_prompt", "selftest"):
        assert hasattr(prompt_harness, attr)