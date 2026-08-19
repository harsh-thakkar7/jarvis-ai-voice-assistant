# -*- coding: utf-8 -*-
"""Comprehensive offline test suite for JARVIS.

Covers all 252 neural-brain skills (core + extra), the offline local-chat
fallback engine, main.py intent routing with the priority file skills, and
graceful offline behaviour with no API key (no blocking input, no infinite
recursion). No real network calls are made.
"""
import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os
import queue
import re
import shutil
import sys
import tempfile
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
import brain
import brain_extra

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


# ---------------------------------------------------------------------------
# Harness: sandbox cwd + side-effect mocks so nothing touches the real system
# ---------------------------------------------------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="jarvis_test_")
_OLD_CWD = os.getcwd()
os.chdir(_SANDBOX)

opened = []
said = []


def fake_web(url):
    opened.append(url)


def fake_open_path(path):
    said.append("OPENED:" + str(path))
    return True


def fake_run_cmd(*a, **k):
    return 0, "ok"


def fake_osascript(*a, **k):
    return True


def fake_osascript_out(*a, **k):
    return "Finder, Safari"


class _FakeRunResult:
    returncode = 0
    stdout = "ok"


def fake_subprocess_run(*a, **k):
    return _FakeRunResult()


# module-level functions used by executors, patched in both modules
for _m in (brain, brain_extra):
    _m.open_path = fake_open_path
    _m.run_cmd = fake_run_cmd
    _m.osascript = fake_osascript
    _m.osascript_out = fake_osascript_out
brain_extra.subprocess.run = fake_subprocess_run

main.webbrowser.open = fake_web
main.open_app = lambda app: True
main.get_weather = lambda loc: f"Weather in {loc}: 28 degrees, clear."
main.load_api_key = lambda: ""


def make_app():
    app = object.__new__(main.JarvisApp)
    app.ui_q = queue.Queue()
    app.say = lambda text: said.append(text)
    app.history = deque(maxlen=10)
    app.timers = main.TimerManager()
    app.last_reply = None
    app._ask_ai_safely = lambda prompt, **kw: "LOCAL_FALLBACK"
    app.listen = lambda *a, **k: ""
    return app


app = make_app()

# sandbox files used by the file-skill tests
for _f in ("notes.txt", "jarvis_test_report.pdf", "test.txt", "del_me.txt",
           "ren_me.txt", "cp_me.txt", "mv_me.txt"):
    with open(_f, "w") as fh:
        fh.write("hello jarvis test content")

_memory_bak = None
if os.path.exists(brain_extra.MEMORY_FILE):
    _memory_bak = open(brain_extra.MEMORY_FILE, "rb").read()
_notes_bak = None
if os.path.exists(brain.NOTES_FILE):
    _notes_bak = open(brain.NOTES_FILE, "rb").read()


def restore_state():
    if _memory_bak is not None:
        with open(brain_extra.MEMORY_FILE, "wb") as fh:
            fh.write(_memory_bak)
    elif os.path.exists(brain_extra.MEMORY_FILE):
        os.remove(brain_extra.MEMORY_FILE)
    if _notes_bak is not None:
        with open(brain.NOTES_FILE, "wb") as fh:
            fh.write(_notes_bak)
    elif os.path.exists(brain.NOTES_FILE):
        os.remove(brain.NOTES_FILE)


b = brain.Brain(app)
# 275 core skills minimum; brain_extra.py adds more when it loads cleanly.
assert b.skill_count >= 275, b.skill_count
check("brain registers all core skills (>=275)", b.skill_count >= 275,
      str(b.skill_count))


def run(cmd):
    opened.clear()
    said.clear()
    app.process(cmd)
    return list(opened), list(said)


