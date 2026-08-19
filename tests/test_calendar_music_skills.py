"""Tests for calendar_music_skills.py — offline; osascript is mocked."""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calendar_music_skills as cms  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {
    "cm_events_today", "cm_create_event", "cm_play_artist",
    "cm_pause", "cm_resume", "cm_now_playing",
}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    cms.register(b)
    return b


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


class FakeOSA:
    """Records every script handed to _run_osascript; replays results."""

    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def __call__(self, script, timeout=15.0):
        self.calls.append(script)
        if self.results:
            return self.results.pop(0)
        return 0, ""


@pytest.fixture()
def fake_osa(monkeypatch):
    def attach(results=None):
        fake = FakeOSA(results)
        monkeypatch.setattr(cms, "_run_osascript", fake)
        return fake
    return attach


# ==========================================================================
# Registration
# ==========================================================================

def test_registers_all_six_skills(brain):
    assert EXPECTED_SKILLS <= set(brain.skills)
    assert set(brain.skills) == EXPECTED_SKILLS


# ==========================================================================
# AppleScript escaping seam
# ==========================================================================

def test_osa_quote_escapes_quotes_and_backslashes():
    assert cms._osa_quote('He said "hi"') == '"He said \\"hi\\""'
    assert cms._osa_quote("back\\slash") == '"back\\\\slash"'
    assert cms._osa_quote("plain") == '"plain"'


# ==========================================================================
# Date parser unit cases
# ==========================================================================

NOW = datetime(2026, 8, 23, 12, 0)  # a Sunday


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: ARG003
        return cls(2026, 8, 23, 12, 0)


@pytest.fixture()
def frozen_now(monkeypatch):
    """Pin datetime.now() inside the module so parsed dates are stable."""
    monkeypatch.setattr(cms, "datetime", _FrozenDatetime)
    return NOW


def test_parse_tomorrow_at_3pm():
    when, rel = cms._parse_when("tomorrow", " at 3pm", now=NOW)
    assert (when.year, when.month, when.day) == (2026, 8, 24)
    assert when.hour == 15 and when.minute == 0
    assert rel == "tomorrow"


def test_parse_friday_is_upcoming_friday():
    when, rel = cms._parse_when("on Friday", "", now=NOW)
    assert when.weekday() == 4
    assert when.date().isoformat() == "2026-08-28"
    assert rel == "on Friday"


def test_parse_today_930am():
    when, rel = cms._parse_when("today", " at 9:30 am", now=NOW)
    assert when.hour == 9 and when.minute == 30
    assert (when.year, when.month, when.day) == (2026, 8, 23)
    assert rel == "today"


def test_parse_defaults_and_bounds():
    # no time given -> default morning hour; pm folds past noon
    when, _ = cms._parse_when("today", "", now=NOW)
    assert when.hour == cms.DEFAULT_EVENT_HOUR
    when, _ = cms._parse_when("tomorrow", " at 11:45 pm", now=NOW)
    assert (when.hour, when.minute) == (23, 45)


# ==========================================================================
# Part A - calendar events today
# ==========================================================================

def test_events_today_lists_time_and_summary(brain, fake_osa):
    fake = fake_osa([(0, "9:00 AM | Standup\n11:30 AM | Lunch with Bruce")])
    reply = run(brain, "cm_events_today", "what's on my calendar today")
    assert "Calendar" in fake.calls[0]
    assert "Standup" in reply and "Lunch with Bruce" in reply
    assert "2 event(s)" in reply
    assert reply.rstrip().endswith(", sir.")


def test_events_today_clear_day(brain, fake_osa):
    fake_osa([(0, "")])
    reply = run(brain, "cm_events_today", "my schedule")
    assert "Nothing" in reply
    assert reply.endswith(", sir.")


def test_events_today_failure_persona(brain, fake_osa):
    fake_osa([(1, "execution error: Not authorized")])
    reply = run(brain, "cm_events_today", "calendar today")
    assert "sir" in reply and "Not authorized" in reply


# ==========================================================================
# Part A - create event
# ==========================================================================

def test_create_event_embeds_escaped_title_and_date(brain, fake_osa,
                                                    frozen_now):
    fake = fake_osa([(0, "created")])
    cmd = 'add event Team standup \\"Q4\\" review tomorrow at 3pm'
    cmd = cmd.replace('\\"', '"')  # plain quotes in the spoken command
    reply = run(brain, "cm_create_event", cmd)

    script = fake.calls[0]
    assert 'Team standup \\"Q4\\" review' in script   # escaped for AppleScript
    assert "2026" in script and ", 8, 24," in script  # locale-proof date parts
    assert "15" in script                             # 3pm -> hour 15
    assert 'summary:"Team' in script
    assert "Team standup" in reply and "tomorrow" in reply
    assert reply.endswith(", sir.")


def test_create_event_on_friday_at_time(brain, fake_osa, frozen_now):
    fake = fake_osa([(0, "created")])
    reply = run(brain, "cm_create_event",
                "schedule demo with the vendor on Friday at 2:15 pm")
    script = fake.calls[0]
    assert "demo with the vendor" in script
    assert ", 8, 28," in script and ", 14, 15)" in script
    assert "Friday" in reply and reply.endswith(", sir.")


