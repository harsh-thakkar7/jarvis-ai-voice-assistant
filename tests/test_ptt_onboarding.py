# -*- coding: utf-8 -*-
"""Tests for ptt_onboarding.py — offline; prefs in tmp_path, probes faked."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hotkey_ptt as hk  # noqa: E402
import ptt_onboarding as pt  # noqa: E402

EXPECTED_URL = (
    "x-apple.systempreferences:com.apple.preference.security?"
    "Privacy_Accessibility"
)


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
def env(tmp_path, monkeypatch):
    """Redirect prefs into tmp_path and fake every OS probe."""
    pf = tmp_path / "jarvis_ptt_prefs.json"
    monkeypatch.setattr(pt, "PREFS_FILE", str(pf))
    calls = {"open_url": []}

    def fake_open_url(argv):
        calls["open_url"].append(list(argv))
        return calls.get("rc", 0)

    monkeypatch.setattr(pt, "_open_url", fake_open_url)
    monkeypatch.setattr(hk.GlobalPTT, "is_trusted", staticmethod(lambda: True))
    return {"tmp": tmp_path, "pf": pf, "calls": calls}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    pt.register(b)
    return b


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return name, ctx, execute(DummyApp(), ctx)


def read_prefs():
    with open(pt.PREFS_FILE, encoding="utf-8") as fh:
        return json.load(fh)


def set_probes(monkeypatch, have=True, trusted=True):
    monkeypatch.setattr(hk, "HAVE_PYNPUT", have)
    if have:

        def probe():
            if trusted is None:
                raise RuntimeError("probe exploded")
            return trusted

        monkeypatch.setattr(hk.GlobalPTT, "is_trusted", staticmethod(probe))


# ==========================================================================
# preflight(): the readiness matrix
# ==========================================================================

def test_preflight_ready_when_pynput_and_trusted(env, monkeypatch):
    set_probes(monkeypatch, have=True, trusted=True)
    st = pt.preflight()
    assert st == {"pynput": True, "trusted": True, "ready": True}


def test_preflight_untrusted_blocks_readiness(env, monkeypatch):
    set_probes(monkeypatch, have=True, trusted=False)
    st = pt.preflight()
    assert st == {"pynput": True, "trusted": False, "ready": False}


def test_preflight_missing_pynput_reports_none_trust(env, monkeypatch):
    set_probes(monkeypatch, have=False)

    def must_not_be_called():
        raise AssertionError("is_trusted probed without pynput")

    monkeypatch.setattr(hk.GlobalPTT, "is_trusted", staticmethod(must_not_be_called))
    st = pt.preflight()
    assert st == {"pynput": False, "trusted": None, "ready": False}


def test_preflight_survives_exploding_trust_probe(env, monkeypatch):
    set_probes(monkeypatch, have=True, trusted=None)
    st = pt.preflight()
    assert st["pynput"] is True
    assert st["trusted"] is False
    assert st["ready"] is False


# ==========================================================================
# open_accessibility_settings(): exact deep link
# ==========================================================================

def test_settings_uses_the_exact_accessibility_deep_link(env):
    assert pt.open_accessibility_settings() is True
    assert env["calls"]["open_url"] == [["open", EXPECTED_URL]]


def test_settings_returns_false_on_nonzero_rc(env):
    env["calls"]["rc"] = 73
    assert pt.open_accessibility_settings() is False
    assert env["calls"]["open_url"][0] == ["open", EXPECTED_URL]


def test_real_seam_signature_matches_deep_link_contract(monkeypatch):
    seen = {}

    class FakeProc:
        returncode = 0

    def fake_run(argv, **kw):
        seen["argv"] = list(argv)
        return FakeProc()

    monkeypatch.setattr(pt.subprocess, "run", fake_run)
    assert pt.open_accessibility_settings() is True
    assert seen["argv"] == ["open", EXPECTED_URL]


# ==========================================================================
# Preference storage: atomic + persistent across reloads
# ==========================================================================

def test_default_is_enabled_when_no_file_exists(env):
    assert pt.is_enabled() is True


def test_toggle_persists_across_reload_of_prefs_file(env):
    assert pt.set_enabled(False) is True
    assert read_prefs() == {"ptt_enabled": False}
    assert pt.is_enabled() is False

    assert pt.set_enabled(True) is True
    assert read_prefs() == {"ptt_enabled": True}
    assert pt.is_enabled() is True

    assert pt.set_enabled(False) is True
    assert read_prefs() == {"ptt_enabled": False}
    assert pt.is_enabled() is False


def test_save_is_atomic_and_leaves_no_tmp_litter(env):
    pt.set_enabled(False)
    leftovers = [p for p in os.listdir(env["tmp"]) if p.endswith(".tmp")]
    assert leftovers == []
    assert os.listdir(env["tmp"]) == ["jarvis_ptt_prefs.json"]


def test_corrupt_prefs_file_falls_back_to_default(env):
    with open(pt.PREFS_FILE, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert pt.is_enabled() is True
    assert pt.set_enabled(False) is True
    assert read_prefs() == {"ptt_enabled": False}


# ==========================================================================
# Registration + detector discipline: noise passes through untouched
# ==========================================================================

def test_registers_exactly_the_three_pt_skills(brain):
    expected = {"pt_status", "pt_enable_settings", "pt_toggle"}
    assert set(brain.skills) == expected


NOISE_COMMANDS = [
    "what time is it",
    "tell me a joke",
    "flip a coin",
    "set a timer for ten minutes",
    "push to talk",           # bare topic mention claims nothing
    "hotkey status report",   # not global-hotkey/push-to-talk status
]


@pytest.mark.parametrize("cmd", NOISE_COMMANDS)
def test_noise_detector_returns_none_for_every_skill(cmd, brain):
    for name, (detect, _execute, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} wrongly fired on {cmd!r}"


@pytest.mark.parametrize("cmd,name", [
    ("push to talk status", "pt_status"),
    ("global hotkey status", "pt_status"),
    ("what's my push to talk status?", "pt_status"),
    ("open accessibility settings", "pt_enable_settings"),
    ("fix push to talk", "pt_enable_settings"),
    ("disable push to talk", "pt_toggle"),
    ("turn off push to talk please", "pt_toggle"),
    ("enable push to talk", "pt_toggle"),
    ("turn on push to talk", "pt_toggle"),
])
def test_each_canonical_command_maps_to_exactly_one_skill(brain, cmd, name):
    hits = [n for n, (detect, _e, _p) in brain.skills.items()
            if detect(cmd) is not None]
    assert hits == [name], f"{cmd!r} matched {hits}"


def test_toggle_detector_encodes_direction(brain):
    detect = brain.skills["pt_toggle"][0]
    assert detect("enable push to talk") == {"kind": "toggle", "enable": True}
    assert detect("disable push to talk") == {"kind": "toggle", "enable": False}


# ==========================================================================
# Executor behaviour (persona-safe, honest)
# ==========================================================================

def test_status_happy_path_reports_operational(env, monkeypatch, brain):
    set_probes(monkeypatch, have=True, trusted=True)
    _n, _c, reply = run(brain, "pt_status", "push to talk status")
    assert "operational" in reply.lower()
    assert reply.endswith(", sir.")


def test_status_untrusted_includes_grant_instructions(env, monkeypatch, brain):
    set_probes(monkeypatch, have=True, trusted=False)
    _n, _c, reply = run(brain, "pt_status", "push to talk status")
    low = reply.lower()
    assert "accessibility" in low
    assert "fix push to talk" in low
    assert reply.endswith(", sir.")


def test_status_missing_pynput_names_the_dependency(env, monkeypatch, brain):
    set_probes(monkeypatch, have=False)
    _n, _c, reply = run(brain, "pt_status", "push to talk status")
    assert "pynput" in reply.lower()
    assert reply.endswith(", sir.")


def test_settings_opens_pane_and_returns_numbered_steps(env, brain):
    _n, _c, reply = run(brain, "pt_enable_settings", "open accessibility settings")
    assert env["calls"]["open_url"] == [["open", EXPECTED_URL]]
    assert "1." in reply and "2." in reply and "3." in reply
    assert "accessibility" in reply.lower()
    assert reply.endswith(", sir.")


def test_settings_failure_still_gives_manual_steps(env, brain):
    env["calls"]["rc"] = 1
    _n, _c, reply = run(
        brain, "pt_enable_settings", "fix push to talk"
    )
    assert "could not" in reply.lower() or "navigate" in reply.lower()
    assert "1." in reply and reply.endswith(", sir.")


def test_toggle_disable_flips_persists_and_is_honest(env, brain):
    assert pt.is_enabled() is True
    _n, _c, reply = run(brain, "pt_toggle", "disable push to talk")
    assert pt.is_enabled() is False
    assert read_prefs() == {"ptt_enabled": False}
    assert "next launch" in reply.lower()
    assert reply.endswith(", sir.")


def test_toggle_reenable_round_trip(env, brain):
    run(brain, "pt_toggle", "disable push to talk")
    _n, _c, reply = run(brain, "pt_toggle", "enable push to talk")
    assert pt.is_enabled() is True
    assert read_prefs() == {"ptt_enabled": True}
    assert "next launch" in reply.lower()


def test_toggle_to_same_state_reports_no_change(env, brain):
    assert pt.is_enabled() is True
    _n, _c, reply = run(brain, "pt_toggle", "enable push to talk")
    assert pt.is_enabled() is True
    assert "already" in reply.lower()


def test_wrapped_executors_never_raise_persona_safe(env, monkeypatch, brain):
    def explode(app, ctx):
        raise ValueError("boom")

    safe = pt._wrap(explode, "pt_test")
    out = safe(DummyApp(), {})
    assert isinstance(out, str)
    assert "misfired" in out.lower()
    assert out.endswith(", sir.")