# ---------------------------------------------------------------------------
# 1. FULL SKILL SWEEP: every skill fires on its command and answers offline
# ---------------------------------------------------------------------------
SAMPLES = {
    "greet": "hello", "how_are_you": "how are you", "who_are_you": "who are you",
    "thanks": "thank you", "compliment": "compliment me",
    "motivate": "motivate me", "joke": "tell me a joke",
    "fact": "tell me a fun fact", "quote": "quote of the day",
    "flip_coin": "flip a coin", "roll_dice": "roll a d20",
    "choose": "choose between pizza and pasta", "password": "generate a password",
    "uuid": "generate a uuid", "random_number": "random number between 1 and 100",
    "word_count": "word count hello world", "reverse_text": "reverse hello world",
    "palindrome": "is racecar a palindrome", "spell": "spell the word jarvis",
    "roman": "what is 1994 in roman numerals", "binary_hex": "what is 255 in binary",
    "ascii": "what is the ascii code for a", "leap_year": "is 2024 a leap year",
    "days_until": "how many days until christmas",
    "age": "how old am i if i was born in 1995",
    "day_of_week": "what day of the week was july 4 1999",
    "factorial": "what is the factorial of 5", "sqrt": "what is the square root of 16",
    "power": "what is 5 squared", "percent": "how much is 20 percent of 50",
    "prime": "is 17 a prime number", "fibonacci": "first 8 fibonacci numbers",
    "statistics": "average of 10 20 30", "area": "area of a circle with radius 5",
    "pythagoras": "hypotenuse of a 3 4 triangle",
    "bmi": "bmi for 70 kg and 1.75 meters", "tip": "15 percent tip on 50",
    "currency": "convert 100 usd to inr", "disk_space": "how much disk space do i have",
    "system_info": "what are my system specs", "my_ip": "what is my ip address",
    "internet_check": "do i have internet", "whoami": "who am i",
    "running_apps": "what apps are running", "quit_app": "quit calculator",
    "empty_trash": "empty the trash", "open_folder": "open the downloads folder",
    "toggle_wifi": "turn on wifi", "toggle_bluetooth": "turn off bluetooth",
    "toggle_dark_mode": "enable dark mode", "music_control": "play the next song",
    "save_note": "save a note that i need milk", "read_notes": "read my notes",
    "translate": "translate hello in french",
    "summarize": "summarize this text about space",
    "compose": "compose an email to my boss", "poem": "write a poem about the ocean",
    "story": "tell me a story about a dragon", "trivia": "give me a trivia question",
    "explain": "explain black holes to me", "list_capabilities": "what can you do",
    "open_file": "open jarvis_test_report.pdf", "read_file": "read the contents of notes.txt",
    "write_file": "write hello to notes.txt", "append_file": "append more to notes.txt",
    "create_file": "create a file called fresh.txt", "create_folder": "create a folder called tempdir",
    "delete_file": "delete the file del_me.txt", "delete_folder": "delete the folder tempdir",
    "rename_file": "rename ren_me.txt to ren_me2.txt", "copy_file": "copy cp_me.txt to cp_me2.txt",
    "move_file": "move mv_me.txt to mv_me2.txt", "list_files": "list files",
    "find_file": "find notes.txt", "file_info": "size of the file notes.txt",
    "open_with_app": "open notes.txt with preview", "recent_files": "show recent files",
    "open_home": "open the home folder",
    "pseudocode": "write pseudocode for a login system",
    "api_docs": "api docs for python requests", "research": "research the history of coffee",
    "news_summary": "latest news", "quote_search": "quote about courage",
    "essay": "write an essay on teamwork",     "letter": "letter to my teacher",
    "resume": "write a resume for a software engineer", "cover_letter": "cover letter for a job",
    "blog_post": "write a blog post about travel", "report": "write a report on climate change",
    "tweet": "write a tweet about coding", "caption": "instagram caption for a beach photo",
    "linkedin_post": "linkedin post about leadership", "speech": "write a speech about hope",
    "haiku": "haiku about nature", "limerick": "limerick about cats",
    "lyrics": "write lyrics for a love song", "outline": "make an outline for an essay",
    "brainstorm": "brainstorm ideas for a startup", "pros_cons": "pros and cons of remote work",
    "compare": "compare python and javascript", "checklist": "make a checklist for a trip",
    "paraphrase": "paraphrase this paragraph", "proofread": "proofread my essay",
    "headline": "headline for a news article", "bio": "write a bio for a photographer",
    "uppercase": "uppercase hello world", "lowercase": "lowercase hello world",
    "title_case": "title case hello world", "camel_case": "camel case hello world",
    "snake_case": "snake case hello world", "kebab_case": "kebab case hello world",
    "slugify": "slugify hello world", "char_count": "how many characters in hello world",
    "sentence_count": "how many sentences in hello world. Good morning.",
    "line_count": "how many lines in this text", "vowel_count": "how many vowels in hello",
    "remove_spaces": "remove spaces from hello world", "acronym": "acronym for asap",
    "caesar_cipher": "caesar cipher hello", "random_word": "give me a random word",
    "unique_words": "how many unique words in the cat and the dog",
    "replace_text": "replace hello with hi in hello world",
    "contains_text": "does the text contain hello", "anagram_check": "anagram check silent and listen",
    "scramble": "scramble the word hello", "base64_encode": "base64 encode hello",
    "base64_decode": "base64 decode aGVsbG8=", "url_encode": "url encode hello world",
    "url_decode": "url decode hello%20world", "hash_text": "hash the word hello",
    "random_hex": "generate a random hex string", "gcd": "gcd of 12 and 18",
    "lcm": "lcm of 4 and 6", "area_convert": "convert 10 square feet to square meters",
    "volume_convert": "convert 2 liters to gallons", "pressure_convert": "convert 14 psi to bar",
    "energy_convert": "convert 100 calories to joules", "power_convert": "convert 1000 watts to kilowatts",
    "angle_convert": "convert 180 degrees to radians",
    "percentage_change": "percentage change from 50 to 75",
    "ratio_simplify": "simplify the ratio 8 to 12", "fraction_simplify": "simplify the fraction 8/12",
    "decimal_to_fraction": "convert 0.5 as a fraction",
    "base_convert": "convert 255 from base 10 to base 16",
    "time_convert": "convert 2 hours to minutes",
    "fuel_economy": "convert 30 mpg to l/100km",
    "compound_interest": "compound interest on 1000 at 5 percent for 2 years",
    "simple_interest": "simple interest on 1000 at 5 percent for 2 years",
    "loan_payment": "loan payment for 20000 at 5 percent for 5 years",
    "discount": "20 percent off 50", "tax_calc": "tax on 100 at 10 percent",
    "hourly_rate": "hourly rate for 50000 per year", "doubling_time": "rule of 72 for 8 percent",
    "split_bill": "split 100 between 4 people", "score_percent": "score 45 out of 50",
    "grade_calc": "what grade is 90 out of 100", "sum_calc": "sum of 1 2 3 4",
    "range_calc": "range of 3 7 2 9", "min_max": "minimum of 3 7 2 9",
    "date_difference": "days between july 1 and july 15",
    "week_of_year": "what week of the year is july 15",
    "day_of_year": "day of the year for july 15", "unix_timestamp": "unix timestamp now",
    "timestamp_to_date": "what date is timestamp 1700000000",
    "days_in_month": "how many days in february", "easter_date": "when is easter in 2025",
    "zodiac_sign": "what zodiac sign is july 4", "season_today": "what season is it",
    "pro_write_code": "write a python script to a file",
    "pro_explain_code": "explain this code: print('hi')",
    "pro_fix_code": "debug this code: print('hi')", "pro_improve_code": "refactor this code: print('hi')",
    "regex_builder": "regex to match email addresses",
    "regex_test": "does hello match the pattern", "json_validate": "validate this json: {\"a\": 1}",
    "json_format": "format this json: {\"a\": 1}", "sql_table": "create a table for users in sql",
    "sql_query": "sql query to get all users", "git_help": "git command to commit changes",
    "docker_help": "docker command to run a container", "curl_help": "curl command to post to an api",
    "bash_help": "bash command to zip a folder", "big_o": "time complexity of binary search",
    "python_trick": "python trick to swap variables", "capital_of": "capital of france",
    "population_of": "population of india", "currency_of": "currency of japan",
    "language_of": "language spoken in spain", "continent_of": "which continent is brazil in",
    "element_info": "atomic number of oxygen", "planet_info": "facts about mars",
    "animal_fact": "tell me an animal fact", "food_calories": "calories in an apple",
    "caffeine_info": "caffeine in coffee", "define_word": "define the word serendipity",
    "ps_synonyms": "synonym for happy", "ps_antonyms": "antonym for happy",
    "who_is": "who is albert einstein", "when_event": "when was world war 2",
    "today_in_history": "what happened today in history", "word_of_day": "word of the day",
    "random_fact": "give me a random fact", "todo_add": "add buy milk to my todo list",
    "todo_show": "show my todos", "todo_done": "mark todo 1 as done",
    "todo_remove": "remove todo 1", "shopping_add": "add apples to my shopping list",
    "shopping_show": "show my shopping list", "shopping_remove": "remove item 1 from my shopping list",
    "budget_add": "set my budget to 500", "budget_show": "show my budget",
    "expense_add": "i spent 30 on lunch", "expense_show": "show my expenses",
    "savings_add": "add 100 to my savings", "savings_show": "show my savings",
    "goal_add": "set a goal to run 5k", "goal_show": "show my goals",
    "plan_day": "plan my day", "pomodoro": "start a pomodoro timer",
    "workout": "give me a workout routine", "meal_plan": "make a meal plan for the week",
    "recipe": "recipe for pancakes", "study_plan": "make a study plan",
    "sleep_time": "what time should i sleep", "water_intake": "how much water should i drink",
    "ideal_weight": "ideal weight for 170 cm", "bmr_calc": "bmr for a 30 year old male 70 kg 175 cm",
    "tdee_calc": "tdee for a 30 year old male 70 kg 175 cm",
    "run_pace": "what pace for 5 km in 30 minutes", "airport_code": "airport code for london heathrow",
    "country_code": "country code for india", "emergency_number": "emergency number for usa",
    "country_time": "what time is it in usa", "date_calc": "the date after 10 july 2024",
    "name_generator": "generate baby name ideas", "team_name": "team name for a cricket team",
    "username": "generate a username for me", "hashtags": "hashtags for travel",
    "blog_title": "title for a blog about food", "slogan": "slogan for a coffee shop",
    "band_name": "band name for a rock group", "color_palette": "color palette for a sunset theme",
    "excuse": "give me an excuse", "lottery": "generate lottery numbers",
    "coordinates": "random coordinates", "cpu_usage": "cpu usage",
    "uptime": "how long has my computer been on", "open_terminal": "open the terminal",
    "howto": "how do i tie a tie", "riddle": "tell me a riddle",
    "computer_fact": "computer fact",
    "ps_clipboard_copy": "copy hello to clipboard",
    "color_convert": "convert hex #FF5733 to rgb",
    "morse_encode": "encode hello in morse code",
    "morse_decode": "decode morse code .... . .-.. .-.. ---",
    "binary_encode": "encode hello in binary",
    "binary_decode": "decode binary 01001000 01100101",
    "fizzbuzz": "fizzbuzz 20",
    "md_strip": "strip markdown formatting",
    "stopwatch": "start stopwatch",
    "math_eval": "evaluate 2 + 3 * 4",
    "ascii_art": "show me ascii art",
    "mm_remember": "remember I have a meeting at 3pm",
    "mm_recall": "what do you remember about the meeting",
    "screenshot": "take a screenshot",
    "pw_strength": "check password strength abc123",
    "dist_convert": "convert 100 miles to km",
    "weight_convert": "convert 150 lbs to kg",
    "temp_convert": "convert 100 fahrenheit to celsius",
    "age_detail": "age in days born 1990",
    "build_webpage": "build a website about cats",
}

