# -*- coding: utf-8 -*-
import os as _os, sys as _sys
_PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _PROJECT_ROOT not in _sys.path:
    _sys.path.insert(0, _PROJECT_ROOT)

import os, sys, re, tempfile, queue, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main, brain, brain_extra

passed = failed = 0
RUNS = 10

def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  FAIL  %s  %s" % (label, detail))

class FakeCanvas:
    def create_text(self, *a, **kw): return 0
    def create_rectangle(self, *a, **kw): return 0
    def create_line(self, *a, **kw): return 0
    def create_oval(self, *a, **kw): return 0
    def itemconfig(self, *a, **kw): pass
    def coords(self, *a, **kw): pass
    def delete(self, *a, **kw): pass
    def find_withtag(self, *a): return []

class FakeLabel:
    def __init__(self, *a, **kw):
        self._text = kw.get("text", "")
        self._fg = kw.get("fg", "")
    def config(self, **kw):
        if "text" in kw: self._text = kw["text"]
        if "fg" in kw: self._fg = kw["fg"]

def make_app():
    app = object.__new__(main.JarvisApp)
    app.ui_q = queue.Queue()
    app.history = []
    app.last_reply = ""
    app.power = 0.98
    app.cpu = 12.0
    app.mem = 45.0
    app.awake = True
    app.running = threading.Event()
    app.running.set()
    app.ai_mode = "LOCAL"
    app.canvas = FakeCanvas()
    app.val_labels = {"AI CORE": FakeLabel(text="LOCAL", fg="#ffd700")}
    app.api_hint_lbl = FakeLabel(text="Say 'set api key' to enable Groq")
    app.micro_lbl = FakeLabel(text="LOCAL // OFFLINE BRAIN")
    app.notes_path = os.path.join(tempfile.mkdtemp(), "notes.txt")
    app.log_path = os.path.join(tempfile.mkdtemp(), "log.txt")
    app.history_path = os.path.join(tempfile.mkdtemp(), "history.json")
    app.memory_path = os.path.join(tempfile.mkdtemp(), "memory.json")
    app.memory = {}
    app.brain = None
    app._extra_registered = False
    app.speech_done = threading.Event()
    app.speech_done.set()
    app.engine = None
    app._say_log = []
    _orig_say = main.JarvisApp.say
    def _mock_say(self_app, text):
        print("JARVIS:", text)
        self_app._say_log.append(text)
        self_app.ui_q.put(("say", text))
    main.JarvisApp.say = _mock_say
    return app


print("== RESEARCH + WRITE DETECTION (x10) ==")
for i in range(RUNS):
    app = make_app()
    check("r%d research about ronaldo write to notes" % (i+1),
          app._is_research_write("research about ronaldo and write to notes.txt"))
    check("r%d research on AI write in notes" % (i+1),
          app._is_research_write("research on AI write in my notes.txt"))
    check("r%d write a report about mars" % (i+1),
          app._is_research_write("write a report about mars to file.txt"))
    check("r%d write about dogs in notes" % (i+1),
          app._is_research_write("write about dogs in notes.txt"))
    check("r%d write an essay on climate" % (i+1),
          app._is_research_write("write an essay on climate in notes.txt"))
    check("r%d write hello to notes NOT detected" % (i+1),
          not app._is_research_write("write hello to notes.txt"))
    check("r%d open youtube NOT detected" % (i+1),
          not app._is_research_write("open youtube"))
    check("r%d weather NOT detected" % (i+1),
          not app._is_research_write("what is the weather"))
    check("r%d research alone NOT detected" % (i+1),
          not app._is_research_write("research ronaldo"))
    check("r%d save research about mars detected" % (i+1),
          app._is_research_write("save research about mars to report.txt"))

