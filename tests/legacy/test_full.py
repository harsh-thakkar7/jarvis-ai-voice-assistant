import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os
import queue
import re
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main

opened = []
said = []


def fake_open(url):
    opened.append(url)


def fake_open_app(app):
    said.append("OPENING_APP:" + app)
    return True


main.webbrowser.open = fake_open
main.open_app = fake_open_app

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def make_app():
    app = object.__new__(main.JarvisApp)
    app.ui_q = queue.Queue()
    app.say = lambda text: said.append(text)
    app.history = deque(maxlen=10)
    app.timers = main.TimerManager()
    app.last_reply = None
    app._ask_ai_safely = lambda prompt, **kw: main.ask_ai(prompt, list(app.history))
    return app


app = make_app()


class _FakePyperclip:
    copied = []

    def copy(self, text):
        self.copied.append(text)


class _FakePyautogui:
    log = []

    def size(self):
        return 1440, 900

    def click(self, x, y):
        self.log.append(("click", x, y))

    def hotkey(self, *keys):
        self.log.append(("hotkey", keys))


sys.modules["pyperclip"] = _FakePyperclip()
sys.modules["pyautogui"] = _FakePyautogui()


def fake_youtube_first_video(self, query):
    return "https://www.youtube.com/watch?v=" + query.replace(" ", "+")


def fake_activate_browser(self):
    pass


main.JarvisApp._youtube_first_video = fake_youtube_first_video
main.JarvisApp._activate_default_browser = fake_activate_browser


def run(cmd):
    opened.clear()
    said.clear()
    app.process(cmd)
    return list(opened), list(said)


print("== 1. TIME / DATE intents ==")
o, s = run("what time is it")
check("what time is it", s and "time is" in s[0], str(s))
o, s = run("what is the date")
check("what is the date", s and "Today is" in s[0], str(s))
o, s = run("what day is it")
check("what day is it", s and "Today is" in s[0], str(s))
o, s = run("search for the best time to post")
check("search-for-time NOT hijacked by time intent",
      o and "google.com/search" in o[0] and not (s and "time is" in s[0]), str(o) + str(s))

print("== 2. ALL WEBSITES ('open <key>' and 'go to <key>') ==")
for name, url in main.WEBSITES.items():
    o, s = run("open " + name)
    check(f"open {name}", o == [url], f"{o} != {url}")
    o, s = run("go to " + name)
    check(f"go to {name}", o == [url], f"{o} != {url}")

print("== 3. 'google X' combos must hit the right sub-site ==")
combos = {
    "open google maps": "https://maps.google.com",
    "open google classroom": "https://classroom.google.com",
    "open google meet": "https://meet.google.com",
    "open google translate": "https://translate.google.com",
    "open google docs": "https://docs.google.com",
    "open google sheets": "https://sheets.google.com",
    "open google slides": "https://slides.google.com",
    "open google news": "https://news.google.com",
    "open google ai studio": "https://aistudio.google.com",
    "open ai studio": "https://aistudio.google.com",
    "open aistudio": "https://aistudio.google.com",
    "open youtube": "https://www.youtube.com",
    "open stackoverflow": "https://stackoverflow.com",
    "open drive": "https://drive.google.com",
}
for cmd, expect in combos.items():
    o, s = run(cmd)
    check(cmd, o == [expect], f"{o} != {expect}")

print("== 4. ALL APPS ==")
# 'open terminal' is handled by the priority open_terminal skill (tested
# separately), not by the generic app-opening path.
for key, target in main.APP_MAP.items():
    if key == "terminal":
        continue
    o, s = run("open " + key)
    check(f"open {key}", any("OPENING_APP:" + target in x for x in s), str(s))

print("== 5. PLAY on YouTube (10 variations) ==")
play_cases = [
    ("play perfect by ed sheeran", "perfect+by+ed+sheeran"),
    ("please play perfect by ad channel", "perfect+by+ad+channel"),
    ("open youtube and play despacito", "despacito"),
    ("play despacito on youtube", "despacito"),
    ("i want to play the song believer", "believer"),
    ("play shape of you", "shape+of+you"),
    ("can you play levitating", "levitating"),
    ("play hello by adele", "hello+by+adele"),
    ("play abc", "abc"),
    ("play a song called stereo hearts", "stereo+hearts"),
]
for i, (cmd, expect) in enumerate(play_cases, 1):
    o, s = run(cmd)
    ok = o and any("youtube.com/watch?v=" + expect in u for u in o)
    check(f"[{i}] {cmd}", ok, f"{o} {s}")

o, s = run("play some music")
check("play some music (no query) falls through to AI", not o and len(s) >= 1, f"{o} {s}")