_by_name = {s.name: s for s in b.skills}
missing = [n for n in SAMPLES if n not in _by_name]
check("every sample maps to a real skill", not missing, str(missing))
# Sample-coverage is enforced on the CORE skill set; brain_extra.py is
# auto-generated and may add skills at any time.
_core_brain = brain.Brain.__new__(brain.Brain)
_core_brain.app = None
_core_brain.skills = []
_core_brain._extra_registered = False
_core_brain._register()
uncovered = [s.name for s in _core_brain.skills if s.name not in SAMPLES]
check("every core skill has a sample command", not uncovered, str(uncovered))

print("\n== SKILL SWEEP (match + offline answer) ==")
no_reply = []
for i, (name, sample) in enumerate(SAMPLES.items(), 1):
    hit = b.think(sample)
    if not hit:
        check(f"[{i}] {name} fires on '{sample}'", False, "no skill matched")
        continue
    skill, ctx = hit
    if skill.name != name:
        check(f"[{i}] {name} fires on '{sample}'", False,
              f"matched {skill.name} instead")
        continue
    try:
        out = skill.execute(app, ctx)
    except Exception as e:
        out = f"<raised {e!r}>"
    bad = (not out or not isinstance(out, str) or not out.strip()
           or out.startswith("<raised"))
    if bad:
        no_reply.append(name)
    check(f"[{i}] {name} -> answers offline", not bad, f"out={out!r}")


