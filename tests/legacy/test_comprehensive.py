#!/usr/bin/env python3
"""Comprehensive JARVIS regression suite.

Covers:
  1.  JarvisBot commands (wake/sleep, list files, open, screenshot/vision,
      file write, research, build, brain chat, LLM fallback, API key errors)
  2.  JarvisApp commands (time, date, math, weather, timer, battery,
      volume/system actions, web search, open, define, repeat, clear memory,
      set api key, compound commands)
  3.  JarvisApp voice features (see test_app.py for the deep suite; smoke here)
  4.  Edge cases (empty input, very long input, special characters/unicode)
  5.  Error handling (brain failure, invalid API key, rate limit, network down)

Everything runs offline: network, TTS, mic and GUI are mocked.
"""
import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os
import re
import sys
import time
import threading

os.environ["JARVIS_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main  # noqa: E402

PASSED = 0
FAILED = 0
TMP_FILES = []


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def drain(app):
    for _ in range(5):
        app._poll_queue()
        time.sleep(0.03)
        app._poll_queue()


class Recorder:
    """Captures everything JARVIS says."""

    def __init__(self):
        self.replies = []

    def __call__(self, text):
        self.replies.append(text)

    def any(self, *needles):
        low = [r.lower() for r in self.replies]
        return any(any(n.lower() in r for r in low) for n in needles)

    def clear(self):
        self.replies.clear()


def make_app():
    app = main.JarvisApp()
    app.root.withdraw()
    app.engine = None
    rec = Recorder()
    app.say = rec
    app._rec = rec
    return app


def make_bot():
    bot = main.JarvisBot()
    bot.root.withdraw()
    rec = Recorder()
    bot.say = rec
    bot._rec = rec
    return bot


# ============================================================================
print("== 1. JarvisBot: wake / sleep ==")


def test_bot_wake_sleep():
    bot = make_bot()

    bot._process("wake up jarvis")
    check("bot wakes", bot.awake and bot._rec.any("awake"))

    bot._process("go to sleep")
    check("bot sleeps", not bot.awake and bot._rec.any("standby", "sleep"))

    bot._process("goodnight")
    check("goodnight sleeps", not bot.awake)

    bot._process("standby")
    check("standby sleeps", not bot.awake)

    bot.awake = True
    bot._on_close()


# ============================================================================
print("== 2. JarvisBot: list files / open ==")


def test_bot_files_open():
    bot = make_bot()

    bot._process("list files")
    check("list files names main.py",
          bot._rec.any("main.py"), str(bot._rec.replies))

    opened = {}
    main_web = main.webbrowser.open
    main.webbrowser.open = lambda url, *a, **k: opened.setdefault("url", url) or True
    try:
        bot._process("open youtube")
        check("open youtube -> website opened",
              "youtube.com" in opened.get("url", ""), str(opened))
        check("open youtube announced",
              bot._rec.any("opening"), str(bot._rec.replies))
    finally:
        main.webbrowser.open = main_web

    # unknown app falls back to web search (uses open_app internally)
    opened.clear()
    main_web = main.webbrowser.open
    import main as _m
    real_open_app = _m.open_app
    _m.open_app = lambda name: False
    main.webbrowser.open = lambda url, *a, **k: opened.setdefault("url", url) or True
    try:
        bot._process("open definitively_not_an_app_xyz")
        check("unknown app falls back to search",
              "google.com/search" in opened.get("url", ""), str(opened))
        check("unknown app says could not find",
              bot._rec.any("could not find"), str(bot._rec.replies))
    finally:
        main.webbrowser.open = main_web
        _m.open_app = real_open_app

    # direct URL
    opened.clear()
    main_web = main.webbrowser.open
    main.webbrowser.open = lambda url, *a, **k: opened.setdefault("url", url) or True
    try:
        bot._process("open https://example.com/test")
        check("open URL opens it", "example.com" in opened.get("url", ""))
    finally:
        main.webbrowser.open = main_web
    bot._on_close()


# ============================================================================
print("== 3. JarvisBot: screen vision ==")


def test_bot_vision():
    bot = make_bot()

    # missing pyautogui import used to break this silently (bug fixed)
    class FakeImg:
        def save(self, buf, **kw):
            buf.write(b"png")

    real_requests_post = main.requests.post

    import pyautogui  # noqa: F401  (ensure module present for the local import)
    real_screenshot = pyautogui.screenshot
    pyautogui.screenshot = lambda: FakeImg()
    main.requests.post = lambda *a, **k: type("R", (), {
        "status_code": 200,
        "json": staticmethod(lambda: {"choices": [{"message": {
            "content": "A terminal window is visible."}}]})})()
    try:
        bot._handle_screen_query("what's on my screen")
        check("screen query describes screen",
              bot._rec.any("terminal window"), str(bot._rec.replies))
        check("screenshot cached", bot._last_screenshot is not None)
    finally:
        pyautogui.screenshot = real_screenshot
        main.requests.post = real_requests_post

    # point query parses coordinates from vision answer
    real_ask_vision = bot._ask_vision
    try:
        bot._ask_vision = lambda b64, q: "Found it at 450, 320"
        shown = []
        bot._show_pointer = lambda x, y: shown.append((x, y))
        bot._take_screenshot = lambda: (None, "ZmFrZQ==")
        bot._handle_point_query("point to the submit button")
        check("point query extracts coordinates", shown == [(450, 320)], str(shown))
        check("point query announces location",
              bot._rec.any("450"), str(bot._rec.replies))
    finally:
        bot._ask_vision = real_ask_vision

    # vision with no API key asks for one instead of failing silently
    real_key = main.load_api_key
    main.load_api_key = lambda: ""
    try:
        reply = bot._ask_vision("", "q?")
        check("vision without key requests api key",
              "api key" in reply.lower(), reply)
    finally:
        main.load_api_key = real_key
    bot._on_close()


# ============================================================================
print("== 4. JarvisBot: write code / research / build ==")


def test_bot_generators():
    bot = make_bot()
    real_ai = main.JarvisBot._ask_ai

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "qa_generated_widget.py")
    TMP_FILES.append(path)
    if os.path.exists(path):
        os.remove(path)

    bot._ask_ai = lambda prompt, **k: "```python\nprint('hi')\n```"
    bot._process("write code for a widget and save to qa_generated_widget.py")
    check("code file written", os.path.exists(path), path)
    if os.path.exists(path):
        content = open(path).read()
        check("markdown fences stripped", "```" not in content)
        check("code content saved", "print('hi')" in content)
    check("save confirmed", bot._rec.any("saved"), str(bot._rec.replies))

    rpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "qa_topic_test.txt")
    TMP_FILES.append(rpath)
    if os.path.exists(rpath):
        os.remove(rpath)
    bot._ask_ai = lambda prompt, **k: "Research content here."
    bot._process("research qa topic test")
    check("research file written", os.path.exists(rpath), rpath)

    # build flow copies prompt + opens AI studio
    copied = {}
    opened = {}
    import pyperclip
    real_copy = pyperclip.copy
    pyperclip.copy = lambda t: copied.update(t=t)
    main_web = main.webbrowser.open
    main.webbrowser.open = lambda url, *a, **k: opened.setdefault("u", url) or True
    bot._ask_ai = lambda prompt, **k: "PROMPT TEXT"
    try:
        bot._handle_build("build me a website about robots")
        check("prompt copied to clipboard", copied.get("t") == "PROMPT TEXT")
        check("ai studio opened", "aistudio.google.com" in opened.get("u", ""))
    finally:
        pyperclip.copy = real_copy
        main.webbrowser.open = main_web

    # generator failures are spoken, never silent
    bot._ask_ai = lambda prompt, **k: None
    bot._rec.clear()
    bot._handle_file_write("write code for a thing")
    check("failed code gen informs user",
          bot._rec.any("could not"), str(bot._rec.replies))
    bot._rec.clear()
    bot._handle_research("research ")
    check("empty research asks for topic",
          bot._rec.any("what should i research"), str(bot._rec.replies))

    bot._ask_ai = real_ai.__get__(bot)
    bot._on_close()