main.JarvisApp._youtube_first_video = lambda self, q: None
o, s = run("play despacito")
check("play fallback -> results page",
      o and any("youtube.com/results?search_query=despacito" in u for u in o), str(o))
main.JarvisApp._youtube_first_video = fake_youtube_first_video

print("== 6. SEARCH / DOMAIN / UNKNOWN APP ==")
o, s = run("search for cute cats")
check("search for cute cats", o and "google.com/search?q=cute+cats" in o[0], str(o))
o, s = run("search python tutorial")
check("search python tutorial", o and "google.com/search" in o[0], str(o))
o, s = run("open example.com")
check("open example.com", o == ["https://example.com"], str(o))
o, s = run("open vlc")
check("open vlc falls back to google search", o and "google.com/search?q=vlc" in o[0], str(o))

print("== 7. BUILD WEBSITE -> Google AI Studio prompt (real Groq call) ==")
main.time.sleep = lambda s: None
app.listen = lambda *a, **k: ""
js_calls = []


def fake_js_exec(self, js):
    js_calls.append(js)
    if "STEP='INSERT'" in js:
        return "inserted"
    return "clicked"


main.JarvisApp._aistudio_js_exec = fake_js_exec
for i in range(2):
    opened.clear()
    said.clear()
    _FakePyperclip.copied = []
    _FakePyautogui.log = []
    js_calls.clear()
    app.process("build me a website about space exploration")
    check(f"build website run {i}: opened AI Studio",
          any("aistudio.google.com" in u for u in opened), str(opened))
    check(f"build website run {i}: prompt copied to clipboard",
          len(_FakePyperclip.copied) == 1
          and "space exploration" in _FakePyperclip.copied[0],
          str(_FakePyperclip.copied))
    check(f"build website run {i}: ran start/type/insert/run JS",
          len(js_calls) == 4
          and all(s in " ".join(js_calls) for s in
                  ("STEP='START'", "STEP='TYPE'", "STEP='INSERT'", "STEP='RUN'")),
          str(js_calls))
    check(f"build website run {i}: spoke status", len(said) >= 1, str(said))

main.JarvisApp._aistudio_js_exec = lambda self, js: None
opened.clear()
said.clear()
_FakePyperclip.copied = []
_FakePyautogui.log = []
app.process("build me a website about space exploration")
check("build website fallback -> clipboard paste via pyautogui",
      ("hotkey", ("command", "v")) in _FakePyautogui.log
      and ("hotkey", ("command", "enter")) in _FakePyautogui.log,
      str(_FakePyautogui.log))
main.JarvisApp._aistudio_js_exec = fake_js_exec

print("== 8. Chat fallback (local brain first, then real Groq) ==")
for i, q in enumerate(["tell me a fun fact", "who made you",
                       "say the alphabet in 5 words"], 1):
    opened.clear()
    said.clear()
    app.process(q)
    check(f"AI chat [{i}] {q}", len(said) >= 1 and "I hit an error" not in " ".join(said), str(said))

print("== 9. Undefined-method bug is gone ==")
check("_try_open_app_name not referenced in main.py",
      not re.search(r"self\._try_open_app_name|def _try_open_app_name",
                    open(main.__file__).read()),
      "still referenced in main.py")

print("== 10. REGRESSION: edge cases (mocked AI/weather) ==")
main.ask_ai = lambda prompt, history=None: "AI_MARKER"
main.load_api_key = lambda: "test-key"
app.listen = lambda *a, **k: ""
main.get_weather = lambda loc: f"Weather in {loc}: 28 degrees, clear."

o, s = run("what time is the movie")
check("movie time -> AI (not local clock)", not o and s == ["AI_MARKER"], str(o) + str(s))
o, s = run("what time is it in new york")
check("time + location -> AI", not o and s == ["AI_MARKER"], str(o) + str(s))
o, s = run("what time is it in the morning")
check("time-of-day is not a location",
      not o and s and s[0].startswith("The time is"), str(o) + str(s))
o, s = run("search for play doh")
check("search not hijacked by play",
      o and "google.com/search?q=play+doh" in o[0], str(o) + str(s))
o, s = run("open youtube and open google")
check("compound: both open",
      o == ["https://www.youtube.com", "https://www.google.com"], str(o))
o, s = run("open google maps and weather")
check("compound: maps + weather",
      o == ["https://maps.google.com",
            "https://www.google.com/search?q=weather"], str(o))