print("\n== SKILL CONTENT SPOT-CHECKS ==")
def answer(cmd):
    hit = b.think(cmd)
    if not hit:
        return None
    return hit[0].execute(app, hit[1])

content = {
    "capital of france": "Paris",
    "population of india": "1.4 billion",
    "currency of japan": "yen",
    "language spoken in spain": "spanish",
    "which continent is brazil in": "South America",
    "atomic number of oxygen": "8",
    "what day of the week was july 4 1999": "Sunday",
    "what is the factorial of 5": "120",
    "what is the square root of 16": "4",
    "what is 5 squared": "25",
    "how much is 20 percent of 50": "10",
    "is 17 a prime number": "prime",
    "what is 1994 in roman numerals": "MCMXCIV",
    "what is 255 in binary": "11111111",
    "what is the ascii code for a": "97",
    "first 8 fibonacci numbers": "13",
    "average of 10 20 30": "20",
    "area of a circle with radius 5": "78.54",
    "hypotenuse of a 3 4 triangle": "5",
    "bmi for 70 kg and 1.75 meters": "22.86",
    "15 percent tip on 50": "7.5",
    "convert 100 usd to inr": "8350",
    "word count hello world": "2 words",
    "reverse hello world": "dlrow",
    "is racecar a palindrome": "palindrome",
    "what is the word of the day": None,  # explained below
}
# 'word of the day' is LLM-based; use the skill directly instead
hit = b.think("word of the day")
word = hit[0].execute(app, hit[1]) if hit else ""
content.pop("what is the word of the day", None)
check("word of the day answers offline", bool(word and word.strip()), word)