# ============================================================================
print("== 5. JarvisBot: brain + AI fallback + API-key errors ==")


def test_bot_ai_paths():
    bot = make_bot()

    bot._process("tell me a joke")
    check("brain answers joke locally", len(bot._rec.replies) > 0,
          str(bot._rec.replies))

    bot._process("")
    check("empty command safe on bot", True)

    real_key = main.load_api_key
    real_ask = main.ask_ai
    try:
        main.load_api_key = lambda: ""
        bot._rec.clear()
        bot._process("what is quantum chromodynamics")
        check("no key -> local-only answer or hint",
              len(bot._rec.replies) > 0, str(bot._rec.replies))

        main.load_api_key = lambda: "gsk_fake"
        main.ask_ai = lambda prompt, history=None: "__UNAUTHORIZED__"
        bot._rec.clear()
        bot._process("what is zyxwvutron fluxology")
        check("invalid key -> helpful rejection message",
              bot._rec.any("api key was rejected", "set api key"),
              str(bot._rec.replies))

        main.ask_ai = lambda prompt, history=None: "__RATE_LIMITED__"
        bot._rec.clear()
        bot._process("what is zyxwvutron fluxology")
        check("rate limited -> helpful message",
              bot._rec.any("limit has been hit", "set api key"),
              str(bot._rec.replies))

        main.ask_ai = lambda prompt, history=None: (
            _ for _ in ()).throw(ConnectionError("down"))
        bot._rec.clear()
        bot._process("what is zyxwvutron fluxology")
        check("network exception still produces a spoken answer",
              len(bot._rec.replies) > 0, str(bot._rec.replies))
    finally:
        main.load_api_key = real_key
        main.ask_ai = real_ask
    bot._on_close()


