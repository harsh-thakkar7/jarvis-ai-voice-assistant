"""Tests for live_screen_brain.py — fully offline; seams monkeypatched."""

import base64
import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import live_screen_brain as lsb  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute)


class DummyApp:
    pass


@pytest.fixture()
def brain(monkeypatch):
    monkeypatch.setenv("JARVIS_TEST", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    old_digest = lsb.LAST_DIGEST
    old_stop = lsb._watcher_stop
    old_thread = lsb._watcher_thread
    with lsb._watch_lock:
        lsb.LAST_DIGEST = None
        lsb._watcher_thread = None
        lsb._watcher_stop = threading.Event()
        lsb._watcher_stop.set()
    b = RecorderBrain()
    lsb.register(b)
    yield b
    lsb._watcher_stop.set()
    if lsb._watcher_thread is not None and lsb._watcher_thread.is_alive():
        lsb._watcher_thread.join(timeout=3)
    with lsb._watch_lock:
        lsb.LAST_DIGEST = old_digest
        lsb._watcher_thread = old_thread
        lsb._watcher_stop = old_stop


def run(brain, name, cmd):
    detect, execute = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


# ==========================================================================
# Registration + detectors
# ==========================================================================

def test_registers_all_seven_skills(brain):
    assert set(brain.skills) == {
        "ls_whats_on_screen", "ls_where_is", "ls_read_screen",
        "ls_explain_screen", "ls_watch_start", "ls_watch_stop",
        "ls_screen_digest",
    }


NOISE = [
    "tell me a joke",
    "what's the weather tomorrow",
    "play some jazz",
    "set a timer for ten minutes",
    "search the web for pandas dataframe merge",
    "git status please",
]


def test_detectors_ignore_noise(brain):
    for phrase in NOISE:
        for name, (detect, _exec) in brain.skills.items():
            assert detect(phrase) is None, (
                f"{name} falsely triggered on {phrase!r}")


HITS = {
    "ls_whats_on_screen": ["what's on my screen", "look at my screen",
                           "can you see my screen"],
    "ls_where_is": ["where is the save button",
                    "where's the settings gear on my screen",
                    "find the export button on my screen"],
    "ls_read_screen": ["read my screen aloud", "transcribe my screen"],
    "ls_explain_screen": ["explain what i'm looking at",
                          "help me with this screen step by step"],
    "ls_watch_start": ["watch my screen", "start watching my screen"],
    "ls_watch_stop": ["stop watching", "stop watching my screen"],
    "ls_screen_digest": ["give me a screen digest",
                         "catch me up on my screen"],
}


def test_detector_hits(brain):
    for name, phrases in HITS.items():
        detect = brain.skills[name][0]
        for phrase in phrases:
            ctx = detect(phrase.lower())
            assert ctx is not None, f"{name} missed {phrase!r}"
            assert isinstance(ctx, dict) and "kind" in ctx


def test_watch_start_rejects_stop_phrase(brain):
    assert brain.skills["ls_watch_start"][0]("stop watching my screen") is None


# ==========================================================================
# Coordinate extraction helper
# ==========================================================================

@pytest.mark.parametrize("text,expected", [
    ("450, 320", (450, 320)),
    ("The button center is at (1024, 768) roughly.", (1024, 768)),
    ("x, y = 37, 590 — done.", (37, 590)),
    ("Coordinates:\n512 , 384\nanything else?", (512, 384)),
    ("1,2,3", (1, 2)),
])
def test_extract_coords_from_messy_text(text, expected):
    assert lsb._extract_coords(text) == expected


@pytest.mark.parametrize("text", [
    "", None, "I see no such element.", "single number 42 only",
])
def test_extract_coords_rejects_noise(text):
    assert lsb._extract_coords(text) is None


# ==========================================================================
# ls_whats_on_screen
# ==========================================================================

def test_whats_on_screen_happy(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")
    monkeypatch.setattr(lsb, "ask_vision",
                        lambda app, b64, q: "A terminal running pytest.")
    reply = run(brain, "ls_whats_on_screen", "what's on my screen")
    assert "terminal running pytest" in reply
    assert reply.endswith(", sir.")


def test_whats_on_screen_capture_offline_persona(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: None)
    reply = run(brain, "ls_whats_on_screen", "look at my screen")
    low = reply.lower()
    assert "would" in low and "screenshot" in low
    assert reply.endswith(", sir.")


def test_whats_on_screen_vision_offline_persona(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")
    monkeypatch.setattr(lsb, "ask_vision", lambda app, b64, q: None)
    reply = run(brain, "ls_whats_on_screen", "see my screen")
    assert "would" in reply.lower() and reply.endswith(", sir.")


# ==========================================================================
# ls_where_is
# ==========================================================================

def test_where_is_formats_coords_and_overlay_note(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")

    def fake_ask(app, b64, q):
        assert "save button" in q and "x, y" in q
        return "Sure! The Save icon appears around x, y ≈ (450, 320)."

    monkeypatch.setattr(lsb, "ask_vision", fake_ask)
    reply = run(brain, "ls_where_is", "where is the save button")
    assert "(450, 320)" in reply
    assert "marker overlay" in reply
    assert "save button" in reply


def test_where_is_unparseable_vision(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")
    monkeypatch.setattr(lsb, "ask_vision",
                        lambda app, b64, q: "I cannot see that anywhere.")
    reply = run(brain, "ls_where_is", "find the export button on my screen")
    assert "couldn't" in reply.lower()
    assert "export button" in reply


def test_where_is_capture_offline_persona(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: None)
    reply = run(brain, "ls_where_is", "where's the settings gear")
    assert "settings gear" in reply
    assert "would" in reply.lower()


# ==========================================================================
# ls_read_screen / ls_explain_screen
# ==========================================================================

def test_read_screen_happy(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")

    def fake_ask(app, b64, q):
        assert "transcribe" in q.lower()
        return "TITLE: Dashboard\nBODY: Welcome back, sir.\nBUTTON: Deploy"

    monkeypatch.setattr(lsb, "ask_vision", fake_ask)
    reply = run(brain, "ls_read_screen", "read my screen aloud")
    assert "Welcome back, sir." in reply and "Deploy" in reply


def test_read_screen_offline_persona(brain, monkeypatch):
    monkeypatch.setattr(lsb, "ask_vision", lambda app, b64, q: None)
    monkeypatch.setattr(lsb, "take_screenshot", lambda: None)
    reply = run(brain, "ls_read_screen", "transcribe my screen")
    assert "would" in reply.lower()


def test_explain_screen_numbered_steps(brain, monkeypatch):
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")

    def fake_ask(app, b64, q):
        assert "step" in q.lower()
        return "1. Open the File menu\n2. Click Export\n3. Choose a format."

    monkeypatch.setattr(lsb, "ask_vision", fake_ask)
    reply = run(brain, "ls_explain_screen",
                "help me with this screen step by step")
    assert "step-by-step" in reply.lower()
    assert "1. Open the File menu" in reply


# ==========================================================================
# Watch thread + digest
# ==========================================================================

def test_watch_disabled_under_jarvis_test(brain):
    reply = run(brain, "ls_watch_start", "watch my screen")
    low = reply.lower()
    assert "disabled" in low
    assert lsb._watcher_thread is None or not lsb._watcher_thread.is_alive()


def test_watch_once_updates_last_digest(monkeypatch):
    monkeypatch.setenv("JARVIS_TEST", "1")
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")
    monkeypatch.setattr(lsb, "ask_vision",
                        lambda app, b64, q: "Editor with tests open.")
    old = lsb.LAST_DIGEST
    try:
        assert lsb._watch_once(DummyApp()) is True
        assert lsb.LAST_DIGEST and "Editor with tests open." in lsb.LAST_DIGEST
        assert lsb.LAST_DIGEST.startswith("[")
    finally:
        with lsb._watch_lock:
            lsb.LAST_DIGEST = old


def test_watch_start_stop_lifecycle(brain, monkeypatch):
    monkeypatch.delenv("JARVIS_TEST", raising=False)
    monkeypatch.setattr(lsb, "take_screenshot", lambda: "ZmFrZQ==")
    monkeypatch.setattr(lsb, "ask_vision",
                        lambda app, b64, q: "Editor with tests open.")
    start = run(brain, "ls_watch_start", "watch my screen")
    assert "watching" in start.lower()
    thread = lsb._watcher_thread
    assert thread is not None and thread.is_alive()
    deadline = time.time() + 5
    while lsb.LAST_DIGEST is None and time.time() < deadline:
        time.sleep(0.02)
    assert lsb.LAST_DIGEST and "Editor" in lsb.LAST_DIGEST

    stop = run(brain, "ls_watch_stop", "stop watching my screen")
    assert "stopped" in stop.lower()
    thread.join(timeout=3)
    assert not thread.is_alive()


def test_watch_stop_when_not_running(brain):
    reply = run(brain, "ls_watch_stop", "stop watching")
    assert "wasn't watching" in reply.lower()


def test_screen_digest_empty_and_filled(brain):
    empty = run(brain, "ls_screen_digest", "give me a screen digest")
    assert "watch my screen" in empty

    with lsb._watch_lock:
        lsb.LAST_DIGEST = "[12:00:00] A spreadsheet, sir."
    filled = run(brain, "ls_screen_digest", "catch me up on my screen")
    assert "[12:00:00]" in filled and "spreadsheet" in filled


# ==========================================================================
# ask_vision seam behaviour
# ==========================================================================

def test_ask_vision_prefers_app_seam(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("REST must not be called when app seam exists")

    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(lsb, "requests", types.SimpleNamespace(post=boom))

    class AppWithVision:
        def _ask_vision(self, b64, question):
            return "app says hi"

    class ExplodingVision:
        def _ask_vision(self, b64, question):
            raise RuntimeError("down")

    assert lsb.ask_vision(AppWithVision(), "QQ==", "?") == "app says hi"
    assert lsb.ask_vision(ExplodingVision(), "QQ==", "?") is None


def test_ask_vision_rest_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-123")
    calls = {}

    class FakeResp:
        def json(self):
            return {"choices": [{"message": {"content": "  rest answer  "}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, payload=json, timeout=timeout)
        return FakeResp()

    monkeypatch.setattr(lsb, "requests",
                        types.SimpleNamespace(post=fake_post))
    out = lsb.ask_vision(DummyApp(), "QUJD", "describe this")
    assert out == "rest answer"
    assert calls["url"] == lsb.GROQ_URL
    assert calls["headers"]["Authorization"] == "Bearer test-key-123"
    assert calls["payload"]["model"] == lsb.GROQ_VISION_MODEL
    image_url = calls["payload"]["messages"][0]["content"][1]["image_url"]["url"]
    assert image_url.endswith("QUJD")


def test_ask_vision_offline_returns_none(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert lsb.ask_vision(DummyApp(), "QUJD", "?") is None
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    assert lsb.ask_vision(DummyApp(), "QUJD", "?") is None
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(lsb, "requests", None)
    assert lsb.ask_vision(DummyApp(), "QUJD", "?") is None


# ==========================================================================
# take_screenshot seam behaviour
# ==========================================================================

class FakeImg:
    data = b"\x89PNG\r\n\x1a\nFAKE-FRAME"

    def save(self, buf, format=None):
        buf.write(self.data)


def test_take_screenshot_pyautogui_path(monkeypatch):
    import multi_monitor as mm
    monkeypatch.setattr(mm, "capture_all_stitched", lambda *a, **k: None)
    fake_mod = types.ModuleType("pyautogui")
    fake_mod.screenshot = lambda: FakeImg()
    monkeypatch.setitem(sys.modules, "pyautogui", fake_mod)
    expected = base64.b64encode(FakeImg.data).decode("ascii")
    assert lsb.take_screenshot() == expected


def test_take_screenshot_falls_back_to_screencapture(monkeypatch, tmp_path):
    import multi_monitor as mm
    monkeypatch.setattr(mm, "capture_all_stitched", lambda *a, **k: None)

    def broken():
        raise RuntimeError("no display")

    fake_mod = types.ModuleType("pyautogui")
    fake_mod.screenshot = broken
    monkeypatch.setitem(sys.modules, "pyautogui", fake_mod)

    payload = b"\x89PNG-fallback-bytes"

    def fake_run(cmd, capture_output=True, timeout=None):
        assert cmd[:1] == ["screencapture"] and "-x" in cmd
        path = cmd[-1]
        with open(path, "wb") as fh:
            fh.write(payload)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(lsb.subprocess, "run", fake_run)
    out = lsb.take_screenshot()
    assert base64.b64decode(out) == payload


def test_take_screenshot_total_failure_returns_none(monkeypatch):
    fake_mod = types.ModuleType("pyautogui")
    fake_mod.screenshot = lambda: (_ for _ in ()).throw(OSError("nope"))
    monkeypatch.setitem(sys.modules, "pyautogui", fake_mod)
    monkeypatch.setattr(lsb.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=1))
    # Multi-monitor stitched path (real capture on this Mac) must also
    # be out of the picture for this total-failure scenario.
    import multi_monitor as mm
    monkeypatch.setattr(mm, "capture_all_stitched", lambda *a, **k: None)
    assert lsb.take_screenshot() is None