print("== EXTRACT WRITE FILE (x10) ==")
for i in range(RUNS):
    app = make_app()
    check("r%d extract notes.txt" % (i+1),
          app._extract_write_file("research about dogs and write in notes.txt") == "notes.txt")
    check("r%d extract report.md" % (i+1),
          app._extract_write_file("write a report about mars to report.md") == "report.md")
    check("r%d extract my_file.html" % (i+1),
          app._extract_write_file("save research about cats to my_file.html") == "my_file.html")
    check("r%d extract None" % (i+1),
          app._extract_write_file("research ronaldo") is None)
    check("r%d extract data.csv" % (i+1),
          app._extract_write_file("write about sports in data.csv") == "data.csv")

print("== CODE WRITE DETECTION (x10) ==")
for i in range(RUNS):
    app = make_app()
    check("r%d write code calc.py" % (i+1),
          app._is_code_write("write code for calculator in calc.py"))
    check("r%d generate fib script" % (i+1),
          app._is_code_write("generate a fibonacci script to fib.js"))
    check("r%d create sorting algo" % (i+1),
          app._is_code_write("create sorting algorithm in sort.py"))
    check("r%d write login program" % (i+1),
          app._is_code_write("write a login program in login.html"))
    check("r%d write hello NOT detected" % (i+1),
          not app._is_code_write("write hello to notes.txt"))
    check("r%d open calculator NOT detected" % (i+1),
          not app._is_code_write("open calculator"))
    check("r%d write calculator code" % (i+1),
          app._is_code_write("write calculator code in pie_chart.py"))
    check("r%d write calculator code py" % (i+1),
          app._is_code_write("write a calculator code in my pie_chart.py"))

print("== MODE INDICATION (x10) ==")
for i in range(RUNS):
    app = make_app()
    app.ai_mode = None
    app._set_ai_mode("LOCAL")
    check("r%d LOCAL set" % (i+1), app.ai_mode == "LOCAL")
    check("r%d LOCAL label" % (i+1), app.val_labels["AI CORE"]._text == "LOCAL")
    check("r%d LOCAL gold fg" % (i+1), app.val_labels["AI CORE"]._fg == "#ffd24d")
    check("r%d LOCAL hint visible" % (i+1), "set api key" in app.api_hint_lbl._text.lower())
    app.ai_mode = None
    app._set_ai_mode("ONLINE")
    check("r%d ONLINE set" % (i+1), app.ai_mode == "ONLINE")
    check("r%d ONLINE label" % (i+1), app.val_labels["AI CORE"]._text == "ONLINE")
    check("r%d ONLINE green fg" % (i+1), app.val_labels["AI CORE"]._fg == "#3fd97a")
    check("r%d ONLINE hint empty" % (i+1), app.api_hint_lbl._text == "")

print("== CHOOSE 3+ OPTIONS (x10) ==")
for i in range(RUNS):
    b = brain.Brain()
    r = b.think("choose between apple, banana, cherry, and dates")
    check("r%d 4-option detected" % (i+1), r is not None)
    if r:
        skill, ctx = r
        check("r%d parsed 4 opts" % (i+1), len(ctx["options"]) == 4)
        result = skill.execute(None, ctx)
        pick = result.replace(", sir.", "").strip().lower()
        opts_lower = [o.lower() for o in ctx["options"]]
        check("r%d pick valid" % (i+1), pick in opts_lower)
    r2 = b.think("choose red or blue")
    check("r%d 2-option works" % (i+1), r2 is not None)
    if r2:
        skill2, ctx2 = r2
        result2 = skill2.execute(None, ctx2)
        pick2 = result2.replace(", sir.", "").strip().lower()
        check("r%d 2-opt valid" % (i+1), pick2 in ["red", "blue"])
    r3 = b.think("choose between python, javascript, go, rust, and java")
    check("r%d 5-option detected" % (i+1), r3 is not None)
    if r3:
        skill3, ctx3 = r3
        check("r%d parsed 5 opts" % (i+1), len(ctx3["options"]) == 5)

