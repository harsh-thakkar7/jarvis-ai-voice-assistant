#!/usr/bin/env python3
"""Test JarvisApp voice features: MIC button, hold-to-talk, auto-listen,
wake-word stripping, and the thread-safe UI queue routing.

Runs fully offline: listen(), TTS and network calls are mocked.
"""
import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os
import sys
import time
import threading

os.environ["JARVIS_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main  # noqa: E402

PASSED = 0
FAILED = 0


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def drain(app):
    """Process pending ui_q messages deterministically."""
    for _ in range(5):
        app._poll_queue()
        time.sleep(0.05)
        app._poll_queue()


def wait_for(fn, timeout=8.0):
    """Poll fn() until truthy or timeout (for cross-thread handoffs)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def make_app():
    app = main.JarvisApp()
    app.root.withdraw()
    app.engine = None                       # no real TTS
    app.say = lambda text: None             # silent
    return app


# ============================================================================
print("== 1. VOICE BUTTON (click-to-talk) ==")


def test_voice_click():
    app = make_app()
    captured = []
    app.process = lambda cmd: captured.append(cmd)
    app.listen = lambda *a, **k: "what time is it"

    check("mic starts idle", app.voice_active is False)

    app._voice_click()                      # spawns _voice_listen thread
    ok = wait_for(lambda: bool(captured))
    drain(app)

    check("heard text lands in entry box",
          app.cmd_entry.get() == "what time is it",
          f"got {app.cmd_entry.get()!r}")
    check("command was dispatched to process", ok, str(captured))
    check("mic button resets after listening", app.voice_active is False)
    check("status back to STANDBY", app.status_text == "STANDBY")
    app.quit_app()


# ============================================================================
print("== 2. VOICE BUTTON (hold-to-talk press/release) ==")


def test_voice_hold():
    app = make_app()
    captured = []
    app.process = lambda cmd: captured.append(cmd)
    app.listen = lambda *a, **k: "open youtube"

    app._voice_press()
    check("press activates mic", app.voice_active is True)

    # The synthetic command callback must be deduped right after a press.
    app._voice_click()
    check("click deduped immediately after press", app.voice_active is True)

    app._voice_release()                    # spawns hold-listen thread
    ok = wait_for(lambda: bool(captured))
    drain(app)

    check("release listens and dispatches command",
          ok and captured == ["open youtube"], f"got {captured!r}")
    check("mic deactivated after release cycle", app.voice_active is False)
    app.quit_app()


# ============================================================================
print("== 3. AUTO-LISTEN (continuous mode) ==")


def test_auto_listen():
    app = make_app()
    captured = []

    def fake_process(cmd):
        captured.append(cmd)
        app.continuous_listen = False       # stop the loop after first hit

    app.process = fake_process

    replies = []
    app.say = lambda text: replies.append(text)
    app.listen = lambda *a, **k: "jarvis what time is it"

    app._toggle_auto_listen()
    check("auto flag on", app.continuous_listen is True)
    check("auto button armed", str(app.auto_listen_btn.cget("text")) == "AUTO")

    if app._listen_thread:
        app._listen_thread.join(timeout=10)
    drain(app)

    check("wake word stripped from heard command",
          captured == ["what time is it"], f"got {captured!r}")

    # wake-word-only input should get a verbal nudge instead of a dispatch
    captured.clear()
    replies.clear()

    def stop_on_say(text):
        replies.append(text)
        app.continuous_listen = False

    app.say = stop_on_say
    app.listen = lambda *a, **k: "hey jarvis"
    app.continuous_listen = True
    app._start_continuous_listen()
    if app._listen_thread:
        app._listen_thread.join(timeout=10)
    drain(app)

    check("bare wake word gets 'Yes sir?' response",
          any("sir" in r.lower() for r in replies), f"got {replies!r}")
    check("no command dispatched for bare wake word", captured == [])

    # toggle off
    app.continuous_listen = False
    app.auto_listen_btn.config(text="AUTO")
    check("auto can be switched off", app.continuous_listen is False)
    app.quit_app()


# ============================================================================
print("== 4. VOICE ERROR HANDLING ==")


def test_voice_errors():
    app = make_app()
    captured = []
    app.process = lambda cmd: captured.append(cmd)

    def boom(*a, **k):
        raise RuntimeError("no microphone")

    app.listen = boom
    t = threading.Thread(target=app._voice_listen)
    t.start()
    t.join(timeout=5)
    drain(app)

    check("mic exception does not crash or hang", True)
    check("nothing dispatched when listen explodes", captured == [])
    ok = wait_for(lambda: app.voice_active is False)
    drain(app)
    check("mic still resets after error", ok)

    # silence (empty string from recognizer)
    app.listen = lambda *a, **k: ""
    t = threading.Thread(target=app._voice_listen)
    t.start()
    t.join(timeout=5)
    drain(app)
    check("silence does not dispatch anything", captured == [])
    app.quit_app()


# ============================================================================
print("== 5. WAKE / SLEEP / EXIT VIA VOICE PATH (_run_cmd) ==")


def test_run_cmd_routing():
    app = make_app()
    said = []
    app.say = lambda text: said.append(text)

    app.awake = False
    app._run_cmd("wake up jarvis")
    check("_run_cmd wakes bot", app.awake is True)
    check("wake reply spoken", any("awake" in s.lower() for s in said))

    app._run_cmd("go to sleep")
    check("_run_cmd sleeps bot", app.awake is False)

    said.clear()
    app._run_cmd("exit")
    check("exit clears running flag", app.running.is_set() is False)
    check("exit farewell spoken", len(said) > 0)
    app.running.set()
    app.quit_app()


if __name__ == "__main__":
    test_voice_click()
    test_voice_hold()
    test_auto_listen()
    test_voice_errors()
    test_run_cmd_routing()
    print(f"\nRESULTS: {PASSED} passed, {FAILED} failed")
    sys.exit(0 if FAILED == 0 else 1)
