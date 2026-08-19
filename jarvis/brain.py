# -*- coding: utf-8 -*-
"""JARVIS neural brain: a local rule-based skill engine that falls back to
the Groq LLM for open-ended language tasks. Local skills stay fast and free;
hybrid skills detect the intent locally and let the LLM do the heavy lifting."""

import datetime
import getpass
import math
import os
import platform
import random
import re
import shutil
import socket
import string
import subprocess
import threading
import uuid

NOTES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "jarvis_notes.txt")

MONTH_NUM = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
             "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
             "november": 11, "december": 12}
MONTH_ABBR = {k[:3]: v for k, v in MONTH_NUM.items()}

FOLDER_PATHS = {
    "downloads": "~/Downloads",
    "documents": "~/Documents",
    "desktop": "~/Desktop",
    "pictures": "~/Pictures",
    "movies": "~/Movies",
    "applications": "/Applications",
    "apps": "/Applications",
    "library": "~/Library",
}

QUIT_MAP = {
    "calculator": "Calculator", "notes": "Notes", "photos": "Photos",
    "music": "Music", "terminal": "Terminal", "finder": "Finder",
    "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
    "spotify": "Spotify", "word": "Microsoft Word", "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint", "settings": "System Settings",
    "code": "Visual Studio Code", "vscode": "Visual Studio Code",
    "pycharm": "PyCharm", "docker": "Docker", "slack": "Slack",
    "zoom": "Zoom", "messages": "Messages", "mail": "Mail",
    "calendar": "Calendar", "reminders": "Reminders", "preview": "Preview",
    "textedit": "TextEdit", "text edit": "TextEdit", "steam": "Steam",
    "tv": "TV", "podcasts": "Podcasts", "contacts": "Contacts",
    "facetime": "FaceTime", "stocks": "Stocks", "clock": "Clock",
    "home": "Home", "shortcuts": "Shortcuts",
}

CURRENCY = {
    "usd": 1.0, "eur": 0.92, "inr": 83.5, "gbp": 0.79, "jpy": 149.0,
    "cad": 1.36, "aud": 1.52, "chf": 0.88, "cny": 7.2, "aed": 3.67,
}
CURRENCY_ALIAS = {
    "$": "usd", "usd": "usd", "dollar": "usd", "dollars": "usd",
    "\u20ac": "eur", "eur": "eur", "euro": "eur", "euros": "eur",
    "\u00a3": "gbp", "gbp": "gbp", "pound": "gbp", "pounds": "gbp",
    "\u00a5": "jpy", "jpy": "jpy", "yen": "jpy",
    "\u20b9": "inr", "inr": "inr", "rupee": "inr", "rupees": "inr", "rs": "inr",
    "cad": "cad", "canadian": "cad",
    "aud": "aud", "australian": "aud",
    "chf": "chf", "franc": "chf", "francs": "chf",
    "cny": "cny", "yuan": "cny",
    "aed": "aed", "dirham": "aed", "dhs": "aed",
}

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs, sir.",
    "Why did the computer go to the doctor? It caught a virus, sir.",
    "Why did the developer go broke? Because they used up all their cache, sir.",
    "There are only 10 kinds of people: those who understand binary and those who do not, sir.",
    "Why was the JavaScript developer sad? Because they did not know how to null their feelings, sir.",
    "Why do robots never win at poker? They always fold under pressure, sir.",
    "I told my computer I needed a break, and now it will not stop sending me KitKat ads, sir.",
    "Why is a computer so good at golf? It never misses a drive, sir.",
]
FACTS = [
    "Honey never spoils. Archaeologists have found edible honey in ancient tombs, sir.",
    "Octopuses have three hearts and blue blood, sir.",
    "A day on Venus is longer than its year, sir.",
    "Bananas are berries, but strawberries are not, sir.",
    "There are more possible chess games than atoms in the observable universe, sir.",
    "Humans share about 60 percent of their DNA with bananas, sir.",
    "The Eiffel Tower grows about 15 centimeters taller in summer heat, sir.",
    "Sharks existed before trees, sir.",
    "Your brain generates enough electricity to power a small light bulb, sir.",
]
QUOTES = [
    "The best way to predict the future is to invent it, sir. - Alan Kay",
    "Stay hungry, stay foolish, sir. - Steve Jobs",
    "The only way to do great work is to love what you do, sir. - Steve Jobs",
    "Success is not final, failure is not fatal. It is the courage to continue that counts, sir. - Churchill",
    "Simplicity is the ultimate sophistication, sir. - Leonardo da Vinci",
    "The future belongs to those who learn more skills and combine them in creative ways, sir. - Robert Greene",
    "In the middle of difficulty lies opportunity, sir. - Albert Einstein",
]
COMPLIMENTS = [
    "You have the mind of a true innovator",
    "Your focus today has been genuinely impressive",
    "You make complex problems look effortless",
    "Your curiosity is one of your greatest assets",
    "You think like a strategist, not just a solver",
    "You are the kind of person legends are built from",
]
MOTIVATION = [
    "Great things never come from comfort zones, sir. Step out and claim today.",
    "You do not have to be great to start, but you have to start to be great, sir.",
    "Discipline is choosing between what you want now and what you want most, sir.",
    "Every expert was once a beginner who refused to give up, sir.",
    "The expert in anything was once a beginner, sir.",
    "Your only limit is the one you set in your mind, sir.",
]


def osascript(script):
    if platform.system() != "Darwin":
        return False
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def osascript_out(script):
    if platform.system() != "Darwin":
        return ""
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def run_cmd(*args, timeout=15):
    try:
        r = subprocess.run(list(args), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception:
        return -1, ""


def open_path(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.run(["open", path], capture_output=True)
        return True
    except Exception:
        return False


_llm_depth = threading.local()


def _llm(app, prompt):
    if getattr(_llm_depth, "depth", 0) > 0:
        return None
    _llm_depth.depth = getattr(_llm_depth, "depth", 0) + 1
    try:
        fn = getattr(app, "_ask_ai_safely", None)
        if fn is None:
            return None
        reply = fn(prompt)
        if not reply or reply == "__UNAUTHORIZED__":
            return None
        if isinstance(reply, str) and reply.startswith("I hit an error"):
            return None
        return reply
    except Exception:
        return None
    finally:
        _llm_depth.depth = getattr(_llm_depth, "depth", 0) - 1


def _nums(cmd):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", cmd)]


def _int_nums(cmd):
    return [int(x) for x in re.findall(r"\d+", cmd)]


def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _net_ok():
    try:
        s = socket.create_connection(("8.8.8.8", 53), timeout=5)
        s.close()
        return True
    except Exception:
        return False


def _month_day(cmd):
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                  r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(\d{4}))?", cmd)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return MONTH_ABBR[m.group(1)], int(m.group(2)), year
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
                  r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
                  r"(?:\s+(\d{4}))?", cmd)
    if m:
        year = int(m.group(3)) if m.group(3) else None
        return MONTH_ABBR[m.group(2)], int(m.group(1)), year
    return None


