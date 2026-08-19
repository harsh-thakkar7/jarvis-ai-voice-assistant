"""Tests for briefing_brain.py — offline; seams (_run_osascript,
_fetch_weather, _now) are stubbed."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import briefing_brain as bb  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {"br_briefing", "br_day_digest"}

FIXED_NOW = datetime(2026, 8, 24, 9, 41)      # a Monday morning
WEATHER_OK = ("Right now in Malibu, it is 21 degrees, feels like 20, "
              "clear, humidity 40 percent.")
EVENT_ROWS = "9:30 AM | Standup\n2:00 PM | Design review"


@pytest.fixture()
def brain():
    b = RecorderBrain()
    bb.register(b)
    return b


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(bb, "_now", lambda: FIXED_NOW)


@pytest.fixture(autouse=True)
def quiet_osascript(monkeypatch):
    """Unit tests never shell out to real osascript; individual tests may
    re-stub with their own fake afterwards."""
    monkeypatch.setattr(
        bb, "_run_osascript",
        lambda script, timeout=15.0: (0, ""))


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


@pytest.fixture()
def full_env(monkeypatch):
    """Every ingredient healthy; records osascript call order."""
    calls = []

    def fake_osa(script, timeout=15.0):
        calls.append(script)
        if 'tell application "Calendar"' in script:
            return 0, EVENT_ROWS
        return 0, "4"

    monkeypatch.setattr(bb, "_run_osascript", fake_osa)
    monkeypatch.setattr(bb, "_fetch_weather", lambda loc: WEATHER_OK)
    return calls


@pytest.fixture()
def weather_calls(monkeypatch):
    seen = []

    def fake_fetch(loc):
        seen.append(loc)
        return WEATHER_OK

    monkeypatch.setattr(bb, "_fetch_weather", fake_fetch)
    return seen


# ==========================================================================
# Registration wiring
# ==========================================================================

def test_registers_both_briefing_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


def test_skills_are_priority_and_wrapped(brain):
    for name in EXPECTED_SKILLS:
        detect, execute, priority = brain.skills[name]
        assert callable(detect) and callable(execute)
        assert priority is True                    # outranks generic skills
        assert execute.__name__.startswith("safe_")


def test_both_detectors_share_one_executor(brain):
    _d1, ex1, _p1 = brain.skills["br_briefing"]
    _d2, ex2, _p2 = brain.skills["br_day_digest"]
    assert ex1 is not None and ex2 is not None     # both wired through _wrap


# ==========================================================================
# Detection — positives
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "good morning jarvis",
    "brief me",
    "daily briefing",
    "give me my morning briefing",
    "jarvis give me my daily briefing please",
    "start my day",
    "hey catch me up",
])
def test_br_briefing_detects_variants(brain, cmd):
    assert brain.skills["br_briefing"][0](cmd) is not None


@pytest.mark.parametrize("cmd", [
    "summarize my day",
    "summarise my day",
    "what's my agenda",
    "whats my agenda today",
    "how's my day looking",
])
def test_br_day_digest_detects_variants(brain, cmd):
    assert brain.skills["br_day_digest"][0](cmd) is not None


# ==========================================================================
# Detection — negatives / collisions with sibling skill packs
# ==========================================================================

COLLISIONS = [
    "what's the weather",
    "weather in malibu",
    "what's on my calendar",
    "check my email",
    "any new mail",
    "show me the news",
    "remind me to stretch",
    "read email 2",
    "tell me a joke",
    "what time is it",
    "add event lunch tomorrow at noon",
    "summarize this text about space",
]


@pytest.mark.parametrize("cmd", COLLISIONS)
def test_no_detector_fires_on_collisions(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_a_brief_essay_is_not_a_briefing(brain):
    assert brain.skills["br_briefing"][0]("write a brief essay about rome") \
        is None


# ==========================================================================
# Spoken location extraction
# ==========================================================================

def test_location_extracted_from_cmd(weather_calls):
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_briefing", "give me my briefing in malibu")
    assert weather_calls == ["Malibu"]


def test_location_for_phrase_and_title_case(weather_calls):
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_day_digest", "summarize my day for new york")
    assert weather_calls == ["New York"]


def test_temporal_words_never_become_cities(weather_calls, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "")
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_day_digest", "what's my agenda for today")
    assert weather_calls == []                     # no city -> no weather try


def test_default_location_used_when_none_spoken(weather_calls, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_briefing", "good morning jarvis")
    assert weather_calls == ["Malibu"]             # mirrors main's fallback


def test_empty_default_location_skips_weather_seam(weather_calls, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "")
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_briefing", "good morning jarvis")
    assert weather_calls == []


# ==========================================================================
# Full-success composition and ordering
# ==========================================================================

def test_full_success_order_and_content(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    reply = run(brain, "br_briefing", "good morning jarvis")
    # Speaking order: date -> weather -> calendar -> mail -> closer.
    order = ["Monday", "Right now in Malibu", "Standup", "unread",
             "lay of the land"]
    positions = [reply.index(part) for part in order]
    assert positions == sorted(positions)
    assert "Good morning" in reply                 # 9:41 fixed clock
    assert "9:41 AM" in reply
    assert "Design review" in reply
    assert reply.rstrip().endswith(", sir.")


def test_full_success_hits_calendar_then_mail(full_env):
    b = RecorderBrain()
    bb.register(b)
    run(b, "br_briefing", "brief me")
    assert len(full_env) == 2                      # one script per app
    assert 'tell application "Calendar"' in full_env[0]
    assert 'tell application "Mail"' in full_env[1]
    assert "read status is false" in full_env[1]   # unread-only count


def test_reply_stays_brief_in_full_success(brain, full_env):
    reply = run(brain, "br_briefing", "brief me")
    sentences = [s for s in reply.replace("; ", ". ").split(". ") if s.strip()]
    assert len(sentences) <= 5                     # spoken-output budget


def test_calendar_capped_at_three_events(brain, monkeypatch):
    def busy(script, timeout=15.0):
        if 'tell application "Calendar"' in script:
            rows = "\n".join(
                ["9:00 AM | Thing 0", "10:00 AM | Thing 1",
                 "11:00 AM | Thing 2", "12:00 PM | Thing 3",
                 "1:00 PM | Thing 4"])
            return 0, rows
        return 0, "4"
    monkeypatch.setattr(bb, "_run_osascript", busy)
    reply = run(brain, "br_briefing", "brief me")
    assert "Thing 2" in reply and "Thing 3" not in reply   # capped at three
    assert "plus 2 more" in reply


# ==========================================================================
# Degradation — each ingredient fails independently
# ==========================================================================

def test_weather_offline_skips_only_weather(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    monkeypatch.setattr(bb, "_fetch_weather", lambda loc: None)
    reply = run(brain, "br_briefing", "brief me")
    assert "degrees" not in reply
    assert "Monday" in reply and "Standup" in reply and "unread" in reply
    assert reply.endswith(", sir.")


def test_calendar_failure_skips_only_events(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    def dead_calendar(script, timeout=15.0):
        if 'tell application "Calendar"' in script:
            return 1, "execution error: Calendar got an error. (-600)"
        return 0, "4"
    monkeypatch.setattr(bb, "_run_osascript", dead_calendar)
    reply = run(brain, "br_briefing", "brief me")
    assert "Standup" not in reply and "event(s)" not in reply
    assert "degrees" in reply and "4 unread" in reply
    assert reply.endswith(", sir.")


def test_mail_failure_skips_only_mail(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    def dead_mail(script, timeout=15.0):
        if 'tell application "Mail"' in script:
            return 1, "Mail got an error: Connection is invalid. (-600)"
        return 0, EVENT_ROWS
    monkeypatch.setattr(bb, "_run_osascript", dead_mail)
    reply = run(brain, "br_briefing", "brief me")
    assert "unread" not in reply
    assert "degrees" in reply and "Standup" in reply
    assert reply.endswith(", sir.")


def test_empty_calendar_spoken_as_clear_day(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "DEFAULT_LOCATION", "Malibu")
    def empty_calendar(script, timeout=15.0):
        if 'tell application "Calendar"' in script:
            return 0, ""
        return 0, "4"
    monkeypatch.setattr(bb, "_run_osascript", empty_calendar)
    reply = run(brain, "br_briefing", "brief me")
    assert "wide open" in reply.lower()
    assert "degrees" in reply and "4 unread" in reply


def test_zero_unread_spoken_as_spotless(brain, full_env, monkeypatch):
    def zero_mail(script, timeout=15.0):
        if 'tell application "Mail"' in script:
            return 0, "0"
        return 0, EVENT_ROWS
    monkeypatch.setattr(bb, "_run_osascript", zero_mail)
    reply = run(brain, "br_briefing", "brief me")
    assert "spotless" in reply.lower() and "unread message" not in reply


def test_garbled_mail_count_fails_soft(brain, full_env, monkeypatch):
    def weird_mail(script, timeout=15.0):
        if 'tell application "Mail"' in script:
            return 0, "banana"
        return 0, EVENT_ROWS
    monkeypatch.setattr(bb, "_run_osascript", weird_mail)
    reply = run(brain, "br_briefing", "brief me")
    assert "unread" not in reply and "Standup" in reply


def test_seams_raising_never_sinks_executor(brain, full_env, monkeypatch):
    def explosive(script, timeout=15.0):
        raise RuntimeError("cable pulled")
    monkeypatch.setattr(bb, "_run_osascript", explosive)
    monkeypatch.setattr(bb, "_fetch_weather",
                        lambda loc: (_ for _ in ()).throw(RuntimeError("x")))
    reply = run(brain, "br_briefing", "brief me")   # must NOT raise
    assert "Monday" in reply and reply.endswith(", sir.")


# ==========================================================================
# Total failure — offline path
# ==========================================================================

def test_total_failure_offline_line(brain, full_env, monkeypatch):
    monkeypatch.setattr(bb, "_fetch_weather", lambda loc: None)

    def dead(script, timeout=15.0):
        return 1, "everything is sad"
    monkeypatch.setattr(bb, "_run_osascript", dead)

    def broken_clock():
        raise OSError("clock unavailable")
    monkeypatch.setattr(bb, "_now", broken_clock)

    reply = run(brain, "br_briefing", "brief me")
    assert "Monday" not in reply and "degrees" not in reply
    assert len(reply) < 160                         # short offline line
    assert reply.endswith(", sir.")


def test_offline_line_via_collect_parts_stub(brain, monkeypatch):
    monkeypatch.setattr(bb, "_collect_parts", lambda loc: [])
    reply = run(brain, "br_day_digest", "summarize my day")
    assert reply == bb._OFFLINE_LINE
    assert reply.endswith(", sir.")


# ==========================================================================
# _wrap containment + guards
# ==========================================================================

def test_wrap_containment_returns_persona_safe_reply(brain, monkeypatch):
    def boom(location):
        raise RuntimeError("composition exploded")

    monkeypatch.setattr(bb, "_collect_parts", boom)
    detect, execute, _prio = brain.skills["br_briefing"]
    reply = execute(DummyApp(), detect("brief me"))
    assert "misfired" in reply and "briefing module" in reply
    assert reply.endswith(", sir.")


def test_non_darwin_guard_disables_detectors(brain, monkeypatch):
    monkeypatch.setattr(bb, "IS_DARWIN", False)
    probes = ["good morning jarvis", "brief me", "daily briefing",
              "summarize my day", "what's my agenda"]
    for name, (detect, _exec, _prio) in brain.skills.items():
        for cmd in probes:
            assert detect(cmd) is None, f"{name} fired while not Darwin"


@pytest.mark.parametrize("cmd", ["what time is it", "play some spotify"])
def test_detectors_ignore_unrelated_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"