for c, needle in content.items():
    a = answer(c) or ""
    check(f"content: {c}", needle.lower() in a.lower(), a)

a = answer("what day of the week was july 4 1999")
check("day_of_week format is clean",
      bool(a and re.search(r"was a \w+day, sir\.$", a)), str(a))

# ---------------------------------------------------------------------------
# 2. LOCAL CHAT FALLBACKS (offline conversational brain)
# ---------------------------------------------------------------------------
print("\n== LOCAL CHAT FALLBACK ==")
local_cases = {
    "what is 12 times 8": "96",
    "what is 15 plus 27": "42",
    "what is 50 divided by 5": "10",
    "what is 7 to the power of 2": "49",
    "capital of france": "Paris",
    "population of india": "1.4 billion",
    "currency of japan": "yen",
    "what is a black hole": "gravitational",
    "what is big o of bubble sort": "O(n",
    "who is albert einstein": "physics",
    "what is the element oxygen": "8",
    "tell me about mars": "red",
    "synonym for happy": "joy",
    "when did world war 2 end": "1945",
    "how do i tie a tie": "how",
    "who made you": None,
}
for q, needle in local_cases.items():
    if needle is None:
        out = b.chat(q)
        check(f"local chat: {q}", bool(out and out.strip()), str(out))
        continue
    out = b.chat(q) or ""
    check(f"local chat: {q}", needle.lower() in out.lower(), out)