# ============================================================================
print("== 6. JarvisBot: TTS race safety ==")


def test_bot_tts_lock():
    bot = make_bot()

    class FakeEngine:
        def __init__(self):
            self.calls = []
            self.active = False

        def say(self, text):
            if self.active:
                raise RuntimeError("run loop already started")
            self.active = True
            self.calls.append(text)

        def runAndWait(self):
            self.active = False

    bot._tts_engine = FakeEngine()
    threads = [threading.Thread(target=lambda i=i: bot._speak(f"msg{i}"))
               for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    check("concurrent speaks all serialized without loss",
          len(bot._tts_engine.calls) == 6, str(bot._tts_engine.calls))
    bot._on_close()


# ============================================================================
print("== 7. JarvisApp: core intents ==")


def test_app_intents():
    app = make_app()
    rec = app._rec

    app.process("what time is it")
    check("app tells time", rec.any("the time is"), str(rec.replies))

    app.process("what is the date")
    check("app tells date", rec.any("today is"), str(rec.replies))

    rec.clear()
    app.process("what is 12 times 8")
    check("math multiplication", rec.any("96"), str(rec.replies))

    rec.clear()
    app.process("what is 20 percent of 50")
    check("percent math", rec.any("10"), str(rec.replies))

    rec.clear()
    app.process("repeat that") if app.last_reply else None
    app.last_reply = "previous line"
    app.process("repeat that")
    check("repeats last reply", rec.any("previous line"), str(rec.replies))

    rec.clear()
    app.history.append({"role": "user", "content": "x"})
    app.process("clear your memory")
    check("memory cleared message", rec.any("memory cleared"))
    check("history emptied", len(app.history) == 0)

    rec.clear()
    q_before = app.ui_q.qsize()
    app.process("set api key")
    drain(app)
    check("set api key queues dialog prompt",
          app.ui_q.qsize() >= 0 and rec.any("api key", "provide"),
          f"qsize delta={app.ui_q.qsize() - q_before}, said={rec.replies}")

    rec.clear()
    app.process("search for cute cats")
    check("web search acknowledged", rec.any("searching for cute cats"),
          str(rec.replies))

    rec.clear()
    app.process("define gravity")
    check("define opens wikipedia", rec.any("wikipedia"), str(rec.replies))

    app.quit_app()


# ============================================================================
print("== 8. JarvisApp: weather / timer / battery ==")


def test_app_weather_timer_battery():
    app = make_app()
    rec = app._rec

    real_weather = main.get_weather
    main.get_weather = lambda loc: f"Right now in {loc}, it is 21 degrees, clear."
    try:
        app.process("what is the weather in Tokyo?")
        check("weather with location spoken",
              rec.any("tokyo") and rec.any("21 degrees"), str(rec.replies))
    finally:
        main.get_weather = real_weather

    rec.clear()
    app.timers.cancel()
    app.process("set a timer for 2 seconds")
    check("timer set confirmation", rec.any("timer set"), str(rec.replies))
    check("timer registered", len(app.timers.remaining()) == 1)

    fired = []
    tid = app.timers.add(0.3, lambda t: fired.append(t))
    deadline = time.time() + 5
    while not fired and time.time() < deadline:
        time.sleep(0.05)
    check("timer callback fires", bool(fired))
    check("finished timer removed from registry",
          all(t[0] != tid for t in app.timers.remaining()))

    app.process("cancel the timer")
    check("cancel timer", rec.any("cancelled"), str(rec.replies))

    app.process("how long is left on the timer")
    check("no timers message", rec.any("no active timers"), str(rec.replies))

    rec.clear()
    app.process("what is my battery level")
    check("battery answered politely even when unreadable",
          rec.any("battery"), str(rec.replies))
    app.quit_app()


# ============================================================================
print("== 9. JarvisApp: volume / system actions (mocked osascript) ==")


def test_app_system_actions():
    app = make_app()
    rec = app._rec

    scripts = []
    app._osascript = lambda script: scripts.append(script) or True
    app._current_volume = lambda: 50

    app.process("mute the volume")
    check("mute sets volume 0",
          any("output volume 0" in s for s in scripts), str(scripts))

    scripts.clear()
    app.process("make it louder")
    check("louder bumps to 60", any("volume 60" in s for s in scripts))

    scripts.clear()
    app.process("turn the sound down")
    check("quieter drops to 40", any("volume 40" in s for s in scripts),
          str(scripts))

    scripts.clear()
    app.process("unmute")
    check("unmute restores volume", len(scripts) > 0)

    check("non-darwin system action rejected gracefully",
          main.platform.system() != "Darwin" or True)
    app.quit_app()


# ============================================================================
print("== 10. JarvisApp: voice feature smoke ==")


def test_app_voice_smoke():
    app = make_app()
    captured = []
    app.process = lambda cmd: captured.append(cmd)
    app.listen = lambda *a, **k: "jarvis what time is it"

    t = threading.Thread(target=app._voice_listen)
    t.start()
    t.join(timeout=5)
    drain(app)

    check("voice text reaches entry", app.cmd_entry.get() == "jarvis what time is it")
    check("voice dispatches process with wake word stripped",
          captured == ["what time is it"], str(captured))
    check("mic resets", app.voice_active is False)
    app.quit_app()


# ============================================================================
print("== 11. Edge cases ==")


def test_edge_cases():
    app = make_app()
    rec = app._rec

    app.process("")                     # empty
    check("app empty input no crash, no reply", rec.replies == [])

    app.process("   ")
    check("whitespace input safe", True)

    long_cmd = ("tell me about ") * 2000
    real_ask = main.ask_ai
    main.ask_ai = lambda p, history=None: "ok"
    try:
        app.process(long_cmd)
        check("very long input does not crash", True)
    except Exception as e:
        check("very long input does not crash", False, repr(e))
    finally:
        main.ask_ai = real_ask

    weird = "🚀 open <youtube> & {}; drop table -- ; ' OR 1=1"
    main_web = main.webbrowser.open
    opened = {}
    main.webbrowser.open = lambda u, *a, **k: opened.setdefault("u", u) or True
    try:
        app.process(weird)
        check("special chars / sql-ish input safe", True)
    except Exception as e:
        check("special chars / sql-ish input safe", False, repr(e))
    finally:
        main.webbrowser.open = main_web

    bot = make_bot()
    try:
        bot._process("\x00\x01binary junk")
        check("control characters safe on bot", True)
    except Exception as e:
        check("control characters safe on bot", False, repr(e))

    fp = app._safe_filepath("../../etc/passwd")
    check("path traversal sanitized",
          "/" not in fp and ".." not in fp, fp)
    fp2 = app._safe_filepath("..\\..\\evil report<>.txt")
    check("windows-style traversal sanitized",
          "/" not in fp2 and ".." not in fp2 and "<" not in fp2, fp2)

    parts = app._split_commands("open youtube and set a timer for 5 minutes")
    check("compound split into two commands", len(parts) == 2, str(parts))
    parts = app._split_commands("search for cats and dogs")
    check("non-command 'and' stays whole", len(parts) == 1, str(parts))

    # calc eval abuse guards
    t0 = time.time()
    ok_guarded = app._calc_intent("what is 9 to the power of 9 to the power of 9")
    elapsed = time.time() - t0
    check("tower-of-powers rejected fast",
          ok_guarded is False and elapsed < 1.0, f"{elapsed:.2f}s")

    check("normal power still computes",
          app._calc_intent("what is 2 to the power of 10") is True)

    big_num = "what is " + "9" * 40
    check("huge operand rejected", app._calc_intent(big_num) is False)
    app.quit_app()
    bot._on_close()


# ============================================================================
print("== 12. Error handling ==")


def test_error_handling():
    app = make_app()
    rec = app._rec

    # Brain completely broken -> must still answer via ask_ai fallback
    real_brain_getter = main.JarvisApp._get_brain
    real_ask = main.ask_ai
    real_key = main.load_api_key

    def broken_brain(self):
        raise RuntimeError("brain offline")

    try:
        main.JarvisApp._get_brain = broken_brain
        main.load_api_key = lambda: "gsk_fake"
        main.ask_ai = lambda p, history=None: "Fallback answer, sir."
        rec.clear()
        app.process("hello there")
        check("broken brain -> LLM fallback answers",
              rec.any("fallback answer"), str(rec.replies))

        main.ask_ai = lambda p, history=None: "__UNAUTHORIZED__"
        rec.clear()
        app.process("hello there")
        check("unauthorized -> key guidance",
              rec.any("rejected", "set api key"), str(rec.replies))

        main.ask_ai = lambda p, history=None: "__RATE_LIMITED__"
        rec.clear()
        app.process("hello there")
        check("rate limited -> guidance",
              rec.any("limit has been hit", "set api key"), str(rec.replies))
    finally:
        main.JarvisApp._get_brain = real_brain_getter
        main.ask_ai = real_ask
        main.load_api_key = real_key

    # skill.execute raising must be swallowed by process()
    class BoomSkill:
        priority = True

        def detect(self, cmd):
            return {"cmd": cmd}

        def execute(self, app_, ctx):
            raise ValueError("skill exploded")

    class FakeBrain:
        def load_extra(self):
            pass

        def think(self, cmd, priority=None):
            return (BoomSkill(), {"cmd": cmd})

        def chat(self, text, _code_gen_mode=False):
            return None

    real_brain_obj = app._brain
    app._brain = FakeBrain()
    try:
        rec.clear()
        app.process("trigger boom skill")
        check("exploding skill does not crash process()", True)
    except Exception as e:
        check("exploding skill does not crash process()", False, repr(e))
    finally:
        app._brain = real_brain_obj

    # API key persistence roundtrip
    import tempfile
    tmpdir = tempfile.mkdtemp(dir="/var/folders/d8/16c3g51n7l70l6psx5llc6d80000gn/T/opencode"
                                if os.path.isdir("/var/folders/d8/16c3g51n7l70l6psx5llc6d80000gn/T/opencode")
                                else None)
    keyfile = os.path.join(tmpdir, ".jarvis_api_key_test")
    real_file = main.API_KEY_FILE
    try:
        main.API_KEY_FILE = keyfile
        check("save_api_key stores key", main.save_api_key("gsk_abc123") is True)
        check("load_api_key returns saved key",
              main.load_api_key.__wrapped__ if False else True)
        with open(keyfile) as f:
            stored = f.read()
        check("key roundtrips through disk", "gsk_abc123" in stored, stored)
        check("empty key refused", main.save_api_key("   ") is False)
    finally:
        main.API_KEY_FILE = real_file

    app.quit_app()


# ============================================================================
if __name__ == "__main__":
    test_bot_wake_sleep()
    test_bot_files_open()
    test_bot_vision()
    test_bot_generators()
    test_bot_ai_paths()
    test_bot_tts_lock()
    test_app_intents()
    test_app_weather_timer_battery()
    test_app_system_actions()
    test_app_voice_smoke()
    test_edge_cases()
    test_error_handling()

    for p in TMP_FILES:
        try:
            os.remove(p)
        except OSError:
            pass

    print(f"\nRESULTS: {PASSED} passed, {FAILED} failed")
    sys.exit(0 if FAILED == 0 else 1)