print("== ASCII EDGE CASES (x10) ==")
for i in range(RUNS):
    b = brain.Brain()
    r = b.think("ascii of A")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d ascii A=65" % (i+1), result is not None and "65" in result, str(result))
    r = b.think("ascii 97")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d ascii 97=a" % (i+1), result is not None and "a" in result.lower(), str(result))
    r = b.think("ascii 999999")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d ascii big handled" % (i+1), result is not None, str(result))

print("== POWER EDGE CASES (x10) ==")
for i in range(RUNS):
    b = brain.Brain()
    r = b.think("2 squared")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d 2sq=4" % (i+1), result is not None and "4" in result, str(result))
    r = b.think("3 cubed")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d 3cube=27" % (i+1), result is not None and "27" in result, str(result))
    r = b.think("2 to the power of 10")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d 2^10=1024" % (i+1), result is not None and "1024" in result, str(result))
    r = b.think("squared")
    check("r%d squared alone returns None" % (i+1), r is None)
    r = b.think("5 to the power of 40")
    if r:
        skill, ctx = r
        result = skill.execute(None, ctx)
    else:
        result = None
    check("r%d huge exp warned" % (i+1), result is not None and "large" in result.lower(), str(result))

print("== WRITE FILE INTEGRATION (x10) ==")
for i in range(RUNS):
    app = make_app()
    fpath = os.path.join(os.path.dirname(os.path.abspath(main.__file__)), "mars_report.txt")
    _orig_gen = app._generate_content
    app._generate_content = lambda p, **kw: ("This is a research report about Mars.\nMars is the 4th planet.", None)
    app._handle_research_write("research about mars and write to mars_report.txt")
    app._generate_content = _orig_gen
    if os.path.exists(fpath):
        with open(fpath, "r") as f:
            content = f.read()
        check("r%d research file created" % (i+1), "Research Report: Mars" in content, content[:80])
        os.remove(fpath)
    else:
        check("r%d research file created" % (i+1), False, "file not found")

print("== CODE WRITE INTEGRATION (x10) ==")
for i in range(RUNS):
    app = make_app()
    fpath = os.path.join(os.path.dirname(os.path.abspath(main.__file__)), "test_calc_output.py")
    _orig_gen = app._generate_content
    app._generate_content = lambda p, **kw: ("def calc(a, b):\n    return a + b", None)
    app._handle_code_write("write calculator code in test_calc_output.py")
    app._generate_content = _orig_gen
    if os.path.exists(fpath):
        with open(fpath, "r") as f:
            content = f.read()
        check("r%d code file created" % (i+1), "def calc" in content, content[:80])
        os.remove(fpath)
    else:
        check("r%d code file created" % (i+1), False, "file not found")

print("== _ask_ai_safely RATE LIMIT HANDLING ==")
for i in range(RUNS):
    app = make_app()
    app.ai_mode = None
    saved = main.ask_ai
    def fake_rate_limit(prompt, hist=None):
        return "__RATE_LIMITED__"
    main.ask_ai = fake_rate_limit
    result = app._ask_ai_safely("test prompt")
    main.ask_ai = saved
    check("r%d rate limit detected" % (i+1), "API key limit" in result, result)
    check("r%d switched to local" % (i+1), app.ai_mode == "LOCAL")
    check("r%d hint shown" % (i+1), "set api key" in app.api_hint_lbl._text.lower())

    app2 = make_app()
    app2.ai_mode = None
    main.ask_ai = lambda p, h=None: "__UNAUTHORIZED__"
    result2 = app2._ask_ai_safely("test prompt")
    main.ask_ai = saved
    check("r%d unauthorized handled" % (i+1), "rejected" in result2.lower(), result2)
    check("r%d unauthorized -> local" % (i+1), app2.ai_mode == "LOCAL")

print("\nRESULT: %d passed, %d failed" % (passed, failed))