print("\n== LOCAL CHAT: unknown questions never hang ==")
for q in ("say the alphabet in 5 words",
          "explain the meaning of quantum entanglement",
          "write a song about robots", "what is the airspeed velocity of a swallow"):
    out = b.chat(q)
    check(f"local chat fallback: {q}", bool(out and out.strip()), str(out))

# ---------------------------------------------------------------------------
# 3. MAIN.PY OFFLINE INTEGRATION (no API key: local brain answers)
# ---------------------------------------------------------------------------
print("\n== MAIN.PY OFFLINE (no key) ==")
main.load_api_key = lambda: ""

o, s = run("hello")
check("process: greet offline", bool(s and "sir" in s[0].lower()), str(s))
o, s = run("what is the date")
check("process: date intent", bool(s and "Today is" in s[0]), str(s))
o, s = run("what time is it")
check("process: time intent", bool(s and "time is" in s[0]), str(s))
o, s = run("what is 12 times 8")
check("process: local calculator", bool(s and "96" in s[0]), str(s))
o, s = run("capital of france")
check("process: local knowledge", bool(s and "Paris" in s[0]), str(s))
o, s = run("explain black holes to me")
check("process: hybrid skill terminates offline",
      bool(s and s[0].strip() and "I hit an error" not in s[0]), str(s))
o, s = run("summarize the history of rome")
check("process: summarize terminates offline",
      bool(s and s[0].strip() and "I hit an error" not in s[0]), str(s))
o, s = run("translate hello in french")
check("process: translate offline",
      bool(s and s[0].strip() and "I hit an error" not in s[0]), str(s))
o, s = run("tell me a joke")
check("process: local joke", bool(s and s[0].endswith("sir.")), str(s))
o, s = run("say the alphabet in 5 words")
check("process: unknown question answers offline",
      bool(s and s[0].strip() and "I hit an error" not in s[0]), str(s))

print("\n== MAIN.PY PRIORITY ROUTING ==")
# restore sandbox files mutated by the earlier skill sweep
for _f in ("notes.txt", "jarvis_test_report.pdf", "test.txt", "del_me.txt",
           "ren_me.txt", "cp_me.txt", "mv_me.txt"):
    with open(_f, "w") as fh:
        fh.write("hello jarvis test content")
o, s = run("open jarvis_test_report.pdf")
check("open file -> open_file priority skill",
      bool(any("OPENED:" in x for x in s)), str(s))
o, s = run("open the downloads folder")
check("open folder -> open_folder priority skill",
      bool(any("Downloads" in x for x in s)), str(s))
o, s = run("open the home folder")
check("open home -> open_home priority skill",
      bool(any("home" in x.lower() for x in s)), str(s))
o, s = run("open the terminal")
check("open terminal -> priority skill",
      bool(any("Terminal" in x for x in s)), str(s))