o, s = run("open")
check("bare open -> clarification", not o and s and "open" in s[0].lower(), str(o) + str(s))
o, s = run("go to")
check("bare go to -> clarification", not o and s and "open" in s[0].lower(), str(o) + str(s))
o, s = run("play fortnite")
check("game is not played on youtube", not o and s and "game" in s[0].lower(), str(o) + str(s))
o, s = run("youtube")
check("bare youtube opens", o == ["https://www.youtube.com"], str(o) + str(s))
o, s = run("gmail")
check("bare gmail opens", o == ["https://mail.google.com"], str(o) + str(s))
o, s = run("what is 5 plus 7")
check("local calculator", not o and s and "equals 12" in s[0], str(o) + str(s))
o, s = run("what is the weather in mumbai")
check("weather lookup", s and "mumbai" in s[0].lower(), str(o) + str(s))
o, s = run("open the youtuve")
check("fuzzy typo -> youtube", o and "youtube" in o[0], str(o) + str(s))
o, s = run("clear your memory")
check("clear memory", not o and s and "memory" in s[0].lower(), str(o) + str(s))

print("== 11. NEW CAPABILITIES ==")
o, s = run("convert 5 miles to kilometers")
check("convert length", s and "kilometers" in s[0].lower(), str(s))
o, s = run("what is 100 fahrenheit in celsius")
check("convert temperature", s and "celsius" in s[0].lower(), str(s))
o, s = run("convert 2 gigabytes to megabytes")
check("convert data", s and "megabytes" in s[0].lower(), str(s))
o, s = run("what time will it be in 2 hours")
check("future time", s and "it will be" in s[0], str(s))
o, s = run("set a timer for 60 minutes")
check("timer set", s and "timer set" in s[0].lower(), str(s))
o, s = run("cancel the timer")
check("cancel timer", s and "cancel" in s[0].lower(), str(s))
o, s = run("what is the battery")
check("battery status", s and s[0].lower().startswith("battery"), str(s))
o, s = run("define quantum")
check("define -> wikipedia", o and "wikipedia.org" in o[0], str(o) + str(s))
o, s = run("search wikipedia for quantum physics")
check("search wikipedia", o and "wikipedia.org" in o[0], str(o) + str(s))
o, s = run("tell me a joke")
check("joke via local brain", s and s[0].endswith("sir."), str(s))
saved_joke = list(s)
o, s = run("repeat that")
check("repeat last reply", s == saved_joke, str(s))
o, s = run("set a timer for 2 minutes and open youtube")
check("compound timer + open",
      s and "timer set" in s[0].lower()
      and o and o[-1] == "https://www.youtube.com", str(o) + str(s))

print("== 12. LOCAL NEURAL BRAIN (through process) ==")
brain_cases = {
    "hello": "sir",
    "how are you": "operational",
    "who are you": "JARVIS",
    "thank you": "sir",
    "compliment me": "sir",
    "motivate me": "sir",
    "tell me a joke": "sir",
    "tell me a fun fact": "sir",
    "give me a quote": "sir",
    "flip a coin": "sir",
    "roll a d20": "You rolled",
    "choose between pizza and pasta": "sir",
    "generate a password": "password",
    "generate a uuid": "UUID",
    "random number between 1 and 100": "Your number",
    "word count hello world": "2 words",
    "reverse hello world": "dlrow",
    "is racecar a palindrome": "palindrome",
    "spell the word jarvis": "jarvis is spelled",
    "what is 1994 in roman numerals": "MCMXCIV",
    "what is 255 in binary": "11111111",
    "what is the ascii code for a": "97",
    "is 2024 a leap year": "Yes",
    "how many days until christmas": "days until christmas",
    "how old am i if i was born in 1995": "years old",
    "what day of the week was july 4 1999": "Sunday",
    "what is the factorial of 5": "120",
    "what is the square root of 16": "4",
    "what is 5 squared": "25",
    "how much is 20 percent of 50": "10",
    "is 17 a prime number": "prime",
    "first 8 fibonacci numbers": "13",
    "average of 10 20 30": "20",
    "area of a circle with radius 5": "78.54",
    "hypotenuse of a 3 4 triangle": "5",
    "bmi for 70 kg and 1.75 meters": "22.86",
    "15 percent tip on 50": "7.5",
    "convert 100 usd to inr": "8350",
    "who am i": "sir",
    "what can you do": "brain",
    "summarize the history of rome": "AI_MARKER",
    "compose an email to my boss": "AI_MARKER",
    "write a poem about the ocean": "AI_MARKER",
    "tell me a story about a dragon": "AI_MARKER",
    "give me a trivia question": "AI_MARKER",
    "what is a black hole": "AI_MARKER",
}
for i, (c, needle) in enumerate(brain_cases.items(), 1):
    o, s = run(c)
    check(f"brain [{i}] {c}",
          s and needle.lower() in s[0].lower() and not o, str(s))
import brain as _brain
check("brain skill_count >= 275", _brain.Brain().skill_count >= 275,
      str(_brain.Brain().skill_count))

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
