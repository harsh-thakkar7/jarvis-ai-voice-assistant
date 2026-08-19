"""Tests for journal_brain.py — offline; clock frozen, storage in tmp_path."""

import datetime as dt
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import journal_brain as jb  # noqa: E402

FIXED_TODAY = dt.date(2026, 8, 23)


def day(n: int) -> str:
    return (FIXED_TODAY + dt.timedelta(days=n)).isoformat()


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


# ==========================================================================
# Fixtures / helpers
# ==========================================================================

@pytest.fixture()
def brain():
    b = RecorderBrain()
    jb.register(b)
    return b


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Redirect JOURNAL_FILE into tmp_path and freeze the clock."""
    jf = tmp_path / "jarvis_journal.json"
    monkeypatch.setattr(jb, "JOURNAL_FILE", str(jf))
    clock = {"day": FIXED_TODAY}
    monkeypatch.setattr(jb, "_today", lambda: clock["day"])

    def travel(days: int) -> None:
        clock["day"] = clock["day"] + dt.timedelta(days=days)

    return {"tmp": tmp_path, "jf": jf, "travel": travel}


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return name, ctx, execute(DummyApp(), ctx)


def read_state():
    with open(jb.JOURNAL_FILE, encoding="utf-8") as fh:
        return json.load(fh)


# ==========================================================================
# Registration
# ==========================================================================

def test_registers_exactly_the_six_journal_skills(brain):
    expected = {"jr_note", "jr_today", "jr_search",
                "jr_learn", "jr_review", "jr_forget"}
    assert set(brain.skills) == expected
    assert len(brain.skills) == 6


def test_all_skills_register_with_default_priority(brain):
    assert all(prio is False for _d, _e, prio in brain.skills.values())


def test_skill_names_follow_jr_prefix_convention(brain):
    assert all(name.startswith("jr_") for name in brain.skills)


# ==========================================================================
# Detector discipline: noise passes through untouched
# ==========================================================================

NOISE_COMMANDS = [
    "what time is it",
    "tell me a joke",
    "joke",
    "flip a coin",
]


@pytest.mark.parametrize("cmd", NOISE_COMMANDS)
def test_noise_detector_returns_none_for_every_skill(cmd):
    for name, detect, _execute, _prio in jb.SKILLS:
        assert detect(cmd) is None, f"{name} wrongly fired on {cmd!r}"


@pytest.mark.parametrize("cmd", [
    "note to self water the ferns",
    "what did i note today",
    "my journal today",
    "search my notes for ferns",
    "teach me fermat: little theorem guy",
    "learn fermat means little theorem guy",
    "review session",
    "spaced repetition review",
    "forget term fermat",
    "delete note about ferns",
])
def test_each_canonical_command_maps_to_exactly_one_skill(brain, cmd):
    hits = [name for name, (detect, _e, _p) in brain.skills.items()
            if detect(cmd) is not None]
    assert len(hits) == 1, f"{cmd!r} matched {hits}"
    assert hits[0].startswith("jr_")


def test_today_phrases_do_not_leak_into_note_detector(brain):
    for cmd in ("my journal today", "what did i note today",
                "search my notes for journal entries",
                "forget term journal",
                "learn journaling means daily notes"):
        assert brain.skills["jr_note"][0](cmd) is None, cmd


# ==========================================================================
# Notes: append / today / search roundtrip
# ==========================================================================

def test_note_then_today_roundtrip(env, brain):
    run(brain, "jr_note", "note to self buy milk")
    run(brain, "jr_note", "journal team sync at 3pm")
    state = read_state()
    assert [n["text"] for n in state["notes"]] == [
        "buy milk", "team sync at 3pm"]
    assert all(n["ts"] == day(0) for n in state["notes"])
    _, _, reply = run(brain, "jr_today", "what did i note today")
    assert "buy milk" in reply and "team sync at 3pm" in reply
    assert "\n  1. " in reply and "\n  2. " in reply
    _, _, reply_alt = run(brain, "jr_today", "my journal today")
    assert "team sync" in reply_alt


def test_today_with_no_entries_is_polite_and_persona_safe(env, brain):
    _, _, reply = run(brain, "jr_today", "what did i note today")
    assert "today" in reply.lower()
    assert reply.rstrip().endswith("sir.")


def test_search_is_case_insensitive_and_reports_dates(env, brain):
    run(brain, "jr_note", "note to self Buy MILK tomorrow")
    run(brain, "jr_note", "journal walk the dog")
    _, _, reply = run(brain, "jr_search", "search my notes for milk")
    assert "Buy MILK tomorrow" in reply
    assert "[" + day(0) + "]" in reply
    assert "walk the dog" not in reply
    _, _, miss = run(brain, "jr_search", "search my notes for zeppelin")
    assert "No notes match" in miss
    assert miss.endswith("sir.")


def test_search_returns_at_most_eight_hits(env, brain):
    for i in range(10):
        run(brain, "jr_note", f"note to self needle item {i}")
    _, _, reply = run(brain, "jr_search", "search my notes for NEEDLE")
    assert reply.count("[2026-08-23]") == jb.SEARCH_LIMIT == 8
    assert "Found 10" in reply
    assert "needle item 9" in reply
    assert "needle item 0" not in reply  # newest-first, capped at eight


def test_notes_are_stored_at_the_monkeypatched_journal_file(env, brain):
    run(brain, "jr_note", "note to self hello")
    assert env["jf"].exists()
    assert str(env["jf"]).startswith(str(env["tmp"]))


# ==========================================================================
# Learning cards
# ==========================================================================

def test_learn_colon_syntax_stores_box_zero_card_due_today(env, brain):
    _, _, reply = run(
        brain, "jr_learn",
        "teach me Leitner boxes: spaced repetition using five boxes")
    state = read_state()
    card = state["cards"]["Leitner boxes"]
    assert card == {"term": "Leitner boxes",
                    "definition": "spaced repetition using five boxes",
                    "box": 0, "due": day(0)}
    assert "Leitner boxes" in reply and reply.endswith("sir.")


def test_learn_means_syntax_stores_card(env, brain):
    run(brain, "jr_learn", "learn Ebbinghaus means forgetting-curve researcher")
    card = read_state()["cards"]["Ebbinghaus"]
    assert card["definition"] == "forgetting-curve researcher"
    assert card["box"] == 0 and card["due"] == day(0)


def test_relearning_a_term_updates_not_duplicates(env, brain):
    run(brain, "jr_learn", "teach me recursion: a function calling itself")
    run(brain, "jr_learn", "teach me recursion: self-reference done right")
    cards = read_state()["cards"]
    assert list(cards) == ["recursion"]
    assert cards["recursion"]["definition"] == "self-reference done right"


# ==========================================================================
# Review: Leitner interval table [0, 1, 3, 7, 16], boxes clamp at 4
# ==========================================================================

def test_review_advances_box_and_due_exactly_per_interval_table(
        env, brain):
    run(brain, "jr_learn", "teach me recursion: a function calling itself")

    def card():
        return read_state()["cards"]["recursion"]

    assert card()["box"] == 0 and card()["due"] == day(0)

    _, _, r1 = run(brain, "jr_review", "review session")
    assert "recursion -> a function calling itself" in r1
    assert card()["box"] == 1 and card()["due"] == day(0)   # +0 days

    _, _, r2 = run(brain, "jr_review", "review session")
    assert card()["box"] == 2 and card()["due"] == day(1)   # +1 day

    env["travel"](1)
    _, _, r3 = run(brain, "jr_review", "spaced repetition review")
    assert card()["box"] == 3 and card()["due"] == day(4)   # +3 days

    env["travel"](1)
    _, _, idle = run(brain, "jr_review", "review session")
    assert "2026-08-27" in idle          # points at the next due date
    assert card()["box"] == 3 and card()["due"] == day(4)   # untouched

    env["travel"](2)
    _, _, r4 = run(brain, "jr_review", "review session")
    assert card()["box"] == 4 and card()["due"] == day(11)  # +7 days

    env["travel"](7)
    _, _, r5 = run(brain, "jr_review", "review session")
    assert card()["box"] == 4 and card()["due"] == day(27)  # +16 days

    env["travel"](1)
    _, _, late = run(brain, "jr_review", "review session")
    assert "2026-09-19" in late
    assert card()["box"] == 4 and card()["due"] == day(27)


def test_review_sheet_lists_every_due_card_and_advances_each(env, brain):
    run(brain, "jr_learn", "teach me alpha: first letter")
    run(brain, "jr_learn", "teach me beta: second letter")
    _, _, sheet = run(brain, "jr_review", "review session")
    assert "alpha -> first letter" in sheet
    assert "beta -> second letter" in sheet
    cards = read_state()["cards"]
    assert all(c["box"] == 1 and c["due"] == day(0) for c in cards.values())


def test_review_before_any_cards_exists(env, brain):
    _, _, reply = run(brain, "jr_review", "review session")
    assert "no cards yet" in reply.lower()
    assert reply.endswith("sir.")


# ==========================================================================
# Forgetting: term match, phrase deletion, .bak rotation before mutation
# ==========================================================================

def test_forget_term_removes_card_case_insensitively(env, brain):
    run(brain, "jr_learn", "teach me Python GIL: global interpreter lock")
    run(brain, "jr_note", "note to self keep the GIL in mind")
    _, _, reply = run(brain, "jr_forget", "forget term PYTHON gil")
    assert read_state()["cards"] == {}
    assert "Removed 1 card" in reply
    assert "Python GIL" in reply
    assert ".bak" in reply
    assert reply.endswith("sir.")


def test_forget_note_deletes_matching_entries_and_reports_count(env, brain):
    run(brain, "jr_note", "note to self buy oat milk")
    run(brain, "jr_note", "journal call the milkman")
    run(brain, "jr_note", "journal walk the dog")
    _, _, reply = run(brain, "jr_forget", "delete my notes about MILK")
    texts = [n["text"] for n in read_state()["notes"]]
    assert texts == ["walk the dog"]
    assert "Deleted 2 notes" in reply
    assert "milk" in reply.lower()


def test_forget_rotates_bak_before_mutation(env, brain):
    run(brain, "jr_note", "note to self precious memory")
    before = open(jb.JOURNAL_FILE, encoding="utf-8").read()
    run(brain, "jr_forget", "delete note about precious")
    bak = jb.JOURNAL_FILE + ".bak"
    assert os.path.exists(bak)
    assert open(bak, encoding="utf-8").read() == before
    assert read_state()["notes"] == []


def test_forget_unknown_term_still_personas_without_damage(env, brain):
    run(brain, "jr_note", "note to self keep this")
    _, _, reply = run(brain, "jr_forget", "forget term unicorn")
    assert "Removed 0 cards" in reply
    assert len(read_state()["notes"]) == 1
    assert reply.endswith("sir.")


# ==========================================================================
# Storage discipline: 500-entry cap, atomic saves, tmp hygiene
# ==========================================================================

def test_note_cap_keeps_newest_five_hundred(env, brain):
    for i in range(505):
        jb._add_note(f"bulk {i}")
    state = read_state()
    assert len(state["notes"]) == jb.JOURNAL_MAX_NOTES == 500
    assert state["notes"][0]["text"] == "bulk 5"
    assert state["notes"][-1]["text"] == "bulk 504"


def test_saves_are_atomic_and_leave_no_tmp_files_behind(env, brain):
    run(brain, "jr_note", "note to self one")
    run(brain, "jr_learn", "teach me atoms: indivisible")
    run(brain, "jr_review", "review session")
    run(brain, "jr_forget", "delete note about one")
    leftovers = [p.name for p in env["tmp"].iterdir()
                 if p.name.endswith(".tmp")]
    assert leftovers == []
    json.loads(open(jb.JOURNAL_FILE, encoding="utf-8").read())  # valid JSON
    assert os.path.exists(jb.JOURNAL_FILE + ".bak")


def test_corrupt_or_missing_journal_recovers_to_empty_state(env):
    with open(jb.JOURNAL_FILE, "w", encoding="utf-8") as fh:
        fh.write("{not json at all")
    state = jb._load()
    assert state == {"notes": [], "cards": {}}


# ==========================================================================
# Persona safety
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    ("jr_note", "note to self stretch"),
    ("jr_today", "what did i note today"),
    ("jr_search", "search my notes for stretch"),
    ("jr_learn", "teach me zen: attention"),
    ("jr_review", "review session"),
    ("jr_forget", "delete note about nothing"),
])
def test_every_reply_is_persona_safe(env, brain, cmd):
    name, phrase = cmd
    _n, _ctx, reply = run(brain, name, phrase)
    assert reply.rstrip().endswith("sir."), (name, reply)


def test_persona_safe_helper_matches_house_rules():
    assert jb._persona_safe("Done already, sir.") == "Done already, sir."
    assert jb._persona_safe("Ready.") == "Ready, sir."
    assert jb._persona_safe("Which one?") == "Which one, sir?"