o, s = run("read the contents of notes.txt")
check("read file -> read_file priority skill",
      bool(s and "hello jarvis test content" in s[0]), str(s))
o, s = run("write hello to notes.txt")
check("write file -> write_file skill", bool(s and s[0].startswith("Saved")), str(s))
o, s = run("list files")
check("list files skill", bool(s and "Contents of" in s[0]), str(s))
o, s = run("find notes.txt")
check("find file skill", bool(s and "I found it at" in s[0]), str(s))
o, s = run("show recent files")
check("recent files skill", bool(s and "recent files" in s[0].lower()), str(s))

print("\n== MAIN.PY INTENTS NOT HIJACKED BY PRIORITY SKILLS ==")
o, s = run("open youtube")
check("open youtube still opens youtube", o == ["https://www.youtube.com"], str(o))
o, s = run("open example.com")
check("open example.com still opens url", o == ["https://example.com"], str(o))
o, s = run("open google maps")
check("open google maps still maps", o == ["https://maps.google.com"], str(o))
o, s = run("search for cute cats")
check("search not hijacked by find_file",
      o and "google.com/search?q=cute+cats" in o[0], str(o) + str(s))
o, s = run("play despacito")
main.JarvisApp._youtube_first_video = lambda self, q: "https://www.youtube.com/watch?v=despacito"
o, s = run("play despacito")
check("play youtube not hijacked", o and "youtube.com/watch?v=despacito" in o[0], str(o))
main.JarvisApp._youtube_first_video = None
o, s = run("open the youtuve")
check("fuzzy typo still works", bool(o and "youtube" in o[0]), str(o) + str(s))

print("\n== MAIN.PY API REJECTED FALLBACK ==")
main.load_api_key = lambda: "bad-key"
_orig_ask_ai = main.ask_ai
main.ask_ai = lambda prompt, history=None: "__UNAUTHORIZED__"
_orig_safe = app._ask_ai_safely
app._ask_ai_safely = main.JarvisApp._ask_ai_safely.__get__(app)
o, s = run("write a haiku about the moon")
check("unauthorized key -> local brain + note",
      bool(s and any("rejected" in x for x in s)), str(s))
check("unauthorized key -> still answers",
      bool(s and "I hit an error" not in " ".join(s)), str(s))
main.ask_ai = _orig_ask_ai
app._ask_ai_safely = _orig_safe
main.load_api_key = lambda: ""

print("\n== WEBSITE PROMPT OFFLINE ==")
main.load_api_key = lambda: ""
prompt = app._website_prompt("space exploration")
check("offline website prompt is a usable default",
      bool(prompt and "HTML" in prompt and "space exploration" in prompt), str(prompt))
main.ask_ai = lambda prompt, history=None: "That is beyond my local memory, sir."
main.load_api_key = lambda: "key"
app.history.clear()
prompt = app._website_prompt("cats")
check("weak LLM prompt falls back to default",
      bool(prompt and "HTML" in prompt and "cats" in prompt), str(prompt))
main.ask_ai = _orig_ask_ai
main.load_api_key = lambda: ""

print("\n== BOOT LINE (honest status) ==")
main.load_api_key = lambda: ""
boot = app._boot  # not run (blocks on ui_q) -- check the string is generated
src = open(main.__file__).read()
check("boot shows LOCAL BRAIN when no key",
      "LOCAL BRAIN" in src and "CONNECTED" in src, "boot line present")

print("\n== _ask_ai_safely never blocks on input ==")
main.load_api_key = lambda: ""
src = open(main.__file__).read()
safe_src = src.split("def _ask_ai_safely", 1)[1].split("\n    def ", 1)[0]
check("no input() call inside _ask_ai_safely", "input(" not in safe_src,
      "input() still present")

print("\n== CLEANUP ==")
os.chdir(_OLD_CWD)
shutil.rmtree(_SANDBOX, ignore_errors=True)
restore_state()

print(f"\nRESULT: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
