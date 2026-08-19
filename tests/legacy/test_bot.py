#!/usr/bin/env python3
"""Test JarvisBot command processing without GUI or microphone."""
import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os, sys
os.environ["JARVIS_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import JarvisBot

PASSED = 0
FAILED = 0

def run_test(name, bot, cmd, check_fn, replies):
    global PASSED, FAILED
    replies.clear()
    bot._process(cmd)
    ok = check_fn(replies, bot)
    status = "PASS" if ok else "FAIL"
    if ok:
        PASSED += 1
    else:
        FAILED += 1
    print(f"  [{status}] {name} -> {replies}")

def test_bot_process():
    global PASSED, FAILED
    bot = JarvisBot()
    bot.root.withdraw()

    replies = []
    def mock_say(text):
        replies.append(text)
    bot.say = mock_say

    # WAKE / SLEEP
    run_test("wake up jarvis", bot, "wake up jarvis",
             lambda r, b: any("awake" in x.lower() for x in r) and b.awake, replies)
    run_test("go to sleep", bot, "go to sleep",
             lambda r, b: any("standby" in x.lower() or "sleep" in x.lower() for x in r) and not b.awake, replies)
    run_test("wake up again", bot, "wake up jarvis",
             lambda r, b: any("awake" in x.lower() for x in r) and b.awake, replies)
    run_test("goodnight sleep", bot, "goodnight",
             lambda r, b: any("sleep" in x.lower() or "standby" in x.lower() for x in r), replies)
    run_test("standby sleep", bot, "standby",
             lambda r, b: any("sleep" in x.lower() or "standby" in x.lower() for x in r), replies)

    # BRAIN SKILLS (offline)
    run_test("hello greeting", bot, "hello",
             lambda r, b: len(r) > 0, replies)
    run_test("who are you", bot, "who are you",
             lambda r, b: len(r) > 0, replies)
    run_test("tell me a joke", bot, "tell me a joke",
             lambda r, b: len(r) > 0, replies)
    run_test("fun fact", bot, "fun fact",
             lambda r, b: len(r) > 0, replies)
    run_test("flip a coin", bot, "flip a coin",
             lambda r, b: len(r) > 0, replies)
    run_test("what time is it", bot, "what time is it",
             lambda r, b: len(r) > 0, replies)
    run_test("what day is it", bot, "what day is it",
             lambda r, b: len(r) > 0, replies)

    # FILE OPERATIONS
    run_test("list files", bot, "list files",
             lambda r, b: len(r) > 0, replies)

    # OPEN
    run_test("open youtube", bot, "open youtube",
             lambda r, b: len(r) > 0, replies)

    # COMMANDS THAT FALL THROUGH TO LLM/BRAIN
    run_test("what is python", bot, "what is python",
             lambda r, b: len(r) > 0, replies)
    run_test("tell me about ai", bot, "tell me about artificial intelligence",
             lambda r, b: len(r) > 0, replies)

    # EDGE CASES
    run_test("empty command", bot, "",
             lambda r, b: True, replies)  # should not crash

    bot._on_close()
    print(f"\nRESULTS: {PASSED} passed, {FAILED} failed")
    return FAILED == 0

if __name__ == "__main__":
    ok = test_bot_process()
    sys.exit(0 if ok else 1)