def _kw(*phrases):
    def detect(cmd):
        for p in phrases:
            if re.search(r"\b" + re.escape(p) + r"\b", cmd):
                return {"phrase": p}
        return None
    return detect


def _kw_greet(*phrases):
    def detect(cmd):
        c = cmd.strip()
        for p in phrases:
            if re.match(r"^" + re.escape(p) + r"\b.*$", c, re.I):
                return {"phrase": p}
        return None
    return detect


class Skill:
    def __init__(self, name, detect, execute, priority=False):
        self.name = name
        self.detect = detect
        self.execute = execute
        self.priority = priority


class Brain:
    # Old coding-execution skills superseded by code_brain_pro; pruned so
    # the PRO versions (registered later) are not shadowed by first-match.
    SUPERSEDED_SKILLS = frozenset({
        "cb_py_function", "cb_js_code", "cb_class", "cb_script",
        "cb_gen_feature", "cb_api_flask", "cb_explain_request",
        "cb_debug_request", "cb_improve_request", "cb_py_to_js",
        "cb_translate", "generate_code", "explain_code", "debug_code",
        "refactor_code", "code_to_file",
        # Legacy clipboard skill fires on ANY message containing
        # "clipboard", shadowing the whole ps_clipboard family.
        "clip_copy",
        # Structured dictionaryapi.dev versions replace the LLM-only ones.
        "synonym", "antonym",
    })

    def __init__(self, app=None):
        self.app = app
        self.skills = []
        self._extra_registered = False
        self._register()
        self.load_extra()
        self._prune_superseded()
        self._load_pro_modules()

    def _prune_superseded(self):
        """Drop old coding skills replaced by code_brain_pro equivalents."""
        if any(s.name in self.SUPERSEDED_SKILLS for s in self.skills):
            self.skills = [s for s in self.skills
                           if s.name not in self.SUPERSEDED_SKILLS]

    def _load_pro_modules(self):
        """Register the upgraded coding/file/power skill packs (fail-soft)."""
        for mod_name in ("code_brain_pro", "file_power", "power_skills",
                         "web_dev_brain", "app_dev_brain",
                         "calendar_music_skills", "mail_skills",
                         "live_screen_brain", "journal_brain",
                         "data_file_tools", "agent_loop",
                         "memory_core", "security_hardening",
                         "briefing_brain", "focus_pomodoro_brain",
                         "net_diagnostics_brain", "ptt_onboarding"):
            try:
                __import__(mod_name).register(self)
            except Exception as exc:
                print("WARNING: %s failed to load: %s" % (mod_name, exc))
        self._load_skill_packs()

    def _load_skill_packs(self):
        """Auto-discover ``skills_*.py`` plug-in modules in the project dir.

        Any module named ``skills_<domain>.py`` exposing ``register(brain)``
        is loaded fail-soft, so new skill packs can be dropped in without
        touching this file.
        """
        import glob
        here = os.path.dirname(os.path.abspath(__file__))
        _packs_dir = here
        for path in sorted(glob.glob(os.path.join(_packs_dir, "skills_*.py"))):
            mod_name = os.path.splitext(os.path.basename(path))[0]
            if not hasattr(self, "_loaded_skill_packs"):
                self._loaded_skill_packs = set()
            if mod_name in self._loaded_skill_packs:
                continue
            self._loaded_skill_packs.add(mod_name)
            try:
                __import__(mod_name).register(self)
            except Exception as exc:
                print("WARNING: %s failed to load: %s" % (mod_name, exc))

    def load_extra(self):
        """Load and register brain_extra.py skills (safe to call repeatedly)."""
        if getattr(self, "_extra_registered", False):
            return True
        try:
            from brain_extra import register_extra
            register_extra(self)
            self._extra_registered = True
            return True
        except Exception as e:
            print("WARNING: brain_extra.py skills failed to load:", e)
            return False

    def register(self, name, detect, execute, priority=False,
                 supersedes=()):
        """Append a skill, optionally pruning the ones it supersedes.

        ``supersedes`` makes replacement relationships explicit so new
        modules can never be shadowed by legacy detectors again.
        """
        self.skills.append(Skill(name, detect, execute, priority))
        if supersedes:
            dead = set(supersedes)
            self.skills = [s for s in self.skills if s.name not in dead]
        # Fresh registrations must not be shadowed by cached misses.
        cache = getattr(self, "_think_cache", None)
        if cache:
            cache.clear()

    @property
    def skill_count(self):
        return len(self.skills)

    def chat(self, text, _code_gen_mode=False):
        self.load_extra()
        # Persistent memory: every exchange lands in the turn log so
        # memory survives restarts.
        try:
            import memory_core
            if text and len(text) < 400:
                memory_core.log_turn("YOU", text)
        except Exception:
            pass
        # Deep-think reasoning layer first: structured step-by-step
        # answers for word problems, plans, comparisons, mechanisms.
        try:
            import deepthink
            reasoned = deepthink.answer(self, text)
            if reasoned:
                self._log_reply(reasoned)
                return reasoned
        except Exception:
            pass
        try:
            from brain_extra import local_chat
            reply = local_chat(self, text, _code_gen_mode=_code_gen_mode)
            self._log_reply(reply)
            return reply
        except Exception as e:
            print("WARNING: offline chat unavailable:", e)
            return None

    def _log_reply(self, reply):
        try:
            if reply and len(str(reply)) < 400:
                import memory_core
                memory_core.log_turn("JARVIS", str(reply))
        except Exception:
            pass

    def think(self, cmd, priority=None):
        # Skill intents are short command phrases. For very large pasted text
        # (e.g. a multi-page essay) the hundreds of detection regexes would
        # otherwise scan the entire buffer many times over. Match against a
        # bounded window of the command so detection stays cheap while every
        # realistic command still matches.
        detect_cmd = cmd
        if len(cmd) > 6000:
            detect_cmd = cmd[:4000]
        cache = getattr(self, "_think_cache", None)
        if cache is not None:
            key = (priority, cmd)
            hit = cache.get(key)
            if hit is not None:
                return hit[0] or None
            found = None
        else:
            key, found = None, None
        for s in self.skills:
            if priority is not None and s.priority != priority:
                continue
            try:
                ctx = s.detect(detect_cmd)
            except Exception:
                ctx = None
            if ctx:
                found = (s, ctx)
                break
        if cache is not None and key is not None:
            if len(cache) > 500:
                cache.clear()
            cache[key] = (found,)
        return found

    def _register(self):
        self.register("greet", _kw_greet("hello", "hi", "hey", "greetings",
                                         "good morning", "good afternoon",
                                         "good evening", "namaste", "howdy",
                                         "good day"), self._greet)
        self.register("how_are_you", _kw("how are you", "how are you doing",
                                         "how do you do", "how is it going",
                                         "how have you been", "whats up",
                                         "what's up", "how goes it"),
                      self._status)
        self.register("who_are_you", _kw("who are you", "who are u",
                                         "what are you", "introduce yourself",
                                         "tell me about yourself",
                                         "what is your name",
                                         "what's your name", "your name",
                                         "your specs"), self._intro)
        self.register("thanks", _kw("thank you", "thank u", "thanks a lot",
                                    "thanks", "much obliged", "appreciate it",
                                    "thank you so much", "cheers"),
                      self._thanks)
        self.register("compliment", _kw("compliment", "say something nice",
                                        "praise me", "give me a compliment",
                                        "something encouraging"),
                      self._compliment)
        self.register("motivate", _kw("motivate", "inspire me",
                                      "motivational", "give me motivation",
                                      "encourage me"), self._motivate)
        self.register("joke", _kw("tell me a joke", "tell a joke",
                                  "make me laugh", "another joke",
                                  "say a joke", "a joke", "joke"),
                      self._joke)
        self.register("fact", _kw("fun fact", "tell me a fact",
                                  "an interesting fact", "another fact",
                                  "give me a fact",
                                  "tell me something interesting",
                                  "fact about"), self._fact)
        self.register("quote", self._quote_detect, self._quote)
        self.register("flip_coin", _kw("flip a coin", "flip the coin",
                                       "toss a coin", "toss the coin",
                                       "coin flip", "heads or tails",
                                       "flip coin", "toss coin"),
                      self._flip_coin)
        self.register("roll_dice", self._dice_detect, self._roll_dice)
        self.register("choose", self._choose_detect, self._choose)
        self.register("password", self._password_detect, self._password)
        self.register("uuid", _kw("uuid", "generate a uuid"), self._uuid)
        self.register("random_number", self._random_detect, self._random_number)
        self.register("word_count", self._word_count_detect, self._word_count)
        self.register("reverse_text", self._reverse_detect, self._reverse_text)
        self.register("palindrome", self._palindrome_detect, self._palindrome)
        self.register("spell", self._spell_detect, self._spell)
        self.register("roman", self._kw_num("roman"), self._roman)
        self.register("binary_hex", self._binary_detect, self._binary_hex)
        self.register("ascii", self._ascii_detect, self._ascii)
        self.register("leap_year", self._leap_detect, self._leap_year)
        self.register("days_until", self._days_until_detect, self._days_until)
        self.register("age", self._age_detect, self._age)
        self.register("day_of_week", self._dow_detect, self._day_of_week)
        self.register("factorial", self._kw_num("factorial"), self._factorial)
        self.register("sqrt", self._kw_num("square root", "sqrt"), self._sqrt)
        self.register("power", self._power_detect, self._power)
        self.register("percent", self._percent_detect, self._percent)
        self.register("prime", self._kw_num("prime"), self._prime)
        self.register("fibonacci", self._kw_num("fibonacci"), self._fibonacci)
        self.register("statistics", self._stats_detect, self._statistics)
        self.register("area", self._area_detect, self._area)
        self.register("pythagoras", self._kw_cmd("hypotenuse", "pythagorean",
                                                 "pythagoras"), self._pythagoras)
        self.register("bmi", self._kw_cmd("bmi", "body mass index"), self._bmi)
        self.register("tip", self._kw_cmd("tip"), self._tip)
        self.register("currency", self._currency_detect, self._currency)
        self.register("disk_space", self._disk_detect, self._disk_space)
        self.register("system_info", self._sysinfo_detect, self._system_info)
        self.register("my_ip", _kw("my ip", "ip address", "my ip address"),
                      self._my_ip)
        self.register("internet_check", self._internet_detect,
                      self._internet_check)
        self.register("whoami", _kw("who am i", "my username",
                                    "current user", "what user am i"),
                      self._whoami)
        self.register("running_apps", self._running_detect, self._running_apps)
        self.register("quit_app", self._quit_detect, self._quit_app)
        self.register("empty_trash", _kw("empty trash", "empty the trash"),
                      self._empty_trash)
        self.register("open_folder", self._folder_detect, self._open_folder,
                      priority=True)
        self.register("toggle_wifi", self._wifi_detect, self._toggle_wifi)
        self.register("toggle_bluetooth", self._bluetooth_detect,
                      self._toggle_bluetooth)
        self.register("toggle_dark_mode", self._dark_detect,
                      self._toggle_dark_mode)
        self.register("music_control", self._music_detect, self._music_control)
        self.register("save_note", self._save_note_detect, self._save_note)
        self.register("read_notes", self._read_notes_detect, self._read_notes)
        self.register("translate", self._translate_detect, self._translate)
        self.register("summarize", self._summarize_detect, self._summarize)
        self.register("compose", self._compose_detect, self._compose)
        self.register("poem", self._poem_detect, self._poem)
        self.register("story", self._story_detect, self._story)
        self.register("trivia", _kw("trivia", "quiz me", "quiz", "trivia question"),
                      self._trivia)
        self.register("explain", self._explain_detect, self._explain)
        self.register("list_capabilities", self._capable_detect,
                      self._capabilities)

    # ---- detect helpers ----

    def _dice_detect(self, cmd):
        if re.search(r"\broll\b.*\b(?:die|dice|d\d+)\b|\broll\s+d\d+", cmd):
            return {"m": cmd}
        return None

    def _num_detect(self, cmd):
        nums = _int_nums(cmd)
        return {"num": nums[0]} if nums else None

    def _kw_num(self, *phrases):
        def detect(cmd):
            if any(re.search(r"\b" + re.escape(p) + r"\b", cmd) for p in phrases):
                nums = _int_nums(cmd)
                if nums:
                    return {"num": nums[0]}
            return None
        return detect

    def _kw_cmd(self, *phrases):
        def detect(cmd):
            if any(re.search(r"\b" + re.escape(p) + r"\b", cmd) for p in phrases):
                return {"cmd": cmd}
            return None
        return detect

    def _random_detect(self, cmd):
        if re.search(r"\b(random number|pick a number|random integer)\b", cmd):
            return {"m": cmd}
        return None

    def _choose_detect(self, cmd):
        m = re.search(r"\b(?:choose|pick)\s+(?:between\s+)?(.+?)\s*$", cmd, re.I)
        if not m:
            return None
        raw = m.group(1).strip(" .,")
        opts = re.split(r"\s*,\s*|\s+or\s+|\s+and\s+", raw)
        opts = [o.strip(" .,!?") for o in opts if o.strip(" .,!?")]
        if len(opts) >= 2:
            return {"options": opts}
        return None

    def _password_detect(self, cmd):
        if re.search(r"\bpassword\b", cmd) and re.search(
                r"\b(generate|make|create|new|random)\b|\bgenerator\b|\bgive me\b",
                cmd):
            m = re.search(r"(\d+)\s*(?:characters?|chars?)?", cmd)
            return {"length": int(m.group(1)) if m else 16}
        return None

    def _word_count_detect(self, cmd):
        m = re.search(r"\bword count\b(.*)$|\bhow many words\b(.*)$", cmd, re.I)
        if not m:
            return None
        text = (m.group(1) or m.group(2) or "").strip()
        text = re.sub(r"^(?:in|are in|does that|does|are)\s*", "", text)
        return {"text": text}

    def _reverse_detect(self, cmd):
        m = re.search(r"\breverse\b\s+(.+)$|\bsay it backwards\s*[:.]?\s*(.+)$",
                      cmd, re.I)
        if m:
            return {"text": (m.group(1) or m.group(2) or "").strip()}
        return None

    def _palindrome_detect(self, cmd):
        if not re.search(r"\bpalindrome\b", cmd, re.I):
            return None
        m = re.search(r"\b(?:is\s+)?([a-z]+)\s+(?:a\s+)?palindrome", cmd, re.I)
        if m:
            return {"word": m.group(1)}
        w = re.sub(r"\bpalindrome\b.*", "", cmd).strip(" .!?")
        w = re.sub(r"^(?:is|a|an|the|word)\s+", "", w)
        w = w.split()[0] if w.split() else ""
        return {"word": w} if w else None

    def _spell_detect(self, cmd):
        m = re.search(r"\bspell\b(?: out)?(?: the word)?\s+(.+?)\s*$", cmd, re.I)
        if m:
            return {"word": m.group(1).strip().strip("?")}
        return None

    def _binary_detect(self, cmd):
        base = None
        if re.search(r"\bin\s+(binary|bin)\b|\bto\s+(binary|bin)\b", cmd):
            base = ("b", "binary")
        elif re.search(r"\bin\s+(hex|hexadecimal)\b|\bto\s+(hex|hexadecimal)\b",
                       cmd):
            base = ("x", "hexadecimal")
        elif re.search(r"\bin\s+(octal|oct)\b|\bto\s+(octal|oct)\b", cmd):
            base = ("o", "octal")
        if not base:
            return None
        nums = _int_nums(cmd)
        return {"num": nums[0], "base": base} if nums else None

    def _ascii_detect(self, cmd):
        if not re.search(r"\bascii\b", cmd, re.I):
            return None
        letter = re.search(r"\b([a-zA-Z])\b", cmd)
        if letter:
            return {"ch": letter.group(1)}
        nums = _int_nums(cmd)
        return {"ch": nums[0]} if nums else None

    def _leap_detect(self, cmd):
        if not re.search(r"\bleap year\b", cmd):
            return None
        nums = _int_nums(cmd)
        return {"year": nums[0] if nums else datetime.date.today().year}

    def _days_until_detect(self, cmd):
        if not re.search(r"\bdays? (until|till|before)\b|\bhow many days\b|"
                         r"\bcountdown to\b", cmd):
            return None
        c = cmd.lower()
        named = {"christmas": (12, 25, "christmas"),
                 "new year": (1, 1, "new year"),
                 "new years": (1, 1, "new year"),
                 "halloween": (10, 31, "halloween"),
                 "valentine": (2, 14, "valentine's day"),
                 "easter": None}
        for k, v in named.items():
            if k in c and v:
                return {"month": v[0], "day": v[1], "name": v[2]}
        if "birthday" in c:
            t = datetime.date.today()
            return {"month": t.month, "day": t.day, "name": "your birthday"}
        md = _month_day(c)
        if md:
            return {"month": md[0], "day": md[1], "year": md[2],
                    "name": "%s %d" % (list(MONTH_NUM.keys())[md[0] - 1], md[1])}
        return None

    def _age_detect(self, cmd):
        if not re.search(r"\bborn in\b|\bhow old am i\b|\bwhat is my age\b", cmd):
            return None
        m = re.search(r"\b((?:19|20)\d{2})\b", cmd)
        return {"year": int(m.group(1))} if m else None

    def _dow_detect(self, cmd):
        if not re.search(r"\bday of the week\b|\bwhat day was\b", cmd):
            return None
        today = datetime.date.today()
        if re.search(r"\btoday\b", cmd):
            return {"date": today}
        if re.search(r"\btomorrow\b", cmd):
            return {"date": today + datetime.timedelta(days=1)}
        if re.search(r"\byesterday\b", cmd):
            return {"date": today - datetime.timedelta(days=1)}
        md = _month_day(cmd)
        if not md:
            return {"date": today}
        year = md[2] if md[2] else today.year
        return {"date": datetime.date(year, md[0], md[1])}

    def _power_detect(self, cmd):
        if re.search(r"\bsquared\b", cmd):
            nums = _nums(cmd)
            if not nums:
                return None
            return {"base": nums[0], "exp": 2}
        if re.search(r"\bcubed\b", cmd):
            nums = _nums(cmd)
            if not nums:
                return None
            return {"base": nums[0], "exp": 3}
        m = re.search(r"(-?\d+(?:\.\d+)?)\s+to the power of\s+"
                      r"(-?\d+(?:\.\d+)?)", cmd)
        if m:
            return {"base": float(m.group(1)), "exp": float(m.group(2))}
        return None

    def _percent_detect(self, cmd):
        if not re.search(r"\bpercent(?:age)?\s+of\b", cmd):
            return None
        nums = _nums(cmd)
        return {"nums": nums} if len(nums) >= 2 else None

    def _stats_detect(self, cmd):
        m = re.search(r"\b(average|mean|median|mode)\s+of\b", cmd, re.I)
        if not m:
            return None
        nums = _nums(cmd)
        if not nums:
            return None
        return {"kind": m.group(1).lower(), "nums": nums}

    def _area_detect(self, cmd):
        if not re.search(r"\barea\b", cmd, re.I):
            return None
        for s in ("circle", "rectangle", "triangle", "square"):
            if s in cmd:
                return {"shape": s, "nums": _nums(cmd)}
        return None

    def _currency_detect(self, cmd):
        found = []
        for key, code in CURRENCY_ALIAS.items():
            if key.isalpha():
                m = re.search(r"(?<![a-z0-9])" + re.escape(key) +
                              r"(?![a-z0-9])", cmd, re.I)
            else:
                m = re.search(r"(?<![a-z0-9])" + re.escape(key), cmd, re.I)
            if m:
                if code not in found:
                    found.append(code)
        return {"codes": found, "cmd": cmd} if found else None

    def _disk_detect(self, cmd):
        return (re.search(r"\b(?:disk|drive|storage)\s+space\b|\bfree space\b|"
                          r"\bhow much space\b|\bhow much (?:disk|storage)\b",
                          cmd))

    def _sysinfo_detect(self, cmd):
        return re.search(r"\b(system info|system information|computer specs|"
                         r"my specs|system specs|machine specs|hardware|"
                         r"about my computer|os info)\b", cmd, re.I)

    def _internet_detect(self, cmd):
        return re.search(r"\b(is my internet|internet (working|connection|"
                         r"online|down)|check internet|test internet|"
                         r"are you online|are you connected|connectivity|"
                         r"do i have internet|do i have wifi)\b",
                         cmd)

    def _running_detect(self, cmd):
        return re.search(r"\b(running apps|what apps are running|"
                         r"which apps are running|running applications|"
                         r"list (?:the )?running)\b", cmd)

    def _quit_detect(self, cmd):
        m = re.match(r"^(?:close|quit|kill)\s+(?:the\s+)?(.+?)\s*$", cmd)
        if not m:
            return None
        return {"name": m.group(1).strip()}

    def _folder_detect(self, cmd):
        c = cmd.strip().lower()
        for key in FOLDER_PATHS:
            if c == key:
                return {"folder": key}
        m = re.search(r"\b(show|take me to|navigate to|browse|go into|open|"
                      r"open up|access|go to)\s+"
                      r"(?:the\s+)?([a-z]+)\s+(folder|directory)\b", cmd, re.I)
        if m and m.group(2).lower() in FOLDER_PATHS:
            return {"folder": m.group(2).lower()}
        m2 = re.search(r"\b(show|take me to|navigate to|browse|go into|open|"
                       r"open up|access|go to)\s+"
                       r"(?:the\s+)?([a-z]+)\b", cmd, re.I)
        if m2 and m2.group(2).lower() in FOLDER_PATHS:
            return {"folder": m2.group(2).lower()}
        return None

    def _wifi_detect(self, cmd):
        if not re.search(r"\bwifi\b|\bwi-fi\b|\bwireless\b", cmd):
            return None
        c = cmd.lower()
        if re.search(r"\b(off|disable|turn off|switch off)\b", c):
            return {"on": False}
        if re.search(r"\b(on|enable|turn on|switch on)\b", c):
            return {"on": True}
        return None

    def _bluetooth_detect(self, cmd):
        if not re.search(r"\bbluetooth\b", cmd):
            return None
        c = cmd.lower()
        if re.search(r"\b(off|disable|turn off|switch off)\b", c):
            return {"on": False}
        if re.search(r"\b(on|enable|turn on|switch on)\b", c):
            return {"on": True}
        return None

    def _dark_detect(self, cmd):
        if re.search(r"\bdark mode\b", cmd):
            return {"dark": True}
        if re.search(r"\blight mode\b", cmd):
            return {"dark": False}
        return None

    def _music_detect(self, cmd):
        c = cmd.lower()
        if re.search(r"\bpause\b", c) and re.search(r"\b(music|song|track)\b", c):
            return {"action": "pause"}
        if re.search(r"\bresume\b", c) and re.search(r"\b(music|song|track)\b", c):
            return {"action": "resume"}
        if re.search(r"\bstop\b", c) and re.search(r"\b(music|song|track)\b", c):
            return {"action": "stop"}
        if re.search(r"\bnext\b", c) and re.search(r"\b(song|track)\b", c):
            return {"action": "next"}
        if re.search(r"\b(previous|prev)\b", c) and re.search(r"\b(song|track)\b", c):
            return {"action": "previous"}
        if re.search(r"\bskip\b", c) and re.search(r"\b(song|track)\b", c):
            return {"action": "next"}
        return None

    def _save_note_detect(self, cmd):
        # NOTE: "remember that/this" intentionally NOT claimed here -
        # memory_core.mm_remember owns persistent recall for those.
        for p in ["save a note", "save this note", "take a note", "make a note",
                  "jot down", "note down",
                  "put this in my notes", "write this down"]:
            if p in cmd:
                text = re.split(p, cmd, 1, flags=re.I)[1].strip()
                text = re.sub(r"^(?:about|that|that:)\s*", "", text)
                return {"text": text}
        return None

    def _read_notes_detect(self, cmd):
        return re.search(r"\b(read|show) (my )?notes\b|\bwhat are my notes\b|"
                         r"\bmy notes\b", cmd)

    def _translate_detect(self, cmd):
        m = re.search(r"(?:translate|say)\s+['\"]?(.+?)['\"]?\s+"
                      r"(?:to|into|in)\s+([a-zA-Z][a-zA-Z '-]*?)\s*$", cmd, re.I)
        if m:
            return {"text": m.group(1).strip(),
                    "lang": m.group(2).strip().lower()}
        return None

    def _summarize_detect(self, cmd):
        m = re.search(r"^(?:summarize|summarise|sum up|tl;?dr|tldr)\b\s*(.*)$",
                      cmd, re.I)
        if m:
            return {"text": m.group(1).strip()}
        return None

    def _compose_detect(self, cmd):
        m = re.search(r"\b(?:compose|draft|write)\s+(?:an?|a)?\s*"
                      r"(email|message|text|letter)\b(.*)$", cmd, re.I)
        if m:
            return {"kind": m.group(1), "topic": m.group(2).strip()}
        return None

    def _poem_detect(self, cmd):
        if not re.search(r"\bpoem\b", cmd):
            return None
        m = re.search(r"\babout\s+(.+?)\s*$", cmd, re.I)
        return {"topic": m.group(1).strip() if m else None}

    def _story_detect(self, cmd):
        if not re.search(r"\bstory\b", cmd):
            return None
        m = re.search(r"\babout\s+(.+?)\s*$", cmd, re.I)
        return {"topic": m.group(1).strip() if m else None}

    def _explain_detect(self, cmd):
        m = re.search(r"^(?:explain|what is|what are|what's|whats)\s+(.+)$",
                      cmd, re.I)
        if not m:
            return None
        topic = m.group(1).strip().strip("?")
        if re.search(r"\b(?:code|script)\b", topic, re.I):
            return None
        return {"topic": topic, "cmd": cmd}

    def _capable_detect(self, cmd):
        if re.match(r"^(what can you do|what can u do|what do you do|"
                    r"how can you help|list your skills|your skills|"
                    r"your capabilities|capabilities|skills|help|help me)$",
                    cmd, re.I):
            return {"m": cmd}
        return None

    # ---- greetings / social ----

    def _greet(self, app, ctx):
        h = datetime.datetime.now().hour
        g = ("Good morning" if h < 12 else
             "Good afternoon" if h < 17 else "Good evening")
        return "%s, sir. How may I assist you?" % g

    def _status(self, app, ctx):
        st = getattr(app, "start_time", None)
        if st is None:
            st = datetime.datetime.now()
        m = int((datetime.datetime.now() - st).total_seconds() // 60)
        return ("All systems fully operational, sir. Uptime %d minutes. "
                "Ready when you are." % m)

    def _intro(self, app, ctx):
        return ("I am JARVIS, your personal AI assistant, sir. I combine a "
                "local neural brain with a large language model, and I control "
                "your computer, apps, websites, timers, and more.")

    def _thanks(self, app, ctx):
        return random.choice(["You are most welcome, sir.",
                              "Always at your service, sir.",
                              "My pleasure, sir."])

    def _compliment(self, app, ctx):
        return random.choice(COMPLIMENTS) + ", sir."

    def _motivate(self, app, ctx):
        return random.choice(MOTIVATION)

    def _joke(self, app, ctx):
        return random.choice(JOKES)

    def _fact(self, app, ctx):
        return random.choice(FACTS)

    def _quote(self, app, ctx):
        return random.choice(QUOTES)

    def _quote_detect(self, cmd):
        if re.search(r"\b(?:quote|quotes)\s+(?:about|on)\b", cmd, re.I):
            return None
        return _kw("quote of the day", "inspirational quote",
                   "give me a quote", "tell me a quote",
                   "a quote", "quote")(cmd)

    # ---- pure utilities ----

    def _flip_coin(self, app, ctx):
        return random.choice(["Heads, sir.", "Tails, sir."])

    def _roll_dice(self, app, ctx):
        m = re.search(r"d(\d+)", ctx.get("m", ""))
        sides = int(m.group(1)) if m else 6
        sides = max(2, min(sides, 1000))
        return "You rolled a %d, sir." % random.randint(1, sides)

    def _choose(self, app, ctx):
        pick = random.choice(ctx["options"]).strip(" .,!?")
        return "%s, sir." % pick.title()

    def _password(self, app, ctx):
        n = max(6, min(ctx.get("length", 16), 64))
        chars = string.ascii_letters + string.digits + "!@#$%&*"
        rng = random.SystemRandom()
        pw = "".join(rng.choice(chars) for _ in range(n))
        return ("Here is a %d character password: %s. I did not store it "
                "anywhere, sir." % (n, pw))

    def _uuid(self, app, ctx):
        return "Here is a fresh UUID, sir: %s." % uuid.uuid4()

    def _random_number(self, app, ctx):
        m = re.search(r"between\s+(\d+)\s+and\s+(\d+)", ctx.get("m", ""))
        lo, hi = (int(m.group(1)), int(m.group(2))) if m else (1, 100)
        if lo > hi:
            lo, hi = hi, lo
        return "Your number is %d, sir." % random.randint(lo, hi)

    def _word_count(self, app, ctx):
        text = ctx.get("text", "")
        n = len([w for w in text.split() if w.strip(".,!?")])
        if n == 0:
            return "I need some text to count, sir."
        return "That is %d words, sir." % n

    def _reverse_text(self, app, ctx):
        return "Here it is backwards, sir: " + ctx["text"][::-1]

    def _palindrome(self, app, ctx):
        word = ctx["word"].strip(" .!?,")
        w = re.sub(r"[^a-z0-9]", "", word.lower())
        if w and w == w[::-1]:
            return "Yes, %s is a palindrome, sir." % word
        return "No, %s is not a palindrome, sir." % word

    def _spell(self, app, ctx):
        word = ctx["word"]
        return "%s is spelled %s." % (word.title(), " ".join(list(word)))

    def _roman(self, app, ctx):
        n = ctx["num"]
        if n <= 0:
            return "I can only convert positive numbers to Roman numerals, sir."
        if n >= 4000:
            return "That number is too large for Roman numerals, sir."
        vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
                (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
        out = ""
        for v, sym in vals:
            while n >= v:
                out += sym
                n -= v
        return "%d in Roman numerals is %s." % (ctx["num"], out)

    def _binary_hex(self, app, ctx):
        n = ctx["num"]
        base, label = ctx["base"]
        return "%d in %s is %s." % (n, label, format(n, base))

    def _ascii(self, app, ctx):
        ch = ctx["ch"]
        if isinstance(ch, str):
            if len(ch) == 1:
                return "The ASCII code for %s is %d." % (ch, ord(ch))
            return "The ASCII code for the first character '%s' is %d." % (ch[0], ord(ch[0]))
        n = int(ch)
        if 0 <= n <= 1114111:
            return "The character for ASCII %d is %s." % (n, chr(n))
        return "The number %d is outside valid Unicode range, sir." % n

    def _leap_year(self, app, ctx):
        y = ctx["year"]
        leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
        if leap:
            return "Yes, %d is a leap year, sir." % y
        return "No, %d is not a leap year, sir." % y

    def _days_until(self, app, ctx):
        today = datetime.date.today()
        year = ctx.get("year")
        if year:
            target = datetime.date(year, ctx["month"], ctx["day"])
        else:
            target = datetime.date(today.year, ctx["month"], ctx["day"])
            if target < today:
                target = datetime.date(today.year + 1, ctx["month"], ctx["day"])
        days = (target - today).days
        return "%d days until %s, sir." % (days, ctx["name"])

    def _age(self, app, ctx):
        now = datetime.date.today().year
        return "You are %d years old, sir." % max(0, now - ctx["year"])

    def _day_of_week(self, app, ctx):
        d = ctx["date"]
        names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday")
        return "%s %d was a %s, sir." % (
            d.strftime("%B"), d.day, names[d.weekday()])

    def _factorial(self, app, ctx):
        n = ctx["num"]
        if n > 1000:
            return "That number is too large for me to compute, sir."
        if n < 0:
            return "Factorial is only defined for non-negative numbers, sir."
        return "The factorial of %d is %d." % (n, math.factorial(n))

    def _sqrt(self, app, ctx):
        n = ctx["num"]
        if n < 0:
            return "The square root of a negative number is imaginary, sir."
        return "The square root of %d is %g." % (n, math.sqrt(n))

    def _power(self, app, ctx):
        b = ctx.get("base")
        e = ctx.get("exp")
        if b is None or e is None:
            return "I need a base and an exponent, sir."
        try:
            b = float(b)
            e = float(e)
        except (TypeError, ValueError):
            return "I need valid numbers for the base and exponent, sir."
        if e > 30:
            return "That exponent is too large to compute quickly, sir."
        return "%g to the power of %g is %g." % (b, e, b ** e)

    def _percent(self, app, ctx):
        x, y = ctx["nums"][0], ctx["nums"][1]
        return "%g percent of %g is %g." % (x, y, x / 100.0 * y)

    def _prime(self, app, ctx):
        n = int(ctx["num"])
        if n < 2:
            return "No, %d is not a prime number, sir." % n
        for i in range(2, int(math.sqrt(n)) + 1):
            if n % i == 0:
                return "No, %d is not a prime number, sir." % n
        return "Yes, %d is a prime number, sir." % n

    def _fibonacci(self, app, ctx):
        n = min(40, ctx.get("num", 10))
        seq = [0, 1]
        while len(seq) < n:
            seq.append(seq[-1] + seq[-2])
        seq = seq[:n]
        return "The first %d Fibonacci numbers are: %s, sir." % (
            n, ", ".join(map(str, seq)))

    def _statistics(self, app, ctx):
        vals = ctx["nums"]
        kind = ctx["kind"]
        if kind in ("average", "mean"):
            r = sum(vals) / len(vals)
        elif kind == "median":
            sv = sorted(vals)
            n = len(sv)
            r = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2
        else:
            counts = {}
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
            r = max(counts, key=counts.get)
        return "The %s is %g, sir." % (kind, r)

    def _area(self, app, ctx):
        shape = ctx["shape"]
        nums = ctx["nums"]
        if shape == "circle":
            if not nums:
                return "For a circle I need its radius, sir."
            r = nums[0]
            return "The area of the circle is %g, sir." % round(math.pi * r * r, 2)
        if shape == "square":
            if not nums:
                return "For a square I need its side length, sir."
            s = nums[0]
            return "The area of the square is %g, sir." % round(s * s, 2)
        if shape == "rectangle":
            if len(nums) < 2:
                return "For a rectangle I need length and width, sir."
            return "The area of the rectangle is %g, sir." % round(
                nums[0] * nums[1], 2)
        if len(nums) < 2:
            return "For a triangle I need base and height, sir."
        return "The area of the triangle is %g, sir." % round(
            nums[0] * nums[1] / 2, 2)

    def _pythagoras(self, app, ctx):
        nums = _nums(ctx.get("cmd", ""))
        if len(nums) < 2:
            return "I need the two shorter sides, sir."
        return "The hypotenuse is %g, sir." % math.hypot(nums[0], nums[1])

    def _bmi(self, app, ctx):
        cmd = ctx["cmd"]
        weight = None
        height = None
        wm = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilos|kilograms?)", cmd)
        if wm:
            weight = float(wm.group(1))
        hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|metres?|meters?)\b", cmd)
        if hm:
            height = float(hm.group(1))
        else:
            hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimetres?|centimeters?)\b", cmd)
            if hm:
                height = float(hm.group(1)) / 100.0
        if weight is None or height is None:
            return "I need your weight in kilograms and height in meters, sir."
        bmi = round(weight / (height ** 2), 2)
        if bmi < 18.5:
            cat = "underweight"
        elif bmi < 25:
            cat = "normal"
        elif bmi < 30:
            cat = "overweight"
        else:
            cat = "obese"
        return "Your BMI is %g, which is %s, sir." % (bmi, cat)

    def _tip(self, app, ctx):
        cmd = ctx["cmd"]
        mp = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|%)", cmd)
        percent = float(mp.group(1)) if mp else 15.0
        nums = _nums(cmd)
        amount = None
        for n in nums:
            if mp is None or abs(n - percent) > 0.0001:
                amount = n
                break
        if amount is None:
            amount = nums[0] if nums else 0.0
        tip = amount * percent / 100.0
        return ("A %g percent tip on %g is %g, making a total of %g, sir."
                % (percent, amount, tip, amount + tip))

    def _currency(self, app, ctx):
        codes = ctx["codes"]
        nums = _nums(ctx["cmd"])
        if not nums:
            return "I need an amount to convert, sir."
        if len(codes) < 2:
            return "Tell me the from and to currencies, sir."
        fr, to = codes[0], codes[-1]
        amount = nums[0]
        usd = amount / CURRENCY[fr]
        conv = usd * CURRENCY[to]
        return "%g %s is about %g %s, sir." % (
            amount, fr.upper(), conv, to.upper())

    def _disk_space(self, app, ctx):
        try:
            usage = shutil.disk_usage("/")
        except Exception:
            return "I could not read the disk space, sir."
        return "Free space is %.1f gigabytes of %.1f total, sir." % (
            usage.free / 1e9, usage.total / 1e9)

    def _system_info(self, app, ctx):
        if platform.system() == "Darwin":
            os_name = "macOS"
            ver = platform.mac_ver()[0] or ""
        else:
            os_name = platform.system()
            ver = platform.release()
        return ("You are running %s %s on a %s machine with %d logical cores "
                "and Python %s, sir." % (os_name, ver, platform.machine(),
                                         os.cpu_count() or 0,
                                         platform.python_version()))

    def _my_ip(self, app, ctx):
        return "Your IP address is %s, sir." % _local_ip()

    def _internet_check(self, app, ctx):
        if _net_ok():
            return "Your internet connection is online, sir."
        return "I cannot reach the internet right now, sir."

    def _whoami(self, app, ctx):
        try:
            user = getpass.getuser()
        except Exception:
            try:
                user = os.getlogin()
            except Exception:
                user = "user"
        return "You are %s, sir." % user

    def _running_apps(self, app, ctx):
        out = osascript_out('tell application "System Events" to get name of '
                            'every process whose background only is false')
        names = [n.strip() for n in out.split(",") if n.strip()][:12]
        if not names:
            return "I could not read the running applications, sir."
        return "Running apps: " + ", ".join(names) + ", sir."

    def _quit_app(self, app, ctx):
        name = re.sub(r"\s+(app|application)s?\s*$", "", ctx["name"])
        app_name = QUIT_MAP.get(name.lower(),
                                name.title() if name else "")
        if not app_name:
            return "Which app should I close, sir?"
        if osascript('tell application "%s" to quit' % app_name):
            return "Closing %s, sir." % app_name
        return "I could not quit %s; it may not be running, sir." % app_name

    def _empty_trash(self, app, ctx):
        if osascript('tell application "Finder" to empty trash'):
            return "Trash emptied, sir."
        return "I could not empty the trash, sir."

    def _open_folder(self, app, ctx):
        key = ctx["folder"]
        path = os.path.expanduser(FOLDER_PATHS[key])
        if open_path(path):
            return "Opening the %s folder, sir." % key.title()
        return "I could not open the %s folder, sir." % key.title()

    def _toggle_wifi(self, app, ctx):
        state = "on" if ctx["on"] else "off"
        rc, _ = run_cmd("networksetup", "-setairportpower", "en0", state)
        if rc == 0:
            return "Wi-Fi turned %s, sir." % state
        return "I could not toggle Wi-Fi, sir."

    def _toggle_bluetooth(self, app, ctx):
        state = "1" if ctx["on"] else "0"
        rc, _ = run_cmd("blueutil", "-p", state)
        if rc == 0:
            return "Bluetooth turned %s, sir." % (
                "on" if ctx["on"] else "off")
        return "I could not toggle Bluetooth, sir."

    def _toggle_dark_mode(self, app, ctx):
        scr = ('tell application "System Events" to tell appearance preferences '
               'to set dark mode to %s' % ("true" if ctx["dark"] else "false"))
        if osascript(scr):
            return ("Dark mode enabled, sir." if ctx["dark"]
                    else "Dark mode disabled, sir.")
        return "I could not change the appearance, sir."

    def _music_control(self, app, ctx):
        verbs = {"pause": "playpause", "resume": "play", "stop": "stop",
                 "next": "next track", "previous": "previous track"}
        labels = {"pause": "paused", "resume": "resumed", "stop": "stopped",
                  "next": "skipped to the next track",
                  "previous": "skipped to the previous track"}
        action = ctx["action"]
        app_name = "Music"
        for cand in ("Music", "Spotify"):
            if osascript('application "%s" is running' % cand):
                app_name = cand
                break
        if osascript('tell application "%s" to %s' % (app_name, verbs[action])):
            return "Music %s, sir." % labels[action]
        return "I could not control the music, sir."

    # ---- notes ----

    def _save_note(self, app, ctx):
        text = ctx.get("text", "").strip()
        if not text:
            return "What should I note down, sir?"
        try:
            with open(NOTES_FILE, "a", encoding="utf-8") as f:
                f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        + " | " + text + "\n")
        except Exception:
            return "I could not save the note, sir."
        return "Noted, sir: %s." % text

    def _read_notes(self, app, ctx):
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                lines = [l for l in f.read().splitlines() if l.strip()]
        except Exception:
            lines = []
        if not lines:
            return "You have no notes yet, sir."
        tail = lines[-3:]
        return "Your notes, sir: " + " | ".join(
            l.split(" | ", 1)[-1] for l in tail)

    # ---- LLM hybrid skills ----

    def _translate(self, app, ctx):
        text, lang = ctx["text"], ctx["lang"]
        reply = _llm(app, 'Translate "%s" into %s. Reply with only the '
                          "translation." % (text, lang))
        if reply is None:
            return "I could not reach my language model to translate that, sir."
        return "In %s, that is: %s" % (lang, reply)

    def _summarize(self, app, ctx):
        text = ctx.get("text", "")
        if not text:
            last = getattr(app, "last_reply", None)
            if not last:
                return "There is nothing to summarize yet, sir."
            text = last
        reply = _llm(app, "Summarize in one short spoken sentence: " + text)
        if reply is None:
            return "I could not reach my language model to summarize that, sir."
        return reply

    def _compose(self, app, ctx):
        kind = ctx["kind"]
        topic = ctx.get("topic") or "a general update"
        reply = _llm(app, "Compose a short professional %s about: %s. "
                          "Reply with only the content." % (kind, topic))
        if reply is None:
            return "I could not reach my language model to compose that, sir."
        return reply

    def _poem(self, app, ctx):
        topic = ctx.get("topic") or "nature"
        reply = _llm(app, "Write a short poem about %s, maximum six lines. "
                          "Reply with only the poem." % topic)
        if reply is None:
            return "I could not reach my language model to write that, sir."
        return reply

    def _story(self, app, ctx):
        topic = ctx.get("topic") or "a curious traveler"
        reply = _llm(app, "Tell a short story about %s in four sentences. "
                          "Reply with only the story." % topic)
        if reply is None:
            return "I could not reach my language model to tell that, sir."
        return reply

    def _trivia(self, app, ctx):
        reply = _llm(app, "Ask me one fun trivia question with three answer "
                          "choices. Reply with only the question and choices.")
        if reply is None:
            return "I could not reach my language model for trivia, sir."
        return reply

    def _explain(self, app, ctx):
        topic = ctx["topic"]
        if re.search(r"like i'?m 5|like im 5|simply", ctx["cmd"]):
            prompt = ("Explain '%s' as if I am five years old, in one short "
                      "spoken sentence." % topic)
        else:
            prompt = "Explain '%s' clearly in one short spoken sentence." % topic
        reply = _llm(app, prompt)
        if reply is None:
            return "I could not reach my language model to explain that, sir."
        return reply

    def _capabilities(self, app, ctx):
        return ("I have a local neural brain plus a language model, sir. I can "
                "open apps and websites, play music, check the time, weather "
                "and battery, set timers and reminders, do math, conversions "
                "and statistics, manage notes and passwords, control volume, "
                "Wi-Fi, Bluetooth, dark mode and the system, tell jokes and "
                "facts, translate, summarize, explain and write things, and "
                "much more, sir.")


if __name__ == "__main__":
    print("brain.py is a support module, sir. Run 'python main.py' instead.")
