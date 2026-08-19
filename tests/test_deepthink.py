"""Tests for deepthink.py — offline, fast, deterministic."""

import os
import sys
import time
import unittest.mock as mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deepthink  # noqa: E402


# --------------------------------------------------------------------------
# Word problems — running totals
# --------------------------------------------------------------------------

def test_running_total_chain():
    reply = deepthink.answer(
        None, "i had 50 dollars, spent 12 on lunch, then earned 8 back")
    assert reply is not None
    assert "Step 1" in reply and "Step 2" in reply
    assert "=> Final amount: 46" in reply


def test_running_total_bought_for():
    reply = deepthink.answer(None, "i had 100, bought a book for 20")
    assert reply is not None
    assert "Final amount: 80" in reply


def test_running_total_verification_failure_returns_none():
    with mock.patch.object(deepthink, "_running_total_reply",
                           wraps=deepthink._running_total_reply):
        # Force the internal forward computation to lie via Fraction monkeypatch
        real_fraction = deepthink.Fraction

        class FlakyFraction(real_fraction):
            _calls = {"n": 0}

            def __new__(cls, *a, **kw):
                return super().__new__(real_fraction, *a, **kw)

        # Simpler seam: patch operator.add used inside module to misbehave once
        calls = {"n": 0}
        real_add = deepthink.operator.add

        def flaky_add(x, y):
            calls["n"] += 1
            result = real_add(x, y)
            if calls["n"] == 1:
                return result + 7  # poison first fold step
            return result

        with mock.patch.object(deepthink.operator, "add", flaky_add):
            assert deepthink.answer(
                None, "i had 50 dollars, spent 12, then earned 8") is None


def test_no_keywords_two_numbers_none():
    assert deepthink.answer(None, "there are 3 apples and 4 oranges listed "
                                  "in the pantry inventory sheet") is None


def test_fewer_than_two_numbers_none():
    assert deepthink.answer(None, "what is 5 plus") is None


def test_ambiguous_signs_decline():
    # numbers + keyword but no resolvable signs / start marker
    assert deepthink.answer(None,
                            "12 45 times reported today total") is None


# --------------------------------------------------------------------------
# Word problems — rates
# --------------------------------------------------------------------------

def test_rate_unit_cost():
    reply = deepthink.answer(None, "5 books cost 45 dollars in total")
    assert reply is not None
    assert "9" in reply


def test_rate_unit_cost_with_quantity():
    reply = deepthink.answer(None, "5 books cost 45 dollars, how much for 3")
    assert reply is not None
    assert "27" in reply


def test_share_among():
    reply = deepthink.answer(None, "share 90 among 6 people")
    assert reply is not None
    assert "15" in reply


def test_each_multiply():
    reply = deepthink.answer(None, "tickets cost 12 each for 5 people")
    assert reply is not None
    assert "60" in reply


# --------------------------------------------------------------------------
# Word problems — transforms
# --------------------------------------------------------------------------

def test_transform_double_add():
    reply = deepthink.answer(None, "double 6 then add 5")
    assert reply is not None
    assert "17" in reply


def test_transform_half_times():
    reply = deepthink.answer(None, "half of 80 then times 3")
    assert reply is not None
    assert "120" in reply


def test_transform_without_gate_word_none():
    assert deepthink.answer(None, "6 add 5") is None


# --------------------------------------------------------------------------
# Planner
# --------------------------------------------------------------------------

def test_plan_day_has_time_blocks():
    reply = deepthink.answer(None, "plan my day")
    assert reply is not None
    assert deepthink._PLAN_RE.search(reply) or any(
        ch.isdigit() for ch in reply)  # structured rows present
    assert "07:00" in reply or "06:30" in reply


def test_plan_distinct_topics():
    workout = deepthink.answer(None, "plan my workout")
    study = deepthink.answer(None, "plan my study schedule")
    assert workout and study
    assert "bench" in workout.lower() or "push" in workout.lower()
    assert "recall" in study.lower() or "material" in study.lower()
    assert workout != study


def test_plan_unknown_topic_falls_back():
    reply = deepthink.answer(None, "plan my month please")
    assert reply is not None
    assert "Step 1" in reply


# --------------------------------------------------------------------------
# Comparator
# --------------------------------------------------------------------------

def test_compare_known_pair():
    reply = deepthink.answer(None, "python vs javascript")
    assert reply is not None
    assert "Pick Python" in reply and "Pick JavaScript" in reply


def test_compare_difference_between():
    reply = deepthink.answer(None, "difference between sql and nosql")
    assert reply is not None
    assert "SQL" in reply


def test_compare_unknown_pair_honest():
    reply = deepthink.answer(None, "zebras vs giraffes")
    assert reply is not None
    assert "first principles" in reply


def test_compare_same_word_none():
    assert deepthink.answer(None, "python vs python") is None


# --------------------------------------------------------------------------
# Explainer
# --------------------------------------------------------------------------

def test_explain_dns():
    reply = deepthink.answer(None, "how does dns resolution work")
    assert reply is not None
    assert "1." in reply and "TTL" in reply


def test_explain_recursion():
    reply = deepthink.answer(None, "why does recursion work")
    assert reply is not None
    assert "base case" in reply.lower()


def test_explain_unknown_none():
    assert deepthink.answer(None, "why does unicorns work magic") is None


# --------------------------------------------------------------------------
# Router safety & performance
# --------------------------------------------------------------------------

def test_empty_and_whitespace_none():
    assert deepthink.answer(None, "") is None
    assert deepthink.answer(None, "   ") is None


def test_giant_input_none_fast():
    junk = "had 5 spent 3 " * 20000
    start = time.perf_counter()
    assert deepthink.answer(None, junk) is None
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize("seed", range(30))
def test_random_unicode_never_raises(seed):
    import random

    rng = random.Random(seed)
    alphabet = ("abc0189 vs plan double half spent gained ?!#€é漢字"
                "\U0001f600\t\n\x00\x07\\ ' \" ")
    s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
    try:
        deepthink.answer(None, s)  # must not raise
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"answer raised on {s!r}: {exc}")


def test_performance_100_calls():
    prompts = (["i had 50, spent 12, earned 8", "plan my day",
                "python vs javascript", "how does hashing work",
                "no numbers here at all"] * 20)
    start = time.perf_counter()
    for p in prompts:
        deepthink.answer(None, p)
    assert time.perf_counter() - start < 1.5