def test_create_event_requires_date_phrase(brain):
    assert brain.skills["cm_create_event"][0]("add event buy milk") is None
    assert brain.skills["cm_create_event"][0](
        "schedule nothing that makes sense here") is None


# ==========================================================================
# Part B - transport controls map to correct verbs
# ==========================================================================

def test_pause_maps_to_pause_verb(brain, fake_osa):
    fake = fake_osa([(0, "")])
    reply = run(brain, "cm_pause", "pause music")
    assert fake.calls[0] == 'tell application "Spotify"\npause\nend tell'
    assert "paused" in reply.lower() and reply.endswith(", sir.")


def test_next_track_maps_to_next_track_verb(brain, fake_osa):
    fake = fake_osa([(0, "")])
    run(brain, "cm_pause", "next track")
    assert (fake.calls[0] ==
            'tell application "Spotify"\nnext track\nend tell')


def test_previous_track_maps_to_previous_track_verb(brain, fake_osa):
    fake = fake_osa([(0, "")])
    run(brain, "cm_pause", "previous track")
    assert (fake.calls[0] ==
            'tell application "Spotify"\nprevious track\nend tell')


def test_resume_maps_to_play_verb(brain, fake_osa):
    fake = fake_osa([(0, "")])
    reply = run(brain, "cm_resume", "resume music")
    assert fake.calls[0] == 'tell application "Spotify"\nplay\nend tell'
    assert "Resuming" in reply and reply.endswith(", sir.")


# ==========================================================================
# Part B - play artist on Spotify
# ==========================================================================

def test_play_artist_embeds_escaped_artist(brain, fake_osa):
    fake = fake_osa([(0, "played")])
    reply = run(brain, "cm_play_artist", 'play Simon "Ghost" Riley on spotify')
    script = fake.calls[0]
    assert 'Simon \\"Ghost\\" Riley' in script
    assert "Simon" in reply and "Spotify" in reply
    assert reply.endswith(", sir.")


def test_play_artist_not_running_suggests_spotify(brain, fake_osa):
    fake_osa([(1, "Spotify got an error: Application can't be seen right now. "
                 "(-1728)")])
    reply = run(brain, "cm_play_artist", "play radiohead on spotify")
    assert "isn't running" in reply
    assert "Spotify" in reply and reply.endswith(", sir.")


# ==========================================================================
# Part B - Music.app fallback + now playing
# ==========================================================================

NOT_RUNNING = (1, "Spotify got an error: Application can't be seen right now.")


def test_pause_falls_back_to_music_app(brain, fake_osa):
    fake = fake_osa([NOT_RUNNING, (0, "")])
    reply = run(brain, "cm_pause", "pause music")
    assert len(fake.calls) == 2
    assert 'application "Music"' in fake.calls[1]
    assert 'application "Spotify"' in fake.calls[0]
    assert "Music.app" in reply and reply.endswith(", sir.")


def test_both_apps_down_notes_spotify(brain, fake_osa):
    fake = fake_osa([NOT_RUNNING,
                     (1, "Music got an error: The application Music is not "
                         "running.")])
    reply = run(brain, "cm_pause", "pause music")
    assert len(fake.calls) == 2
    assert "suggest launching Spotify" in reply
    assert reply.endswith(", sir.")


def test_now_playing_parses_song_artist(brain, fake_osa):
    fake = fake_osa([(0, "Supermassive Black Hole - Muse")])
    reply = run(brain, "cm_now_playing", "what song is playing?")
    assert 'tell application "Spotify"' in fake.calls[0]
    assert "Supermassive Black Hole" in reply and "Muse" in reply
    assert reply.endswith(", sir.")


def test_parse_now_playing_unit():
    assert cms._parse_now_playing("Song - Artist") == ("Song", "Artist")
    assert cms._parse_now_playing("A - B - C") == ("A", "B - C")


def test_now_playing_stopped_state(brain, fake_osa):
    fake_osa([(0, "silence")])
    reply = run(brain, "cm_now_playing", "now playing")
    assert "silence" in reply.lower()


def test_now_playing_falls_back_to_music_app(brain, fake_osa):
    fake = fake_osa([NOT_RUNNING, (0, "Yesterday - The Beatles")])
    reply = run(brain, "cm_now_playing", "what's playing")
    assert 'application "Music"' in fake.calls[1]
    assert "Yesterday" in reply and "The Beatles" in reply
    assert "(via Music.app)" in reply


# ==========================================================================
# Negative detection + guards
# ==========================================================================

@pytest.mark.parametrize("cmd", ["open youtube", "tell me a joke"])
def test_detectors_ignore_unrelated_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_non_darwin_guard_disables_detectors(brain, monkeypatch):
    monkeypatch.setattr(cms, "IS_DARWIN", False)
    probes = ["what's on my calendar today", "add event lunch tomorrow at 3pm",
              "play muse on spotify", "pause music"]
    for name, (detect, _exec, _prio) in brain.skills.items():
        for cmd in probes:
            assert detect(cmd) is None, f"{name} fired while not Darwin"


def test_executor_wraps_crashes_in_persona(brain, monkeypatch):
    def boom(script, timeout=15.0):
        raise RuntimeError("cable pulled")

    monkeypatch.setattr(cms, "_run_osascript", boom)
    reply = run(brain, "cm_now_playing", "what song is playing")
    assert reply.endswith(", sir.") and "misfired" in reply
