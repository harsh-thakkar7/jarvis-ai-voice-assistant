import os

os.environ["PATH"] = "/opt/homebrew/bin:" + os.environ.get("PATH", "")

import sys
import json
import math
import time
import queue
import random
import re
import threading
import platform
import subprocess
import webbrowser
import datetime
import difflib
import base64
import shlex
from collections import deque

# All subsystems live in the jarvis/ package folder.
_JARVIS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jarvis")
if _JARVIS_DIR not in sys.path:
    sys.path.insert(0, _JARVIS_DIR)
from brain import Brain

import brain as brain_core
import brain_extra as brain_extra_core  # extra skills + offline chat auto-load

import requests
import speech_recognition as sr
import tkinter as tk
from tkinter import font as tkfont

try:
    import pyttsx3
    HAVE_TTS = True
except Exception:
    HAVE_TTS = False

try:
    import psutil
    HAVE_PSUTIL = True
except Exception:
    HAVE_PSUTIL = False

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# llama3-8b-8192 (and the whole legacy llama chat line) was decommissioned by
# Groq; openai/gpt-oss-20b is the supported general-purpose replacement.
GROQ_MODEL = "openai/gpt-oss-20b"
# Vision model used for screen analysis; degrades gracefully when the key's
# model list does not include it.
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Selectable chat models (Clicky-style model picker). The active one is
# mutable at runtime via the "use model ..." / "switch model" voice command.
GROQ_MODEL_CHOICES = [
    "openai/gpt-oss-20b",
    "meta-llama/llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-70b-8192",
]
ACTIVE_MODEL = GROQ_MODEL


def _system_prompt():
    """Fresh per-call so long-running sessions report the correct date."""
    return (
        "You are JARVIS, the intelligent AI assistant from Iron Man. "
        "You are confident, witty, loyal and highly capable. "
        "Keep answers short and conversational because they will be spoken out loud. "
        "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y") + "."
    )

WEBSITES = {
    "google ai studio": "https://aistudio.google.com",
    "google classroom": "https://classroom.google.com",
    "google translate": "https://translate.google.com",
    "google docs": "https://docs.google.com",
    "google sheets": "https://sheets.google.com",
    "google slides": "https://slides.google.com",
    "google meet": "https://meet.google.com",
    "google news": "https://news.google.com",
    "ai studio": "https://aistudio.google.com",
    "aistudio": "https://aistudio.google.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "netflix": "https://www.netflix.com",
    "stackoverflow": "https://stackoverflow.com",
    "maps": "https://maps.google.com",
    "drive": "https://drive.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com",
    "instagram": "https://www.instagram.com",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "flipkart": "https://www.flipkart.com",
    "telegram": "https://web.telegram.org",
    "discord": "https://discord.com/app",
    "soundcloud": "https://soundcloud.com",
    "openai": "https://openai.com",
    "translate": "https://translate.google.com",
    "weather": "https://www.google.com/search?q=weather",
    "youtube music": "https://music.youtube.com",
    "yt": "https://www.youtube.com",
    "yt music": "https://music.youtube.com",
    "insta": "https://www.instagram.com",
    "ig": "https://www.instagram.com",
    "fb": "https://www.facebook.com",
    "spotify web": "https://open.spotify.com",
    "pinterest": "https://www.pinterest.com",
    "twitch": "https://www.twitch.tv",
    "notion": "https://www.notion.so",
    "canva": "https://www.canva.com",
    "figma": "https://www.figma.com",
    "teams": "https://teams.microsoft.com",
    "google keep": "https://keep.google.com",
    "google maps": "https://maps.google.com",
    "icloud": "https://www.icloud.com",
    "tumblr": "https://www.tumblr.com",
    "quora": "https://www.quora.com",
    "hacker news": "https://news.ycombinator.com",
    "medium": "https://medium.com",
    "apple": "https://www.apple.com",
    "apple music web": "https://music.apple.com",
    "duckduckgo": "https://duckduckgo.com",
    "yahoo": "https://www.yahoo.com",
    "ebay": "https://www.ebay.com",
    "prime video": "https://www.primevideo.com",
    "hulu": "https://www.hulu.com",
    "disney plus": "https://www.disneyplus.com",
}

APP_MAP = {
    "calculator": "Calculator",
    "notes": "Notes",
    "photos": "Photos",
    "music": "Music",
    "terminal": "Terminal",
    "finder": "Finder",
    "safari": "Safari",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "spotify": "Spotify",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "settings": "System Settings",
    "code": "Visual Studio Code",
    "pycharm": "PyCharm",
    "docker": "Docker",
    "slack": "Slack",
    "zoom": "Zoom",
    "messages": "Messages",
    "imessage": "Messages",
    "mail": "Mail",
    "calendar": "Calendar",
    "reminders": "Reminders",
    "preview": "Preview",
    "textedit": "TextEdit",
    "text edit": "TextEdit",
    "vscode": "Visual Studio Code",
    "steam": "Steam",
    "tv": "TV",
    "podcasts": "Podcasts",
    "contacts": "Contacts",
    "facetime": "FaceTime",
    "voice memos": "Voice Memos",
    "stocks": "Stocks",
    "clock": "Clock",
    "home": "Home",
    "shortcuts": "Shortcuts",
}

USE_WHISPER = False

DESIGN_W, DESIGN_H = 1280, 800

PLACEHOLDER = "TYPE A COMMAND, SIR..."

QUICK_CMDS = [
    ("TIME", "what time is it"),
    ("DATE", "what is the date"),
    ("WEATHER", "what is the weather"),
    ("BATTERY", "what is the battery"),
    ("CLEAR TXT", "__clear__"),
]

CYAN = "#00d9ff"
BRIGHT = "#9ff3ff"
GOLD = "#ffd24d"
GREEN = "#3fd97a"
RED = "#ff5533"
DIMTXT = "#3fa9c2"
BORD = "#0e4a5e"
PANELBG = "#00070c"

COLORS = {
    "sleep": {"ring": "#0b2c3a", "glow": "#03151d", "bright": "#155d77",
              "core": "#0a4a63", "core_rgb": (10, 74, 99)},
    "standby": {"ring": "#0d4a60", "glow": "#052028", "bright": "#2ab3d9",
                "core": "#0b86b3", "core_rgb": (11, 134, 179)},
    "listen": {"ring": "#3fe6ff", "glow": "#003a4d", "bright": "#9ff3ff",
               "core": "#00d9ff", "core_rgb": (0, 217, 255)},
    "think": {"ring": "#ffd25e", "glow": "#4a3600", "bright": "#fff0b3",
              "core": "#ffc20f", "core_rgb": (255, 194, 15)},
    "speak": {"ring": "#6fdfff", "glow": "#003a4d", "bright": "#c9f6ff",
              "core": "#2fd0ff", "core_rgb": (47, 208, 255)},
}

MODE_PARAMS = {"sleep": (0.03, 0.3), "standby": (0.04, 0.8),
               "listen": (0.13, 2.6), "think": (0.10, 3.4),
               "speak": (0.09, 1.7)}

DOCK_MAP = {"sleep": 0, "standby": 0, "listen": 4, "think": 3, "speak": 2}

GAME_WORDS = {
    "fortnite", "minecraft", "gta", "gta v", "gta5", "gta 5", "cod",
    "call of duty", "valorant", "apex legends", "apex", "pubg", "csgo",
    "counter strike", "counterstrike", "among us", "roblox", "fifa",
    "nba 2k", "league of legends", "lol", "dota", "dota 2", "overwatch",
    "rocket league", "geometry dash", "elden ring", "zelda", "mario",
    "pokemon", "skyrim", "gta san andreas", "the last of us", "gow",
    "god of war", "fifa 23", "fifa 24", "elden ring", "genshin",
    "genshin impact", "stardew valley", "hades", "doom", "tetris",
    "chess", "clash of clans", "candy crush",
}

WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "heavy freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "light showers",
    81: "showers", 82: "heavy showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorms",
    96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def _short_wait(seconds):
    """Wait for a UI/agent action, skipping the delay entirely under tests."""
    if os.environ.get("JARVIS_TEST"):
        return
    time.sleep(seconds)


from urllib.parse import quote  # noqa: E402  (build-mode deep links for AI Studio)

API_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".jarvis_api_key")


def aistudio_build_url(prompt, is_app=False):
    """Return a Google AI Studio Build-mode deep link with the prompt pre-filled.

    AI Studio's Build mode (https://aistudio.google.com/apps) accepts the app
    idea as a URL parameter so the prompt box is populated automatically and
    the user lands directly on the "New app" screen — exactly the flow JARVIS
    promises. Android builds additionally select the Android platform picker.
    """
    q = quote((prompt or "").strip())
    url = "https://aistudio.google.com/apps?prompt=" + q
    if is_app:
        url += "&features=build_android_app"
    return url

_BUILD_VERB_RE = r"(?:build|make|create|develop|code|generate|design|construct)"
_KIND_WORDS = ("mobile application", "android application", "web application",
               "mobile app", "android app", "web app", "webpage", "website",
               "web site", "application", "app", "site")
_KIND_RE = r"(?:" + "|".join(_KIND_WORDS) + r")"


def parse_build_request(cmd):
    """Understand spoken build commands, handling the *topic in the middle*:
    "build me a coffee shop website", "make me an app for a todo list",
    "build a website about coffee", "build me an android app to track habits".

    Returns a dict {"is_build": bool, "kind": "web"|"app", "topic": str}
    or None when the command is not a website/app build request.
    """
    if not cmd:
        return None
    c = cmd.strip()
    if not re.search(r"\b" + _BUILD_VERB_RE + r"\b", c, re.I):
        return None
    kind_m = re.search(r"\b" + _KIND_RE + r"\b", c, re.I)
    if not kind_m:
        return None
    kind = kind_m.group(0)
    # An app/application/android/mobile kind => an "app" build (Android in AI Studio).
    is_app = bool(re.search(r"\b(?:app|application|android|mobile)\b", kind, re.I))
    before = c[:kind_m.start()]
    after = c[kind_m.end():]
    # Strip boilerplate ("build me a / make an ...") from the leading chunk.
    lead = re.sub(r"^\s*" + _BUILD_VERB_RE + r"\s+"
                  r"(?:me\s+|please\s+)?(?:\ban\b|\ba\b|\bthe\b)?\s*", "", before, flags=re.I)
    lead = re.sub(r"^\s*(?:for|about|on|of|that|called|named|titled)\s+"
                  r"(?:\ban\b|\ba\b|\bthe\b)?\s*", "", lead, flags=re.I).strip(" .,;-")
    # Strip connectors ("to / for / that / which / about") from the tail chunk.
    tail = re.sub(r"^\s*(?:to|for|that|which|which|with|in|on|about)\s+"
                  r"(?:\ban\b|\ba\b|\bthe\b)?\s*", "", after, flags=re.I).strip(" .,;-")
    topic = (" " .join(x for x in (lead, tail) if x)).strip()
    if not topic:
        topic = kind
    return {"is_build": True, "kind": "app" if is_app else "web", "topic": topic}


# ---------------------------------------------------------------------------
# Web search with citations (Clicky-style grounded answers)
# ---------------------------------------------------------------------------
def web_search(query, max_results=4):
    """Run a best-effort web search via DuckDuckGo Lite and return a list of
    dicts: [{"title", "url", "snippet"}] — used to cite sources in answers.

    Returns [] on any failure so callers degrade gracefully to plain replies.
    """
    if not query:
        return []
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        r = requests.get("https://lite.duckduckgo.com/lite/",
                         params={"q": query}, headers=headers, timeout=12)
        if r.status_code != 200:
            return []
        html = r.text
        out = []
        # Titles live in <a class='result-link' href='//duckduckgo.com/l/?uddg=<enc>&rut=...'>...
        anchor_re = re.compile(
            r"<a[^>]*class=['\"]result-link['\"][^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
            re.S)
        snippet_re = re.compile(r"<td[^>]*class=['\"]result-snippet['\"][^>]*>(.*?)</td>",
                                re.S)
        titles = [(url, _strip_tags(txt)) for url, txt in anchor_re.findall(html)]
        snippets = [_strip_tags(s) for s in snippet_re.findall(html)]
        for i, (url, title) in enumerate(titles):
            real = _decode_ddg_url(url)
            if not real:
                continue
            snip = snippets[i] if i < len(snippets) else ""
            out.append({"title": title, "url": real, "snippet": snip[:220]})
            if len(out) >= max_results:
                break
        return out
    except Exception:
        return []


def _strip_tags(text):
    import html as _html
    text = re.sub(r"<[^>]+>", "", text or "")
    return _html.unescape(text).strip()


def _decode_ddg_url(link):
    """Extract the real destination from a DDG redirect href like
    //duckduckgo.com/l/?uddg=<urlencoded>&rut=..."""
    try:
        from urllib.parse import unquote
        m = re.search(r"uddg=([^&]+)", link)
        if not m:
            return None
        return unquote(m.group(1))
    except Exception:
        return None


def format_sources(sources, max_n=3):
    """Turn a web_search() result list into a display-only "Sources:" block.

    Returns "" when there are no sources so callers can append safely.
    """
    if not sources:
        return ""
    lines = []
    for i, s in enumerate(sources[:max_n], 1):
        title = s.get("title") or "Source"
        url = s.get("url") or ""
        lines.append(f"{i}. {title}" + (f" — {url}" if url else ""))
    return "Sources:\n" + "\n".join(lines)


def make_cited_display(answer, sources):
    """Append a citations block to an answer for *visual* display only.

    The returned string speaks cleanly if passed to say() when sources are
    empty; callers that want to avoid reading sources aloud should speak
    `answer` and display the return value of this helper.
    """
    block = format_sources(sources)
    if not block:
        return answer
    return answer.rstrip() + "\n\n" + block


def _is_web_worthy(query):
    """Heuristic: does this free-form question need live web sources?

    Only fire web_search on informational/factual/enquiry-style queries so we
    don't add network latency or citations to casual chat, jokes, or personal
    commands.
    """
    if not query:
        return False
    q = query.strip().lower()
    # Skip short/one-word and opinion/chat commands outright.
    if len(q) < 6:
        return False
    # Web-worthy lead words.
    if re.match(r"^(what|who|why|when|where|how|which|is|are|explain|define|"
                r"tell me about|describe|current|latest|recent|best|top|news|"
                r"facts|difference between|capital of|meaning of|history of)\b",
                q):
        return True
    if any(k in q for k in ("what is", "what are", "who is", "who was",
                            "why is", "what does", "how does", "how do",
                            "what happened", "meaning", "definition",
                            "latest", "current", "news", "weather in",
                            "capital of", "population of", "president of")):
        return True
    return False


def open_aistudio_build(prompt, is_app=False):


    """Open the AI Studio Build-mode URL for the given app idea.

    Returns True if the browser was asked to open the build page. The prompt
    arrives pre-filled in the prompt section thanks to the `prompt` URL param.
    """
    try:
        webbrowser.open(aistudio_build_url(prompt, is_app))
        return True
    except Exception:
        return False


# --- Privacy guard ---------------------------------------------------------
# Clicky-style: skip screen capture entirely when a sensitive window is
# frontmost (password managers, banking, login pages, secret files).

SENSITIVE_APP_HINTS = (
    "1password", "bitwarden", "lastpass", "keepass", "password",
    "authenticator", "authy", "chrome extension", "apple wallet",
    "money", "bank", "banking", "chase", "wells fargo", "paypal",
    "capital one", "credit card", "crypto", "wallet", "login",
    "sign-in", "sign in", "password manager", "grep .env",
)

SENSITIVE_WINDOW_HINTS = (
    "login", "sign in", "signin", "password", "banking", "credit card",
    "card number", "cvv", "secret", ".env", "private key", "passphrase",
    "two-step", "2fa", "otp", "verification code", "authenticate",
)


def frontmost_app_and_window():
    """Return (app_name, window_title) of the frontmost app on macOS.

    Best-effort; returns ("", "") when detection is unavailable.
    """
    if platform.system() != "Darwin":
        return "", ""
    try:
        r1 = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first process '
             'whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        app = r1.stdout.strip()
        r2 = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of window 1 of '
             'first process whose frontmost is true'],
            capture_output=True, text=True, timeout=5)
        win = r2.stdout.strip()
        return app, win
    except Exception:
        return "", ""


def privacy_guard_blocked():
    """Return True when the frontmost window looks sensitive.

    Mirrors Clicky's Privacy Guard: when a password manager / banking /
    login window is active, JARVIS skips screenshots instead of capturing a
    password, secret, or .env file that might be on screen.
    """
    app, win = frontmost_app_and_window()
    if not app and not win:
        return False
    hay = (app + " " + win).lower()
    if any(h in hay for h in SENSITIVE_APP_HINTS):
        return True
    if any(h in hay for h in SENSITIVE_WINDOW_HINTS):
        return True
    return False


_key_file_warned = False


def load_api_key():
    global _key_file_warned
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except Exception:
        content = ""
    if not content:
        return ""
    if not _key_file_warned:
        _key_file_warned = True
        try:
            from jarvis_logging import get_logger
            get_logger("main").warning(
                "API key loaded from plaintext file %s - prefer setting "
                "the GROQ_API_KEY environment variable instead",
                API_KEY_FILE)
        except Exception:
            pass
    content = content.strip("'\"")
    m = re.search(r"gsk_[A-Za-z0-9_-]+", content)
    if m:
        return m.group(0)
    if len(content) > 10:
        return content
    return ""


def save_api_key(key):
    key = (key or "").strip()
    if not key:
        return False
    key = key.strip("'\"")
    if len(key) < 10:
        return False
    try:
        with open(API_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
        try:
            os.chmod(API_KEY_FILE, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def sanitize_filename(filename, default_ext=".txt"):
    """Sanitize a filename to prevent path traversal."""
    name = os.path.basename(str(filename or ""))
    name = name.replace("\\", "_")
    name = re.sub(r"[^a-zA-Z0-9_.\-]", "_", name)
    if not name or name.startswith(".") or ".." in name:
        name = "output" + default_ext
    return name


def ask_ai(prompt, history=None):
    # Provider abstraction: JARVIS_PROVIDER (openai|anthropic|ollama)
    # routes through llm_client; default stays the native Groq path.
    provider_name = os.environ.get("JARVIS_PROVIDER", "").strip().lower()
    if provider_name and provider_name != "groq":
        try:
            from llm_client import LLMClient
            reply = LLMClient().chat(prompt, history=history,
                                     system=_system_prompt())
            if reply is not None:
                return reply
        except Exception:
            pass
    api_key = load_api_key()
    if not api_key:
        return None
    messages = [{"role": "system", "content": _system_prompt()}]
    if history:
        messages.extend(list(history)[-10:])
    if (not messages or messages[-1].get("content") != prompt
            or messages[-1].get("role") != "user"):
        messages.append({"role": "user", "content": prompt})
    payload = {
        "model": ACTIVE_MODEL,
        "messages": messages,
        "temperature": 0.8,
    }
    last_err = None
    for attempt in range(2):
        try:
            resp = requests.post(
                GROQ_URL, json=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + api_key},
                timeout=15,
            )
            if resp.status_code == 401:
                return "__UNAUTHORIZED__"
            if resp.status_code == 429:
                return "__RATE_LIMITED__"
            if resp.status_code in (500, 502, 503, 504):
                last_err = f"{resp.status_code} {resp.reason}"
                time.sleep(1)
                continue
            if resp.status_code == 400:
                try:
                    err = resp.json().get("error", {}).get("message", resp.text[:200])
                except Exception:
                    err = resp.text[:200]
                return f"I hit an API error: {err}"
            resp.raise_for_status()
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}) \
                .get("content", "")
            if not content.strip():
                # Reasoning models can spend all tokens thinking and return
                # empty content; surface the reasoning text instead of nothing.
                content = (data.get("choices") or [{}])[0].get("message", {}) \
                    .get("reasoning", "") or ""
            return content.strip()
        except requests.exceptions.Timeout:
            last_err = "request timed out"
            time.sleep(1)
        except requests.exceptions.ConnectionError:
            last_err = "cannot reach Groq servers"
            time.sleep(1)
        except Exception as e:
            last_err = str(e)[:200]
            time.sleep(1)
    return f"I hit an error connecting to my systems, sir: {last_err}"


def get_weather(location):
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en"},
            timeout=15,
        ).json()
        results = geo.get("results") or []
        if not results:
            return None
        r = results[0]
        lat, lon = r["latitude"], r["longitude"]
        name = r.get("name") or location
        f = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": ("temperature_2m,apparent_temperature,weather_code,"
                            "wind_speed_10m,relative_humidity_2m"),
            },
            timeout=15,
        ).json()
        cur = f.get("current") or {}
        if not cur:
            return None
        code = cur.get("weather_code")
        desc = WEATHER_CODES.get(code, "variable")
        temp = cur.get("temperature_2m")
        feels = cur.get("apparent_temperature")
        wind = cur.get("wind_speed_10m")
        hum = cur.get("relative_humidity_2m")
        parts = []
        if temp is not None:
            parts.append("%.0f degrees" % temp)
        if feels is not None:
            parts.append("feels like %.0f" % feels)
        parts.append(desc)
        if hum is not None:
            parts.append("humidity %.0f percent" % hum)
        if wind is not None:
            parts.append("wind %.0f kilometers per hour" % wind)
        if not parts:
            return None
        return "Right now in %s, it is %s." % (name, ", ".join(parts))
    except Exception:
        return None


class TimerManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._timers = {}
        self._next_id = 0

    def add(self, seconds, callback, label=""):
        with self._lock:
            tid = self._next_id
            self._next_id += 1

        def _fire(t):
            # Remove from registry first so a blocked callback can never
            # leave a finished timer lingering in remaining().
            self.done(tid)
            try:
                callback(t)
            except Exception as e:
                print("TIMER CALLBACK ERROR:", e)

        timer = threading.Timer(seconds, _fire, args=(tid,))
        timer.daemon = True
        with self._lock:
            self._timers[tid] = (timer, seconds, time.time(), label)
        timer.start()
        return tid

    def cancel(self, tid=None):
        with self._lock:
            if tid is None:
                # Cancel and clear in one locked pass: snapshot-then-clear
                # let timers registered in between leak as live threads.
                cancelled = False
                for t, _, _, _ in self._timers.values():
                    t.cancel()
                    cancelled = True
                self._timers.clear()
                return cancelled
            entry = self._timers.pop(tid, None)
        if entry:
            entry[0].cancel()
            return True
        return False

    def remaining(self):
        with self._lock:
            items = list(self._timers.items())
        out = []
        for tid, (_, secs, start, label) in items:
            out.append((tid, max(0, secs - (time.time() - start)), label))
        return out

    def done(self, tid):
        with self._lock:
            self._timers.pop(tid, None)


LENGTH_UNITS = {
    "millimeter": 0.001, "millimeters": 0.001, "mm": 0.001,
    "centimeter": 0.01, "centimeters": 0.01, "cm": 0.01,
    "meter": 1.0, "meters": 1.0, "m": 1.0, "metre": 1.0, "metres": 1.0,
    "kilometer": 1000.0, "kilometers": 1000.0, "km": 1000.0, "kms": 1000.0,
    "mile": 1609.344, "miles": 1609.344,
    "yard": 0.9144, "yards": 0.9144,
    "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
    "inch": 0.0254, "inches": 0.0254, "in": 0.0254,
}

MASS_UNITS = {
    "milligram": 1e-6, "milligrams": 1e-6, "mg": 1e-6,
    "gram": 0.001, "grams": 0.001, "g": 0.001,
    "kilogram": 1.0, "kilograms": 1.0, "kg": 1.0, "kilo": 1.0,
    "tonne": 1000.0, "tonnes": 1000.0, "ton": 907.185, "tons": 907.185,
    "pound": 0.453592, "pounds": 0.453592, "lb": 0.453592, "lbs": 0.453592,
    "ounce": 0.0283495, "ounces": 0.0283495, "oz": 0.0283495,
}

SPEED_UNITS = {
    "kilometers per hour": 1.0, "kilometer per hour": 1.0,
    "km per hour": 1.0, "km/h": 1.0, "kmh": 1.0, "kph": 1.0,
    "miles per hour": 1.609344, "mile per hour": 1.609344,
    "mph": 1.609344, "meters per second": 3.6, "metres per second": 3.6,
    "m/s": 3.6, "knot": 1.852, "knots": 1.852,
}

DATA_UNITS = {
    "bit": 0.125, "bits": 0.125,
    "byte": 1.0, "bytes": 1.0, "b": 1.0,
    "kilobyte": 1024.0, "kilobytes": 1024.0, "kb": 1024.0,
    "megabyte": 1024.0 ** 2, "megabytes": 1024.0 ** 2, "mb": 1024.0 ** 2,
    "gigabyte": 1024.0 ** 3, "gigabytes": 1024.0 ** 3, "gb": 1024.0 ** 3,
    "terabyte": 1024.0 ** 4, "terabytes": 1024.0 ** 4, "tb": 1024.0 ** 4,
}

TEMP_UNITS = {
    "celsius": "C", "degree celsius": "C", "degrees celsius": "C", "c": "C",
    "fahrenheit": "F", "degree fahrenheit": "F", "degrees fahrenheit": "F",
    "f": "F", "kelvin": "K", "k": "K",
}

CONVERT_TABLES = {"length": LENGTH_UNITS, "weight": MASS_UNITS,
                  "mass": MASS_UNITS, "speed": SPEED_UNITS,
                  "data": DATA_UNITS, "storage": DATA_UNITS}


def open_app(app_name):
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(app_name)
            return True
        if system == "Darwin":
            r = subprocess.run(["open", "-a", app_name], capture_output=True)
            return r.returncode == 0
        # Generic POSIX: launching via run() would block until the app exits;
        # spawn detached instead so JARVIS stays responsive.
        with open(os.devnull, "wb") as devnull:
            subprocess.Popen([app_name], stdout=devnull, stderr=devnull,
                             stdin=subprocess.DEVNULL,
                             start_new_session=True)
        return True
    except Exception:
        return False


class JarvisApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S.")
        self.root.resizable(True, True)
        self.root.configure(bg="#000000")
        self.root.minsize(800, 500)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.root.bind("<F11>", self._toggle_fullscreen)
        self.fullscreen = False

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.root.update_idletasks()

        self.sx = max(0.5, sw / DESIGN_W)
        self.sy = max(0.5, sh / DESIGN_H)
        self._ready = False

        self.ui_q = queue.Queue()
        self.speech_done = threading.Event()
        self.running = threading.Event()
        self.running.set()

        self.status_text = "BOOT"
        self.awake = False
        self.booting = True
        self.boot_progress = 0.0
        self.spin = 0.0
        self.t = 0
        self.pulse_amp = 0.04
        self.speech_pending = False
        self.pending_since = 0.0
        self.was_busy = False
        self._last_sec = -1
        self.start_time = datetime.datetime.now()
        self.cpu = 0.0
        self.mem = 0.0
        self.power = 0.98
        self.bars_spec = []
        self._typing = None
        self._line_q = deque(maxlen=400)  # bounded: fast producers must not leak
        self._placements = []
        self.cmd_history = deque(maxlen=50)
        self._hist_idx = None
        self._hint_map = {}
        self._hover_iid = None
        self.history = deque(maxlen=10)
        self.log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "jarvis_transcript.log")
        self.timers = TimerManager()
        self.last_reply = None
        self._brain = None
        self.ai_mode = "ONLINE" if load_api_key() else "LOCAL"
        self.continuous_listen = False
        self._listen_thread = None
        self.speaking = threading.Event()
        self._ptt_active = False
        self._ptt_stop = threading.Event()
        self._ptt_thread = None
        self._ptt_audio = None
        self._ptt_error = None
        self._last_mic_err = None
        self._active_timers = []
        self._overlay = None
        self._last_screenshot = None

        self.engine = None
        if HAVE_TTS:
            self._init_engine()

        self._set_geo()
        self._build_ui()
        self._ready = True
        self.root.bind("<Configure>", self._on_resize)
        self._draw_reactor()
        self._animate()

    def _init_engine(self):
        try:
            e = pyttsx3.init()
            for v in e.getProperty("voices"):
                n = v.name.lower()
                if any(k in n for k in ("david", "alex", "daniel", "male")):
                    e.setProperty("voice", v.id)
                    break
            e.setProperty("rate", 185)
            e.setProperty("volume", 1.0)
            e.startLoop(useDriverLoop=False)
            self.engine = e
        except Exception as err:
            print("TTS init failed:", err)
            self.engine = None

    def _X(self, x):
        return int(x * self.sx)

    def _Y(self, y):
        return int(y * self.sy)

    def _set_geo(self):
        s = min(self.sx, self.sy)
        self.cx = self._X(640)
        self.cy = self._Y(360)
        self.R = int(120 * s)
        self.dock_xs = [self._X(x) for x in (320, 470, 620, 770, 920)]
        self.dock_cy = self._Y(774)

    def _make_fonts(self):
        s = min(self.sx, self.sy)
        self.F_TITLE = tkfont.Font(family="Helvetica Neue", size=max(10, int(30 * s)), weight="bold")
        self.F_TITLE_HALO = tkfont.Font(family="Helvetica Neue", size=max(12, int(36 * s)), weight="bold")
        self.F_MICRO = tkfont.Font(family="Menlo", size=max(6, int(9 * s)))
        self.F_HUD = tkfont.Font(family="Menlo", size=max(6, int(9 * s)))
        self.F_STAT = tkfont.Font(family="Menlo", size=max(8, int(12 * s)), weight="bold")
        self.F_PANEL_H = tkfont.Font(family="Helvetica Neue", size=max(8, int(13 * s)), weight="bold")
        self.F_VAL = tkfont.Font(family="Menlo", size=max(7, int(11 * s)), weight="bold")
        self.F_BIG = tkfont.Font(family="Menlo", size=max(14, int(26 * s)), weight="bold")
        self.F_TX = tkfont.Font(family="Menlo", size=max(7, int(12 * s)))

    def _apply_fonts(self):
        self.status_lbl.config(font=self.F_STAT)
        for lbl in self.val_labels.values():
            lbl.config(font=self.F_VAL)
        self.clock_lbl.config(font=self.F_BIG)
        self.date_lbl.config(font=self.F_MICRO)
        self.micro_lbl.config(font=self.F_MICRO)
        self.tx.config(font=self.F_TX)
        self.cmd_entry.config(font=self.F_MICRO)
        self.send_btn.config(font=self.F_MICRO)
        for b in self.quick_btns:
            b.config(font=self.F_MICRO)
        self.exit_btn.config(font=self.F_MICRO)

    def _place(self, w, x, y, **kw):
        self._placements.append((w, x, y, kw))
        self._place_apply(w, x, y, kw)

    def _place_apply(self, w, x, y, kw):
        c = dict(kw)
        for k in ("width", "height"):
            if c.get(k) is not None:
                c[k] = int(c[k] * (self.sx if k == "width" else self.sy))
        w.place(x=self._X(x), y=self._Y(y), **c)

    def _reposition_widgets(self):
        for w, x, y, kw in self._placements:
            try:
                self._place_apply(w, x, y, kw)
            except Exception:
                pass

    def _apply_scale(self):
        self.sx = max(0.5, self.root.winfo_width() / DESIGN_W)
        self.sy = max(0.5, self.root.winfo_height() / DESIGN_H)
        self._set_geo()
        self._make_fonts()
        if self._ready:
            self._redraw_static()
            self._reposition_widgets()
            self._apply_fonts()

    def _on_resize(self, event):
        if not self._ready or event.widget is not self.root:
            return
        if event.width < 100 or event.height < 100:
            return
        try:
            self._apply_scale()
        except Exception:
            pass

    def _toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        return "break"

    def _build_ui(self):
        self.canvas = tk.Canvas(self.root, bg="#000000", highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._make_fonts()
        self._redraw_static()
        self._make_widgets()
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

    def _redraw_static(self):
        self.canvas.delete("static")
        self._vignette()
        self._corner_brackets()
        self._top_hud()
        self._panel_left()
        self._panel_right()
        self._panel_bottom()
        self._reactor_static()

    def _vignette(self):
        self.canvas.create_oval(self._X(140), -100, self._X(1140), self._Y(900),
                                outline="", fill="#00060a", tags="static")
        self.canvas.create_oval(self._X(340), self._Y(100), self._X(940), self._Y(700),
                                outline="", fill="#00121c", tags="static")
        self.canvas.create_oval(self._X(470), self._Y(220), self._X(810), self._Y(560),
                                outline="", fill="#00202f", tags="static")

    def _corner_brackets(self):
        self.canvas.create_line(self._X(24), self._Y(70), self._X(24), self._Y(12),
                                self._X(80), self._Y(12), fill=BORD, width=2, tags="static")
        self.canvas.create_line(self._X(1256), self._Y(12), self._X(1200), self._Y(12),
                                self._X(1200), self._Y(70), fill=BORD, width=2, tags="static")
        self.canvas.create_line(self._X(24), self._Y(740), self._X(24), self._Y(788),
                                self._X(80), self._Y(788), fill=BORD, width=2, tags="static")
        self.canvas.create_line(self._X(1256), self._Y(788), self._X(1200), self._Y(788),
                                self._X(1200), self._Y(740), fill=BORD, width=2, tags="static")

    def _top_hud(self):
        self.canvas.create_text(self._X(640), self._Y(42), text="J.A.R.V.I.S.",
                                font=self.F_TITLE_HALO, fill="#00364a", tags="static")
        self.canvas.create_text(self._X(640), self._Y(40), text="J.A.R.V.I.S.",
                                font=self.F_TITLE, fill="#eaffff", tags="static")
        self.canvas.create_text(self._X(640), self._Y(68), text="JUST A RATHER VERY INTELLIGENT SYSTEM",
                                font=self.F_MICRO, fill=DIMTXT, tags="static")
        self.canvas.create_line(self._X(250), self._Y(84), self._X(1030), self._Y(84),
                                fill=BORD, width=1, tags="static")

    def _panel(self, x0, y0, x1, y1, title, sub):
        X, Y = self._X, self._Y
        self.canvas.create_rectangle(X(x0), Y(y0), X(x1), Y(y1), outline=BORD,
                                     fill=PANELBG, width=1, tags="static")
        self.canvas.create_line(X(x0 + 1), Y(y0 + 14), X(x0 + 1), Y(y0 + 1),
                                X(x0 + 14), Y(y0 + 1), fill="#2be3ff", width=2, tags="static")
        self.canvas.create_line(X(x1 - 1), Y(y0 + 14), X(x1 - 1), Y(y0 + 1),
                                X(x1 - 14), Y(y0 + 1), fill="#2be3ff", width=2, tags="static")
        self.canvas.create_line(X(x0 + 1), Y(y1 - 14), X(x0 + 1), Y(y1 - 1),
                                X(x0 + 14), Y(y1 - 1), fill="#2be3ff", width=2, tags="static")
        self.canvas.create_line(X(x1 - 1), Y(y1 - 14), X(x1 - 1), Y(y1 - 1),
                                X(x1 - 14), Y(y1 - 1), fill="#2be3ff", width=2, tags="static")
        self.canvas.create_text(X(x0 + 15), Y(y0 + 18), text=title, anchor="w",
                                fill="#eaffff", font=self.F_PANEL_H, tags="static")
        if sub:
            self.canvas.create_text(X(x0 + 15), Y(y0 + 36), text=sub, anchor="w",
                                    fill=DIMTXT, font=self.F_MICRO, tags="static")

    def _panel_left(self):
        self._panel(40, 150, 360, 545, "// SYSTEM", "MK II DIAGNOSTICS")
        rows = [
            ("POWER CORE", 210, "bar"),
            ("VOICE LINK", 240, "text"),
            ("NETWORK", 268, "text"),
            ("AI CORE", 296, "text"),
            ("CPU LOAD", 328, "bar"),
            ("MEMORY", 358, "bar"),
            ("UPTIME", 388, "text"),
            ("SENSORS", 418, "text"),
            ("THREAT LVL", 448, "text"),
        ]
        for name, y, kind in rows:
            self.canvas.create_text(self._X(55), self._Y(y), text=name, anchor="w",
                                    fill=DIMTXT, font=self.F_HUD, tags="static")
            if kind == "bar":
                self.canvas.create_rectangle(self._X(190), self._Y(y - 3), self._X(302),
                                             self._Y(y + 3), outline="#0d4a5e",
                                             fill="#00141f", width=1, tags="static")

    def _panel_right(self):
        self._panel(920, 150, 1240, 545, "// TELEMETRY", "FLIGHT & COMMS")
        self.canvas.create_rectangle(self._X(935), self._Y(192), self._X(1225), self._Y(262),
                                     outline="#0d4a5e", fill="#00070c", width=1, tags="static")
        self.canvas.create_line(self._X(935), self._Y(227), self._X(1225), self._Y(227),
                                fill="#0e4a5e", width=1, tags="static")
        self.canvas.create_line(self._X(935), self._Y(360), self._X(1225), self._Y(360),
                                fill="#0e4a5e", width=1, tags="static")
        self.canvas.create_text(self._X(935), self._Y(385), text="VOICE COMMANDS",
                                anchor="w",
                                fill=DIMTXT, font=self.F_PANEL_H, tags="static")
        cmds = [
            ("open youtube  /  open calculator", "open youtube"),
            ("search for <topic>", "search for jarvis"),
            ("play <song name>", "play shape of you"),
            ("build a website about <topic>", "build a website about space"),
            ("ask anything - Groq Llama core", "tell me something interesting"),
            ("say 'set api key'  =  update key", None),
            ("say 'go to sleep'  =  standby", "go to sleep"),
            ("say 'wake up jarvis'  =  wake", "wake up jarvis"),
        ]
        y = 412
        self._hint_map = {}
        for cm, act in cmds:
            if act:
                hit = self.canvas.create_rectangle(self._X(930), self._Y(y - 8),
                                                   self._X(1230), self._Y(y + 8),
                                                   outline="", fill=PANELBG,
                                                   tags=("static", "hint"))
            t = self.canvas.create_text(self._X(1220), self._Y(y), text=cm, anchor="e",
                                        fill="#5fb3c8", font=self.F_MICRO,
                                        tags=("static", "hint"))
            if act:
                self._hint_map[hit] = (t, act)
                self._hint_map[t] = (t, act)
            y += 17

    def _panel_bottom(self):
        self._panel(60, 565, 1220, 790, "// COMM LINK", "VOICE TRANSCRIPT & COMMAND INPUT")
        self.canvas.create_line(self._X(75), self._Y(766), self._X(1205), self._Y(766),
                                fill=BORD, width=1, tags="static")
        for i, x in enumerate(self.dock_xs):
            self.canvas.create_text(x, self._Y(768), text=["SYS", "PWR", "COM", "NAV", "STA"][i],
                                    anchor="center", fill=DIMTXT, font=self.F_MICRO, tags="static")
        self.canvas.create_text(self._X(28), self._Y(772), text="STARK INDUSTRIES // JARVIS MK-II",
                                anchor="w", fill="#2a6b80", font=self.F_MICRO, tags="static")
        self.canvas.create_text(self._X(1252), self._Y(772), text="ARC REACTOR MK IV",
                                anchor="e", fill="#2a6b80", font=self.F_MICRO, tags="static")

    def _reactor_static(self):
        cx, cy, R = self.cx, self.cy, self.R
        for rr in (R + 72, R + 50):
            self.canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                    outline="#083042", width=1, tags="static")
        for i in range(48):
            a = math.radians(i * 360 / 48)
            x1 = cx + math.cos(a) * (R + 26)
            y1 = cy + math.sin(a) * (R + 26)
            x2 = cx + math.cos(a) * (R + 34)
            y2 = cy + math.sin(a) * (R + 34)
            self.canvas.create_line(x1, y1, x2, y2, fill=BORD, width=1, tags="static")
        pts = []
        for k in range(6):
            a = math.radians(k * 60 + 30)
            pts += [cx + math.cos(a) * (R - 58), cy + math.sin(a) * (R - 58)]
        self.canvas.create_polygon(pts, outline="#0d4a5e", fill="", width=1, tags="static")

    def _make_widgets(self):
        self.status_lbl = tk.Label(self.root, text="BOOTING", bg="#000000",
                                   fg=CYAN, font=self.F_STAT)
        self._place(self.status_lbl, 650, 106, anchor="center")

        row_fns = {
            "POWER CORE": lambda: f"{self.power * 100:.0f}%",
            "VOICE LINK": lambda: "ONLINE",
            "NETWORK": lambda: "LINKED",
            "AI CORE": lambda: getattr(self, "ai_mode", "LOCAL"),
            "CPU LOAD": lambda: f"{self.cpu:.0f}%",
            "MEMORY": lambda: f"{self.mem:.0f}%",
            "UPTIME": lambda: "00:00:00",
            "SENSORS": lambda: "NOMINAL",
            "THREAT LVL": lambda: "0%",
        }
        rows_y = {"POWER CORE": 210, "VOICE LINK": 240, "NETWORK": 268,
                  "AI CORE": 296, "CPU LOAD": 328, "MEMORY": 358,
                  "UPTIME": 388, "SENSORS": 418, "THREAT LVL": 448}
        self.val_labels = {}
        for name, y in rows_y.items():
            if name == "AI CORE":
                fg = GREEN if self.ai_mode == "ONLINE" else GOLD
            else:
                fg = "#bfe9f2"
            lbl = tk.Label(self.root, text=row_fns[name](), bg="#00070c",
                           fg=fg, font=self.F_VAL)
            self._place(lbl, 345, y, anchor="e")
            self.val_labels[name] = lbl

        self.api_hint_lbl = tk.Label(
            self.root,
            text="",
            bg="#00070c",
            fg=GOLD,
            font=self.F_MICRO)
        self._place(self.api_hint_lbl, 345, 312, anchor="e")
        if self.ai_mode == "LOCAL":
            self.api_hint_lbl.config(text="Say 'set api key' to enable Groq")

        self.bars_spec = [
            (190, 207, 110, lambda: self.power, "#2be3ff"),
            (190, 295, 110, lambda: self.cpu / 100.0, GOLD),
            (190, 325, 110, lambda: self.mem / 100.0, GREEN),
        ]

        self.clock_lbl = tk.Label(self.root, text="", bg="#000000", fg=CYAN, font=self.F_BIG)
        self._place(self.clock_lbl, 1080, 280, anchor="center")
        self.date_lbl = tk.Label(self.root, text="", bg="#000000", fg=DIMTXT, font=self.F_MICRO)
        self._place(self.date_lbl, 1080, 314, anchor="center")
        self.micro_lbl = tk.Label(
            self.root,
            text="ARC CORE v4.1 // %s" % ("LINK STABLE" if self.ai_mode == "ONLINE"
                                          else "OFFLINE BRAIN"),
            bg="#000000", fg="#2a6b80", font=self.F_MICRO)
        self._place(self.micro_lbl, 1080, 336, anchor="center")

        self.tx = tk.Text(self.root, bg=PANELBG, fg="#9fe9ff", font=self.F_TX,
                          wrap="word", borderwidth=0, highlightthickness=0,
                          insertbackground=CYAN, padx=12, pady=8, state="disabled")
        self._place(self.tx, 75, 612, width=1118, height=78)
        sb = tk.Scrollbar(self.root, orient="vertical", command=self.tx.yview,
                          bg="#001018", activebackground=CYAN, troughcolor=PANELBG,
                          relief="flat", bd=0)
        self._place(sb, 1195, 612, width=6, height=78)
        self.tx.configure(yscrollcommand=sb.set)
        self.tx.tag_configure("you_head", foreground="#8ad3ff")
        self.tx.tag_configure("you_body", foreground="#cfefff")
        self.tx.tag_configure("j_head", foreground=GOLD)
        self.tx.tag_configure("j_body", foreground="#ffe9a8")
        self.tx.tag_configure("s_head", foreground=GREEN)
        self.tx.tag_configure("s_body", foreground="#7fd9a0")

        self.cmd_entry = tk.Entry(self.root, bg="#00141f", fg="#2a6b80",
                                  insertbackground=CYAN, relief="flat",
                                  highlightthickness=1, highlightbackground="#0d4a5e",
                                  highlightcolor="#2be3ff", font=self.F_MICRO)
        self.cmd_entry.insert(0, PLACEHOLDER)
        self.cmd_entry.bind("<Return>", self._on_entry_return)
        self.cmd_entry.bind("<Up>", self._hist_up)
        self.cmd_entry.bind("<Down>", self._hist_down)
        self.cmd_entry.bind("<FocusIn>", self._entry_focus_in)
        self.cmd_entry.bind("<FocusOut>", self._entry_focus_out)
        self._place(self.cmd_entry, 78, 696, width=1024, height=30)

        self.send_btn = tk.Button(self.root, text="EXEC", command=self._send,
                                  bg="#00141f", fg=CYAN, relief="flat", font=self.F_MICRO,
                                  activebackground="#0d3a4d", activeforeground=GOLD,
                                  cursor="hand2", padx=8, pady=2)
        self._place(self.send_btn, 1116, 696, width=76, height=30)

        self.voice_btn = tk.Button(self.root, text="MIC", command=self._voice_click,
                                   bg="#00141f", fg=GREEN, relief="flat", font=self.F_MICRO,
                                   activebackground="#0d3a4d", activeforeground=GOLD,
                                   cursor="hand2", padx=8, pady=2)
        self._place(self.voice_btn, 1195, 696, width=42, height=30)
        self.voice_active = False
        self.voice_btn.bind("<ButtonPress-1>", self._voice_press)
        self.voice_btn.bind("<ButtonRelease-1>", self._voice_release)
        self._voice_hold_timer = None
        self._voice_hold_mode = False

        self.auto_listen_btn = tk.Button(self.root, text="AUTO", command=self._toggle_auto_listen,
                                         bg="#00141f", fg="#5fb3c8", relief="flat", font=self.F_MICRO,
                                         activebackground="#0d3a4d", activeforeground=GOLD,
                                         cursor="hand2", padx=4, pady=2)
        self._place(self.auto_listen_btn, 1195, 732, width=42, height=22)

        self.quick_btns = []
        qx = 78
        for label, cmd in QUICK_CMDS:
            b = tk.Button(self.root, text=label, command=lambda c=cmd: self._quick_cmd(c),
                          bg="#00141f", fg="#5fb3c8", relief="flat", font=self.F_MICRO,
                          activebackground="#0d3a4d", activeforeground="#eaffff",
                          cursor="hand2", padx=4, pady=1)
            self._place(b, qx, 732, width=112, height=22)
            self.quick_btns.append(b)
            qx += 118

        self.exit_btn = tk.Button(self.root, text="EXIT", command=self.quit_app,
                                  bg="#000a10", fg=RED, relief="flat", font=self.F_MICRO,
                                  activebackground="#220000", activeforeground=GOLD,
                                  cursor="hand2", padx=14, pady=3)
        self._place(self.exit_btn, 1195, 18)

    def _on_entry_return(self, event=None):
        self._send()
        return "break"

    def _entry_focus_in(self, event=None):
        if self.cmd_entry.get() == PLACEHOLDER:
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.config(fg="#9fe9ff")

    def _entry_focus_out(self, event=None):
        if not self.cmd_entry.get():
            self.cmd_entry.insert(0, PLACEHOLDER)
            self.cmd_entry.config(fg="#2a6b80")

    def _hist_up(self, event=None):
        if not self.cmd_history:
            return "break"
        if self._hist_idx is None:
            self._hist_idx = len(self.cmd_history) - 1
        else:
            self._hist_idx = max(0, self._hist_idx - 1)
        self.cmd_entry.delete(0, "end")
        self.cmd_entry.insert(0, self.cmd_history[self._hist_idx])
        self.cmd_entry.config(fg="#9fe9ff")
        return "break"

    def _hist_down(self, event=None):
        if self._hist_idx is None:
            return "break"
        if self._hist_idx < len(self.cmd_history) - 1:
            self._hist_idx += 1
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.insert(0, self.cmd_history[self._hist_idx])
        else:
            self._hist_idx = None
            self.cmd_entry.delete(0, "end")
            self.cmd_entry.config(fg="#2a6b80")
        return "break"

    def _send(self):
        self._submit_text(self.cmd_entry.get())

    def _voice_click(self):
        # A real mouse click also fires <ButtonPress-1>/<ButtonRelease-1>;
        # ignore the duplicate invocation so the two paths do not fight.
        if time.time() - getattr(self, "_voice_last_press", 0.0) < 0.5:
            return
        self._voice_last_press = time.time()
        if self._ptt_active or self.voice_active:
            self._ptt_stop.set()
            return
        threading.Thread(target=self._voice_listen, daemon=True).start()

    def _voice_listen(self):
        """One-shot click-to-talk: listen once, dispatch what was heard."""
        try:
            if self.speaking.is_set():
                self.ui_q.put(("sys", "Please wait until I finish speaking, sir."))
                return
            self.voice_active = True
            self.ui_q.put(("sys", "Listening..."))
            self.ui_q.put(("status", "LISTENING"))
            heard = self.listen(timeout=8, phrase_limit=12)
            if heard == "__REQUEST_ERROR__":
                self.ui_q.put(("sys",
                               "Speech service unavailable. Check internet connection."))
            elif heard and heard.strip():
                self.ui_q.put(("sys", "You said: " + heard))
                self.ui_q.put(("entry_set", heard))
                threading.Thread(target=self._run_cmd, args=(heard,),
                                 daemon=True).start()
            else:
                self.ui_q.put(("sys", "No speech detected"))
        except Exception as e:
            print("VOICE ERROR:", e)
        finally:
            self._ptt_active = False
            self.voice_active = False
            self.ui_q.put(("voice_btn_idle", None))
            if not self.continuous_listen:
                self.ui_q.put(("status", "STANDBY"))

    def _begin_voice_session(self):
        self.voice_active = True
        self._ptt_active = True
        # Reuse the same Event for every session: replacing it here raced
        # against quit_app(), which sets the old object and missed sessions.
        self._ptt_stop.clear()
        self._ptt_audio = None
        self._ptt_error = None
        self.ui_q.put(("sys", "Listening..."))
        self.ui_q.put(("status", "LISTENING"))
        if not os.environ.get("JARVIS_TEST"):
            # Raw capture needs real microphone hardware; tests inject
            # listen()/process instead.
            self._ptt_thread = threading.Thread(target=self._ptt_record, daemon=True)
            self._ptt_thread.start()

    def _ptt_record(self):
        """Record mic frames from button press until release."""
        try:
            r = sr.Recognizer()
            mic = sr.Microphone()
            with mic as source:
                self._last_mic_err = None
                r.adjust_for_ambient_noise(source, duration=0.2)
                frames = []
                max_bytes = mic.SAMPLE_RATE * mic.SAMPLE_WIDTH * 15
                total = 0
                while not self._ptt_stop.is_set() and total < max_bytes:
                    frame = source.stream.read(mic.CHUNK)
                    frames.append(frame)
                    total += len(frame)
                if frames:
                    self._ptt_audio = sr.AudioData(b"".join(frames),
                                                   mic.SAMPLE_RATE,
                                                   mic.SAMPLE_WIDTH)
        except Exception as e:
            self._ptt_error = self._mic_error_message(e)

    def _ptt_finish(self):
        """Stop recording on release, recognize and dispatch what was heard."""
        t = getattr(self, "_ptt_thread", None)
        self._ptt_stop.set()
        if t and t is not threading.current_thread():
            t.join(timeout=3)
        try:
            if self._ptt_error:
                self.ui_q.put(("sys", self._ptt_error))
                return
            audio = self._ptt_audio
            if getattr(self.listen, "__func__", None) is not JarvisApp.listen:
                # An alternate listen() implementation is installed
                # (tests, alternate input sources): keep one consistent
                # recognition path instead of double-processing frames.
                heard = self.listen(timeout=4, phrase_limit=10)
            elif audio is not None:
                heard = self._recognize_audio(audio)
            else:
                heard = ""
            if heard == "__REQUEST_ERROR__":
                self.ui_q.put(("sys",
                               "Speech service unavailable. Check internet connection."))
                return
            heard = (heard or "").strip()
            if heard:
                self.ui_q.put(("sys", "You said: " + heard))
                self.ui_q.put(("entry_set", heard))
                threading.Thread(target=self._run_cmd, args=(heard,),
                                 daemon=True).start()
            else:
                self.ui_q.put(("sys", "No speech detected"))
        finally:
            self._ptt_active = False
            self.voice_active = False
            self.ui_q.put(("voice_btn_idle", None))
            if not self.continuous_listen:
                self.ui_q.put(("status", "STANDBY"))

    def _voice_press(self, event=None):
        self._voice_last_press = time.time()
        if self._ptt_active or self.voice_active:
            return
        if self.speaking.is_set():
            self.ui_q.put(("sys", "Please wait until I finish speaking, sir."))
            return
        self._voice_hold_mode = True
        self._begin_voice_session()

    def _voice_release(self, event=None):
        if not self._voice_hold_mode:
            return
        self._voice_hold_mode = False
        if not self._ptt_active:
            return
        threading.Thread(target=self._ptt_finish, daemon=True).start()

    def _toggle_auto_listen(self):
        self.continuous_listen = not self.continuous_listen
        if self.continuous_listen:
            self.auto_listen_btn.config(text="AUTO", bg="#0d3a4d", fg=GOLD)
            self._start_continuous_listen()
        else:
            self.auto_listen_btn.config(text="AUTO", bg="#00141f", fg="#5fb3c8")
            self._stop_continuous_listen()

    def _start_continuous_listen(self):
        if self._listen_thread and self._listen_thread.is_alive():
            return
        self._listen_thread = threading.Thread(target=self._continuous_listen_loop, daemon=True)
        self._listen_thread.start()

    def _stop_continuous_listen(self):
        self.continuous_listen = False

    def _continuous_listen_loop(self):
        self.ui_q.put(("status", "LISTENING"))
        while self.continuous_listen:
            if self.speaking.is_set():
                time.sleep(0.15)
                continue
            if self.status_text != "LISTENING":
                self.ui_q.put(("status", "LISTENING"))
            try:
                heard = self.listen(timeout=5, phrase_limit=8)
            except Exception as e:
                self.ui_q.put(("sys", self._mic_error_message(e)))
                time.sleep(1)
                continue
            if not self.continuous_listen:
                break
            if not (heard and heard.strip()):
                continue
            low = heard.strip().lower()
            if low == "stop" or "stop listening" in low:
                self.continuous_listen = False
                self.ui_q.put(("auto_off", None))
                self.say("Continuous listening disabled, sir.")
                break
            if re.search(r"\b(goodbye|exit)\b", low):
                self.say("Shutting down. It has been a pleasure, sir.")
                self.running.clear()
                self.ui_q.put(("shutdown", None))
                return
            m = re.search(r"\b(?:hey\s+)?jarvis\b[,!.]?\s*(.*)$", low)
            if m:
                cmd = m.group(1).strip(" .,")
                if cmd:
                    self.ui_q.put(("sys", "You said: " + cmd))
                    self.ui_q.put(("entry_set", cmd))
                    threading.Thread(target=self._run_cmd, args=(cmd,),
                                     daemon=True).start()
                else:
                    self.say("Yes sir?")
        if not self.speaking.is_set():
            self.ui_q.put(("status", "STANDBY"))

    def _submit_text(self, cmd):
        cmd = (cmd or "").strip()
        if not cmd or cmd == PLACEHOLDER:
            return
        if not self.cmd_history or self.cmd_history[-1] != cmd:
            self.cmd_history.append(cmd)
        self._hist_idx = None
        self.cmd_entry.delete(0, "end")
        self.cmd_entry.config(fg="#9fe9ff")
        self.ui_q.put(("you", cmd))
        self.awake = True
        self.ui_q.put(("awake", None))
        self.ui_q.put(("status", "THINKING"))
        self.cmd_entry.focus_set()
        threading.Thread(target=self._run_cmd, args=(cmd,), daemon=True).start()

    def _run_cmd(self, cmd):
        try:
            if self._is_exit(cmd):
                self.say("Shutting down. It has been a pleasure, sir.")
                self.ui_q.put(("shutdown", None))
                self.running.clear()
                return
            if self._is_sleep_command(cmd):
                self.awake = False
                self.ui_q.put(("sleep", None))
                self.say("Entering standby, sir. Say wake up jarvis when you need me.")
                return
            # "jarvis, what time is it" -> run the trailing command
            m = re.match(r"^\s*(?:hey\s+)?jarvis\s*[,.!?]?\s*(.+)$", cmd, re.I)
            if m and not re.search(r"\b(wake up|wakeup)\b", cmd, re.I):
                self.awake = True
                self.ui_q.put(("awake", None))
                self.process(m.group(1).strip())
                return
            if self._is_wake_command(cmd):
                self.awake = True
                self.ui_q.put(("awake", None))
                self.say("Yes sir, I am awake. Now proceed.")
                return
            self.process(cmd)
        except Exception as e:
            print("ERROR:", e)
            self.ui_q.put(("status", "STANDBY"))
            try:
                self.say("Something went wrong handling that, sir.")
            except Exception:
                pass

    def _quick_cmd(self, cmd):
        if cmd == "__clear__":
            self._clear_transcript()
        else:
            self._submit_text(cmd)

    def _clear_transcript(self):
        try:
            self.tx.config(state="normal")
            self.tx.delete("1.0", "end")
            self.tx.config(state="disabled")
        except Exception:
            pass
        self._line_q.clear()
        self._typing = None
        self._append("SYS", "Transcript cleared, sir.")
        self.say("Transcript cleared, sir.")

    def _on_canvas_click(self, event):
        for iid, (t, act) in self._hint_map.items():
            x0, y0, x1, y1 = self.canvas.bbox(iid)
            if x0 is None:
                continue
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                self._submit_text(act)
                return "break"
        return None

    def _on_canvas_motion(self, event):
        target = None
        for iid, (t, act) in self._hint_map.items():
            x0, y0, x1, y1 = self.canvas.bbox(iid)
            if x0 is None:
                continue
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                target = iid
                break
        if target is not None and target != self._hover_iid:
            self._clear_hover()
            self._hover_iid = target
            self.canvas.itemconfig(self._hint_map[target][0], fill="#eaffff")
            self.canvas.configure(cursor="hand2")
        elif target is None and self._hover_iid is not None:
            self._clear_hover()
        return None

    def _on_canvas_leave(self, event):
        self._clear_hover()

    def _clear_hover(self):
        for t, _act in self._hint_map.values():
            try:
                self.canvas.itemconfig(t, fill="#5fb3c8")
            except Exception:
                pass
        self._hover_iid = None
        self.canvas.configure(cursor="")

    def _mode(self):
        s = self.status_text
        if s == "SLEEP":
            return "sleep"
        if s == "LISTENING":
            return "listen"
        if s == "THINKING":
            return "think"
        if s == "SPEAKING":
            return "speak"
        return "standby"

    def _status_color(self):
        s = self.status_text
        if s in ("THINKING", "SPEAKING"):
            return GOLD
        if s == "SLEEP":
            return "#155d77"
        return CYAN

    def _draw_reactor(self):
        self.canvas.delete("reactor")
        c = COLORS[self._mode()]
        cx, cy, R = self.cx, self.cy, self.R

        for rr, w in ((R + 95, 16), (R + 75, 8), (R + 58, 4)):
            self.canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                    outline=c["glow"], width=w, tags="reactor")
        for rr, w in ((R + 36, 2), (R + 16, 1), (R, 3)):
            self.canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                                    outline=c["ring"], width=w, tags="reactor")

        for i in range(3):
            a = self.spin + i * 120
            rr = R + 36
            self.canvas.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=a,
                                   extent=72, style="arc", outline=c["bright"],
                                   width=5, tags="reactor")
        for i in range(6):
            a = -self.spin * 1.4 + i * 60
            rr = R - 22
            self.canvas.create_arc(cx - rr, cy - rr, cx + rr, cy + rr, start=a,
                                   extent=24, style="arc", outline=c["bright"],
                                   width=3, tags="reactor")

        pulse = 1 + self.pulse_amp * math.sin(self.t / 5)
        r0 = (R - 44) * pulse
        base = (255, 255, 255)
        for k in range(14, 0, -1):
            r = r0 * (k / 14)
            col = _hex(_lerp(base, c["core_rgb"], 1 - k / 14))
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    fill=col, outline="", tags="reactor")
        self.canvas.create_arc(cx - r0 - 2, cy - r0 - 2, cx + r0 + 2, cy + r0 + 2,
                               start=self.spin * 2.5, extent=40, style="arc",
                               outline="#ffffff", width=2, tags="reactor")

    def _draw_wave(self):
        self.canvas.delete("wave")
        x0 = self._X(935)
        x1 = self._X(1225)
        base = self._Y(227)
        pts = []
        listening = self.status_text == "LISTENING"
        for i in range(64):
            x = x0 + i * ((x1 - x0) / 63)
            y = base + math.sin(i * 0.45 + self.t * 0.3) * 7
            y += math.sin(i * 0.13 - self.t * 1.7) * 4
            if listening:
                y += random.uniform(-3, 3)
                y += math.sin(i * 0.9 + self.t * 0.5) * 4
            pts.append((x, y))
        self.canvas.create_line(pts, fill="#2be3ff", width=1, tags="wave")

    def _draw_bars(self):
        self.canvas.delete("bars")
        for dx, dy, dw, getter, col in self.bars_spec:
            x = self._X(dx)
            y = self._Y(dy)
            w = self._X(dw)
            frac = max(0.0, min(1.0, getter()))
            self.canvas.create_rectangle(x, y, x + w, y + 6, outline="",
                                         fill="#00141f", tags="bars")
            fw = max(2, w * frac)
            self.canvas.create_rectangle(x, y, x + fw, y + 6, fill=col,
                                         outline="", tags="bars")

    def _draw_dot(self):
        self.canvas.delete("dot")
        col = self._status_color()
        cx = self._X(612)
        cy = self._Y(106)
        r = 4 + 1.5 * math.sin(self.t / 4)
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                fill=col, outline="", tags="dot")
        self.canvas.create_oval(cx - r - 3, cy - r - 3, cx + r + 3, cy + r + 3,
                                outline=col, width=1, tags="dot")

    def _draw_dock(self):
        self.canvas.delete("dock")
        idx = DOCK_MAP[self._mode()]
        for i, x in enumerate(self.dock_xs):
            r = 9 if i == idx else 6
            if i == idx:
                r += 1 * math.sin(self.t / 3)
            col = "#2be3ff" if i == idx else "#0d3a4d"
            self.canvas.create_oval(x - r, self.dock_cy - r, x + r, self.dock_cy + r,
                                    outline=col, width=2 if i == idx else 1, tags="dock")

    def _draw_scan(self):
        self.canvas.delete("scan")
        y = (self.t * 2.5) % max(100, self.root.winfo_height())
        self.canvas.create_line(0, y, self.root.winfo_width(), y,
                                fill="#083042", width=1, tags="scan")

    def _draw_boot(self):
        self.canvas.delete("boot")
        x0 = self._X(480)
        w = self._X(320)
        y0 = self._Y(122)
        y1 = self._Y(126)
        self.canvas.create_rectangle(x0, y0, x0 + w, y1, outline="#0d4a5e",
                                     fill="#00141f", tags="boot")
        fw = w * self.boot_progress
        self.canvas.create_rectangle(x0, y0, x0 + fw, y1, fill="#2be3ff",
                                     outline="", tags="boot")
        self.canvas.create_text(x0 + w + 6, y0, text=f"{int(self.boot_progress * 100):3d}%",
                                anchor="w", fill=DIMTXT, font=self.F_MICRO, tags="boot")

    def _animate(self):
        if not self.running.is_set():
            return  # app is shutting down; stop the animation loop cleanly
        self._poll_queue()
        if self.engine:
            try:
                self.engine.iterate()
            except Exception:
                pass
            self._tts_tick()

        self.t += 1
        amp, speed = MODE_PARAMS[self._mode()]
        self.pulse_amp = amp
        self.spin = (self.spin + speed) % 360

        self._draw_reactor()
        self._draw_wave()
        self._draw_bars()
        self._draw_dot()
        self._draw_dock()
        self._draw_scan()
        self._tick_mic_blink()
        if self.booting:
            self._draw_boot()
        self._update_clock()
        self._typing_tick()
        self.root.after(30, self._animate)

    def _tts_tick(self):
        if self.engine is None:
            return
        try:
            busy = self.engine.isBusy()
        except Exception:
            busy = False
        if self.speech_pending and busy:
            self.speech_pending = False
        if self.was_busy and not busy:
            self.speech_done.set()
            self.speaking.clear()
            if self.status_text == "SPEAKING":
                if self.continuous_listen:
                    self.status_text = "LISTENING"
                    self.status_lbl.config(text="LISTENING", fg=CYAN)
                else:
                    self.status_text = "STANDBY"
                    self.status_lbl.config(text="STANDBY", fg=CYAN)
        if self.speech_pending and not busy and time.time() - self.pending_since > 5:
            self.speech_pending = False
            self.speech_done.set()
            self.speaking.clear()
        self.was_busy = busy

    def _tick_mic_blink(self):
        """Flash the MIC button while a voice session is active."""
        btn = getattr(self, "voice_btn", None)
        if btn is None:
            return
        active = bool(getattr(self, "_ptt_active", False)) or \
                 bool(getattr(self, "voice_active", False))
        try:
            if active:
                phase = (self.t // 8) % 2
                if phase:
                    btn.config(text="MIC", bg=GREEN, fg="#00251a")
                else:
                    btn.config(text="MIC", bg="#0d3a4d", fg="#eaffff")
            elif btn.cget("text") != "MIC" or str(btn.cget("bg")) != "#00141f":
                btn.config(text="MIC", bg="#00141f", fg=GREEN)
        except Exception:
            pass

    def _poll_queue(self):
        while True:
            try:
                msg = self.ui_q.get_nowait()
            except queue.Empty:
                return
            k = msg[0]
            if k == "status":
                self.status_text = msg[1]
                self.status_lbl.config(text=msg[1], fg=self._status_color())
            elif k == "you":
                self._append("YOU", msg[1])
            elif k == "say":
                self._speak(msg[1])
            elif k == "say_done":
                self.speech_pending = False
                self.speech_done.set()
                self.speaking.clear()
                if self.continuous_listen:
                    self.status_text = "LISTENING"
                    self.status_lbl.config(text="LISTENING", fg=CYAN)
                elif self.status_text == "SPEAKING":
                    self.status_text = "STANDBY"
                    self.status_lbl.config(text="STANDBY", fg=CYAN)
            elif k == "sys":
                self._append("SYS", msg[1])
            elif k == "auto_off":
                self.continuous_listen = False
                try:
                    self.auto_listen_btn.config(text="AUTO", bg="#00141f",
                                                fg="#5fb3c8")
                except Exception:
                    pass
            elif k == "boot_line":
                self._append("SYS", msg[1])
            elif k == "boot_progress":
                self.boot_progress = msg[1]
            elif k == "boot_done":
                self.booting = False
                self.canvas.delete("boot")
                try:
                    self.cmd_entry.focus_set()
                except Exception:
                    pass
            elif k == "awake":
                self.awake = True
            elif k == "sleep":
                self.awake = False
            elif k == "api_key_prompt":
                self._show_api_key_dialog()
            elif k == "entry_set":
                try:
                    self.cmd_entry.delete(0, "end")
                    self.cmd_entry.insert(0, msg[1] or "")
                    self.cmd_entry.config(fg="#9fe9ff")
                except Exception:
                    pass
            elif k == "voice_btn_idle":
                self.voice_active = False
                try:
                    self.voice_btn.config(text="MIC", bg="#00141f")
                except Exception:
                    pass
            elif k == "shutdown":
                self.quit_app()
                return

    def _append(self, who, text):
        self._line_q.append((who, text))
        self._log(who, text)

    def _log(self, who, text):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write("%s  %s> %s\n" % (
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    who, text))
        except Exception:
            pass

    def _typing_tick(self):
        if self._typing is None:
            if not self._line_q:
                return
            who, text = self._line_q.popleft()
            self.tx.config(state="normal")
            if who == "YOU":
                self.tx.insert("end", "YOU> ", ("you_head",))
            elif who == "SYS":
                self.tx.insert("end", "SYS> ", ("s_head",))
            else:
                self.tx.insert("end", "JARVIS> ", ("j_head",))
            self.tx.config(state="disabled")
            self._typing = [who, text, 0]
            return
        who, text, idx = self._typing
        chunk = text[idx:idx + 4]
        if chunk:
            self.tx.config(state="normal")
            tag = "you_body" if who == "YOU" else ("s_body" if who == "SYS" else "j_body")
            self.tx.insert("end", chunk, (tag,))
            self.tx.config(state="disabled")
            self.tx.see("end")
            self._typing[2] = idx + 4
        else:
            self.tx.config(state="normal")
            self.tx.insert("end", "\n")
            self.tx.config(state="disabled")
            self.tx.see("end")
            self._typing = None

    def _speak(self, text):
        self._append("JARVIS", text)
        self.speaking.set()
        if self.engine is None:
            if platform.system() == "Darwin":
                self.status_text = "SPEAKING"
                self.status_lbl.config(text="SPEAKING", fg=GOLD)
                threading.Thread(target=self._say_fallback, args=(text,),
                                 daemon=True).start()
                return
            self.speaking.clear()
            self.status_text = "STANDBY"
            self.status_lbl.config(text="STANDBY", fg=CYAN)
            return
        self.status_text = "SPEAKING"
        self.status_lbl.config(text="SPEAKING", fg=GOLD)
        try:
            self.engine.say(text)
        except Exception:
            # Engine died mid-utterance: release waiters instead of leaving
            # the status stuck on SPEAKING forever.
            self.speech_pending = False
            self.speech_done.set()
            self.speaking.clear()
            self.status_text = "STANDBY"
            self.status_lbl.config(text="STANDBY", fg=CYAN)
            return
        self.speech_pending = True
        self.pending_since = time.time()

    def _say_fallback(self, text):
        try:
            subprocess.run(["say", text], capture_output=True, timeout=120)
        except Exception:
            pass
        self.ui_q.put(("say_done", None))

    def _update_clock(self):
        now = datetime.datetime.now()
        if now.second == self._last_sec:
            return
        self._last_sec = now.second
        self.clock_lbl.config(text=now.strftime("%H:%M:%S"))
        self.date_lbl.config(text=now.strftime("%A  ·  %d %b %Y"))
        if HAVE_PSUTIL:
            try:
                self.cpu = psutil.cpu_percent(interval=None)
                self.mem = psutil.virtual_memory().percent
                battery = psutil.sensors_battery()
                if battery is not None:
                    self.power = battery.percent / 100.0
            except Exception:
                pass
        else:
            self.cpu = 20 + 30 * abs(math.sin(self.t / 40))
            self.mem = 45 + 15 * math.sin(self.t / 60)
        self.val_labels["CPU LOAD"].config(text=f"{self.cpu:.0f}%")
        self.val_labels["MEMORY"].config(text=f"{self.mem:.0f}%")
        up = now - self.start_time
        secs = int(up.total_seconds())
        self.val_labels["UPTIME"].config(
            text="%02d:%02d:%02d" % (secs // 3600, (secs % 3600) // 60, secs % 60))

    def say(self, text):
        print("JARVIS:", text)
        self.ui_q.put(("say", text))
        self.speech_done.clear()
        if os.environ.get("JARVIS_TEST"):
            self.speech_done.set()
            return
        if self.engine is None and platform.system() != "Darwin":
            self.speech_done.set()
        else:
            threading.Thread(target=self._watch_for_interrupt, daemon=True).start()
            self.speech_done.wait(timeout=120)

    def _say_cited(self, answer, sources):
        """Speak an answer and show its sources in the transcript (not spoken)."""
        self.say(answer)
        block = format_sources(sources)
        if block:
            try:
                self._append("JARVIS", "\n" + block)
            except Exception:
                pass

    def _watch_for_interrupt(self):
        try:
            time.sleep(0.35)
            with sr.Microphone() as source:
                r = sr.Recognizer()
                r.pause_threshold = 0.6
                audio = r.listen(source, timeout=3, phrase_time_limit=3)
            heard = r.recognize_google(audio, language="en-US").lower()
        except Exception:
            return
        if any(k in heard for k in ("stop", "shut up", "quiet", "silence",
                                    "enough", "cut it", "cut that")):
            try:
                if self.engine is not None:
                    self.engine.stop()
            except Exception:
                pass
            self.speech_pending = False
            self.speech_done.set()

    def listen(self, timeout=6, phrase_limit=10):
        if self.speaking.is_set():
            return ""
        r = sr.Recognizer()
        r.energy_threshold = 150
        r.dynamic_energy_threshold = True
        r.dynamic_energy_ratio = 1.2
        r.pause_threshold = 0.7
        # Fast-listen: reuse a previously calibrated noise floor instead
        # of burning 1 s on ambient calibration every single listen.
        cached = getattr(self, "_cached_energy", None)
        fast = os.environ.get("JARVIS_SLOW_LISTEN") != "1"
        try:
            with sr.Microphone() as source:
                self._last_mic_err = None
                if fast and cached:
                    r.energy_threshold = cached
                    r.dynamic_energy_threshold = False
                else:
                    r.adjust_for_ambient_noise(source, duration=1.0)
                    if fast:
                        self._cached_energy = r.energy_threshold
                audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        except Exception as e:
            msg = self._mic_error_message(e)
            if msg != getattr(self, "_last_mic_err", None):
                self._last_mic_err = msg
                self.ui_q.put(("sys", msg))
            return ""
        heard = self._recognize_audio(audio)
        if heard == "__REQUEST_ERROR__":
            self.say("My speech service is unreachable, sir. Please check your internet connection.")
            return ""
        return heard

    @staticmethod
    def _mic_error_message(err):
        """Map a voice-pipeline exception to a user-friendly message."""
        if isinstance(err, sr.RequestError):
            return "Speech service unavailable. Check internet connection."
        try:
            text = str(err).lower()
        except Exception:
            text = ""
        if ("permission" in text or "authoriz" in text or "consent" in text
                or "not allowed" in text or "-9999" in text or "-9996" in text):
            return "Microphone permission required. Check System Preferences."
        return "No microphone detected. Check audio settings."

    def _recognize_audio(self, audio):
        """Recognize captured AudioData. Returns lowercased text,
        '' for unintelligible input, or '__REQUEST_ERROR__' on service failure."""
        try:
            audio = self._boost_audio(audio)
        except Exception:
            pass
        r = sr.Recognizer()
        try:
            if USE_WHISPER:
                try:
                    heard = r.recognize_whisper(audio, model="base", language="en")
                    if heard and heard.strip():
                        return heard.lower()
                except Exception:
                    pass
            return r.recognize_google(audio, language="en-US").lower()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            return "__REQUEST_ERROR__"
        except Exception:
            return ""

    def _boost_audio(self, audio):
        try:
            import array
            raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
            samples = array.array("h", raw)
            if not samples:
                return audio
            peak = max(abs(s) for s in samples)
            if peak <= 0 or peak >= 30000:
                return audio
            gain = min(12000 / peak, 3.0)
            if gain <= 1.0:
                return audio
            boosted = array.array("h", (max(-32768, min(32767, int(s * gain)))
                                        for s in samples))
            return sr.AudioData(boosted.tobytes(), 16000, 2)
        except Exception:
            return audio

    def _get_brain(self):
        if getattr(self, "_brain", None) is None:
            self._brain = Brain(self)
        if not getattr(self._brain, "_extra_attempted", False):
            # brain_extra loading is attempted once per brain; repeated
            # attempts just spam warnings when the module is unavailable.
            self._brain._extra_attempted = True
            try:
                self._brain.load_extra()
            except Exception as e:
                print("BRAIN WARNING:", e)
        return self._brain

    def _generate_content(self, prompt, _code_gen_mode=False):
        """Generate content via Groq API. Returns (text, error_msg_or_None).

        If Groq fails, falls back to local brain for simple tasks and
        returns None for tasks that truly need the LLM.
        """
        reply = self._ask_ai_safely(prompt, _code_gen_mode=_code_gen_mode)
        if not reply:
            return None, "I could not generate the content, sir."
        if reply.startswith("My API key was rejected"):
            return None, reply
        if reply.startswith("Your API key limit"):
            return None, reply
        if reply.startswith("I hit an error"):
            local = self._local_chat(prompt)
            if local:
                return local, None
            return None, reply
        if reply.startswith("That is beyond my local memory"):
            return None, reply
        return reply, None

    def _is_research_write(self, cmd):
        has_topic = bool(re.search(
            r"\b(research\s+(?:about|on|the\b|a\b|an\b)|"
            r"write\s+(?:a|an|the|my|one|about|about\s+one|a\s+detailed|a\s+comprehensive)?\s*"
            r"(?:report|notes?|essay|article|summary|page|paragraph|section)|"
            r"write\s+about)\b", cmd))
        has_dest = bool(re.search(
            r"\b(in|to|in my|into|save|save in|save to|notes|notepad|document|file)\b", cmd))
        has_save_intent = bool(re.search(
            r"\b(save|store|write|keep)\b.*\b(it|this|that|the|content|information|research)\b"
            r".*\b(in|to|notes|file|document)\b", cmd, re.I))
        bare_research = bool(re.match(r"\bresearch\s+", cmd))
        return (has_topic and has_dest) or has_save_intent or bare_research

    def _safe_filepath(self, filename):
        """Sanitize a filename to prevent path traversal."""
        return sanitize_filename(filename)

    def _extract_write_file(self, cmd):
        m = re.search(
            r"([a-zA-Z0-9_.-]+\.(?:txt|py|js|html|css|java|c|cpp|md|json|csv|xml|pdf))\b",
            cmd, re.IGNORECASE)
        if m:
            return m.group(1)
        alias = re.search(
            r"\b(notes|notepad|document|journal|diary|log|memo|file)\b",
            cmd, re.IGNORECASE)
        if alias:
            word = alias.group(1).lower()
            if word in ("notes", "note"):
                return "notes.txt"
            if word in ("notepad",):
                return "notepad.txt"
            if word in ("document", "doc"):
                return "document.txt"
            if word in ("journal",):
                return "journal.txt"
            if word in ("diary",):
                return "diary.txt"
            if word in ("log",):
                return "log.txt"
            if word in ("memo",):
                return "memo.txt"
            return "notes.txt"
        return None

    def _is_code_write(self, cmd):
        has_action = bool(re.search(
            r"\b(write|generate|create|save|put|build|make|program|"
            r"develop|compose|draft|assemble|implement|design)\b",
            cmd, re.IGNORECASE))
        has_code_target = bool(re.search(
            r"\b(code|script|program|function|algorithm|implementation|calculator|"
            r"fibonacci|sorting|login|signup|database|todo|chat|api|server|"
            r"game|website|html|python|javascript|app|parser|converter|"
            r"simulator|generator|manager|tracker|assistant|bot|tool|utility|"
            r"library|module|class|interface|template|scaffold|boilerplate)\b",
            cmd, re.IGNORECASE))
        has_dest = bool(re.search(
            r"\b(in|to|into|file|\.py|\.js|\.html|\.java|\.c|\.cpp|"
            r"for me|and save|and write|and put)\b",
            cmd, re.IGNORECASE))
        # Match if: action + code target + dest
        if has_action and has_code_target and has_dest:
            return True
        if has_action and has_code_target and re.search(r"\bpython\b", cmd, re.I):
            return True
        # Match explicit code-writing phrases
        if has_action and has_code_target:
            # Require a clear writing intent, not just mentioning "code"
            if re.search(r"\b(write|generate|create|save|make|build|program)\b",
                         cmd, re.I) and re.search(r"\b(code|script|program)\b", cmd, re.I):
                return True
        return False

    def _handle_research_write(self, cmd):
        topic = cmd
        for p in ["research and write about", "research about", "research on",
                    "write about", "write a report on", "write a report about",
                    "write notes on", "write notes about", "write an essay on",
                    "write an article on", "write about", "write one page about",
                    "write one page on", "write a page about", "write a page on",
                    "write detailed notes about", "write comprehensive notes about",
                    "write the notes about", "save the research about",
                    "write the research about", "write about him",
                    "write about her", "write about them", "write",
                    "research"]:
            topic = re.sub(r"\b" + re.escape(p) + r"\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\b(in|to|in my|into|save|save in|save to|file|notes|"
                       r"notepad|document|about him|about her|about them|and|the|a|an|my|his|her|their)\b",
                       " ", topic, flags=re.IGNORECASE)
        topic = " ".join(topic.split()).strip(" .,")
        if not topic:
            self.say("What should I research about, sir?")
            return
        filename = self._extract_write_file(cmd)
        if not filename:
            filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".txt"
        filename = self._safe_filepath(filename)
        self.ui_q.put(("status", "THINKING"))
        self.say(f"Researching {topic} and writing it to {filename}, sir.")
        content, err = self._generate_content(
            f"Write a comprehensive, detailed one-page research report about {topic}. "
            "Include key facts, achievements, career highlights, and interesting details. "
            "Make it well-structured with paragraphs. Keep it detailed but readable. "
            "Write at least 300 words.")
        if err:
            self.say(err)
            return
        full = f"Research Report: {topic.title()}\n{'=' * 50}\n\n{content}\n"
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full)
            self.say(f"Research on {topic} has been written to {filename}, sir. "
                     f"File saved at {filepath}.")
        except Exception as e:
            self.say(f"Could not write to {filename}, sir: {e}")

    def _strip_code_chatter(self, code):
        """Remove conversational prefixes/suffixes so only code remains."""
        if not code:
            return code
        lines = code.split("\n")
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                start = i + 1
                continue
            if re.match(r"^(?:#|/\*|//|<!--|\"|\'|def |class |import |from |"
                        r"function |const |let |var |<!DOCTYPE|<html|print\(|"
                        r"console\.|public |private |protected |static |void |"
                        r"int |float |double |char |bool |return |if |for |"
                        r"while |try |except |with |as |elif |else |raise |"
                        r"print\(|input\(|True|False|None|\d+|[a-zA-Z_]\w*\s*[=+\-*/<>!]=?)",
                        stripped):
                start = i
                break
            # If line looks like prose (no code symbols), skip it
            if not re.search(r"[(){}\[\]=;:\/\\<>]", stripped) and len(stripped.split()) > 4:
                start = i + 1
                continue
            start = i
            break
        code = "\n".join(lines[start:])
        end = len(lines)
        for i in range(len(lines) - 1, start - 1, -1):
            stripped = lines[i].strip()
            if not stripped:
                end = i
                continue
            if re.match(r"^(?:#|/\*|//|<!--|\"|\'|print\(|console\.|return |"
                        r"if |for |while |def |class |import |function |const |"
                        r"let |var |else |elif |try |except |with |raise |"
                        r"print\(|input\(|True|False|None|\d+|[a-zA-Z_]\w*\s*[=+\-*/<>!]=?)",
                        stripped):
                end = i + 1
                break
            if not re.search(r"[(){}\[\]=;:\/\\<>]", stripped) and len(stripped.split()) > 4:
                end = i
                continue
            end = i + 1
            break
        return "\n".join(lines[start:end]).strip()

    def _handle_code_write(self, cmd):
        # Prefer the PRO coding engine: local templates first, validated
        # LLM generation with retry, and .bak write-back when a target
        # file is named. Falls back to the legacy path if unavailable.
        try:
            import code_brain_pro
            handled = code_brain_pro.delegate_code_write(self, cmd)
        except Exception:
            handled = None
        if handled:
            self.say(handled)
            return
        filename = None
        m = re.search(r"\b(\w+\.(?:py|js|html|css|java|c|cpp|md|json|csv|xml))\b", cmd)
        if m:
            filename = m.group(1)
        topic = cmd
        for p in ["write code for", "write a code for", "write code in",
                    "save code to", "put code in", "paste code in",
                    "write a program for", "write program for",
                    "write a calculator in", "write calculator in",
                    "make a calculator in", "create a calculator in",
                    "write a calculator code in", "generate code for",
                    "write code", "write a code", "code a",
                    "develop a", "develop an", "develop",
                    "compose a", "compose an", "compose",
                    "draft a", "draft an", "draft",
                    "assemble a", "assemble an", "assemble",
                    "implement a", "implement an", "implement",
                    "design a", "design an", "design",
                    "build me a", "build me an", "build a", "build an",
                    "make me a", "make me an", "make a", "make an",
                    "create me a", "create me an", "create a", "create an",
                    "write me a", "write me an", "write a", "write an",
                    "generate a", "generate an", "generate"]:
            if p in topic:
                topic = re.sub(r"\b" + re.escape(p) + r"\b", " ", topic, flags=re.IGNORECASE)
                break
        topic = re.sub(r"\b(in|to|into|file|code|script|program|for|and|my|the|a|an|"
                       r"write|generate|create|save|put|build|develop|compose|draft|"
                       r"assemble|implement|design|python|javascript|html|java|c\+\+|"
                       r"that|which|please|sir|boss|me|your)\b",
                       " ", topic, flags=re.IGNORECASE)
        topic = " ".join(topic.split()).strip(" .,")
        if not filename:
            # Infer filename from topic
            if topic:
                filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".py"
            else:
                filename = "generated_code.py"
            # Detect language preference from command
            if re.search(r"\bjavascript|\.js\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".js"
            elif re.search(r"\bhtml\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".html"
            elif re.search(r"\bjava\b", cmd, re.I) and "javascript" not in cmd.lower():
                filename = filename.rsplit(".", 1)[0] + ".java"
            elif re.search(r"\bc\+\+|\.cpp\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".cpp"
        filename = self._safe_filepath(filename)
        self.ui_q.put(("status", "THINKING"))
        self.say(f"Generating code for {topic or 'your request'} and saving to {filename}, sir.")
        lang = "Python" if filename.endswith(".py") else \
               "JavaScript" if filename.endswith(".js") else \
               "HTML" if filename.endswith(".html") else \
               "Java" if filename.endswith(".java") else \
               "C++" if filename.endswith(".cpp") else "code"
        content, err = self._generate_content(
            f"Write complete, working {lang} code for: {topic or 'a general purpose program'}. "
            "Output ONLY the code, no explanation, no code fences, no markdown. "
            "Make it runnable and complete.", _code_gen_mode=True)
        if err:
            self.say(err)
            return
        code = content.strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
        code = self._strip_code_chatter(code)
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code + "\n")
            self.say(f"Code has been saved to {filename}, sir. File is at {filepath}.")
        except Exception as e:
            self.say(f"Could not write to {filename}, sir: {e}")

    def _ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def _show_info_window(self, title, body):
        self._ui(lambda: self._show_info_window_ui(title, body))

    def _show_info_window_ui(self, title, body):
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#161b22")
            frame = tk.Frame(win, bg="#161b22", padx=12, pady=10)
            frame.pack()
            tk.Label(frame, text=title, font=("Helvetica Neue", 12, "bold"),
                     fg="#e6edf3", bg="#161b22").pack(anchor="w")
            txt = tk.Text(frame, wrap="word", width=60, height=min(20, body.count("\n") + 2),
                          font=("Courier", 11), bg="#0d1117", fg="#c9d1d9",
                          insertbackground="#c9d1d9", relief="flat",
                          highlightthickness=1, highlightbackground="#30363d")
            txt.pack(pady=(6, 0))
            txt.insert("1.0", body[:3000])
            txt.config(state="disabled")
            x = max(8, self.root.winfo_x() + self.root.winfo_width() - 520)
            y = max(8, self.root.winfo_y() + 80)
            win.geometry(f"+{x}+{y}")
            win.after(12000, win.destroy)
        except Exception:
            pass

    @staticmethod
    def _is_placeholder_reply(out):
        s = str(out).strip().lower()
        return s.startswith((
            "i could not reach my language model",
            "local_fallback",
            "that is beyond my local memory",
        ))

    def _ask_ai(self, prompt):
        local = self._local_chat(prompt)
        if local and not self._is_placeholder_reply(local):
            return local
        if not load_api_key():
            return None
        try:
            reply = ask_ai(prompt, list(self.history))
        except Exception as e:
            print("AI REQUEST ERROR:", e)
            return None
        if reply in ("__UNAUTHORIZED__", "__RATE_LIMITED__", None):
            return None
        return reply

    # ================================================================
    # Screen vision
    # ================================================================
    def _take_screenshot(self):
        if privacy_guard_blocked():
            self.say("Privacy guard is on, sir — I won't capture that window.")
            return None, None
        try:
            import pyautogui
            img = pyautogui.screenshot()
            self._last_screenshot = img
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return img, b64
        except Exception as e:
            self.say(f"Screenshot failed: {e}")
            return None, None

    def _ask_vision(self, b64_image, question):
        api_key = load_api_key()
        if not api_key:
            return "I need an API key for vision, sir. Say 'set api key'."
        try:
            resp = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_VISION_MODEL,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{b64_image}"
                            }}
                        ]}
                    ],
                    "max_tokens": 1024,
                },
                timeout=30,
            )
            data = resp.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            return "Could not analyze the screen, sir."
        except Exception as e:
            return "Vision request failed: " + str(e)

    def _handle_screen_query(self, cmd):
        self.say("Capturing screen, sir.")
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("Could not capture screen.")
            return
        low = (cmd or "").lower()
        if "read" in low and ("page" in low or "screen" in low):
            question = ("Read the text visible on this screen. Transcribe the main "
                        "content, then summarize what this page is in one sentence.")
        else:
            question = "Describe everything visible on this screen in detail."
        answer = self._ask_vision(b64, question)
        self.say(answer)

    def _handle_point_query(self, cmd):
        cmd_lower = cmd.lower().strip()
        should_click = cmd_lower.startswith("click on ") or cmd_lower.startswith("click ")
        target = cmd
        for prefix in ("click on ", "click ", "point to ", "show me where ",
                        "find the ", "where is ", "locate "):
            if cmd_lower.startswith(prefix):
                target = cmd[len(prefix):].strip()
                break
        if not target:
            self.say("What should I find, sir?")
            return
        self.say(f"Finding '{target}' on screen, sir.")
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("Could not capture screen.")
            return
        question = (f"Find the UI element: '{target}'. Return ONLY the approximate "
                     f"pixel coordinates (x, y) of its center, like: 450, 320")
        answer = self._ask_vision(b64, question)
        coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
        if coords:
            x, y = int(coords[0][0]), int(coords[0][1])
            self._show_pointer(x, y)
            if should_click:
                self._click_at(x, y)
                self.say(f"Clicked '{target}' at {x}, {y}.")
            else:
                self.say(f"Found '{target}' at coordinates {x}, {y}.")
        else:
            self.say(answer)

    def _show_pointer(self, x, y):
        self._ui(lambda: self._show_pointer_ui(x, y))

    @staticmethod
    def _clamp_pointer_to_display(x, y, size=80):
        px, py = int(x) - size // 2, int(y) - size // 2
        try:
            import multi_monitor
            disp = multi_monitor.display_for_point(x, y)
        except Exception:
            disp = None
        if not disp:
            return px, py
        try:
            dx = int(disp.get("x", 0))
            dy = int(disp.get("y", 0))
            dw = int(disp.get("width", 0))
            dh = int(disp.get("height", 0))
        except Exception:
            return px, py
        if dw <= 0 or dh <= 0:
            return px, py
        px = max(dx, min(px, dx + dw - size))
        py = max(dy, min(py, dy + dh - size))
        return px, py

    def _show_pointer_ui(self, x, y):
        if self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.85)
        size = 80
        px, py = self._clamp_pointer_to_display(x, y, size)
        win.geometry(f"{size}x{size}+{px}+{py}")
        c = None
        try:
            c = tk.Canvas(win, width=size, height=size, bg="",
                          highlightthickness=0)
        except Exception:
            c = tk.Canvas(win, width=size, height=size,
                          bg="#0d1117", highlightthickness=0)
        c.pack()
        c.create_oval(4, 4, size - 4, size - 4, outline="#ff4444", width=3)
        c.create_oval(14, 14, size - 14, size - 14, outline="#ff4444", width=2)
        c.create_text(size // 2, size // 2, text="X", fill="#ff4444",
                      font=("Helvetica Neue", 16, "bold"))
        self._overlay = win
        try:
            rings = [c.create_oval(4, 4, size - 4, size - 4,
                                   outline="#ff4444", width=3)]
            state = {"phase": 0}

            def _pulse():
                if not self._overlay is win:
                    return
                state["phase"] = (state["phase"] + 1) % 6
                r = 4 + state["phase"] * 2
                c.coords(rings[0], r, r, size - r, size - r)
                c.itemconfigure(rings[0],
                                width=5 - state["phase"] // 2)
                win.after(90, _pulse)

            _pulse()
        except Exception:
            pass
        win.after(6000, lambda: self._hide_pointer())

    def _hide_pointer(self):
        if self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None

    # ================================================================
    # File operations
    # ================================================================
    def _data_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    def _extract_filename(self, cmd):
        m = re.search(r"\bfile\s+(?:called\s+|named\s+)?(.+?)\s*[.?!]*$", cmd, re.I)
        if m:
            name = m.group(1).strip().strip("\"'").strip()
        else:
            m2 = re.search(r"[\w.\-]+\.(?:txt|md|json|csv|py|js|ts|html|css|xml|"
                           r"yaml|yml|log|ini|cfg|sh)\b", cmd, re.I)
            name = m2.group(0).strip() if m2 else ""
        name = re.sub(r"\s+dot\s+", ".", name, flags=re.I)
        name = re.sub(r"\s+(please|now|for me)$", "", name, flags=re.I)
        return name or None

    def _resolve_file(self, name, default_ext=".txt"):
        if not name:
            return None
        name = str(name).strip().strip("\"'`").strip()
        if not name:
            return None
        name = re.sub(r"\s+dot\s+", ".", name, flags=re.I)
        if "." not in os.path.basename(name) and default_ext:
            name += default_ext
        return os.path.join(self._data_dir(),
                            sanitize_filename(name, default_ext=default_ext))

    def file_create(self, cmd):
        cm = re.search(r"\bwith\s+(?:the\s+)?content\s+(.+?)\s*$", cmd,
                       re.I | re.S)
        content = ""
        head = cmd
        if cm:
            content = cm.group(1).strip().strip("\"'")
            head = cmd[:cm.start()]
        path = self._resolve_file(self._extract_filename(head))
        if not path:
            self.say("What should I call the file, sir?")
            return
        try:
            if os.path.exists(path):
                self.say(f"{os.path.basename(path)} already exists, sir. Overwriting.")
            with open(path, "w", encoding="utf-8") as f:
                f.write((content + "\n") if content else "")
            if content:
                self.say(f"Created {os.path.basename(path)} with your content.")
            else:
                self.say(f"Created empty file {os.path.basename(path)}, sir.")
        except Exception as e:
            self.say(f"Could not create file: {e}")

    def file_read(self, cmd):
        path = self._resolve_file(self._extract_filename(cmd))
        if not path:
            self.say("Which file should I read, sir?")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            self.say(f"I could not find {os.path.basename(path)}, sir.")
            return
        except Exception as e:
            self.say(f"Could not read file: {e}")
            return
        if not text:
            self.say(f"{os.path.basename(path)} is empty.")
            return
        self._show_info_window(os.path.basename(path), text[:1800])
        spoken = text[:220].replace("\n", " ")
        self.say(f"{os.path.basename(path)} says: {spoken}"
                 + (" ..." if len(text) > 220 else ""))

    def file_delete(self, cmd):
        path = self._resolve_file(self._extract_filename(cmd))
        if not path:
            self.say("Which file should I delete, sir?")
            return
        if not os.path.exists(path):
            self.say(f"{os.path.basename(path)} does not exist, sir.")
            return
        try:
            os.remove(path)
            self.say(f"Deleted {os.path.basename(path)}, sir.")
        except Exception as e:
            self.say(f"Could not delete file: {e}")

    def file_rename(self, cmd):
        m = re.search(r"rename\s+(?:the\s+)?file\s+(.+?)\s+to\s+(.+?)\s*[.?!]*$",
                      cmd, re.I)
        if not m:
            self.say("Say: rename file old dot txt to new dot txt")
            return
        src = self._resolve_file(m.group(1))
        dst = self._resolve_file(m.group(2))
        if not src or not dst or src == dst:
            self.say("I need both the old and the new file name, sir.")
            return
        if not os.path.exists(src):
            self.say(f"{os.path.basename(src)} does not exist, sir.")
            return
        try:
            os.replace(src, dst)
            self.say(f"Renamed {os.path.basename(src)} to {os.path.basename(dst)}.")
        except Exception as e:
            self.say(f"Could not rename file: {e}")

    # ================================================================
    # Code execution
    # ================================================================
    _DANGEROUS_SHELL = re.compile(
        r"\b(sudo|rm\s+(-rf|-fr|--recursive)|mkfs|diskutil\s+erase|dd\s+if="
        r"|shutdown|reboot|halt|killall|\bcurl\b[^|]*\|\s*(ba)?sh"
        r"|chmod\s+777\s+/)", re.I)

    def _run_subprocess(self, args, timeout=20):
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout,
                cwd=self._data_dir())
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                msg = err.splitlines()[-1][:200] if err \
                    else f"exit code {proc.returncode}"
                return None, msg
            return out, None
        except subprocess.TimeoutExpired:
            return None, f"timed out after {timeout} seconds"
        except FileNotFoundError:
            return None, "program not found"
        except Exception as e:
            return None, str(e)

    def run_python_code(self, cmd):
        m = re.search(r"(?:run|execute)\s+python(?:\s+code)?\s*:?\s*(.+?)\s*$",
                      cmd, re.I | re.S)
        code = m.group(1).strip() if m else ""
        if not code:
            self.say("What Python code shall I run, sir?")
            return
        self.say("Running Python code, sir.")
        out, err = self._run_subprocess([sys.executable, "-c", code], timeout=15)
        if err:
            self.say(f"Python error: {err}")
            return
        self._show_info_window("Python output", out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("It ran cleanly with no output, sir.")

    def execute_script(self, cmd):
        m = re.search(r"(?:run|execute)\s+(?:the\s+)?script\s+(.+?)\s*[.?!]*$",
                      cmd, re.I)
        path = self._resolve_file(m.group(1), default_ext=".py") if m else None
        if not path or not os.path.exists(path):
            self.say("I could not find that script, sir.")
            return
        self.say(f"Running {os.path.basename(path)}, sir.")
        out, err = self._run_subprocess([sys.executable, path], timeout=30)
        if err:
            self.say(f"The script failed: {err}")
            return
        self._show_info_window(os.path.basename(path), out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("The script ran with no output, sir.")

    def run_shell_command(self, cmd):
        m = re.search(r"shell\s+(?:command|cmd)\s+(.+?)\s*$", cmd, re.I | re.S)
        raw = m.group(1).strip() if m else ""
        if not raw:
            self.say("Which shell command should I run, sir?")
            return
        if self._DANGEROUS_SHELL.search(raw):
            self.say("That command looks dangerous, sir. I must decline.")
            return
        try:
            args = shlex.split(raw)
        except ValueError:
            args = None
        if not args:
            self.say("I could not parse that command, sir.")
            return
        self.say(f"Running: {' '.join(args)}")
        out, err = self._run_subprocess(args, timeout=15)
        if err:
            self.say(f"The command failed: {err}")
            return
        self._show_info_window("$ " + raw, out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("The command finished with no output, sir.")

    # ================================================================
    # OS notifications
    # ================================================================
    def _notify(self, title, message):
        title = str(title).replace("\\", "").replace('"', "'")
        message = str(message).replace("\\", "").replace('"', "'")
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["osascript", "-e",
                                  f'display notification "{message}" '
                                  f'with title "{title}" sound name "Glass"'])
            elif platform.system() == "Windows":
                try:
                    from plyer import notification
                    notification.notify(title=title, message=message, timeout=8)
                except Exception:
                    pass
        except Exception:
            pass

    # ================================================================
    # Reminders
    # ================================================================
    _REMINDER_UNITS = {"sec": 1, "secs": 1, "second": 1, "seconds": 1,
                       "min": 60, "mins": 60, "minute": 60, "minutes": 60,
                       "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
                       "day": 86400, "days": 86400}

    def set_reminder(self, cmd):
        m = re.search(r"remind\s+me\s+(?:to\s+)?(.+?)\s*[.?!]*$", cmd, re.I)
        if not m:
            self.say("Tell me what to remind you about, sir.")
            return
        body = m.group(1).strip()
        delay = None
        when_txt = ""
        dm = re.search(
            r"\bin\s+(\d+(?:\.\d+)?)\s*"
            r"(sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?|days?)\b", body, re.I)
        tm = re.search(
            r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", body, re.I)
        if dm:
            val = float(dm.group(1))
            unit = dm.group(2).lower()
            delay = val * self._REMINDER_UNITS.get(unit, 60)
            when_txt = f"in {dm.group(1)} {unit}" + ("s" if float(dm.group(1)) != 1 and not unit.endswith("s") else "")
        elif tm:
            now = datetime.datetime.now()
            hour = int(tm.group(1))
            minute = int(tm.group(2) or 0)
            ap = (tm.group(3) or "").replace(".", "").lower()
            if ap.startswith("p") and hour < 12:
                hour += 12
            if ap.startswith("a") and hour == 12:
                hour = 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            delay = (target - now).total_seconds()
            when_txt = "at " + target.strftime("%I:%M %p").lstrip("0")
        if delay is None:
            self.say("When should I remind you, sir? For example: in 10 minutes "
                     "or at 5 pm.")
            return
        span = dm if dm else tm
        task = (body[:span.start()].strip() or body[span.end():].strip()
                or "your reminder").strip(" ,.")

        def _fire():
            try:
                self._active_timers.remove(t)
            except Exception:
                pass
            self.say(f"Reminder, sir: {task}.")
            self._notify("JARVIS Reminder", task)

        t = threading.Timer(max(1.0, delay), _fire)
        t.daemon = True
        self._active_timers.append(t)
        t.start()
        self.say(f"Noted, sir. I will remind you to {task} {when_txt}.")

    # ================================================================
    # Calendar
    # ================================================================
    _WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                 "friday": 4, "saturday": 5, "sunday": 6}

    def _calendar_path(self):
        return os.path.join(self._data_dir(), "jarvis_calendar.json")

    def _load_events(self):
        try:
            with open(self._calendar_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
        except Exception:
            pass
        return []

    def _save_events(self, events):
        try:
            with open(self._calendar_path(), "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2)
        except Exception as e:
            print("CALENDAR SAVE ERROR:", e)

    def _parse_when(self, text):
        tl = text.lower()
        day = datetime.date.today()
        if "day after tomorrow" in tl:
            day += datetime.timedelta(days=2)
        elif "tomorrow" in tl:
            day += datetime.timedelta(days=1)
        else:
            m = re.search(r"\bin\s+(\d+)\s*(day|week)s?\b", tl)
            if m:
                step = int(m.group(1)) * (7 if m.group(2) == "week" else 1)
                day += datetime.timedelta(days=step)
            else:
                for name, idx in self._WEEKDAYS.items():
                    if re.search(r"\b" + name + r"\b", tl):
                        day += datetime.timedelta(days=(idx - day.weekday()) % 7 or 7)
                        break
        tstr = None
        mtm = (re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", tl)
               or re.search(r"\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", tl))
        if mtm and mtm.group(1):
            hour = int(mtm.group(1))
            minute = int(mtm.group(2) or 0)
            ap = (mtm.group(3) or "").replace(".", "").lower()
            if ap.startswith("p") and hour < 12:
                hour += 12
            if ap.startswith("a") and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                tstr = f"{hour:02d}:{minute:02d}"
        return day.isoformat(), tstr

    def calendar_add(self, cmd):
        text = re.sub(r"^\s*(?:hey\s+)?(?:jarvis[,:]\s*)?", "", cmd, flags=re.I)
        text = re.sub(r"\badd\s+(?:an?\s+)?(?:new\s+)?"
                      r"(?:event|appointment|meeting)\b[:\s]*", " ", text,
                      flags=re.I)
        text = re.sub(r"\b(?:to|on|in)\s+(?:my\s+)?calendar\b", " ", text, flags=re.I)
        text = re.sub(r"\s{2,}", " ", text).strip(" .,!") or "event"
        date_iso, tstr = self._parse_when(text)
        title = re.sub(r"\b(?:day after tomorrow|tomorrow|today|tonight)\b",
                       " ", text, flags=re.I)
        title = re.sub(r"\bin\s+\d+\s*(?:day|week)s?\b", " ", title, flags=re.I)
        title = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?",
                       " ", title, flags=re.I)
        title = re.sub(r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?", " ",
                       title, flags=re.I)
        for wd in self._WEEKDAYS:
            title = re.sub(r"\b" + wd + r"\b", " ", title, flags=re.I)
        title = re.sub(r"\s{2,}", " ", title).strip(" ,.-") or text
        events = self._load_events()
        events.append({"date": date_iso, "time": tstr or "", "title": title})
        events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")))
        self._save_events(events)
        nice = date_iso
        try:
            d = datetime.date.fromisoformat(date_iso)
            nice = d.strftime("%B %d")
            if d.year != datetime.date.today().year:
                nice += f" {d.year}"
        except Exception:
            pass
        when = f"{nice} at {tstr}" if tstr else nice
        self.say(f"Scheduled '{title}' for {when}, sir.")

    def calendar_list(self, cmd):
        events = self._load_events()
        today_iso = datetime.date.today().isoformat()
        upcoming = sorted((e for e in events if e.get("date", "") >= today_iso),
                          key=lambda e: (e.get("date", ""), e.get("time", "")))
        if not upcoming:
            self.say("Your calendar is completely clear, sir.")
            return
        lines = [f"{i}. {e.get('date', '?')} "
                 f"{e.get('time') or '--:--'}  —  {e.get('title', '(untitled)')}"
                 for i, e in enumerate(upcoming, 1)]
        self._show_info_window("Upcoming Events", "\n".join(lines) + "\n")
        nxt = upcoming[0]
        when = nxt.get("date", "") + (f" at {nxt['time']}" if nxt.get("time") else "")
        plural = "event" if len(upcoming) == 1 else "events"
        self.say(f"You have {len(upcoming)} upcoming {plural}, sir. "
                 f"Next is {nxt.get('title', 'an event')} on {when}.")

    # ================================================================
    # Email draft
    # ================================================================
    def draft_email(self, cmd):
        self.say("Drafting email, sir.")
        topic = re.sub(
            r"^\s*(?:please\s+)?(?:draft|compose|prepare|write)\s+(?:me\s+)?"
            r"(?:an?\s+)?(?:email\b)?", " ", cmd, flags=re.I)
        topic = topic.replace("email", " ").strip(" .,!") or "a general update"
        content = self._ask_ai(
            f'Draft a short professional email about: "{topic}". '
            "First line must be 'Subject: ...'. Then greeting, concise body, "
            "sign-off. Maximum 130 words. Output only the email.")
        if not content or self._is_placeholder_reply(content):
            content = (f"Subject: {topic.title()}\n\nHi,\n\n"
                       f"I wanted to follow up regarding {topic}. Please let me "
                       "know a good time to discuss.\n\nBest regards,")
        clipped = False
        try:
            import pyperclip
            pyperclip.copy(content)
            clipped = True
        except Exception:
            pass
        suffix = "  (copied to clipboard)" if clipped else ""
        self._show_info_window("Email Draft" + suffix, content)
        if clipped:
            self.say("Your email draft is ready and copied to the clipboard, sir.")
        else:
            self.say("Your email draft is ready, sir.")

    # ================================================================
    # Translation
    # ================================================================
    _TRANSLATIONS = {
        "hello": {"spanish": "hola", "french": "bonjour", "german": "hallo",
                  "italian": "ciao", "hindi": "namaste", "japanese": "konnichiwa"},
        "thank you": {"spanish": "gracias", "french": "merci", "german": "danke",
                      "italian": "grazie", "hindi": "dhanyavaad",
                      "japanese": "arigatou"},
        "goodbye": {"spanish": "adiós", "french": "au revoir",
                    "german": "auf wiedersehen", "italian": "arrivederci"},
        "good morning": {"spanish": "buenos días", "french": "bonjour",
                         "german": "guten morgen", "italian": "buongiorno"},
        "good night": {"spanish": "buenas noches", "french": "bonne nuit",
                       "german": "gute nacht", "italian": "buonanotte"},
        "yes": {"spanish": "sí", "french": "oui", "german": "ja", "italian": "sì"},
        "no": {"spanish": "no", "french": "non", "german": "nein", "italian": "no"},
        "please": {"spanish": "por favor", "french": "s'il vous plaît",
                   "german": "bitte", "italian": "per favore"},
        "water": {"spanish": "agua", "french": "eau", "german": "wasser",
                  "italian": "acqua", "hindi": "paani"},
        "friend": {"spanish": "amigo", "french": "ami", "german": "freund",
                   "italian": "amico", "hindi": "dost"},
    }
    _FOREIGN_MEANINGS = {
        "bonjour": "hello (French)", "hola": "hello (Spanish)",
        "gracias": "thank you (Spanish)", "merci": "thank you (French)",
        "danke": "thank you (German)", "ciao": "hello or goodbye (Italian)",
        "namaste": "greetings (Hindi)", "arigato": "thank you (Japanese)",
        "adios": "goodbye (Spanish)", "auf wiedersehen": "goodbye (German)",
        "buenos dias": "good morning (Spanish)",
        "bonsoir": "good evening (French)",
    }
    _LANG_ALIASES = {
        "spanish": "spanish", "espanol": "spanish", "castilian": "spanish",
        "french": "french", "francais": "french", "german": "german",
        "deutsch": "german", "italian": "italian", "hindi": "hindi",
        "japanese": "japanese", "portuguese": "portuguese", "russian": "russian",
        "chinese": "chinese", "korean": "korean", "arabic": "arabic",
        "english": "english",
    }

    def translate_text(self, cmd):
        m = re.search(r"translate\s+(?:this\s+|that\s+|the\s+)?['\"\u201c\u201d]?(.+?)"
                      r"['\"\u201c\u201d]?\s+(?:to|into|in)\s+([a-zA-Z]+)", cmd, re.I)
        src = target = None
        if not m:
            m = re.search(r"how\s+(?:do|would)\s+(?:you|i|we)\s+say\s+"
                          r"['\"\u201c\u201d]?(.+?)['\"\u201c\u201d]?\s+in\s+([a-zA-Z]+)", cmd, re.I)
        if not m:
            m = re.search(r"what\s+does\s+['\"\u201c\u201d]?(.+?)['\"\u201c\u201d]?\s+mean"
                          r"(?:\s+in\s+([a-zA-Z]+))?", cmd, re.I)
            if m:
                src, target = m.group(1), (m.group(2) or "english")
        if m and src is None:
            src, target = m.group(1), m.group(2)
        if not src or not target:
            self.say("Say: translate hello to Spanish, sir.")
            return
        tlang = self._LANG_ALIASES.get(target.lower().strip(), target.lower().strip())
        key = src.lower().strip(" .?!")
        if tlang == "english":
            meaning = (self._FOREIGN_MEANINGS.get(key)
                       or next((v for k, v in self._FOREIGN_MEANINGS.items()
                                if key in k), None))
            if meaning:
                self.say(f"'{src}' means {meaning}, sir.")
                return
        entry = self._TRANSLATIONS.get(key)
        if entry and tlang in entry:
            self.say(f"'{src}' in {tlang.title()} is '{entry[tlang]}'.")
            return
        self.say("Translating, sir.")
        if tlang == "english":
            prompt = (f"What does '{src}' mean in English? Answer with one short "
                      "sentence that gives the translation and its language.")
        else:
            prompt = (f"Translate this text to {tlang.title()}: '{src}'. "
                      "Reply with ONLY the translation, nothing else.")
        reply = self._ask_ai(prompt)
        if reply:
            self.say(reply.strip())
        else:
            self.say(f"I could not translate '{src}' offline, sir.")

    # ================================================================
    # Unit conversion
    # ================================================================
    UNITS = {
        "mm": ("length", 0.001), "millimeter": ("length", 0.001),
        "millimeters": ("length", 0.001),
        "cm": ("length", 0.01), "centimeter": ("length", 0.01),
        "centimeters": ("length", 0.01),
        "m": ("length", 1.0), "meter": ("length", 1.0), "meters": ("length", 1.0),
        "metre": ("length", 1.0), "metres": ("length", 1.0),
        "km": ("length", 1000.0), "kilometer": ("length", 1000.0),
        "kilometers": ("length", 1000.0), "kilometre": ("length", 1000.0),
        "kilometres": ("length", 1000.0),
        "mi": ("length", 1609.344), "mile": ("length", 1609.344),
        "miles": ("length", 1609.344),
        "ft": ("length", 0.3048), "foot": ("length", 0.3048),
        "feet": ("length", 0.3048),
        "in": ("length", 0.0254), "inch": ("length", 0.0254),
        "inches": ("length", 0.0254),
        "yd": ("length", 0.9144), "yard": ("length", 0.9144),
        "yards": ("length", 0.9144),
        "mg": ("mass", 1e-06), "milligram": ("mass", 1e-06),
        "milligrams": ("mass", 1e-06),
        "g": ("mass", 0.001), "gram": ("mass", 0.001), "grams": ("mass", 0.001),
        "kg": ("mass", 1.0), "kilogram": ("mass", 1.0),
        "kilograms": ("mass", 1.0), "kilo": ("mass", 1.0), "kilos": ("mass", 1.0),
        "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237),
        "pound": ("mass", 0.45359237), "pounds": ("mass", 0.45359237),
        "oz": ("mass", 0.028349523125), "ounce": ("mass", 0.028349523125),
        "ounces": ("mass", 0.028349523125),
        "ton": ("mass", 907.18474), "tons": ("mass", 907.18474),
        "ml": ("volume", 0.001), "milliliter": ("volume", 0.001),
        "milliliters": ("volume", 0.001),
        "l": ("volume", 1.0), "liter": ("volume", 1.0), "liters": ("volume", 1.0),
        "litre": ("volume", 1.0), "litres": ("volume", 1.0),
        "gal": ("volume", 3.785411784), "gallon": ("volume", 3.785411784),
        "gallons": ("volume", 3.785411784),
        "cup": ("volume", 0.2365882365), "cups": ("volume", 0.2365882365),
        "mps": ("speed", 1.0), "m/s": ("speed", 1.0),
        "kmh": ("speed", 0.2777777777777778), "kph": ("speed", 0.2777777777777778),
        "km/h": ("speed", 0.2777777777777778),
        "kmph": ("speed", 0.2777777777777778),
        "mph": ("speed", 0.44704),
        "knot": ("speed", 0.5144444444444445),
        "knots": ("speed", 0.5144444444444445),
    }
    TEMPERATURE_UNITS = {"c": "celsius", "celsius": "celsius",
                         "f": "fahrenheit", "fahrenheit": "fahrenheit",
                         "k": "kelvin", "kelvin": "kelvin"}

    @staticmethod
    def _temp_convert(v, f_from, t_to):
        if f_from == t_to:
            return v
        if f_from == "celsius":
            c = v
        elif f_from == "fahrenheit":
            c = (v - 32) * 5 / 9
        else:
            c = v - 273.15
        if t_to == "celsius":
            return c
        if t_to == "fahrenheit":
            return c * 9 / 5 + 32
        return c + 273.15

    @staticmethod
    def _fmt_num(x):
        x = round(x, 4)
        if abs(x - round(x)) < 1e-9:
            return f"{int(round(x)):,}"
        return f"{x:,.4f}".rstrip("0").rstrip(".")

    def convert_units(self, cmd):
        m = re.search(
            r"(-?\d+(?:\.\d+)?)\s*(?:degrees?\s+|\u00b0\s*)?"
            r"([a-zA-Z\u00b0/]+?)\s+(?:to|into|in|as|=)\s+"
            r"(?:degrees?\s+|\u00b0\s*)?([a-zA-Z\u00b0/]+?)\s*[.?!,]*$", cmd.strip(), re.I)
        if not m:
            return None
        value = float(m.group(1))
        u_from = m.group(2).lower().rstrip(".")
        u_to = m.group(3).lower().rstrip(".")
        d_from, d_to = m.group(2), m.group(3)
        t_from = self.TEMPERATURE_UNITS.get(u_from)
        t_to = self.TEMPERATURE_UNITS.get(u_to)
        if t_from and t_to:
            result = self._temp_convert(value, t_from, t_to)
            return (f"{self._fmt_num(value)} degrees {t_from.title()} equals "
                    f"{self._fmt_num(result)} degrees {t_to.title()}, sir.")
        if t_from or t_to:
            return "I can only convert temperature into other temperature units, sir."
        a = self.UNITS.get(u_from)
        b = self.UNITS.get(u_to)
        if not a or not b:
            return None
        if a[0] != b[0]:
            return f"I cannot convert {a[0]} into {b[0]}, sir."
        result = value * a[1] / b[1]
        return (f"{self._fmt_num(value)} {d_from} equals "
                f"{self._fmt_num(result)} {d_to}, sir.")

    # ================================================================
    # Color tool
    # ================================================================
    COLOR_PALETTE = [
        ("red", "#FF0000"), ("crimson", "#DC143C"), ("tomato", "#FF6347"),
        ("coral", "#FF7F50"), ("salmon", "#FA8072"), ("orange", "#FFA500"),
        ("gold", "#FFD700"), ("yellow", "#FFFF00"), ("khaki", "#F0E68C"),
        ("olive", "#808000"), ("lime", "#00FF00"), ("green", "#008000"),
        ("emerald", "#50C878"), ("mint", "#98FF98"), ("teal", "#008080"),
        ("turquoise", "#40E0D0"), ("cyan", "#00FFFF"), ("sky blue", "#87CEEB"),
        ("royal blue", "#4169E1"), ("blue", "#0000FF"), ("navy", "#000080"),
        ("indigo", "#4B0082"), ("purple", "#800080"), ("violet", "#EE82EE"),
        ("lavender", "#E6E6FA"), ("magenta", "#FF00FF"), ("pink", "#FFC0CB"),
        ("hot pink", "#FF69B4"), ("brown", "#A52A2A"), ("chocolate", "#D2691E"),
        ("beige", "#F5F5DC"), ("maroon", "#800000"), ("gray", "#808080"),
        ("silver", "#C0C0C0"), ("white", "#FFFFFF"), ("black", "#000000"),
    ]

    @staticmethod
    def _hex_to_rgb(hx):
        hx = hx.lstrip("#")
        return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _rgb_to_hsl(r, g, b):
        r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
        mx, mn = max(r_, g_, b_), min(r_, g_, b_)
        l = (mx + mn) / 2.0
        if mx == mn:
            return 0.0, 0.0, l * 100.0
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r_:
            h = ((g_ - b_) / d) % 6
        elif mx == g_:
            h = (b_ - r_) / d + 2
        else:
            h = (r_ - g_) / d + 4
        return h * 60.0, s * 100.0, l * 100.0

    def _nearest_color_name(self, rgb):
        best, best_d = None, float("inf")
        for name, hx in self.COLOR_PALETTE:
            pr = self._hex_to_rgb(hx)
            dist = sum((a - b) ** 2 for a, b in zip(rgb, pr))
            if dist < best_d:
                best_d, best = dist, name
        return best

    def color_info(self, cmd):
        hm = re.search(r"#?\b([0-9a-fA-F]{6})\b", cmd)
        if hm:
            raw = hm.group(1)
            hx = "#" + raw.upper()
            rgb = self._hex_to_rgb(raw)
            h, s, l = self._rgb_to_hsl(*rgb)
            name = self._nearest_color_name(rgb)
            self._show_color_swatch(hx, f"{hx} \u00b7 {name}")
            return (f"{hx} is red {rgb[0]}, green {rgb[1]}, blue {rgb[2]} \u2014 "
                    f"hue {int(h)} degrees, saturation {int(s)} percent, "
                    f"lightness {int(l)} percent. Closest named color: {name}.")
        fam = re.search(r"\b(nice|pretty|beautiful|good|random|dark|light|pastel)?\s*"
                        r"(red|orange|yellow|green|teal|cyan|blue|purple|pink|brown|"
                        r"gray|grey|black|white)s?\b", cmd, re.I)
        if fam:
            family = fam.group(2).lower()
            family = {"grey": "gray", "violet": "purple"}.get(family, family)
            picks = [(nm, hx) for nm, hx in self.COLOR_PALETTE if family in nm.lower()]
            if picks:
                name, hx = random.choice(picks)
                self._show_color_swatch(hx, f"{name} \u00b7 {hx}")
                return f"A lovely {family} for you, sir: {name}, hex code {hx}."
        return None

    def _show_color_swatch(self, hex_color, label):
        self._ui(lambda: self._show_color_swatch_ui(hex_color, label))

    def _show_color_swatch_ui(self, hex_color, label):
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#161b22")
            frame = tk.Frame(win, bg="#161b22", padx=10, pady=10)
            frame.pack()
            sw = tk.Canvas(frame, width=150, height=60, highlightthickness=1,
                           highlightbackground="#30363d", bg=hex_color)
            sw.pack()
            tk.Label(frame, text=label, font=("Helvetica Neue", 10),
                     fg="#c9d1d9", bg="#161b22").pack(pady=(4, 0))
            x = max(8, self.root.winfo_x() - 190)
            y = max(8, self.root.winfo_y())
            win.geometry(f"+{x}+{y}")
            win.after(7000, win.destroy)
        except Exception:
            pass

    # ================================================================
    # QR codes
    # ================================================================
    def generate_qr(self, cmd):
        m = re.search(r"qr\s*-?\s*code\s*(?:for|of|with|containing)?\s*:?\s*"
                      r"(.+?)\s*[.?!]*$", cmd, re.I)
        data = m.group(1).strip().strip("\"'") if m else ""
        if not data:
            self.say("What should the QR code contain, sir?")
            return
        fname = "qr_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
        path = os.path.join(self._data_dir(), fname)
        try:
            import qrcode
            qrcode.make(data).save(path)
        except Exception:
            from urllib.parse import quote
            webbrowser.open("https://api.qrserver.com/v1/create-qr-code/"
                            f"?size=320x320&data={quote(data)}")
            self.say("I generated the QR code in your browser, sir.")
            return
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            elif platform.system() == "Windows":
                os.startfile(path)
            else:
                webbrowser.open("file://" + path)
        except Exception:
            pass
        self.say(f"QR code saved as {fname} and opened, sir.")

    def _handle_fix_screen(self, cmd):
        """Take a screenshot, analyze the screen, and attempt to fix issues."""
        self.say("Let me take a look at your screen, sir.")
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("I could not capture your screen, sir.")
            return
        
        analysis = self._ask_vision(b64, (
            "Look at this screen carefully. Is there any error, warning, bug, "
            "or issue visible? Describe exactly what you see that needs fixing. "
            "If there's an error message, quote it exactly. "
            "If there's a form with missing fields, describe which ones. "
            "If there's a button that needs clicking, describe its location. "
            "Be specific about what needs to be done to fix the issue."
        ))
        
        if not analysis or analysis == "__UNAUTHORIZED__":
            self.say("I need an API key for vision, sir. Say 'set api key'.")
            return
        
        self.say(f"I see the following on your screen:\n{analysis}")
        
        fix = self._ask_vision(b64, (
            f"Based on this screen analysis: '{analysis}'\n"
            "What specific action should be taken to fix this issue? "
            "Reply with ONE of these action types and details:\n"
            "- CLICK: [description of what to click and where]\n"
            "- TYPE: [what text to type and where]\n"
            "- SCROLL: [up or down and how much]\n"
            "- SHORTCUT: [keyboard shortcut to press]\n"
            "- CODE: [code to write to fix the issue]\n"
            "- NONE: [if no action is needed]\n"
            "Be specific about coordinates if CLICK, or text if TYPE."
        ))
        
        if not fix or fix == "__UNAUTHORIZED__":
            self.say("I could not determine a fix, sir.")
            return
        
        self.say(f"Here is what I recommend: {fix}")
        
        try:
            import pyautogui
            
            fix_upper = fix.upper()
            
            if fix_upper.startswith("CLICK"):
                coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", fix)
                if coords:
                    x, y = int(coords[0][0]), int(coords[0][1])
                    self._click_at(x, y)
                    self.say(f"Clicked at {x}, {y} to fix the issue.")
                else:
                    self.say("I found the fix but could not determine exact coordinates.")
            
            elif fix_upper.startswith("TYPE"):
                text_match = re.search(r"[:'\"\"](.+?)['\"\"]?$", fix)
                if text_match:
                    text = text_match.group(1).strip()
                    pyautogui.typewrite(text, interval=0.02)
                    self.say(f"Typed: {text}")
                else:
                    self.say("I found the fix but could not determine the text to type.")
            
            elif fix_upper.startswith("SCROLL"):
                if "up" in fix.lower():
                    pyautogui.scroll(3)
                    self.say("Scrolled up.")
                elif "down" in fix.lower():
                    pyautogui.scroll(-3)
                    self.say("Scrolled down.")
                else:
                    pyautogui.scroll(-3)
                    self.say("Scrolled down.")
            
            elif fix_upper.startswith("SHORTCUT"):
                keys = re.findall(r"\b(ctrl|command|cmd|alt|shift|enter|tab|esc|delete|backspace|space|up|down|left|right|[a-z])\b", fix.lower())
                if keys:
                    pyautogui.hotkey(*keys[:4])
                    self.say(f"Pressed shortcut: {'+'.join(keys[:4])}")
                else:
                    self.say("I found the fix but could not determine the shortcut keys.")
            
            elif fix_upper.startswith("CODE"):
                code_match = re.search(r"[:'\"\"](.+?)['\"\"]?$", fix, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    self.say(f"Here is the code to fix the issue:\n{code}")
                else:
                    self.say("I found the fix but could not extract the code.")
            
            else:
                self.say("I analyzed your screen but no automatic fix was possible. Please fix manually.")
        
        except ImportError:
            self.say("I need pyautogui for automatic fixes, sir.")
        except Exception as e:
            self.say(f"Could not apply the automatic fix: {e}")

    def process(self, command):
        if not isinstance(command, str):
            return
        cmd = command.lower().strip()
        if not cmd or cmd == PLACEHOLDER.lower():
            return

        m_j = re.match(r"^(?:hey\s+)?jarvis\s*[,.!?\s]+\s*(.+)$", cmd, re.I)
        if m_j:
            cmd = m_j.group(1).strip()

        clauses = self._split_commands(cmd)
        if len(clauses) > 1:
            for c in clauses:
                self.process(c)
            return
        cmd = clauses[0]

        if self._future_time_intent(cmd):
            self._handle_future_time(cmd)
            return
        if self._time_intent(cmd):
            self._handle_time(cmd)
            return
        if self._date_intent(cmd):
            now = datetime.datetime.now().strftime("%A, %B %d, %Y")
            self.say(f"Today is {now}.")
            return

        if self._is_sleep_command(cmd):
            self.awake = False
            self.say("Entering standby, sir. Say wake up jarvis when you need me.")
            return

        if self._is_wake_command(cmd):
            self.awake = True
            self.say("I am awake and ready, sir.")
            return

        br = parse_build_request(cmd)
        if br:
            self.build_website(br["topic"], br["kind"])
            return

        if self._is_research_write(cmd):
            self._handle_research_write(cmd)
            return

        if self._is_code_write(cmd):
            self._handle_code_write(cmd)
            return

        try:
            hit = self._get_brain().think(cmd, priority=True)
        except Exception as e:
            print("BRAIN ERROR:", e)
            hit = None
        if hit:
            skill, ctx = hit
            self.ui_q.put(("status", "THINKING"))
            try:
                out = skill.execute(self, ctx)
            except Exception as e:
                print("BRAIN ERROR:", e)
                out = None
            if out:
                self.last_reply = out
                # Keep user/assistant turns paired so the LLM context
                # stays coherent when the local skill handled this command.
                self.history.append({"role": "user", "content": cmd})
                self.history.append({"role": "assistant", "content": out})
                self.say(out)
                return

        if any(w in cmd for w in ["fix this", "fix the error", "fix my screen",
                                   "fix what you see", "fix the screen",
                                   "fix the bug", "fix the issue",
                                   "help me fix", "can you fix"]):
            self._handle_fix_screen(cmd)
            return

        # Screen queries
        if any(w in cmd for w in ["what's on my screen", "read my screen",
                                   "what is on my screen", "describe my screen",
                                   "screenshot", "what do you see",
                                   "what's on the screen"]):
            self._handle_screen_query(cmd)
            return

        # Point queries
        if any(w in cmd for w in ["point to", "show me where", "find the",
                                   "where is", "click on", "locate"]):
            self._handle_point_query(cmd)
            return

        if self._weather_intent(cmd):
            self._handle_weather(cmd)
            return

        if self._is_open(cmd):
            self._handle_open(cmd)
            return

        if self._is_search(cmd):
            self._handle_search(cmd)
            return

        if self._play_youtube(cmd):
            return

        # File operations
        if re.search(r"\b(delete|remove)\s+(?:the\s+)?file\b", cmd):
            self.file_delete(cmd)
            return
        if re.search(r"\brename\s+(?:the\s+)?file\b", cmd):
            self.file_rename(cmd)
            return
        if re.search(r"\b(read|show|view|cat|open)\s+(?:the\s+)?(?:contents\s+of\s+)?(?:text\s+)?file\b", cmd):
            self.file_read(cmd)
            return
        if re.search(r"\b(create|make)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?file\b|\bnew\s+file\b", cmd):
            self.file_create(cmd)
            return

        # Code execution
        if re.search(r"\b(run|execute)\s+python(?:\s+code)?\b", cmd):
            self.run_python_code(cmd)
            return
        if re.search(r"\b(execute|run)\s+(?:the\s+)?script\b", cmd):
            self.execute_script(cmd)
            return
        if re.search(r"\b(run|execute)\s+(?:a\s+)?shell\s+(?:command|cmd)\b", cmd):
            self.run_shell_command(cmd)
            return

        # Reminders
        if re.search(r"\bremind\s+me\b", cmd):
            self.set_reminder(cmd)
            return

        # To-do / task list
        if self._is_todo(cmd):
            self._handle_todo(cmd)
            return

        # Calendar
        if re.search(r"\b(add|schedule)\s+(?:an?\s+)?(?:new\s+)?(?:event|appointment|meeting)\b", cmd):
            self.calendar_add(cmd)
            return
        if re.search(r"\b(calendar|schedule|upcoming\s+events|what'?s?\s+(?:on\s+)?(?:my\s+)?calendar)\b", cmd):
            self.calendar_list(cmd)
            return

        # Email
        if re.search(r"\b(draft|compose|prepare|write)\s+me\s+(?:an?\s+)?email\b", cmd):
            self.draft_email(cmd)
            return

        # Translation
        if re.search(r"\btranslate\b", cmd):
            self.translate_text(cmd)
            return

        # QR code
        if re.search(r"\bqr\s*-?\s*code\b", cmd):
            self.generate_qr(cmd)
            return

        # Color tool
        if re.search(r"\bcolor\b", cmd) or re.search(r"#?[0-9a-fA-F]{6}\b", cmd):
            result = self.color_info(cmd)
            if result:
                self.say(result)
                return

        if self._calc_intent(cmd):
            return

        if self._convert_intent(cmd):
            return

        if self._timer_intent(cmd):
            self._handle_timer(cmd)
            return

        if self._battery_intent(cmd):
            self._handle_battery(cmd)
            return

        if self._is_define(cmd):
            self._handle_define(cmd)
            return

        if self._system_action(cmd):
            return

        if self._is_api_key(cmd):
            self.set_api_key()
            return

        if self._is_clear_memory(cmd):
            self.history.clear()
            self.say("Memory cleared, sir. I am running clean.")
            return

        if self._is_repeat(cmd):
            if self.last_reply:
                self.say(self.last_reply)
            else:
                self.say("I have not said anything yet, sir.")
            return

        try:
            hit = self._get_brain().think(cmd)
        except Exception as e:
            print("BRAIN ERROR:", e)
            hit = None
        if hit:
            skill, ctx = hit
            self.ui_q.put(("status", "THINKING"))
            try:
                out = skill.execute(self, ctx)
            except Exception as e:
                print("BRAIN ERROR:", e)
                out = None
            if out:
                self.last_reply = out
                self.history.append({"role": "user", "content": cmd})
                self.history.append({"role": "assistant", "content": out})
                self.say(out)
            return

        self.ui_q.put(("status", "THINKING"))
        self.history.append({"role": "user", "content": cmd})
        reply = self._ask_ai_safely(cmd)
        if reply == "__UNAUTHORIZED__":
            self.history.pop()
            self.say("That key was rejected too, sir. Please double check it on groq dot com.")
            return
        if reply is None:
            self.history.pop()
            return
        self.history.append({"role": "assistant", "content": reply})
        self.last_reply = reply
        sources = web_search(cmd) if _is_web_worthy(cmd) else []
        if sources:
            self._say_cited(reply, sources)
        else:
            self.say(reply)

    def _split_commands(self, cmd):
        parts = re.split(r"\s*,\s*|\s+and\s+|\s+then\s+|\s*;\s*", cmd)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return [cmd]

        def command_like(p):
            if re.search(r"\b(open|go to|play|search|build|make|create|set|"
                         r"start|timer|remind|convert|calculate|compute|"
                         r"define|weather|battery|volume)\b", p):
                return True
            if self._time_intent(p) or self._date_intent(p):
                return True
            if self._weather_intent(p) or self._calc_intent(p):
                return True
            if self._match_website(p):
                return True
            for key in APP_MAP:
                if re.search(r"\b" + re.escape(key) + r"\b", p):
                    return True
            return False

        if all(command_like(p) for p in parts):
            first = parts[0].strip().lower()
            if first.startswith(("open ", "go to ")):
                verb = first.split()[0]
                for i in range(1, len(parts)):
                    p = parts[i].strip().lower()
                    if not re.match(r"^(?:open|go to|play|search|build|make|create|set|"
                                    r"start|timer|remind|convert|calculate|compute|define|"
                                    r"battery|volume)\b", p) and self._match_website(p):
                        parts[i] = f"{verb} {parts[i]}"
            return parts
        return [cmd]

    def _is_search(self, cmd):
        return bool(re.search(r"\bsearch(?:ing)?\b|\blook\s+up\b|\bgoogle\b", cmd))

    def _handle_search(self, cmd):
        query = re.sub(r"^(?:search for|search)\s*", "", cmd).strip(" .,")
        if not query:
            self.say("What should I search for, sir?")
            return
        if "wikipedia" in query:
            topic = re.sub(r"\bwikipedia\b", "", query).strip(" .,")
            topic = re.sub(r"^(?:for|about|on)\s+", "", topic)
            if not topic:
                self.say("What should I look up on Wikipedia, sir?")
                return
            self.say(f"Searching Wikipedia for {topic}.")
            webbrowser.open("https://en.wikipedia.org/wiki/Special:Search?search="
                            + topic.replace(" ", "+"))
            return
        self.say(f"Searching for {query}.")
        webbrowser.open("https://www.google.com/search?q=" + query.replace(" ", "+"))

    def _is_open(self, cmd):
        # "open X" or "go to X" at the start; or a bare website/app name
        if re.match(r"^(?:open|go\s+to|launch)\b", cmd):
            return True
        return self._bare_name(cmd) is not None

    def _bare_name(self, cmd):
        c = cmd.strip(" .,")
        if not c or c in ("open", "go to"):
            return None
        m = self._match_website(c)
        if m and m[0] == c:
            return ("website", m[0], m[1])
        for key, app in APP_MAP.items():
            if c == key:
                return ("app", key, app)
        return None

    def _open_target(self, kind, name, target):
        if kind == "website":
            self.say(f"Opening {name}.")
            webbrowser.open(target)
            return
        if open_app(target):
            self.say(f"Opening {target}.")
        else:
            self.say(f"I could not find {target}, sir.")

    def _fuzzy_target(self, rest):
        close_web = difflib.get_close_matches(rest, list(WEBSITES), n=1, cutoff=0.7)
        if close_web:
            name = close_web[0]
            return ("website", name, WEBSITES[name])
        close_app = difflib.get_close_matches(rest, list(APP_MAP), n=1, cutoff=0.7)
        if close_app:
            key = close_app[0]
            return ("app", key, APP_MAP[key])
        return None

    def _handle_open(self, cmd):
        if not re.match(r"^(?:open|go\s+to|launch)\b", cmd):
            b = self._bare_name(cmd)
            if b:
                self._open_target(b[0], b[1], b[2])
            return
        m = re.match(r"^(?:go to|open|launch)\s*(.*)$", cmd)
        rest = (m.group(1) if m else cmd).strip(" .,")
        rest = re.sub(r"^(?:the|a|an|please|just)\s+", "", rest).strip()
        if not rest:
            self.say("What would you like me to open, sir?")
            return
        match = self._match_website(rest)
        if match:
            name, url = match
            self.say(f"Opening {name}.")
            webbrowser.open(url)
            return
        for key, app in APP_MAP.items():
            if re.search(r"\b" + re.escape(key) + r"\b", rest):
                if open_app(app):
                    self.say(f"Opening {app}.")
                else:
                    self.say(f"I could not find {app}, sir. Searching the web for it instead.")
                    webbrowser.open("https://www.google.com/search?q=" + app.replace(" ", "+"))
                return
        fuzzy = self._fuzzy_target(rest)
        if fuzzy:
            kind, name, target = fuzzy
            self.say(f"Did you mean {name}? Opening it, sir.")
            self._open_target(kind, name, target)
            return
        if "." in rest:
            self.say(f"Opening {rest}.")
            webbrowser.open("https://" + rest)
            return
        self.say(f"I could not find {rest}, sir. Searching the web for it instead.")
        webbrowser.open("https://www.google.com/search?q=" + rest.replace(" ", "+"))

    TIME_OF_DAY = {"morning", "afternoon", "evening", "night", "tonight",
                   "noon", "midnight"}

    def _time_intent(self, cmd):
        return bool(re.search(
            r"\b(what('s| is| s)? the time|what time is it|current time|"
            r"time now|tell me the time)\b", cmd))

    def _location_in(self, cmd):
        m = re.search(r"\bin\s+(?:the\s+)?([A-Za-z][A-Za-z .'-]*?)[?.!]*$", cmd)
        if not m:
            return None
        loc = m.group(1).strip(" .")
        if not loc or loc.lower() in self.TIME_OF_DAY or "time" in loc.lower():
            return None
        return loc

    def _handle_time(self, cmd):
        loc = self._location_in(cmd)
        if loc:
            self.ui_q.put(("status", "THINKING"))
            reply = self._ask_ai_safely(
                f"What is the current local time in {loc}? "
                "Answer in one short spoken sentence.")
            if reply and reply != "__UNAUTHORIZED__":
                self.say(reply)
            return
        now = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        self.say(f"The time is {now}.")

    def _date_intent(self, cmd):
        return bool(re.search(
            r"\b(what('s| is| s)? the date|what date|today.?s date|"
            r"what day(?! of the week| was))\b", cmd))

    def _match_website(self, rest):
        best = None
        best_len = -1
        for name, url in WEBSITES.items():
            for m in re.finditer(r"\b" + re.escape(name) + r"\b", rest):
                length = m.end() - m.start()
                if length > best_len:
                    best_len = length
                    best = (name, url)
        return best

    def _play_youtube(self, cmd):
        if re.search(r"\b(pause|resume|stop|next|previous|skip)\b", cmd) and \
                re.search(r"\b(music|song|track)\b", cmd):
            return False
        if re.search(r"\bsearch\b", cmd):
            return False
        if not re.search(r"\bplay\b", cmd):
            if ("open" in cmd or "go to" in cmd
                    or not re.search(r"\bsong\b|\bmusic\b", cmd)):
                return False
        m = re.search(r"\bplay\b", cmd)
        query = cmd[m.end():] if m else cmd
        query = re.sub(r"\bon youtube\b|\bin youtube\b|youtube", " ", query)
        for w in ("please", "can you", "could you", "will you", "would you",
                  "i want to", "can", "could", "will", "would", "do", "the",
                  "and", "some", "a", "an", "song", "music", "called",
                  "named", "name", "to"):
            query = re.sub(r"\b" + re.escape(w) + r"\b", " ", query)
        query = re.sub(r"\s+", " ", query).strip(" .,")
        if not query:
            return False
        if query in GAME_WORDS:
            self.say(f"{query.title()} is a game, sir. I can search it on YouTube "
                     "if you want to watch a playthrough.")
            return True
        self.say(f"Playing {query} on YouTube.")
        video = self._youtube_first_video(query)
        if video:
            webbrowser.open(video)
        else:
            webbrowser.open("https://www.youtube.com/results?search_query="
                            + query.replace(" ", "+"))
        return True

    def _youtube_first_video(self, query):
        try:
            resp = requests.get(
                "https://www.youtube.com/results",
                params={"search_query": query},
                headers={
                    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0.0.0 Safari/537.36")
                },
                timeout=8,
            )
            m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', resp.text)
            if m:
                return "https://www.youtube.com/watch?v=" + m.group(1)
        except Exception:
            pass
        return None

    def _local_chat(self, prompt, _code_gen_mode=False):
        getter = getattr(self, "_get_brain", None)
        if not callable(getter):
            return None
        try:
            return getter().chat(prompt, _code_gen_mode=_code_gen_mode)
        except Exception as e:
            print("LOCAL CHAT ERROR:", e)
            return None

    def _ask_ai_safely(self, prompt, _code_gen_mode=False):
        """Smart routing: try local brain first, then Groq for complex tasks.

        Returns the response string, or None if nothing worked.
        """
        if not load_api_key():
            self._set_ai_mode("LOCAL")
            local = self._local_chat(prompt, _code_gen_mode=_code_gen_mode)
            if local:
                return local
            return ("I am running on my local brain only, sir, since no "
                    "API key is set. Say 'set api key' to enable my full "
                    "language model.")

        # Try local brain first for speed
        local = self._local_chat(prompt, _code_gen_mode=_code_gen_mode)
        if local:
            return local

        # Local brain couldn't handle it — use Groq
        reply = ask_ai(prompt, list(self.history))
        if reply is None:
            return local or None
        if reply == "__UNAUTHORIZED__":
            self._set_ai_mode("LOCAL")
            local = self._local_chat(prompt)
            if local:
                return ("My API key was rejected, sir, so I switched to my "
                        "local brain automatically. " + local)
            return ("My API key was rejected, sir. Please check it is correct. "
                    "Say 'set api key' to give me a fresh key.")
        if reply == "__RATE_LIMITED__":
            self._set_ai_mode("LOCAL")
            local = self._local_chat(prompt)
            msg = ("Your API key limit has been hit, sir. "
                   "I switched to my local brain automatically. "
                   "Say 'set api key' to paste a new Groq key to continue "
                   "with Groq, or I will keep running on local brain.")
            if local:
                return msg + " " + local
            return msg
        if reply and reply.startswith("I hit an error"):
            self._set_ai_mode("LOCAL")
            offline = self._local_chat(prompt)
            return offline if offline else reply
        self._set_ai_mode("ONLINE")
        return reply

    def _set_ai_mode(self, mode):
        if getattr(self, "ai_mode", None) == mode:
            return
        self.ai_mode = mode
        lbl = None
        try:
            lbl = self.val_labels.get("AI CORE")
        except Exception:
            lbl = None
        if lbl is not None:
            lbl.config(text=mode, fg=GREEN if mode == "ONLINE" else GOLD)
        try:
            self.micro_lbl.config(
                text="%s // %s" % (mode, "LINK STABLE" if mode == "ONLINE"
                                   else "OFFLINE BRAIN"))
        except Exception:
            pass
        try:
            if mode == "LOCAL":
                self.api_hint_lbl.config(text="Say 'set api key' to enable Groq")
            else:
                self.api_hint_lbl.config(text="")
        except Exception:
            pass

    def _is_api_key(self, cmd):
        return any(p in cmd for p in ["set api key", "set the api key",
                                       "change api key", "update api key",
                                       "new api key", "add api key",
                                       "enter api key", "paste api key",
                                       "configure api key", "setup api key"])

    def _is_clear_memory(self, cmd):
        return any(p in cmd for p in ["clear your memory", "clear memory",
                                      "forget everything", "forget the conversation",
                                      "wipe your memory", "reset your memory"])

    CALC_WORDS = {
        "plus": "+", "minus": "-", "times": "*", "multiplied by": "*",
        "divided by": "/", "over": "/", "to the power of": "**",
        "percent of": "*", "of": "*",
    }

    @staticmethod
    def _safe_arith_eval(expr):
        """Evaluate a pure arithmetic expression via the AST.

        Replaces eval(): only numbers and + - * / % ** and parentheses are
        accepted, so no names, attributes or calls can ever be reached.
        """
        import ast

        allowed_bin = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                       ast.Pow, ast.FloorDiv}

        def _ev(node):
            if isinstance(node, ast.Expression):
                return _ev(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value,
                                                             (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_bin:
                left = _ev(node.left)
                right = _ev(node.right)
                if left is None or right is None:
                    return None
                if isinstance(node.op, ast.Pow) and \
                        (abs(right) > 1000 or abs(left) > 1e12 or
                         (isinstance(right, float)) or
                         (abs(right) > 64)):
                    return None
                try:
                    return {ast.Add: lambda a, b: a + b,
                            ast.Sub: lambda a, b: a - b,
                            ast.Mult: lambda a, b: a * b,
                            ast.Div: lambda a, b: a / b,
                            ast.Mod: lambda a, b: a % b,
                            ast.Pow: lambda a, b: a ** b,
                            ast.FloorDiv: lambda a, b: a // b}[type(node.op)](left, right)
                except Exception:
                    return None
            if isinstance(node, ast.UnaryOp) and \
                    isinstance(node.op, (ast.UAdd, ast.USub)):
                v = _ev(node.operand)
                if v is None:
                    return None
                return -v if isinstance(node.op, ast.USub) else v
            return None

        try:
            tree = ast.parse(expr, mode="eval")
        except Exception:
            return None
        val = _ev(tree)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        return val

    def _calc_intent(self, cmd):
        m = re.search(r"\b(?:calculate|compute|work out|solve|how much is|"
                      r"what is|what's|whats)\s+(.+)$", cmd, re.IGNORECASE)
        if not m:
            return False
        expr = m.group(1).strip(" ?!.")
        if len(expr) > 200:
            return False
        expr = expr.replace("percent", "/100").replace("%", "/100")
        for w, op in self.CALC_WORDS.items():
            expr = re.sub(r"\b" + w + r"\b", op, expr, flags=re.IGNORECASE)
        expr = expr.replace(",", "")
        expr = re.sub(r"\bequals?\b", "", expr, flags=re.IGNORECASE)
        if not re.fullmatch(r"[0-9+\-*/()<>=.\s%]+", expr):
            return False
        for num in re.findall(r"\d+", expr):
            if len(num.lstrip("0") or "0") > 9:
                return False
        if "**" in expr:
            # Right-associative chains like 9**9**9 explode even with small
            # numbers, so allow at most one power op with bounded operands.
            if expr.count("**") > 1:
                return False
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", expr)]
            if len(nums) != 2 or any(abs(n) > 1000 for n in nums):
                return False
        try:
            val = self._safe_arith_eval(expr)
        except Exception:
            return False
        if val is None:
            return False
        original = m.group(1).strip().strip("?")
        self.say(f"{original} equals {val:g}.")
        return True

    def _weather_intent(self, cmd):
        if "open" in cmd or "go to" in cmd:
            return False
        return bool(re.search(r"\bweather\b|\bforecast\b|\btemperature\b|"
                              r"\b(?:is|it) raining\b|how hot|how cold", cmd))

    def _weather_location(self, cmd):
        m = re.search(r"\b(?:in|for)\s+(?:the\s+)?"
                      r"([A-Za-z][A-Za-z .'-]*?)[?.!]*$", cmd)
        if not m:
            return None
        loc = m.group(1).strip(" .")
        if "weather" in loc.lower() or "forecast" in loc.lower():
            return None
        return loc or None

    def _handle_weather(self, cmd):
        loc = self._weather_location(cmd)
        if not loc:
            self.say("For which city, sir?")
            loc = self.listen(timeout=4, phrase_limit=4)
            if loc:
                loc = loc.strip().title()
        if not loc:
            self.ui_q.put(("status", "THINKING"))
            reply = self._ask_ai_safely(
                f"What is the weather? Answer in one short sentence.")
            if reply and reply != "__UNAUTHORIZED__":
                self.say(reply)
            return
        self.ui_q.put(("status", "THINKING"))
        text = get_weather(loc)
        if not text:
            reply = self._ask_ai_safely(
                f"What is the weather in {loc}? Answer in one short sentence.")
            if reply and reply != "__UNAUTHORIZED__":
                self.say(reply)
            return
        self.say(text)

    def _future_time_intent(self, cmd):
        if not re.search(r"\bwhat time\b", cmd):
            return False
        return bool(re.search(r"\b(?:in|after)\s+\d+\s*(hours?|hrs?|h|"
                              r"minutes?|mins?|m|seconds?|secs?|s)\b", cmd))

    def _handle_future_time(self, cmd):
        total = 0
        parts = []
        for m in re.finditer(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|"
                             r"seconds?|secs?|s)\b", cmd):
            n = int(m.group(1))
            u = m.group(2)
            if u.startswith("h"):
                total += n * 3600
                parts.append(f"{n} hours")
            elif u.startswith("m"):
                total += n * 60
                parts.append(f"{n} minutes")
            else:
                total += n
                parts.append(f"{n} seconds")
        if not total:
            self.say("I did not catch the duration, sir.")
            return
        target = datetime.datetime.now() + datetime.timedelta(seconds=total)
        when = target.strftime("%I:%M %p").lstrip("0")
        self.say(f"In {' and '.join(parts)}, it will be {when}.")

    def _unit_lookup(self, token, table):
        tok = (token or "").strip().lower()
        if not tok:
            return None
        if tok in table:
            return tok
        tokens = set(re.findall(r"[a-z0-9]+", tok))
        cands = []
        for k in table:
            ktokens = re.findall(r"[a-z0-9]+", k)
            if not ktokens:
                continue
            if all(len(t) > 1 for t in ktokens):
                if all(t in tokens for t in ktokens) or k in tok:
                    cands.append(k)
            else:
                if any(t == k for t in tokens):
                    cands.append(k)
        if not cands:
            return None
        cands.sort(key=len, reverse=True)
        return cands[0]

    def _convert_intent(self, cmd):
        m = re.search(r"\bconvert\s+(-?\d+(?:\.\d+)?)\s+([a-z0-9/ ]+?)\s+"
                      r"(?:to|into|in)\s+([a-z0-9/ ]+?)\s*$", cmd)
        if m:
            val = float(m.group(1))
            fr, to = m.group(2), m.group(3)
        else:
            m = re.search(r"\bhow many\s+([a-z0-9/ ]+?)\s+(?:are )?in\s+"
                          r"(?:a|an|one)\s+([a-z0-9/ ]+?)\s*$", cmd)
            if m:
                to, fr = m.group(1), m.group(2)
                val = 1.0
            else:
                m = re.search(r"\bhow many\s+([a-z0-9/ ]+?)\s+(?:are )?in\s+"
                              r"(-?\d+(?:\.\d+)?)\s+([a-z0-9/ ]+?)\s*$", cmd)
                if m:
                    to, val, fr = m.group(1), float(m.group(2)), m.group(3)
                else:
                    m = re.search(r"\bwhat is\s+(-?\d+(?:\.\d+)?)\s+"
                                  r"([a-z0-9/ ]+?)\s+in\s+([a-z0-9/ ]+?)\s*$", cmd)
                    if not m:
                        return False
                    val, fr, to = float(m.group(1)), m.group(2), m.group(3)

        fr_key = self._unit_lookup(fr, TEMP_UNITS)
        to_key = self._unit_lookup(to, TEMP_UNITS)
        if fr_key and to_key:
            result = self._convert_temp(val, fr_key, to_key)
            self.say(f"{val:g} {fr} equals {result:g} {to}.")
            return True

        for table in (LENGTH_UNITS, MASS_UNITS, SPEED_UNITS, DATA_UNITS):
            fk = self._unit_lookup(fr, table)
            tk = self._unit_lookup(to, table)
            if fk and tk:
                result = val * table[fk] / table[tk]
                self.say(f"{val:g} {fr} equals {result:g} {to}.")
                return True
        return False

    def _convert_temp(self, val, fr_key, to_key):
        fr, to = TEMP_UNITS[fr_key], TEMP_UNITS[to_key]
        if fr == to:
            return val
        if fr == "C":
            c = val
        elif fr == "F":
            c = (val - 32) * 5 / 9
        else:
            c = val - 273.15
        if to == "C":
            return c
        if to == "F":
            return c * 9 / 5 + 32
        return c + 273.15

    def _timer_intent(self, cmd):
        if re.search(r"\b(cancel|stop|end|kill)\s+(the\s+)?(timer|countdown)s?\b", cmd):
            return True
        if re.search(r"\bhow (much time|long).*(timer|countdown)\b", cmd):
            return True
        return bool(re.search(r"\b(timer|countdown)\b", cmd) and
                    re.search(r"\b(set|start|make|for|in|of)\b", cmd))

    def _timer_duration(self, cmd):
        total = 0
        found = False
        for m in re.finditer(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|"
                             r"seconds?|secs?|s)\b", cmd):
            n = int(m.group(1))
            u = m.group(2)
            if u.startswith("h"):
                total += n * 3600
            elif u.startswith("m"):
                total += n * 60
            else:
                total += n
            found = True
        return total if found else None

    def _timer_fired(self, tid):
        self.timers.done(tid)
        self.say("Timer finished, sir.")

    def _handle_timer(self, cmd):
        if re.search(r"\b(cancel|stop|end|kill)\s+(the\s+)?(timer|countdown)s?\b", cmd):
            if self.timers.cancel():
                self.say("Timers cancelled, sir.")
            else:
                self.say("There are no active timers, sir.")
            return
        if re.search(r"\bhow (much time|long).*(timer|countdown)\b", cmd):
            remaining = self.timers.remaining()
            if not remaining:
                self.say("There are no active timers, sir.")
                return
            bits = []
            for _tid, left, label in remaining:
                secs = int(left)
                h, rem = divmod(secs, 3600)
                mns, scs = divmod(rem, 60)
                parts = []
                if h:
                    parts.append(f"{h} hour{'s' if h != 1 else ''}")
                if mns:
                    parts.append(f"{mns} minute{'s' if mns != 1 else ''}")
                if scs or not parts:
                    parts.append(f"{scs} second{'s' if scs != 1 else ''}")
                bits.append(" ".join(parts))
            self.say("Time remaining: " + ", ".join(bits) + ".")
            return
        secs = self._timer_duration(cmd)
        if not secs:
            self.say("For how long should I set the timer, sir?")
            return
        self.timers.add(secs, self._timer_fired)
        h, rem = divmod(secs, 3600)
        mns, scs = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if mns:
            parts.append(f"{mns} minute{'s' if mns != 1 else ''}")
        if scs or not parts:
            parts.append(f"{scs} second{'s' if scs != 1 else ''}")
        label = " ".join(parts)
        self.say(f"Timer set for {label}, sir. I will let you know when it is done.")

    def _battery_intent(self, cmd):
        return bool(re.search(r"\bbattery\b|\bhow much (power|charge)\b", cmd))

    def _battery_report(self):
        pct = None
        plugged = None
        if HAVE_PSUTIL:
            try:
                b = psutil.sensors_battery()
                if b is not None:
                    pct = int(b.percent)
                    plugged = b.power_plugged
            except Exception:
                pass
        if pct is None:
            try:
                r = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                   text=True, timeout=10)
                m = re.search(r"(\d+)%", r.stdout)
                if m:
                    pct = int(m.group(1))
                    plugged = "AC" in r.stdout or "charging" in r.stdout
            except Exception:
                pass
        if pct is None:
            self.say("I could not read the battery status, sir.")
            return
        if plugged is None:
            status = "charge state unknown"
        else:
            status = "on charger" if plugged else "on battery"
        self.say(f"Battery is at {pct} percent, {status}, sir.")

    def _handle_battery(self, cmd):
        self._battery_report()

    def _is_define(self, cmd):
        return bool(re.match(r"^(define|what does)\s+", cmd))

    def _handle_define(self, cmd):
        term = re.sub(r"^(define|what does)\s+", "", cmd).strip(" ?")
        if not term:
            self.say("What would you like me to define, sir?")
            return
        self.say(f"Looking up {term} on Wikipedia, sir.")
        webbrowser.open("https://en.wikipedia.org/wiki/Special:Search?search="
                        + term.replace(" ", "+"))

    def _is_todo(self, cmd):
        return bool(re.search(r"\btodo\b|\bto[- ]do\b|\btask\s+list\b|"
                              r"\b(?:add|list|show|clear|done|complete|"
                              r"finish|delete|remove)\b.*\btask\b",
                              cmd, re.I)) and \
            bool(re.search(r"\b(add|create|new|list|show|read|clear|wipe|"
                           r"done|complete|check|finish|delete|remove|drop)\b",
                           cmd, re.I))

    def _handle_todo(self, cmd):
        try:
            import jarvis.todo_list as todo
            parsed = todo.parse_intent(cmd)
        except Exception:
            self.say("I could not reach my task list, sir.")
            return
        if parsed is None:
            self.say("Tell me to add, list, complete, or remove a task, sir.")
            return
        verb, payload = parsed
        if verb == "add":
            count = todo.add_task(payload)
            self.say(f"Added task {count} to your to-do list: {payload}, sir.")
        elif verb == "list":
            tasks = todo.list_tasks()
            if not tasks:
                self.say("Your to-do list is empty, sir.")
                return
            lines = []
            for i, t in enumerate(tasks, 1):
                mark = "[x]" if t.get("done") else "[ ]"
                lines.append(f"{i}. {mark} {t.get('text', '')}")
            reply = "Your to-do list, sir: " + " | ".join(lines)
            self.say(reply)
            if hasattr(self, "show_list_panel"):
                try:
                    self.show_list_panel(lines, "To-Do List")
                except Exception:
                    pass
        elif verb == "clear":
            todo.clear_tasks()
            self.say("Cleared your to-do list, sir.")
        elif verb == "done":
            if todo.done_task(payload):
                self.say(f"Marked '{payload}' as done, sir.")
            else:
                self.say(f"I could not find '{payload}' on your to-do list, sir.")
        elif verb == "delete":
            removed = todo.delete_task(payload)
            if removed is not None:
                self.say(f"Removed '{removed.get('text', '')}' from your to-do list, sir.")
            else:
                self.say("I could not find that task to remove, sir.")

    def _is_repeat(self, cmd):
        return any(cmd == p or cmd.startswith(p + " ") or cmd.startswith(p + ",")
                   for p in ("repeat", "repeat that", "say that again",
                             "can you repeat", "say again", "what did you say"))

    def _osascript(self, script):
        if platform.system() != "Darwin":
            return False
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def _current_volume(self):
        try:
            r = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=15)
            return int(r.stdout.strip())
        except Exception:
            return None

    def _system_action(self, cmd):
        if platform.system() != "Darwin":
            return False

        if re.search(r"\b(lock|secure)\s+(the\s+)?(computer|screen|mac)\b", cmd) \
                or "lock my computer" in cmd:
            if self._osascript('tell application "System Events" to keystroke "q" '
                               'using {control down, command down}'):
                self.say("Computer locked, sir.")
            else:
                self.say("I could not lock the computer, sir.")
            return True

        if re.search(r"\btake\s+a?\s*screenshot\b", cmd) or \
                re.search(r"\b(screen\s+)?capture\b", cmd) or cmd.strip() == "screenshot":
            path = os.path.join(
                os.path.expanduser("~"), "Desktop",
                "Jarvis_Screenshot_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
            try:
                r = subprocess.run(["screencapture", "-x", path],
                                   capture_output=True, timeout=15)
                ok = r.returncode == 0 and os.path.exists(path)
            except Exception:
                ok = False
            if ok:
                self.say("Screenshot saved to your desktop, sir.")
            else:
                self.say("I could not take a screenshot, sir. I may need "
                         "screen recording permission.")
            return True

        if re.search(r"\b(sleep|nap)\s+(the\s+)?computer\b", cmd) or \
                "sleep my computer" in cmd:
            try:
                subprocess.run(["pmset", "sleepnow"], capture_output=True, timeout=10)
                self.say("Putting the computer to sleep, sir. Goodnight.")
            except Exception:
                self.say("I could not put the computer to sleep, sir.")
            return True

        if re.search(r"\b(shut down|turn off|power off|restart)\s+"
                     r"(the\s+)?computer\b", cmd) or "shut down my computer" in cmd:
            action = "restart" if "restart" in cmd else "shut down"
            self.say(f"Are you sure you want to {action} the computer, sir? "
                     "Say confirm to proceed.")
            confirm = self.listen(timeout=5, phrase_limit=3)
            if confirm and "confirm" in confirm:
                verb = "restart" if action == "restart" else "shut down"
                self._osascript('display dialog "JARVIS is %s the computer now."'
                                % ("restarting" if action == "restart" else "shutting down"))
                subprocess.run(["osascript", "-e",
                                'tell application "System Events" to %s' % verb],
                               capture_output=True, timeout=10)
                self.say(f"{action}ting now, sir. Goodnight.")
            else:
                self.say("Understood, sir. I will leave the computer running.")
            return True

        if re.search(r"\bremind(er)?\b", cmd):
            m = re.search(r"\b(?:remind me (?:to|about)|set (?:a|an) reminder "
                          r"(?:to|for)|set a reminder|remind me)\s+(.+)$", cmd)
            note = m.group(1).strip(" .") if m else None
            if note:
                note = note.strip()
                # Neutralise characters that could break out of the AppleScript
                # string literal (quotes are remapped, backslashes dropped).
                safe_note = note.replace("\\", "").replace('"', "'")
                ok = self._osascript('tell application "Reminders" to make new '
                                     'reminder with properties {name:"%s"}' %
                                     safe_note)
                if ok:
                    self.say(f"Reminder set, sir: {note}.")
                else:
                    self.say("I could not create that reminder, sir. "
                             "Please make sure Reminders is running.")
                return True
            self.say("What should I remind you about, sir?")
            return True

        if re.search(r"\b(volume|sound|mute|unmute|loud|louder|quiet|quieter)\b", cmd):
            if re.search(r"\b(mute|silent|mute the volume|sound off)\b", cmd):
                self._osascript("set volume output volume 0")
                self.say("Muted, sir.")
                return True
            if re.search(r"\b(unmute|restore|sound on|turn on sound)\b", cmd):
                self._osascript("set volume output volume 60")
                self.say("Volume restored, sir.")
                return True
            if re.search(r"\b(increase|raise|up|louder|max)\b", cmd):
                cur = self._current_volume()
                nv = min(100, (cur + 10) if cur is not None else 70)
                self._osascript(f"set volume output volume {nv}")
                self.say(f"Volume set to {nv} percent, sir.")
                return True
            if re.search(r"\b(decrease|lower|down|quieter|min)\b", cmd):
                cur = self._current_volume()
                nv = max(0, (cur - 10) if cur is not None else 30)
                self._osascript(f"set volume output volume {nv}")
                self.say(f"Volume set to {nv} percent, sir.")
                return True
            self.say("I can adjust the volume if you say make it louder or quieter, sir.")
            return True

        return False

    def set_api_key(self):
        self.say("Please provide your Groq API key, sir.")
        self.ui_q.put(("api_key_prompt", None))

    def _show_api_key_dialog(self):
        try:
            from tkinter import simpledialog
            key = simpledialog.askstring(
                "J.A.R.V.I.S. - API Key",
                "Paste your Groq API key, sir.\n"
                "(console.groq.com -> API Keys)\n"
                "Leave empty to keep running on the local brain:",
                parent=self.root, show="")
        except Exception:
            key = None
        key = (key or "").strip()
        if not key:
            self.ui_q.put(("say", "No API key received, sir. I will keep "
                                  "running on my local brain."))
            return
        if save_api_key(key):
            self._set_ai_mode("ONLINE")
            self.ui_q.put(("say", "API key saved, sir. My systems are ready."))
        else:
            self.ui_q.put(("say", "I could not save that API key, sir."))

    def _is_build_website(self, cmd):
        return any(p in cmd for p in [
            "build me a website", "build a website", "make me a website",
            "make a website", "create me a website", "create a website",
            "build website", "make website", "create website",
            "website about", "website for",
            "build me an app", "build an app", "make me an app",
            "make an app", "create me an app", "create an app",
            "build app", "make app", "create app",
            "build me an application", "build an application",
            "make me an application", "make an application",
            "create me an application", "create an application",
            "build application", "make application", "create application",
            "app about", "app for", "application about", "application for",
            "build me android", "build android", "make me android",
            "make android", "create android", "build android app",
            "make android app", "create android app",
            "mobile app", "mobile application",
            "android app", "android application",
            "build me a mobile", "build a mobile", "make me a mobile",
            "make a mobile", "create a mobile",
        ])

    def _is_app_request(self, cmd):
        """Check if the user wants an app (not a website)."""
        return any(p in cmd for p in [
            "app", "application", "android", "mobile",
        ]) and not any(p in cmd for p in [
            "website", "web", "site", "html", "webpage",
        ])

    def _website_topic(self, cmd):
        for p in ["build me a website", "make me a website", "create me a website",
                  "build a website", "make a website", "create a website",
                  "build me an app", "make me an app", "create me an app",
                  "build an app", "make an app", "create an app",
                  "build me an application", "make me an application",
                  "create me an application", "build an application",
                  "make an application", "create an application",
                  "build me android", "build android", "make me android",
                  "make android", "create android", "build android app",
                  "make android app", "create android app",
                  "build me a mobile", "build a mobile", "make me a mobile",
                  "make a mobile", "create a mobile",
                  "build me a", "make me a", "create me a",
                  "build a", "make a", "create a",
                  "build", "make", "create",
                  "website", "app", "application", "android"]:
            if p in cmd:
                cmd = cmd.replace(p, " ")
                break
        topic = " ".join(cmd.split()).strip(" .,")
        for w in ("about", "for", "on"):
            if topic == w or topic.startswith(w + " "):
                topic = topic[len(w):].strip()
        low = topic.lower()
        for art in ("a ", "an ", "the ", "n "):
            if low.startswith(art):
                topic = topic[len(art):].strip()
                low = topic.lower()
                break
        return topic or "yourself"

    def build_website(self, topic, kind=None):
        self.ui_q.put(("status", "THINKING"))
        is_app = (kind == "app") if kind else self._is_app_request(topic)
        if is_app:
            self.say("Preparing an Android app prompt for Google AI Studio, sir.")
            prompt = self._app_prompt(topic)
        else:
            self.say("Preparing a prompt for Google AI Studio, sir.")
            prompt = self._website_prompt(topic)
        if not prompt:
            return
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except Exception:
            pass
        if is_app:
            self.say("Taking you to Google AI Studio to build this Android app, sir.")
        else:
            self.say("Taking you to Google AI Studio to build this, sir.")
        opened = open_aistudio_build(prompt, is_app)
        if not opened:
            self.say("I couldn't open the browser, sir. Your prompt is on the clipboard — "
                     "open aistudio.google.com, press New App, and paste it in.")
            return
        _short_wait(5)
        if is_app:
            if self._aistudio_automate_app(prompt):
                self.say("I've opened the Android app builder with your prompt, sir. "
                         "The preview is generating on the right now.")
            else:
                self.say("I've opened the Android app builder with your prompt pre-filled, sir. "
                         "Press Run prompt and the preview will appear.")
        else:
            if self._aistudio_automate(prompt, "web"):
                self.say("I've opened the app builder with your prompt, sir. "
                         "The preview is generating on the right now.")
            else:
                self.say("I've opened the app builder with your prompt pre-filled, sir. "
                         "Press Run prompt and the preview will appear.")

    def _ask_build_kind(self):
        """Ask user whether they want a website or full application.

        Non-blocking: defaults to 'web' if no voice input within 2 seconds.
        """
        try:
            answer = self.listen(timeout=2, phrase_limit=4)
        except Exception:
            answer = ""
        answer = (answer or "").lower()
        if any(w in answer for w in ("full", "application", "app")):
            if not any(w in answer for w in ("website", "web", "site")):
                return "app"
        return "web"

    def _default_website_prompt(self, topic):
        return (
            "Create a complete single-file HTML website about %s. Include embedded "
            "CSS and JavaScript, a modern responsive layout, tasteful colors, a "
            "navigation bar, a hero section, several content sections, and a "
            "contact/footer area. Make it professional, polished, and ready to use."
            % topic
        )

    def _website_prompt(self, topic):
        ask = (
            "Write a single detailed prompt to paste into Google AI Studio so Gemini "
            f"creates a polished website about {topic}. The prompt must request a "
            "complete single-file HTML page with embedded CSS and JavaScript, a modern "
            "responsive layout, tasteful colors, and a professional look. Output ONLY "
            "the prompt text itself, no quotes, no code fences, no explanation."
        )
        raw = self._ask_ai_safely(ask)
        if raw == "__UNAUTHORIZED__":
            self.say("That key was rejected too, sir. Please double check it on groq dot com.")
            return self._default_website_prompt(topic)
        if raw is None:
            return self._default_website_prompt(topic)
        if raw.startswith("I hit an error"):
            return self._default_website_prompt(topic)
        raw = raw.strip().strip('"').strip("'")
        if len(raw) < 40 or not any(w in raw.lower() for w in
                                   ("website", "html", "page", "site")):
            return self._default_website_prompt(topic)
        return raw

    def _default_app_prompt(self, topic):
        return (
            "Create a complete, functional Android mobile application about %s. "
            "Include a modern Material Design UI with navigation, multiple screens, "
            "buttons, text fields, images, and proper layout. The app should be "
            "fully working with Kotlin or Java. Include all necessary activities, "
            "layouts, and resources. Make it professional and ready to run."
            % topic
        )

    def _app_prompt(self, topic):
        ask = (
            "Write a single detailed prompt to paste into Google AI Studio so Gemini "
            f"creates a polished Android mobile application about {topic}. The prompt "
            "must request a complete working Android app with Material Design, "
            "multiple screens, navigation, and all necessary code. Output ONLY "
            "the prompt text itself, no quotes, no code fences, no explanation."
        )
        raw = self._ask_ai_safely(ask)
        if raw == "__UNAUTHORIZED__":
            self.say("That key was rejected too, sir. Please double check it on groq dot com.")
            return self._default_app_prompt(topic)
        if raw is None:
            return self._default_app_prompt(topic)
        if raw.startswith("I hit an error"):
            return self._default_app_prompt(topic)
        raw = raw.strip().strip('"').strip("'")
        if len(raw) < 40:
            return self._default_app_prompt(topic)
        return raw

    def _activate_default_browser(self):
        try:
            for name in ("Google Chrome", "Safari", "Microsoft Edge",
                         "Firefox", "Brave Browser", "Arc"):
                check = subprocess.run(
                    ["osascript", "-e", f'application "{name}" is running'],
                    capture_output=True, text=True)
                if check.stdout.strip() == "true":
                    subprocess.run(
                        ["osascript", "-e", f'tell application "{name}" to activate'],
                        capture_output=True)
                    return
        except Exception:
            pass

    def _aistudio_js_exec(self, js):
        for app, tmpl in (
            ("Google Chrome",
             'tell application "Google Chrome" to execute '
             "front window's active tab javascript \"{js}\""),
            ("Safari",
             'tell application "Safari" to do JavaScript '
             "\"{js}\" in current tab of front window")):
            try:
                chk = subprocess.run(["osascript", "-e",
                                      f'application "{app}" is running'],
                                     capture_output=True, text=True)
                if chk.stdout.strip() != "true":
                    continue
                res = subprocess.run(["osascript", "-e", tmpl.format(js=js)],
                                     capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                continue
        return None

    def _aistudio_js_start(self):
        js = ("const STEP='START';(()=>{const labels=['start building',"
              "'start building with gemini api','start','build','get started','create'];"
              "const els=document.querySelectorAll('button,a,[role=button],[role=link]');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.textContent||'')"
              ".trim().toLowerCase();if(labels.indexOf(t)>=0&&el.offsetParent!==null)"
              "{el.click();return 'clicked';}}return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_js_type(self, kind):
        if kind == "app":
            labels = ("'full-stack app','full stack app','fullstack app',"
                      "'build a full-stack app','real app','build an app',"
                      "'full-stack','full stack','app'")
        else:
            labels = ("'web app','website','build a website','build a web app',"
                      "'create a website','web app preview','web'")
        js = ("const STEP='TYPE';(()=>{const labels=[" + labels + "];"
              "const els=document.querySelectorAll('button,a,[role=button],[role=radio],"
              "[role=tab],[role=menuitem],label');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.textContent||'')"
              ".trim().toLowerCase();if(labels.indexOf(t)>=0&&el.offsetParent!==null)"
              "{el.click();return 'clicked';}}"
              "const all=document.querySelectorAll('div,span,button,a,[role=button]');"
              "for(const el of all){const t=(el.textContent||'').trim().toLowerCase();"
              "if(el.textContent.length<60&&el.offsetParent!==null"
              "&&labels.some(l=>t===l||t.indexOf(l+' ')==0)){el.click();return 'clicked-fuzzy';}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_js_insert(self, prompt):
        b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        js = ("const STEP='INSERT';(()=>{const b64='" + b64 + "';"
              "const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));"
              "const p=new TextDecoder().decode(bytes);"
              "let el=document.querySelector('textarea,[contenteditable=true],"
              "[role=textbox],.ql-editor,[data-placeholder]');"
              "if(!el){const all=document.querySelectorAll('*');"
              "for(const e of all){if(e.contentEditable==='true'"
              "&&e.offsetParent!==null){el=e;break;}}}"
              "if(!el)return 'no-editor';"
              "el.focus();"
              "if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){"
              "const nativeSet=Object.getOwnPropertyDescriptor("
              "window.HTMLTextAreaElement.prototype,'value').set;"
              "nativeSet.call(el,p);"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "return 'set-value';}"
              "const range=document.createRange();"
              "range.selectNodeContents(el);"
              "const s=window.getSelection();s.removeAllRanges();"
              "s.addRange(range);"
              "const ok1=document.execCommand('insertText',false,p);"
              "if(ok1){el.dispatchEvent(new Event('input',{bubbles:true}));"
              "return 'inserted';}"
              "el.textContent=p;"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "return 'set-text';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and res != "no-editor")

    def _aistudio_js_run(self):
        js = ("const STEP='RUN';(()=>{const labels=['run','send','submit','generate',"
              "'start','build','create'];"
              "const els=document.querySelectorAll('button,[role=button]');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.title||"
              "el.textContent||'').trim().toLowerCase();"
              "if(labels.indexOf(t)>=0&&el.offsetParent!==null){el.click();return 'clicked';}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_automate(self, prompt, kind):
        self._activate_default_browser()
        _short_wait(5)
        for attempt in range(3):
            if self._aistudio_js_type(kind):
                break
            time.sleep(1.5)
        time.sleep(2)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)
        return False

    def _aistudio_js_click_android_build(self):
        """Click 'Build an Android App' or similar button in Google AI Studio."""
        js = ("const STEP='ANDROID';(()=>{const labels=["
              "'build an android app','build android app','android app',"
              "'build an app','build app','create an app',"
              "'build a full-stack app','full-stack app','fullstack app',"
              "'build a full-stack','full stack app','full stack',"
              "'build an application','build application',"
              "'mobile app','android','app'];"
              "const els=document.querySelectorAll('button,a,[role=button],"
              "[role=radio],[role=tab],[role=menuitem],label,div,span');"
              "for(const el of els){const t=(el.getAttribute('aria-label')"
              "||el.textContent||'').trim().toLowerCase();"
              "if(el.offsetParent!==null&&labels.some(l=>t===l||t.indexOf(l+' ')==0))"
              "{el.click();return 'clicked-'+t;}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_automate_app(self, prompt):
        """Automate Google AI Studio for Android app building."""
        self._activate_default_browser()
        _short_wait(5)
        for attempt in range(3):
            if self._aistudio_js_click_android_build():
                break
            time.sleep(1.5)
        time.sleep(2)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)
        return False

    def _paste_and_run_in_aistudio(self, prompt):
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except Exception:
            try:
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(prompt.encode("utf-8"))
            except Exception:
                return False
        self._activate_default_browser()
        time.sleep(3)
        try:
            import pyautogui
            w, h = pyautogui.size()
            pyautogui.click(w // 2, h // 2)
            time.sleep(0.8)
            pyautogui.hotkey("command", "a")
            time.sleep(0.3)
            pyautogui.hotkey("command", "v")
            time.sleep(1.0)
            pyautogui.hotkey("command", "enter")
            time.sleep(1.5)
            return True
        except Exception:
            return False

    def _click_at(self, x, y, clicks=1):
        """Click at arbitrary screen coordinates using pyautogui."""
        try:
            import pyautogui
            pyautogui.click(x, y, clicks=clicks)
            return True
        except Exception:
            return False

    def _click_element_by_text(self, text):
        """Use screen vision to find a UI element by its text label and click it.

        Returns (True, description) on success, (False, reason) on failure.
        """
        img, b64 = self._take_screenshot()
        if not b64:
            return False, "Could not capture screen."
        question = (f"Find the UI element with the text '{text}' on this screen. "
                    f"Return ONLY the approximate pixel coordinates (x, y) of its "
                    f"center, like: 450, 320")
        answer = self._ask_vision(b64, question)
        coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
        if not coords:
            return False, f"Could not locate '{text}' on screen."
        x, y = int(coords[0][0]), int(coords[0][1])
        self._click_at(x, y)
        return True, f"Clicked '{text}' at ({x}, {y})."

    def _smart_click_in_aistudio(self, prompt):
        """Smart automation: find the input field, click it, paste prompt, submit.

        Uses a combination of JS injection (when Chrome/Safari is available)
        and pyautogui fallback with vision-guided clicking.
        """
        self._activate_default_browser()
        time.sleep(3)

        # Phase 1: Try JS injection (fastest, most reliable)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)

        # Phase 2: Try finding and clicking the textarea/input via vision
        try:
            import pyautogui
            img, b64 = self._take_screenshot()
            if b64:
                question = ("Find the main text input area, chat box, or prompt field "
                            "on this screen. Return ONLY the approximate pixel "
                            "coordinates (x, y) of its center, like: 640, 400")
                answer = self._ask_vision(b64, question)
                coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
                if coords:
                    x, y = int(coords[0][0]), int(coords[0][1])
                    pyautogui.click(x, y)
                    time.sleep(0.5)
                    pyautogui.hotkey("command", "a")
                    time.sleep(0.2)
                    pyautogui.hotkey("command", "v")
                    time.sleep(1.0)
                    # Try to find and click the submit/run button
                    img2, b64_2 = self._take_screenshot()
                    if b64_2:
                        q2 = ("Find the 'Run', 'Send', 'Submit', or 'Generate' button "
                              "on this screen. Return ONLY the approximate pixel "
                              "coordinates (x, y) of its center.")
                        a2 = self._ask_vision(b64_2, q2)
                        c2 = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", a2)
                        if c2:
                            bx, by = int(c2[0][0]), int(c2[0][1])
                            pyautogui.click(bx, by)
                            time.sleep(1.5)
                            return True
                    # Fallback: press Enter to submit
                    pyautogui.hotkey("command", "enter")
                    time.sleep(1.5)
                    return True
        except Exception:
            pass

        # Phase 3: Last resort - center screen click + paste + enter
        return self._paste_and_run_in_aistudio(prompt)

    def _is_wake_command(self, t):
        if re.search(r"\b(wake up|wakeup)\b", t):
            return True
        # A bare address ("jarvis", "hey jarvis") also wakes JARVIS, but a
        # sentence that merely mentions the name does not.
        if not re.search(r"\bjarvis\b", t, re.I):
            return False
        stripped = re.sub(r"\b(hey|hi|hello|ok|okay|jarvis|are you there|"
                          r"you there|there)\b", " ", t, flags=re.I)
        return not stripped.strip(" .,!?'\"")

    def _is_sleep_command(self, t):
        if re.search(r"^(?:go\s+to\s+)?sleep(?:\s+mode)?$", t.strip()):
            return True
        return any(w in t for w in ["go to sleep", "sleep mode", "standby",
                                    "power down", "goodnight"])

    def _is_exit(self, t):
        if re.search(r"\b(shut down|shutdown|turn off|power off)\s+(the\s+)?(computer|mac|pc)\b", t):
            return False
        return any(w in t for w in ["exit", "quit", "shut down", "shutdown", "goodbye"])

    def _boot(self):
        brain = self._get_brain()
        lines = [
            "BIOS v2.1 ............ OK",
            "VOICE ENGINE ......... LOADED",
            "SPEECH RECOGNITION ... ONLINE",
            "BRAIN MODULE ......... %d SKILLS" % brain.skill_count,
            "EXTRA BRAIN .......... %s" % ("LOADED" if brain._extra_registered
                                           else "NOT AVAILABLE"),
            "GROQ LLM CORE ......... %s" % ("CONNECTED" if load_api_key()
                                            else "LOCAL BRAIN"),
            "TEXT COMMAND LINK ..... ONLINE",
            "HUD INTERFACE ........ READY",
        ]
        for i, line in enumerate(lines):
            if not self.running.is_set():
                return
            self.ui_q.put(("boot_line", line))
            self.ui_q.put(("boot_progress", (i + 1) / len(lines)))
            time.sleep(0.6)
        if not self.running.is_set():
            return
        self.ui_q.put(("boot_done", None))
        self.say("All systems operational. Say wake up jarvis to begin, sir.")

    def _sleep_loop(self):
        self.ui_q.put(("status", "SLEEP"))
        while self.running.is_set() and not self.awake:
            text = self.listen(timeout=5, phrase_limit=6)
            if not text:
                # listen() returns instantly when no mic exists; without a
                # pause this loop busy-spins one core at 100%.
                time.sleep(0.2)
                continue
            print("YOU (wake):", text)
            self.ui_q.put(("you", text))
            # In sleep mode any utterance addressing JARVIS by name wakes him.
            if not (self._is_wake_command(text) or "jarvis" in text):
                continue
            self.awake = True
            self.ui_q.put(("awake", None))
            rest = re.sub(r"\bwake up\b|\bwakeup\b|\bjarvis\b", " ", text)
            rest = re.sub(r"\s+", " ", rest).strip(" .,")
            if rest:
                self.say("Yes sir, at your service.")
                time.sleep(0.4)
                self.process(rest)
            else:
                self.say("Yes sir, I am awake. Now proceed.")
                time.sleep(0.6)
            return

    def _awake_loop(self):
        self.ui_q.put(("status", "STANDBY"))
        while self.running.is_set() and self.awake:
            self.ui_q.put(("status", "LISTENING"))
            text = self.listen(timeout=6, phrase_limit=10)
            if not text:
                self.ui_q.put(("status", "STANDBY"))
                time.sleep(0.2)  # avoid busy-spin when mic fails instantly
                continue
            print("YOU:", text)
            self.ui_q.put(("you", text))
            text = text.replace("jarvis", " ").strip()
            if not text:
                continue
            if self._is_exit(text):
                self.say("Shutting down. It has been a pleasure, sir.")
                self.ui_q.put(("shutdown", None))
                self.running.clear()
                return
            if self._is_sleep_command(text):
                self.awake = False
                self.ui_q.put(("sleep", None))
                self.say("Entering standby, sir. Say wake up jarvis when you need me.")
                time.sleep(0.6)
                return
            try:
                self.process(text)
            except Exception as e:
                print("ERROR:", e)
                self.ui_q.put(("status", "STANDBY"))
            time.sleep(0.4)

    def _jarvis_loop(self):
        try:
            self._boot()
        except Exception as e:
            print("BOOT ERROR:", e)
        if not self.running.is_set():
            return
        self.awake = False
        self.ui_q.put(("sleep", None))
        while self.running.is_set():
            self._sleep_loop()
            if not self.running.is_set():
                break
            self._awake_loop()

    def quit_app(self):
        self.running.clear()
        self.speech_done.set()
        self.speaking.clear()
        self.continuous_listen = False
        self._ptt_stop.set()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        threading.Thread(target=self._jarvis_loop, daemon=True).start()
        self.root.mainloop()


# ============================================================================
# JARVIS BOT MODE — Clicky-style floating screen-aware assistant
# Small circle orb, voice-first, with popup menus
# ============================================================================

class JarvisBot:
    """Small floating circle orb that stays on top.
    Left-click: voice input.  Right-click: action menu.
    The orb glows when listening, pulses when thinking, and speaks replies."""

    ORB_SIZE = 56  # diameter of the circle
    STATE_FILE = ".jarvis_bot_state.json"
    CLICK_DELAY_MS = 250      # wait before treating a click as a single click
    HOLD_THRESHOLD_MS = 500   # presses longer than this are holds, not clicks
    DRAG_THRESHOLD_PX = 4     # movement beyond this counts as a drag
    MAX_VOICE_FAILS = 3       # consecutive failures before showing troubleshooting

    def __init__(self):
        self.running = threading.Event()
        self.running.set()
        self._brain = None
        self.history = deque(maxlen=30)
        # Clicky-style per-app memory: separate conversation history keyed by
        # the active application so context never bleeds between apps.
        self._app_history = {}          # app name -> deque(maxlen=20)
        self._app_history_mem_limit = 20
        self._active_app = ""
        self.last_reply = ""
        self.listening = False
        self.thinking = False
        self._voice_thread = None
        self.awake = True
        # Always-on wake word ("Hey Jarvis") — Clicky-style hands-free entry.
        self.wake_word_enabled = False
        self._wake_thread = None
        self._main_thread = threading.current_thread()

        # --- voice command history (last 10 commands) ---
        self.voice_history = deque(maxlen=10)
        self._voice_fail_streak = 0

        # --- timer bookkeeping ---
        self._active_timers = []

        # --- click detection (timer-based, no spurious double-clicks) ---
        self._pending_single_click = None  # after id for delayed single-click action
        self._double_clicked = False
        self._press_time = 0.0
        self._is_dragging = False

        # --- root window (tiny, borderless, transparent) ---
        self.root = tk.Tk()
        self.root.title("JARVIS")
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{self.ORB_SIZE}x{self.ORB_SIZE}+{sw - 90}+{sh // 2 - self.ORB_SIZE // 2}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.configure(bg="black")
        if platform.system() == "Windows":
            self.root.wm_attributes("-transparentcolor", "black")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # --- orb canvas ---
        self.canvas = tk.Canvas(self.root, width=self.ORB_SIZE, height=self.ORB_SIZE,
                                bg="black", highlightthickness=0)
        self.canvas.pack()
        self._orb_id = self.canvas.create_oval(
            4, 4, self.ORB_SIZE - 4, self.ORB_SIZE - 4,
            fill="#0d1117", outline="#00d4ff", width=2)
        self._glow_id = self.canvas.create_oval(
            8, 8, self.ORB_SIZE - 8, self.ORB_SIZE - 8,
            outline="#00d4ff", width=1)
        self.canvas.create_text(self.ORB_SIZE // 2, self.ORB_SIZE // 2,
                                text="J", fill="#00d4ff",
                                font=("Helvetica Neue", 14, "bold"),
                                tags="label")

        # --- drag support + timer-based click detection ---
        self._drag_x = 0
        self._drag_y = 0
        self.canvas.bind("<Button-1>", self._on_left_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<Button-3>", self._on_right_click)

        # --- right-click popup menu ---
        self.menu = tk.Menu(self.root, tearoff=0, bg="#161b22", fg="#c9d1d9",
                            activebackground="#1f6feb", activeforeground="white",
                            font=("Helvetica Neue", 11))
        menu_items = [
            ("🎤  Voice Command", self._voice_input),
            ("📸  Read My Screen", self._ask_about_screen),
            ("📖  Read Screen Aloud", self._read_screen_aloud),
            None,
            ("📄  New File…", self._menu_new_file),
            ("📖  Read File…", self._menu_read_file),
            ("🗑  Delete File…", self._menu_delete_file),
            ("🔁  Rename File…", self._menu_rename_file),
            ("▶️  Run Python…", self._menu_run_python),
            ("⌨️  Shell Command…", self._menu_run_shell),
            None,
            ("📅  My Calendar", self._menu_calendar),
            ("➕  Add Event…", self._menu_add_event),
            ("⏰  Set Reminder…", self._menu_reminder),
            ("✉️  Draft Email…", self._menu_email),
            None,
            ("🌍  Translate…", self._menu_translate),
            ("📐  Unit Converter…", self._menu_convert),
            ("🎨  Color Tool…", self._menu_color),
            ("🔳  Generate QR…", self._menu_qr),
            None,
            ("🖱  Point to Element", self._point_mode),
            ("🎯  Follow Cursor", self._toggle_follow_cursor),
            ("✍  Write Code", self._write_mode),
            ("📝  Research & Write", self._research_mode),
            ("🌐  Build Website/App", self._build_mode),
            ("📁  List Files", self._list_files),
            ("🕘  History", self._show_voice_history),
            ("⚙  Settings", self._show_settings),
            ("❌  Quit", self._on_close),
        ]
        for item in menu_items:
            if item is None:
                self.menu.add_separator()
            else:
                self.menu.add_command(label=item[0], command=item[1])

        # --- status bar (appears below orb on hover) ---
        self._status_win = None
        self._status_label = None

        # --- overlay windows for pointer ---
        self._overlay = None

        # --- screenshot cache ---
        self._last_screenshot = None

        # --- TTS engine ---
        self._tts_engine = None
        self._tts_lock = threading.Lock()
        self._init_tts()
        # Clicky enhancement pack (quick bar / reply bubble / status
        # panel). Fail-soft: a broken add-on can never kill the orb.
        try:
            import bot_clicky
            bot_clicky.attach(self)
        except Exception:
            pass

        # --- thinking animation ---
        self._pulse_id = None
        self._pulse_phase = 0

        # --- hold-to-talk pulse ---
        self._hold_pulse_id = None
        self._hold_phase = 0

        # --- restore saved position ---
        self._load_state()

        # --- clickable add-ons (quick bar / reply bubble / status panel) ---
        try:
            import bot_clicky
            self._clicky = bot_clicky.attach(self)
        except Exception as _clicky_exc:  # add-ons must never break the orb
            print("WARNING: bot_clicky failed to load:", _clicky_exc)
            self._clicky = None

    # ================================================================
    # Main-thread marshalling (tkinter is not thread-safe)
    # ================================================================
    def _ui(self, fn):
        """Run fn on the tkinter main thread."""
        if threading.current_thread() is self._main_thread:
            fn()
            return
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    # ================================================================
    # TTS
    # ================================================================
    def _init_tts(self):
        try:
            import pyttsx3
            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty("rate", 180)
            voices = self._tts_engine.getProperty("voices")
            for v in voices:
                if "daniel" in v.name.lower() or "male" in v.name.lower():
                    self._tts_engine.setProperty("voice", v.id)
                    break
        except Exception:
            self._tts_engine = None

    def _speak(self, text):
        """Speak text aloud; streams sentence-chunks when the engine
        exposes an iterate() driver (true streaming + barge-in), else
        falls back to the classic say/runAndWait path. If no engine is
        available at all, shells out to macOS ``say`` so the orb is
        NEVER silent."""
        if not text:
            return
        if not self._tts_engine:
            if platform.system() == "Darwin":
                threading.Thread(target=self._bot_say_fallback,
                                 args=(text,), daemon=True).start()
            return

        def _do():
            try:
                with self._tts_lock:
                    streamable = hasattr(self._tts_engine, "iterate")
                    if not streamable and \
                            hasattr(self._tts_engine, "runAndWait"):
                        self._tts_engine.say(text)
                        self._tts_engine.runAndWait()
                        return
                    speaker = getattr(self, "_stream_speaker", None)
                    if speaker is None:
                        try:
                            from streaming_tts import StreamingSpeaker
                            speaker = StreamingSpeaker(
                                driver=self._tts_engine)
                            self._stream_speaker = speaker
                        except Exception:
                            speaker = None
                    if speaker is not None and \
                            hasattr(speaker, "speak"):
                        import threading as _th
                        stop = _th.Event()
                        self._tts_stop = stop
                        speaker.speak(text, stop)
                        return
                # Last-resort legacy block.
                with self._tts_lock:
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
            except Exception:
                # Engine blew up mid-utterance: never go silent.
                try:
                    self._bot_say_fallback(text)
                except Exception:
                    pass
        threading.Thread(target=_do, daemon=True).start()

    def _bot_say_fallback(self, text):
        """macOS ``say`` CLI fallback for the orb."""
        try:
            subprocess.Popen(["/usr/bin/say", str(text)[:600]],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def interrupt_speech(self):
        """Barge-in: stop the current utterance immediately."""
        stop = getattr(self, "_tts_stop", None)
        if stop:
            stop.set()
        speaker = getattr(self, "_stream_speaker", None)
        if speaker:
            try:
                speaker.interrupt()
            except Exception:
                pass

    # ================================================================
    # Per-app memory (Clicky-style)
    # ================================================================
    def _frontmost_app_name(self):
        """Name of the app that has focus, for per-app context."""
        if self._active_app:
            return self._active_app
        app, _w = frontmost_app_and_window()
        return app or "desktop"

    def _app_memory(self):
        """The per-app history deque for the currently focused app."""
        app = self._frontmost_app_name()
        mem = self._app_history.setdefault(
            app, deque(maxlen=self._app_history_mem_limit))
        mem_name = getattr(self, "_app_memory_name", None)
        if mem_name != app:
            self._app_memory_name = app
        return mem

    def _bot_context_history(self):
        return list(self._app_memory())

    # ================================================================
    # Brain
    # ================================================================
    def _get_brain(self):
        if self._brain is None:
            self._brain = Brain(self)
        try:
            self._brain.load_extra()
        except Exception:
            pass
        return self._brain

    def _ask_ai(self, prompt):
        # One local attempt up front; a second identical call below just
        # duplicated work (and still reached the network with no API key).
        local = self._local_chat(prompt)
        if local and not self._is_placeholder_reply(local):
            return local
        if not load_api_key():
            return None
        try:
            reply = ask_ai(prompt, list(self.history))
        except Exception as e:
            print("AI REQUEST ERROR:", e)
            return ("I could not reach my language model, sir. Please check "
                    "your connection and try again.")
        if reply == "__UNAUTHORIZED__":
            return ("My API key was rejected, sir. Say 'set api key' to give "
                    "me a fresh Groq key, or I will keep running on my local brain.")
        if reply == "__RATE_LIMITED__":
            return ("Your API key limit has been hit, sir. Say 'set api key' to "
                    "paste a new Groq key, or I will keep running on my local brain.")
        if reply and not reply.startswith("__"):
            self.history.append({"role": "user", "content": prompt})
            self.history.append({"role": "assistant", "content": reply})
            return reply
        return None

    def say(self, text):
        """Speak and show a temporary tooltip."""
        self.last_reply = text
        self._speak(text)
        self._show_toast(text)

    def _say_cited(self, answer, sources):
        """Speak an answer and show its sources on screen (reply bubble +
        toast) without reading the sources aloud."""
        display = make_cited_display(answer, sources)
        self.last_reply = display
        self._speak(answer)
        self._show_toast(display, duration=6000)

    def ui_q_put(self, item):
        pass

    # ================================================================
    # Orb animations
    # ================================================================
    def _pulse(self, color="#00d4ff", speed=120):
        """Animate a pulsing glow on the orb."""
        if self._pulse_id:
            self.root.after_cancel(self._pulse_id)
            self._pulse_id = None
        self._pulse_phase = 0

        def _step():
            if not self.running.is_set():
                return
            self._pulse_phase += 1
            p = self._pulse_phase % 20
            alpha = 0.4 + 0.6 * abs(p - 10) / 10.0
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            r2 = min(255, int(r * alpha))
            g2 = min(255, int(g * alpha))
            b2 = min(255, int(b * alpha))
            clr = "#%02x%02x%02x" % (r2, g2, b2)
            self.canvas.itemconfig(self._glow_id, outline=clr)
            self._pulse_id = self.root.after(speed, _step)
        _step()

    def _stop_pulse(self, color="#00d4ff"):
        if self._pulse_id:
            self.root.after_cancel(self._pulse_id)
            self._pulse_id = None
        self.canvas.itemconfig(self._glow_id, outline=color)

    def _set_state(self, state):
        """Update orb visual state: idle, listening, thinking, speaking."""
        self._ui(lambda: self._set_state_ui(state))

    def _set_state_ui(self, state):
        if state == "listening":
            self.canvas.itemconfig(self._orb_id, fill="#0a1628", outline="#00ff88")
            self.canvas.itemconfig(self._glow_id, outline="#00ff88")
            self._pulse("#00ff88", speed=100)
        elif state == "thinking":
            self.canvas.itemconfig(self._orb_id, fill="#0d1117", outline="#ffd700")
            self.canvas.itemconfig(self._glow_id, outline="#ffd700")
            self._pulse("#ffd700", speed=80)
        elif state == "speaking":
            self.canvas.itemconfig(self._orb_id, fill="#0d1117", outline="#00d4ff")
            self.canvas.itemconfig(self._glow_id, outline="#00d4ff")
            self._pulse("#00d4ff", speed=150)
        else:  # idle
            self._stop_pulse("#00d4ff")
            self.canvas.itemconfig(self._orb_id, fill="#0d1117", outline="#00d4ff")

    # ================================================================
    # Toast (temporary floating message)
    # ================================================================
    def _show_toast(self, text, duration=4000):
        """Show a temporary floating toast message near the orb."""
        self._ui(lambda: self._show_toast_ui(text, duration))

    def _show_toast_ui(self, text, duration=4000):
        if self._status_win:
            try:
                self._status_win.destroy()
            except Exception:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.92)
        win.configure(bg="#161b22")

        # Calculate position: to the left of the orb (clamped on-screen)
        x = max(8, self.root.winfo_x() - 340)
        y = max(8, self.root.winfo_y())

        # Wrap text
        display = text[:200] + "..." if len(text) > 200 else text
        lbl = tk.Label(win, text=display, font=("Helvetica Neue", 11),
                       fg="#c9d1d9", bg="#161b22", wraplength=300,
                       justify="left", padx=12, pady=8)
        lbl.pack()
        win.geometry(f"+{x}+{y}")
        self._status_win = win
        self.root.after(duration, lambda: self._destroy_toast(win))

    def _destroy_toast(self, win):
        try:
            if win == self._status_win:
                win.destroy()
                self._status_win = None
        except Exception:
            pass

    # ================================================================
    # Mouse events (timer-based click detection + hold-to-talk)
    # ================================================================
    def _on_left_press(self, event):
        """Button-1 pressed. A second press before the pending single-click
        timer fires means the user double-clicked -> start voice input."""
        self._follow_resume()  # touching the orb wakes a parked follower
        self._drag_x = event.x
        self._drag_y = event.y
        self._press_time = time.time()
        self._is_dragging = False

        if self._pending_single_click is not None:
            # Second click arrived within the delay window: double click.
            self._cancel_pending_click()
            self._double_clicked = True
            self._stop_hold_pulse()
            self._voice_input()
            return

        self._double_clicked = False
        self._start_hold_pulse()

    def _on_drag(self, event):
        dx = event.x - self._drag_x
        dy = event.y - self._drag_y
        if not self._is_dragging:
            if abs(event.x - self._drag_x) > self.DRAG_THRESHOLD_PX or \
               abs(event.y - self._drag_y) > self.DRAG_THRESHOLD_PX:
                self._is_dragging = True
                self._stop_hold_pulse()  # dragging, not holding
            else:
                return
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _on_left_release(self, event):
        held_ms = (time.time() - self._press_time) * 1000.0
        self._stop_hold_pulse()

        if self._double_clicked:
            # Voice already started on the second press; nothing to schedule.
            return

        if self._is_dragging:
            self._save_state()
            return

        if held_ms > self.HOLD_THRESHOLD_MS:
            # Long hold without drag: hold-to-talk feedback only.
            return

        if self._pending_single_click is None:
            # First quick click: wait CLICK_DELAY_MS in case a double follows.
            self._pending_single_click = self.root.after(
                self.CLICK_DELAY_MS, self._single_click_action)

    def _single_click_action(self):
        """Fires only when no double-click followed within CLICK_DELAY_MS."""
        self._pending_single_click = None
        self._show_toast("⚡ Single tap orb.\n"
                         "Double-click: 🎤 voice\n"
                         "Right-click: menu\n"
                         "Drag: move", duration=2500)

    def _on_right_click(self, event):
        """Right-click: show action menu."""
        self._follow_resume()  # menu interaction resumes cursor-following
        self.menu.post(event.x_root, event.y_root)

    # ================================================================
    # Hold-to-talk visual feedback (continuous green pulse while held)
    # ================================================================
    def _start_hold_pulse(self):
        self._stop_hold_pulse()
        self._hold_phase = 0
        self.canvas.itemconfig(self._orb_id, fill="#0a2214", outline="#00ff88")
        self._hold_step()

    def _hold_step(self):
        if not self.running.is_set():
            return
        self._hold_phase += 1
        p = self._hold_phase % 14
        alpha = 0.35 + 0.65 * abs(p - 7) / 7.0
        clr = "#%02x%02x%02x" % (0, min(255, int(255 * alpha)),
                                 min(255, int(136 * alpha)))
        self.canvas.itemconfig(self._glow_id, outline=clr)
        self._hold_pulse_id = self.root.after(90, self._hold_step)

    def _stop_hold_pulse(self):
        if self._hold_pulse_id:
            try:
                self.root.after_cancel(self._hold_pulse_id)
            except Exception:
                pass
            self._hold_pulse_id = None

    # ================================================================
    # Voice input (robust, with noise calibration)
    # ================================================================
    def _voice_input(self):
        """Listen via microphone with proper calibration."""
        if self.listening:
            return
        self.listening = True
        self._set_state("listening")
        self._show_toast("🎤 Listening... speak now", duration=15000)
        threading.Thread(target=self._do_voice, daemon=True).start()

    def _do_voice(self):
        text = None
        try:
            r = sr.Recognizer()  # sr imported at module level: a local import
            # here raised NameError from inside the except clauses below when
            # speech_recognition was missing.
            # Calibrate for ambient noise
            with sr.Microphone() as source:
                r.adjust_for_ambient_noise(source, duration=1.0)
                r.energy_threshold = 150  # lower = more sensitive
                r.pause_threshold = 1.5
                r.dynamic_energy_threshold = True
                audio = r.listen(source, timeout=10, phrase_time_limit=15)
            text = r.recognize_google(audio)
        except sr.WaitTimeoutError:
            text = self._register_voice_failure("No speech detected.")
        except sr.UnknownValueError:
            text = self._register_voice_failure("Could not understand audio.")
        except sr.RequestError as e:
            text = self._register_voice_failure(f"Voice service error: {e}")
        except Exception as e:
            text = self._register_voice_failure(f"Voice error: {e}")
        finally:
            self.listening = False
            self._set_state("idle")

        if text:
            self._voice_fail_streak = 0  # success resets the failure streak
            self.voice_history.append(text)
            self._show_toast(f"You said: {text}", duration=2000)
            self._process(text)

    # ================================================================
    # Always-on wake word ("Hey Jarvis") — Clicky-style hands-free
    # ================================================================
    @staticmethod
    def _wake_phrase(text):
        """Return the command after a wake phrase, or None if not a wake."""
        if not text:
            return None
        t = text.strip()
        m = re.search(r"\b(?:hey|ok|okay|hi|hello)?\s*jarvis\b[,:.!]?\s*(.*)$",
                      t, re.I)
        if not m:
            return None
        cmd = m.group(1).strip(" .,!?'\"")
        return cmd

    def _toggle_wake_word(self):
        if self.wake_word_enabled:
            self._stop_wake_word()
            self.say("Wake word off, sir. Push-to-talk only.")
        else:
            self.wake_word_enabled = True
            self._wake_thread = threading.Thread(
                target=self._wake_listen_loop, daemon=True)
            self._wake_thread.start()
            self.say("Wake word on. Just say 'Hey Jarvis' and then your command.")

    def _stop_wake_word(self):
        self.wake_word_enabled = False
        self._wake_thread = None

    def _wake_listen_loop(self):
        """Background daemon: continuously listens, wakes on 'Hey Jarvis'."""
        if os.environ.get("JARVIS_TEST"):
            return
        self._show_toast("👂 Wake word listening... say 'Hey Jarvis'", duration=3000)
        while self.wake_word_enabled:
            try:
                r = sr.Recognizer()
                with sr.Microphone() as source:
                    r.adjust_for_ambient_noise(source, duration=0.5)
                    r.energy_threshold = 150
                    r.pause_threshold = 1.2
                    audio = r.listen(source, timeout=5, phrase_time_limit=12)
                text = r.recognize_google(audio)
            except Exception:
                text = None
            if not self.wake_word_enabled:
                break
            if not text:
                continue
            self.voice_history.append(text)
            cmd = self._wake_phrase(text)
            if cmd is None:
                # Heard something address-free; ignore unless it names Jarvis
                continue
            self._show_toast(f"You said: {text}", duration=2000)
            self.awake = True
            self._process(cmd if cmd else "wake up")

    def _register_voice_failure(self, msg):
        """Record a recognition failure; after MAX_VOICE_FAILS in a row show
        troubleshooting tips instead of the bare error."""
        self._voice_fail_streak += 1
        if self._voice_fail_streak >= self.MAX_VOICE_FAILS:
            self._voice_fail_streak = 0
            self._show_toast(
                f"{msg}\n\n⚠️ Voice failed {self.MAX_VOICE_FAILS} times in a row."
                "\nTroubleshooting tips:\n"
                "• Check microphone permissions (System Settings → Privacy → Microphone)\n"
                "• Speak louder and closer to the mic\n"
                "• Check your internet connection\n"
                "• Reduce background noise, then try again",
                duration=9000)
        else:
            self._show_toast(
                f"{msg} ({self._voice_fail_streak}/{self.MAX_VOICE_FAILS} failed)",
                duration=2500)
        return None

    # ================================================================
    # Model picker + TTS voice picker (Clicky-style user control)
    # ================================================================
    def _which_model(self):
        self.say(f"I am running on model {ACTIVE_MODEL}, sir.")

    def _set_model(self, cmd):
        """Set the active chat model from a spoken command like
        'use model llama 70', 'switch model to gpt oss', 'model llama 8'."""
        low = cmd.lower()
        if "list" in low or "what models" in low or "options" in low:
            names = "· ".join(GROQ_MODEL_CHOICES)
            self.say(f"Available models, sir: {names}. Say 'use model' and a keyword.")
            return
        # Map spoken keywords -> exact model ids. Handles both
        # "use model llama 70" and "switch model to gpt oss" and "model llama 8".
        m = re.search(
            r"(?:use|switch|set|change|activate)\s+(?:the\s+)?"
            r"(?:model\s+)?(?:to\s+)?(?P<name>.+)$", low)
        if not m:
            m = re.search(r"\bmodel\s+(?:to\s+)?(?P<name>.+)$", low)
        key = (m.group("name") if m else low).strip(" .,")
        match = None
        for cand in GROQ_MODEL_CHOICES:
            if all(tok in cand.lower() for tok in key.split()
                   if len(tok) > 2) or key in cand.lower():
                match = cand
                break
        if not match and key:
            # Allow partial like "llama" / "70b" / "oss"
            for cand in GROQ_MODEL_CHOICES:
                if key in cand.lower() or any(w in cand.lower()
                                             for w in key.split()):
                    match = cand
                    break
        if not match:
            self.say("I didn't catch which model, sir. Say 'list models' "
                     "or 'use model' followed by a name.")
            return
        global ACTIVE_MODEL
        ACTIVE_MODEL = match
        self._show_toast(f"Model set to {match}", duration=3000)
        self.say(f"Switched to model {match.split('/')[-1].split('-')[0]}, sir.")

    def _change_voice(self, cmd):
        """Pick a TTS voice from a spoken command like 'use male voice' /
        'change voice to female' / 'use the australian voice'."""
        low = cmd.lower()
        engine = getattr(self, "_tts_engine", None)
        if engine is None:
            self._try_init_tts()
            engine = getattr(self, "_tts_engine", None)
        if engine is None:
            self.say("Voice selection is not available without a text-to-speech engine, sir.")
            return
        try:
            voices = engine.getProperty("voices")
        except Exception:
            self.say("I couldn't read the available voices, sir.")
            return
        key = low
        pick = None
        preferred = None
        for v in voices:
            n = v.name.lower()
            if "daniel" in n or "male" in n:
                preferred = v.id
            if any(k in n for k in ("female", "samantha", "victoria", "karen",
                                    "moira", "serena", "zira")):
                if key and ("female" in key and (
                        "female" in n or "samantha" in n or "victoria" in n
                        or "karen" in n or "moira" in n or "serena" in n)):
                    pick = v.id
                    break
            if key and "male" in key and ("male" in n or "daniel" in n
                                          or "alex" in n or "david" in n):
                pick = v.id
                break
            if key and ("australian" in key and "australia" in n):
                pick = v.id
                break
            if key and ("british" in key or "uk" in key) and (
                    "uk" in n or "british" in n or "daniel" in n):
                pick = v.id
                break
            if key and ("american" in key or "us" in key) and (
                    "us" in n or "united states" in n or "samantha" in n):
                pick = v.id
                break
        if pick is None and preferred:
            pick = preferred
        if pick is None:
            self.say("I couldn't find that voice. Try 'change voice to male' "
                     "or 'change voice to female', sir.")
            return
        try:
            engine.setProperty("voice", pick)
        except Exception:
            self.say("I couldn't set that voice, sir.")
            return
        self.say("Voice changed, sir. How is this one?")

    def _try_init_tts(self):
        try:
            import pyttsx3
            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty("rate", 180)
        except Exception:
            self._tts_engine = None

    # ================================================================
    # Command processing — helper methods shared with JarvisApp
    # ================================================================
    def _time_intent(self, cmd):
        return bool(re.search(
            r"\b(what('s| is| s)? the time|what time is it|current time|"
            r"time now|tell me the time)\b", cmd))

    def _date_intent(self, cmd):
        return bool(re.search(
            r"\b(what('s| is| s)? the date|what date|today.?s date|"
            r"what day(?! of the week| was))\b", cmd))

    def _battery_intent(self, cmd):
        return bool(re.search(r"\bbattery\b|\bhow much (power|charge)\b", cmd))

    def _is_define(self, cmd):
        return bool(re.match(r"^(define|what does)\s+", cmd))

    def _is_repeat(self, cmd):
        return any(cmd == p or cmd.startswith(p + " ") or cmd.startswith(p + ",")
                   for p in ("repeat", "repeat that", "say that again",
                             "can you repeat", "say again", "what did you say"))

    def _is_clear_memory(self, cmd):
        return any(p in cmd for p in ["clear your memory", "clear memory",
                                       "forget everything", "forget the conversation",
                                       "wipe your memory", "reset your memory"])

    def _is_api_key(self, cmd):
        return any(p in cmd for p in ["set api key", "change api key",
                                       "new api key", "add api key",
                                       "enter api key", "paste api key",
                                       "configure api key", "setup api key"])

    def set_api_key(self):
        self.say("Please provide your Groq API key, sir.")
        self._show_toast("Paste your API key in the console.", duration=5000)

    def _set_ai_mode(self, mode):
        pass

    def _osascript(self, script):
        if platform.system() != "Darwin":
            return False
        try:
            r = subprocess.run(["osascript", "-e", script],
                               capture_output=True, timeout=15)
            return r.returncode == 0
        except Exception:
            return False

    def _current_volume(self):
        if platform.system() != "Darwin":
            return None
        try:
            r = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, timeout=15)
            return int(r.stdout.strip())
        except Exception:
            return None

    def _system_action(self, cmd):
        if platform.system() != "Darwin":
            return False
        if re.search(r"\b(lock|secure)\s+(the\s+)?(computer|screen|mac)\b", cmd) \
                or "lock my computer" in cmd:
            if self._osascript('tell application "System Events" to keystroke "q" '
                               'using {control down, command down}'):
                self.say("Computer locked, sir.")
            else:
                self.say("I could not lock the computer, sir.")
            return True
        if re.search(r"\btake\s+a?\s*screenshot\b", cmd) or \
                re.search(r"\b(screen\s+)?capture\b", cmd) or cmd.strip() == "screenshot":
            self._handle_screen_query(cmd)
            return True
        if re.search(r"\bvolume\b", cmd):
            if re.search(r"\b(max|full|louder|increase|up)\b", cmd):
                cur = self._current_volume()
                nv = min(100, (cur + 10) if cur is not None else 80)
                self._osascript(f"set volume output volume {nv}")
                self.say(f"Volume set to {nv} percent, sir.")
                return True
            if re.search(r"\b(decrease|lower|down|quieter|min|muted?|mute)\b", cmd):
                cur = self._current_volume()
                nv = max(0, (cur - 10) if cur is not None else 30)
                self._osascript(f"set volume output volume {nv}")
                self.say(f"Volume set to {nv} percent, sir.")
                return True
        return False

    def _handle_time(self, cmd):
        now = datetime.datetime.now().strftime("%I:%M %p").lstrip("0")
        self.say(f"The time is {now}.")

    def _handle_battery(self, cmd):
        self._battery_report()

    def _battery_report(self):
        pct = None
        plugged = None
        if HAVE_PSUTIL:
            try:
                b = psutil.sensors_battery()
                if b is not None:
                    pct = int(b.percent)
                    plugged = b.power_plugged
            except Exception:
                pass
        if pct is None:
            try:
                r = subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                   text=True, timeout=10)
                m = re.search(r"(\d+)%", r.stdout)
                if m:
                    pct = int(m.group(1))
                    plugged = "AC" in r.stdout or "charging" in r.stdout
            except Exception:
                pass
        if pct is None:
            self.say("I could not read the battery status, sir.")
            return
        status = "on charger" if plugged else "on battery" if plugged is not None else "charge state unknown"
        self.say(f"Battery is at {pct} percent, {status}, sir.")

    def _handle_define(self, cmd):
        term = re.sub(r"^(define|what does)\s+", "", cmd).strip(" ?")
        if not term:
            self.say("What would you like me to define, sir?")
            return
        self.say(f"Looking up {term} on Wikipedia, sir.")
        webbrowser.open("https://en.wikipedia.org/wiki/Special:Search?search="
                        + term.replace(" ", "+"))

    def _is_todo(self, cmd):
        return bool(re.search(r"\btodo\b|\bto[- ]do\b|\btask\s+list\b|"
                              r"\b(?:add|list|show|clear|done|complete|"
                              r"finish|delete|remove)\b.*\btask\b",
                              cmd, re.I)) and \
            bool(re.search(r"\b(add|create|new|list|show|read|clear|wipe|"
                           r"done|complete|check|finish|delete|remove|drop)\b",
                           cmd, re.I))

    def _handle_todo(self, cmd):
        try:
            import jarvis.todo_list as todo
            parsed = todo.parse_intent(cmd)
        except Exception:
            self.say("I could not reach my task list, sir.")
            return
        if parsed is None:
            self.say("Tell me to add, list, complete, or remove a task, sir.")
            return
        verb, payload = parsed
        if verb == "add":
            count = todo.add_task(payload)
            self.say(f"Added task {count} to your to-do list: {payload}, sir.")
        elif verb == "list":
            tasks = todo.list_tasks()
            if not tasks:
                self.say("Your to-do list is empty, sir.")
                return
            lines = []
            for i, t in enumerate(tasks, 1):
                mark = "[x]" if t.get("done") else "[ ]"
                lines.append(f"{i}. {mark} {t.get('text', '')}")
            reply = "Your to-do list, sir: " + " | ".join(lines)
            self.say(reply)
            if hasattr(self, "show_list_panel"):
                try:
                    self.show_list_panel(lines, "To-Do List")
                except Exception:
                    pass
        elif verb == "clear":
            todo.clear_tasks()
            self.say("Cleared your to-do list, sir.")
        elif verb == "done":
            if todo.done_task(payload):
                self.say(f"Marked '{payload}' as done, sir.")
            else:
                self.say(f"I could not find '{payload}' on your to-do list, sir.")
        elif verb == "delete":
            removed = todo.delete_task(payload)
            if removed is not None:
                self.say(f"Removed '{removed.get('text', '')}' from your to-do list, sir.")
            else:
                self.say("I could not find that task to remove, sir.")

    def _local_chat(self, prompt, _code_gen_mode=False):
        getter = getattr(self, "_get_brain", None)
        if not callable(getter):
            return None
        try:
            return getter().chat(prompt, _code_gen_mode=_code_gen_mode)
        except Exception as e:
            print("LOCAL CHAT ERROR:", e)
            return None

    def _ask_ai_safely(self, prompt, _code_gen_mode=False):
        if not load_api_key():
            self._set_ai_mode("LOCAL")
            local = self._local_chat(prompt, _code_gen_mode=_code_gen_mode)
            if local:
                return local
            return ("I am running on my local brain only, sir, since no "
                    "API key is set. Say 'set api key' to enable my full "
                    "language model.")
        local = self._local_chat(prompt, _code_gen_mode=_code_gen_mode)
        if local:
            return local
        reply = ask_ai(prompt, self._bot_context_history())
        if reply is None:
            return local or None
        if reply == "__UNAUTHORIZED__":
            self._set_ai_mode("LOCAL")
            local = self._local_chat(prompt)
            if local:
                return ("My API key was rejected, sir, so I switched to my "
                        "local brain: " + local)
            return ("My API key was rejected, sir. Say 'set api key' to "
                    "paste a new Groq key, or I will keep running on my "
                    "local brain.")
        if reply == "__RATE_LIMITED__":
            return ("Your API key limit has been hit, sir. Say 'set api key' "
                    "to paste a new Groq key, or I will keep running on my "
                    "local brain.")
        if reply and not reply.startswith("__"):
            mem = self._app_memory()
            mem.append({"role": "user", "content": prompt})
            mem.append({"role": "assistant", "content": reply})
            return reply
        return None

    # ================================================================
    # AI Studio automation helpers (shared with JarvisApp)
    # ================================================================
    def _activate_default_browser(self):
        try:
            for name in ("Google Chrome", "Safari", "Microsoft Edge",
                         "Firefox", "Brave Browser", "Arc"):
                check = subprocess.run(
                    ["osascript", "-e", f'application "{name}" is running'],
                    capture_output=True, text=True)
                if check.stdout.strip() == "true":
                    subprocess.run(
                        ["osascript", "-e", f'tell application "{name}" to activate'],
                        capture_output=True)
                    return
        except Exception:
            pass

    def _aistudio_js_exec(self, js):
        for app, tmpl in (
            ("Google Chrome",
             'tell application "Google Chrome" to execute '
             "front window's active tab javascript \"{js}\""),
            ("Safari",
             'tell application "Safari" to do JavaScript '
             "\"{js}\" in current tab of front window")):
            try:
                chk = subprocess.run(["osascript", "-e",
                                      f'application "{app}" is running'],
                                     capture_output=True, text=True)
                if chk.stdout.strip() != "true":
                    continue
                res = subprocess.run(["osascript", "-e", tmpl.format(js=js)],
                                     capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    return res.stdout.strip()
            except Exception:
                continue
        return None

    def _aistudio_js_start(self):
        js = ("const STEP='START';(()=>{const labels=['start building',"
              "'start building with gemini api','start','build','get started','create'];"
              "const els=document.querySelectorAll('button,a,[role=button],[role=link]');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.textContent||'')"
              ".trim().toLowerCase();if(labels.indexOf(t)>=0&&el.offsetParent!==null)"
              "{el.click();return 'clicked';}}return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_js_insert(self, prompt):
        b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
        js = ("const STEP='INSERT';(()=>{const b64='" + b64 + "';"
              "const bytes=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));"
              "const p=new TextDecoder().decode(bytes);"
              "let el=document.querySelector('textarea,[contenteditable=true],"
              "[role=textbox],.ql-editor,[data-placeholder]');"
              "if(!el){const all=document.querySelectorAll('*');"
              "for(const e of all){if(e.contentEditable==='true'"
              "&&e.offsetParent!==null){el=e;break;}}}"
              "if(!el)return 'no-editor';"
              "el.focus();"
              "if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){"
              "const nativeSet=Object.getOwnPropertyDescriptor("
              "window.HTMLTextAreaElement.prototype,'value').set;"
              "nativeSet.call(el,p);"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "return 'set-value';}"
              "const range=document.createRange();"
              "range.selectNodeContents(el);"
              "const s=window.getSelection();s.removeAllRanges();"
              "s.addRange(range);"
              "const ok1=document.execCommand('insertText',false,p);"
              "if(ok1){el.dispatchEvent(new Event('input',{bubbles:true}));"
              "return 'inserted';}"
              "el.textContent=p;"
              "el.dispatchEvent(new Event('input',{bubbles:true}));"
              "return 'set-text';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and res != "no-editor")

    def _aistudio_js_run(self):
        js = ("const STEP='RUN';(()=>{const labels=['run','send','submit','generate',"
              "'start','build','create'];"
              "const els=document.querySelectorAll('button,[role=button]');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.title||"
              "el.textContent||'').trim().toLowerCase();"
              "if(labels.indexOf(t)>=0&&el.offsetParent!==null){el.click();return 'clicked';}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _paste_and_run_in_aistudio(self, prompt):
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except Exception:
            try:
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(prompt.encode("utf-8"))
            except Exception:
                return False
        self._activate_default_browser()
        time.sleep(3)
        try:
            import pyautogui
            w, h = pyautogui.size()
            pyautogui.click(w // 2, h // 2)
            time.sleep(0.8)
            pyautogui.hotkey("command", "a")
            time.sleep(0.3)
            pyautogui.hotkey("command", "v")
            time.sleep(1.0)
            pyautogui.hotkey("command", "enter")
            time.sleep(1.5)
            return True
        except Exception:
            return False

    def _click_at(self, x, y, clicks=1):
        try:
            import pyautogui
            pyautogui.click(x, y, clicks=clicks)
            return True
        except Exception:
            return False

    def _click_element_by_text(self, text):
        img, b64 = self._take_screenshot()
        if not b64:
            return False, "Could not capture screen."
        question = (f"Find the UI element with the text '{text}' on this screen. "
                    f"Return ONLY the approximate pixel coordinates (x, y) of its "
                    f"center, like: 450, 320")
        answer = self._ask_vision(b64, question)
        coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
        if not coords:
            return False, f"Could not locate '{text}' on screen."
        x, y = int(coords[0][0]), int(coords[0][1])
        self._click_at(x, y)
        return True, f"Clicked '{text}' at ({x}, {y})."

    def _smart_click_in_aistudio(self, prompt):
        self._activate_default_browser()
        time.sleep(3)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)
        try:
            import pyautogui
            img, b64 = self._take_screenshot()
            if b64:
                question = ("Find the main text input area, chat box, or prompt field "
                            "on this screen. Return ONLY the approximate pixel "
                            "coordinates (x, y) of its center, like: 640, 400")
                answer = self._ask_vision(b64, question)
                coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
                if coords:
                    x, y = int(coords[0][0]), int(coords[0][1])
                    pyautogui.click(x, y)
                    time.sleep(0.5)
                    pyautogui.hotkey("command", "a")
                    time.sleep(0.2)
                    pyautogui.hotkey("command", "v")
                    time.sleep(1.0)
                    img2, b64_2 = self._take_screenshot()
                    if b64_2:
                        q2 = ("Find the 'Run', 'Send', 'Submit', or 'Generate' button "
                              "on this screen. Return ONLY the approximate pixel "
                              "coordinates (x, y) of its center.")
                        a2 = self._ask_vision(b64_2, q2)
                        c2 = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", a2)
                        if c2:
                            bx, by = int(c2[0][0]), int(c2[0][1])
                            pyautogui.click(bx, by)
                            time.sleep(1.5)
                            return True
                    pyautogui.hotkey("command", "enter")
                    time.sleep(1.5)
                    return True
        except Exception:
            pass
        return self._paste_and_run_in_aistudio(prompt)

    def _handle_fix_screen(self, cmd):
        """Take a screenshot, analyze the screen, and attempt to fix issues."""
        self.say("Let me take a look at your screen, sir.")
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("I could not capture your screen, sir.")
            return
        
        analysis = self._ask_vision(b64, (
            "Look at this screen carefully. Is there any error, warning, bug, "
            "or issue visible? Describe exactly what you see that needs fixing. "
            "If there's an error message, quote it exactly. "
            "If there's a form with missing fields, describe which ones. "
            "If there's a button that needs clicking, describe its location. "
            "Be specific about what needs to be done to fix the issue."
        ))
        
        if not analysis or analysis == "__UNAUTHORIZED__":
            self.say("I need an API key for vision, sir. Say 'set api key'.")
            return
        
        self.say(f"I see the following on your screen:\n{analysis}")
        
        fix = self._ask_vision(b64, (
            f"Based on this screen analysis: '{analysis}'\n"
            "What specific action should be taken to fix this issue? "
            "Reply with ONE of these action types and details:\n"
            "- CLICK: [description of what to click and where]\n"
            "- TYPE: [what text to type and where]\n"
            "- SCROLL: [up or down and how much]\n"
            "- SHORTCUT: [keyboard shortcut to press]\n"
            "- CODE: [code to write to fix the issue]\n"
            "- NONE: [if no action is needed]\n"
            "Be specific about coordinates if CLICK, or text if TYPE."
        ))
        
        if not fix or fix == "__UNAUTHORIZED__":
            self.say("I could not determine a fix, sir.")
            return
        
        self.say(f"Here is what I recommend: {fix}")
        
        try:
            import pyautogui
            
            fix_upper = fix.upper()
            
            if fix_upper.startswith("CLICK"):
                coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", fix)
                if coords:
                    x, y = int(coords[0][0]), int(coords[0][1])
                    self._click_at(x, y)
                    self.say(f"Clicked at {x}, {y} to fix the issue.")
                else:
                    self.say("I found the fix but could not determine exact coordinates.")
            
            elif fix_upper.startswith("TYPE"):
                text_match = re.search(r"[:'\"\"](.+?)['\"\"]?$", fix)
                if text_match:
                    text = text_match.group(1).strip()
                    pyautogui.typewrite(text, interval=0.02)
                    self.say(f"Typed: {text}")
                else:
                    self.say("I found the fix but could not determine the text to type.")
            
            elif fix_upper.startswith("SCROLL"):
                if "up" in fix.lower():
                    pyautogui.scroll(3)
                    self.say("Scrolled up.")
                elif "down" in fix.lower():
                    pyautogui.scroll(-3)
                    self.say("Scrolled down.")
                else:
                    pyautogui.scroll(-3)
                    self.say("Scrolled down.")
            
            elif fix_upper.startswith("SHORTCUT"):
                keys = re.findall(r"\b(ctrl|command|cmd|alt|shift|enter|tab|esc|delete|backspace|space|up|down|left|right|[a-z])\b", fix.lower())
                if keys:
                    pyautogui.hotkey(*keys[:4])
                    self.say(f"Pressed shortcut: {'+'.join(keys[:4])}")
                else:
                    self.say("I found the fix but could not determine the shortcut keys.")
            
            elif fix_upper.startswith("CODE"):
                code_match = re.search(r"[:'\"\"](.+?)['\"\"]?$", fix, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    self.say(f"Here is the code to fix the issue:\n{code}")
                else:
                    self.say("I found the fix but could not extract the code.")
            
            else:
                self.say("I analyzed your screen but no automatic fix was possible. Please fix manually.")
        
        except ImportError:
            self.say("I need pyautogui for automatic fixes, sir.")
        except Exception as e:
            self.say(f"Could not apply the automatic fix: {e}")

    def _get_recent_context(self, n=3):
        """Get the last n conversation turns for context."""
        recent = list(self.history)[-n*2:] if self.history else []
        return "\n".join(f"{'User' if i%2==0 else 'JARVIS'}: {m['content']}" 
                        for i, m in enumerate(recent))

    def _is_action_command(self, cmd):
        """Detect voice-activated action commands."""
        return bool(re.search(r"\b(open|close|click|type|scroll|switch|go back|go forward|"
                              r"maximize|minimize|fullscreen|refresh|reload|save|undo|redo|"
                              r"copy|paste|cut|select all)\b", cmd))

    def _handle_smart_fix(self, cmd):
        """Enhanced fix that uses conversation context."""
        context = self._get_recent_context()
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("Could not capture screen.")
            return
        
        prompt = f"Previous conversation:\n{context}\n\nUser request: {cmd}\n\nCurrent screen screenshot attached. What action should be taken?"
        if context:
            analysis = self._ask_vision(b64, prompt)
        else:
            analysis = self._handle_fix_screen(cmd)
            return

    # ================================================================
    # JarvisApp feature-parity helpers
    # ================================================================

    CALC_WORDS = {
        "plus": "+", "minus": "-", "times": "*", "multiplied by": "*",
        "divided by": "/", "over": "/", "to the power of": "**",
        "percent of": "*", "of": "*",
    }

    def _generate_content(self, prompt, _code_gen_mode=False):
        reply = self._ask_ai_safely(prompt, _code_gen_mode=_code_gen_mode)
        if not reply:
            return None, "I could not generate the content, sir."
        if reply.startswith("My API key was rejected"):
            return None, reply
        if reply.startswith("Your API key limit"):
            return None, reply
        if reply.startswith("I hit an error"):
            local = self._local_chat(prompt)
            if local:
                return local, None
            return None, reply
        if reply.startswith("That is beyond my local memory"):
            return None, reply
        return reply, None

    def _split_commands(self, cmd):
        parts = re.split(r"\s*,\s*|\s+and\s+|\s+then\s+|\s*;\s*", cmd)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            return [cmd]

        def command_like(p):
            if re.search(r"\b(open|go to|play|search|build|make|create|set|"
                         r"start|timer|remind|convert|calculate|compute|"
                         r"define|weather|battery|volume)\b", p):
                return True
            if self._time_intent(p) or self._date_intent(p):
                return True
            if self._weather_intent(p) or self._calc_intent(p):
                return True
            if self._match_website(p):
                return True
            for key in APP_MAP:
                if re.search(r"\b" + re.escape(key) + r"\b", p):
                    return True
            return False

        if all(command_like(p) for p in parts):
            first = parts[0].strip().lower()
            if first.startswith(("open ", "go to ")):
                verb = first.split()[0]
                for i in range(1, len(parts)):
                    p = parts[i].strip().lower()
                    if not re.match(r"^(?:open|go to|play|search|build|make|create|set|"
                                    r"start|timer|remind|convert|calculate|compute|define|"
                                    r"battery|volume)\b", p) and self._match_website(p):
                        parts[i] = f"{verb} {parts[i]}"
            return parts
        return [cmd]

    def _match_website(self, rest):
        best = None
        best_len = -1
        for name, url in WEBSITES.items():
            for m in re.finditer(r"\b" + re.escape(name) + r"\b", rest):
                length = m.end() - m.start()
                if length > best_len:
                    best_len = length
                    best = (name, url)
        return best

    def _is_search(self, cmd):
        return bool(re.search(r"\bsearch(?:ing)?\b|\blook\s+up\b|\bgoogle\b", cmd))

    def _handle_search(self, cmd):
        query = re.sub(r"^(?:search for|search)\s*", "", cmd).strip(" .,")
        if not query:
            self.say("What should I search for, sir?")
            return
        if "wikipedia" in query:
            topic = re.sub(r"\bwikipedia\b", "", query).strip(" .,")
            topic = re.sub(r"^(?:for|about|on)\s+", "", topic)
            if not topic:
                self.say("What should I look up on Wikipedia, sir?")
                return
            self.say(f"Searching Wikipedia for {topic}.")
            webbrowser.open("https://en.wikipedia.org/wiki/Special:Search?search="
                            + topic.replace(" ", "+"))
            return
        self.say(f"Searching for {query}.")
        webbrowser.open("https://www.google.com/search?q=" + query.replace(" ", "+"))

    def _play_youtube(self, cmd):
        if re.search(r"\b(pause|resume|stop|next|previous|skip)\b", cmd) and \
                re.search(r"\b(music|song|track)\b", cmd):
            return False
        if re.search(r"\bsearch\b", cmd):
            return False
        if not re.search(r"\bplay\b", cmd):
            if ("open" in cmd or "go to" in cmd
                    or not re.search(r"\bsong\b|\bmusic\b", cmd)):
                return False
        m = re.search(r"\bplay\b", cmd)
        query = cmd[m.end():] if m else cmd
        query = re.sub(r"\bon youtube\b|\bin youtube\b|youtube", " ", query)
        for w in ("please", "can you", "could you", "will you", "would you",
                  "i want to", "can", "could", "will", "would", "do", "the",
                  "and", "some", "a", "an", "song", "music", "called",
                  "named", "name", "to"):
            query = re.sub(r"\b" + re.escape(w) + r"\b", " ", query)
        query = re.sub(r"\s+", " ", query).strip(" .,")
        if not query:
            return False
        if query in GAME_WORDS:
            self.say(f"{query.title()} is a game, sir. I can search it on YouTube "
                     "if you want to watch a playthrough.")
            return True
        self.say(f"Playing {query} on YouTube.")
        video = self._youtube_first_video(query)
        if video:
            webbrowser.open(video)
        else:
            webbrowser.open("https://www.youtube.com/results?search_query="
                            + query.replace(" ", "+"))
        return True

    def _youtube_first_video(self, query):
        try:
            resp = requests.get(
                "https://www.youtube.com/results",
                params={"search_query": query},
                headers={
                    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0.0.0 Safari/537.36")
                },
                timeout=8,
            )
            m = re.search(r'"videoId":"([A-Za-z0-9_-]{11})"', resp.text)
            if m:
                return "https://www.youtube.com/watch?v=" + m.group(1)
        except Exception:
            pass
        return None

    def _weather_intent(self, cmd):
        if "open" in cmd or "go to" in cmd:
            return False
        return bool(re.search(r"\bweather\b|\bforecast\b|\btemperature\b|"
                              r"\b(?:is|it) raining\b|how hot|how cold", cmd))

    def _weather_location(self, cmd):
        m = re.search(r"\b(?:in|for)\s+(?:the\s+)?"
                      r"([A-Za-z][A-Za-z .'-]*?)[?.!]*$", cmd)
        if not m:
            return None
        loc = m.group(1).strip(" .")
        if "weather" in loc.lower() or "forecast" in loc.lower():
            return None
        return loc or None

    def _handle_weather(self, cmd):
        loc = self._weather_location(cmd)
        if not loc:
            self.say("For which city, sir?")
            loc = self.listen(timeout=4, phrase_limit=4)
            if loc:
                loc = loc.strip().title()
        if not loc:
            self._set_state("thinking")
            reply = self._ask_ai_safely(
                "What is the weather? Answer in one short sentence.")
            if reply and reply != "__UNAUTHORIZED__":
                self.say(reply)
            return
        self._set_state("thinking")
        text = get_weather(loc)
        if not text:
            reply = self._ask_ai_safely(
                f"What is the weather in {loc}? Answer in one short sentence.")
            if reply and reply != "__UNAUTHORIZED__":
                self.say(reply)
            return
        self.say(text)

    def _future_time_intent(self, cmd):
        if not re.search(r"\bwhat time\b", cmd):
            return False
        return bool(re.search(r"\b(?:in|after)\s+\d+\s*(hours?|hrs?|h|"
                              r"minutes?|mins?|m|seconds?|secs?|s)\b", cmd))

    def _handle_future_time(self, cmd):
        total = 0
        parts = []
        for m in re.finditer(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|"
                             r"seconds?|secs?|s)\b", cmd):
            n = int(m.group(1))
            u = m.group(2)
            if u.startswith("h"):
                total += n * 3600
                parts.append(f"{n} hours")
            elif u.startswith("m"):
                total += n * 60
                parts.append(f"{n} minutes")
            else:
                total += n
                parts.append(f"{n} seconds")
        if not total:
            self.say("I did not catch the duration, sir.")
            return
        target = datetime.datetime.now() + datetime.timedelta(seconds=total)
        when = target.strftime("%I:%M %p").lstrip("0")
        self.say(f"In {' and '.join(parts)}, it will be {when}.")

    @staticmethod
    def _safe_arith_eval(expr):
        import ast

        allowed_bin = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                       ast.Pow, ast.FloorDiv}

        def _ev(node):
            if isinstance(node, ast.Expression):
                return _ev(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value,
                                                             (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_bin:
                left = _ev(node.left)
                right = _ev(node.right)
                if left is None or right is None:
                    return None
                if isinstance(node.op, ast.Pow) and \
                        (abs(right) > 1000 or abs(left) > 1e12 or
                         (isinstance(right, float)) or
                         (abs(right) > 64)):
                    return None
                try:
                    return {ast.Add: lambda a, b: a + b,
                            ast.Sub: lambda a, b: a - b,
                            ast.Mult: lambda a, b: a * b,
                            ast.Div: lambda a, b: a / b,
                            ast.Mod: lambda a, b: a % b,
                            ast.Pow: lambda a, b: a ** b,
                            ast.FloorDiv: lambda a, b: a // b}[type(node.op)](left, right)
                except Exception:
                    return None
            if isinstance(node, ast.UnaryOp) and \
                    isinstance(node.op, (ast.UAdd, ast.USub)):
                v = _ev(node.operand)
                if v is None:
                    return None
                return -v if isinstance(node.op, ast.USub) else v
            return None

        try:
            tree = ast.parse(expr, mode="eval")
        except Exception:
            return None
        val = _ev(tree)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        return val

    def _calc_intent(self, cmd):
        m = re.search(r"\b(?:calculate|compute|work out|solve|how much is|"
                      r"what is|what's|whats)\s+(.+)$", cmd, re.IGNORECASE)
        if not m:
            return False
        expr = m.group(1).strip(" ?!.")
        if len(expr) > 200:
            return False
        expr = expr.replace("percent", "/100").replace("%", "/100")
        for w, op in self.CALC_WORDS.items():
            expr = re.sub(r"\b" + w + r"\b", op, expr, flags=re.IGNORECASE)
        expr = expr.replace(",", "")
        expr = re.sub(r"\bequals?\b", "", expr, flags=re.IGNORECASE)
        if not re.fullmatch(r"[0-9+\-*/()<>=.\s%]+", expr):
            return False
        for num in re.findall(r"\d+", expr):
            if len(num.lstrip("0") or "0") > 9:
                return False
        if "**" in expr:
            if expr.count("**") > 1:
                return False
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", expr)]
            if len(nums) != 2 or any(abs(n) > 1000 for n in nums):
                return False
        try:
            val = self._safe_arith_eval(expr)
        except Exception:
            return False
        if val is None:
            return False
        original = m.group(1).strip().strip("?")
        self.say(f"{original} equals {val:g}.")
        return True

    def _unit_lookup(self, token, table):
        tok = (token or "").strip().lower()
        if not tok:
            return None
        if tok in table:
            return tok
        tokens = set(re.findall(r"[a-z0-9]+", tok))
        cands = []
        for k in table:
            ktokens = re.findall(r"[a-z0-9]+", k)
            if not ktokens:
                continue
            if all(len(t) > 1 for t in ktokens):
                if all(t in tokens for t in ktokens) or k in tok:
                    cands.append(k)
            else:
                if any(t == k for t in tokens):
                    cands.append(k)
        if not cands:
            return None
        cands.sort(key=len, reverse=True)
        return cands[0]

    def _convert_intent(self, cmd):
        m = re.search(r"\bconvert\s+(-?\d+(?:\.\d+)?)\s+([a-z0-9/ ]+?)\s+"
                      r"(?:to|into|in)\s+([a-z0-9/ ]+?)\s*$", cmd)
        if m:
            val = float(m.group(1))
            fr, to = m.group(2), m.group(3)
        else:
            m = re.search(r"\bhow many\s+([a-z0-9/ ]+?)\s+(?:are )?in\s+"
                          r"(?:a|an|one)\s+([a-z0-9/ ]+?)\s*$", cmd)
            if m:
                to, fr = m.group(1), m.group(2)
                val = 1.0
            else:
                m = re.search(r"\bhow many\s+([a-z0-9/ ]+?)\s+(?:are )?in\s+"
                              r"(-?\d+(?:\.\d+)?)\s+([a-z0-9/ ]+?)\s*$", cmd)
                if m:
                    to, val, fr = m.group(1), float(m.group(2)), m.group(3)
                else:
                    m = re.search(r"\bwhat is\s+(-?\d+(?:\.\d+)?)\s+"
                                  r"([a-z0-9/ ]+?)\s+in\s+([a-z0-9/ ]+?)\s*$", cmd)
                    if not m:
                        return False
                    val, fr, to = float(m.group(1)), m.group(2), m.group(3)

        fr_key = self._unit_lookup(fr, TEMP_UNITS)
        to_key = self._unit_lookup(to, TEMP_UNITS)
        if fr_key and to_key:
            result = self._convert_temp(val, fr_key, to_key)
            self.say(f"{val:g} {fr} equals {result:g} {to}.")
            return True

        for table in (LENGTH_UNITS, MASS_UNITS, SPEED_UNITS, DATA_UNITS):
            fk = self._unit_lookup(fr, table)
            tk = self._unit_lookup(to, table)
            if fk and tk:
                result = val * table[fk] / table[tk]
                self.say(f"{val:g} {fr} equals {result:g} {to}.")
                return True
        return False

    def _convert_temp(self, val, fr_key, to_key):
        fr, to = TEMP_UNITS[fr_key], TEMP_UNITS[to_key]
        if fr == to:
            return val
        if fr == "C":
            c = val
        elif fr == "F":
            c = (val - 32) * 5 / 9
        else:
            c = val - 273.15
        if to == "C":
            return c
        if to == "F":
            return c * 9 / 5 + 32
        return c + 273.15

    def _timer_intent(self, cmd):
        if re.search(r"\b(cancel|stop|end|kill)\s+(the\s+)?(timer|countdown)s?\b", cmd):
            return True
        if re.search(r"\bhow (much time|long).*(timer|countdown)\b", cmd):
            return True
        return bool(re.search(r"\b(timer|countdown)\b", cmd) and
                    re.search(r"\b(set|start|make|for|in|of)\b", cmd))

    def _timer_duration(self, cmd):
        total = 0
        found = False
        for m in re.finditer(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|"
                             r"seconds?|secs?|s)\b", cmd):
            n = int(m.group(1))
            u = m.group(2)
            if u.startswith("h"):
                total += n * 3600
            elif u.startswith("m"):
                total += n * 60
            else:
                total += n
            found = True
        return total if found else None

    def _timer_fired(self, tid):
        if not hasattr(self, '_timer_entries'):
            return
        self._timer_entries = [e for e in self._timer_entries if e['id'] != tid]
        self.say("Timer finished, sir.")
        self._show_toast("Timer finished, sir.", duration=5000)

    def _handle_timer(self, cmd):
        if re.search(r"\b(cancel|stop|end|kill)\s+(the\s+)?(timer|countdown)s?\b", cmd):
            if hasattr(self, '_timer_entries') and self._timer_entries:
                for e in self._timer_entries:
                    e['timer'].cancel()
                self._timer_entries.clear()
                self.say("Timers cancelled, sir.")
            else:
                self.say("There are no active timers, sir.")
            return
        if re.search(r"\bhow (much time|long).*(timer|countdown)\b", cmd):
            if not hasattr(self, '_timer_entries') or not self._timer_entries:
                self.say("There are no active timers, sir.")
                return
            bits = []
            for e in self._timer_entries:
                elapsed = time.time() - e['start']
                left = max(0, e['duration'] - elapsed)
                secs = int(left)
                h, rem = divmod(secs, 3600)
                mns, scs = divmod(rem, 60)
                parts = []
                if h:
                    parts.append(f"{h} hour{'s' if h != 1 else ''}")
                if mns:
                    parts.append(f"{mns} minute{'s' if mns != 1 else ''}")
                if scs or not parts:
                    parts.append(f"{scs} second{'s' if scs != 1 else ''}")
                bits.append(" ".join(parts))
            self.say("Time remaining: " + ", ".join(bits) + ".")
            return
        secs = self._timer_duration(cmd)
        if not secs:
            self.say("For how long should I set the timer, sir?")
            return
        if not hasattr(self, '_timer_entries'):
            self._timer_entries = []
        tid = len(self._timer_entries) + 1
        t = threading.Timer(secs, self._timer_fired, args=(tid,))
        t.daemon = True
        self._timer_entries.append({
            'id': tid, 'timer': t, 'start': time.time(), 'duration': secs
        })
        self._active_timers.append(t)
        t.start()
        h, rem = divmod(secs, 3600)
        mns, scs = divmod(rem, 60)
        parts = []
        if h:
            parts.append(f"{h} hour{'s' if h != 1 else ''}")
        if mns:
            parts.append(f"{mns} minute{'s' if mns != 1 else ''}")
        if scs or not parts:
            parts.append(f"{scs} second{'s' if scs != 1 else ''}")
        label = " ".join(parts)
        self.say(f"Timer set for {label}, sir. I will let you know when it is done.")

    def _is_research_write(self, cmd):
        has_topic = bool(re.search(
            r"\b(research\s+(?:about|on|the\b|a\b|an\b)|"
            r"write\s+(?:a|an|the|my|one|about|about\s+one|a\s+detailed|a\s+comprehensive)?\s*"
            r"(?:report|notes?|essay|article|summary|page|paragraph|section)|"
            r"write\s+about)\b", cmd))
        has_dest = bool(re.search(
            r"\b(in|to|in my|into|save|save in|save to|notes|notepad|document|file)\b", cmd))
        has_save_intent = bool(re.search(
            r"\b(save|store|write|keep)\b.*\b(it|this|that|the|content|information|research)\b"
            r".*\b(in|to|notes|file|document)\b", cmd, re.I))
        bare_research = bool(re.match(r"\bresearch\s+", cmd))
        return (has_topic and has_dest) or has_save_intent or bare_research

    def _safe_filepath(self, filename):
        return sanitize_filename(filename)

    def _extract_write_file(self, cmd):
        m = re.search(
            r"([a-zA-Z0-9_.-]+\.(?:txt|py|js|html|css|java|c|cpp|md|json|csv|xml|pdf))\b",
            cmd, re.IGNORECASE)
        if m:
            return m.group(1)
        alias = re.search(
            r"\b(notes|notepad|document|journal|diary|log|memo|file)\b",
            cmd, re.IGNORECASE)
        if alias:
            word = alias.group(1).lower()
            if word in ("notes", "note"):
                return "notes.txt"
            if word in ("notepad",):
                return "notepad.txt"
            if word in ("document", "doc"):
                return "document.txt"
            if word in ("journal",):
                return "journal.txt"
            if word in ("diary",):
                return "diary.txt"
            if word in ("log",):
                return "log.txt"
            if word in ("memo",):
                return "memo.txt"
            return "notes.txt"
        return None

    def _handle_research_write(self, cmd):
        topic = cmd
        for p in ["research and write about", "research about", "research on",
                    "write about", "write a report on", "write a report about",
                    "write notes on", "write notes about", "write an essay on",
                    "write an article on", "write about", "write one page about",
                    "write one page on", "write a page about", "write a page on",
                    "write detailed notes about", "write comprehensive notes about",
                    "write the notes about", "save the research about",
                    "write the research about", "write about him",
                    "write about her", "write about them", "write",
                    "research"]:
            topic = re.sub(r"\b" + re.escape(p) + r"\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\b(in|to|in my|into|save|save in|save to|file|notes|"
                       r"notepad|document|about him|about her|about them|and|the|a|an|my|his|her|their)\b",
                       " ", topic, flags=re.IGNORECASE)
        topic = " ".join(topic.split()).strip(" .,")
        if not topic:
            self.say("What should I research about, sir?")
            return
        filename = self._extract_write_file(cmd)
        if not filename:
            filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".txt"
        filename = self._safe_filepath(filename)
        self._set_state("thinking")
        self.say(f"Researching {topic} and writing it to {filename}, sir.")
        content = self._ask_ai(
            f"Write a comprehensive, detailed one-page research report about {topic}. "
            "Include key facts, achievements, career highlights, and interesting details. "
            "Make it well-structured with paragraphs. Keep it detailed but readable. "
            "Write at least 300 words.")
        if not content:
            self.say("I could not generate the research, sir.")
            return
        full = f"Research Report: {topic.title()}\n{'=' * 50}\n\n{content}\n"
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(full)
            self.say(f"Research on {topic} has been written to {filename}, sir. "
                     f"File saved at {filepath}.")
        except Exception as e:
            self.say(f"Could not write to {filename}, sir: {e}")

    def _is_code_write(self, cmd):
        has_action = bool(re.search(
            r"\b(write|generate|create|save|put|build|make|program|"
            r"develop|compose|draft|assemble|implement|design)\b",
            cmd, re.IGNORECASE))
        has_code_target = bool(re.search(
            r"\b(code|script|program|function|algorithm|implementation|calculator|"
            r"fibonacci|sorting|login|signup|database|todo|chat|api|server|"
            r"game|website|html|python|javascript|app|parser|converter|"
            r"simulator|generator|manager|tracker|assistant|bot|tool|utility|"
            r"library|module|class|interface|template|scaffold|boilerplate)\b",
            cmd, re.IGNORECASE))
        has_dest = bool(re.search(
            r"\b(in|to|into|file|\.py|\.js|\.html|\.java|\.c|\.cpp|"
            r"for me|and save|and write|and put)\b",
            cmd, re.IGNORECASE))
        if has_action and has_code_target and has_dest:
            return True
        if has_action and has_code_target and re.search(r"\bpython\b", cmd, re.I):
            return True
        if has_action and has_code_target:
            if re.search(r"\b(write|generate|create|save|make|build|program)\b",
                         cmd, re.I) and re.search(r"\b(code|script|program)\b", cmd, re.I):
                return True
        return False

    def _strip_code_chatter(self, code):
        if not code:
            return code
        lines = code.split("\n")
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                start = i + 1
                continue
            if re.match(r"^(?:#|/\*|//|<!--|\"|\'|def |class |import |from |"
                        r"function |const |let |var |<!DOCTYPE|<html|print\(|"
                        r"console\.|public |private |protected |static |void |"
                        r"int |float |double |char |bool |return |if |for |"
                        r"while |try |except |with |as |elif |else |raise |"
                        r"print\(|input\(|True|False|None|\d+|[a-zA-Z_]\w*\s*[=+\-*/<>!]=?)",
                        stripped):
                start = i
                break
            if not re.search(r"[(){}\[\]=;:\/\\<>]", stripped) and len(stripped.split()) > 4:
                start = i + 1
                continue
            start = i
            break
        code = "\n".join(lines[start:])
        end = len(lines)
        for i in range(len(lines) - 1, start - 1, -1):
            stripped = lines[i].strip()
            if not stripped:
                end = i
                continue
            if re.match(r"^(?:#|/\*|//|<!--|\"|\'|print\(|console\.|return |"
                        r"if |for |while |def |class |import |function |const |"
                        r"let |var |else |elif |try |except |with |raise |"
                        r"print\(|input\(|True|False|None|\d+|[a-zA-Z_]\w*\s*[=+\-*/<>!]=?)",
                        stripped):
                end = i + 1
                break
            if not re.search(r"[(){}\[\]=;:\/\\<>]", stripped) and len(stripped.split()) > 4:
                end = i
                continue
            end = i + 1
            break
        return "\n".join(lines[start:end]).strip()

    def _handle_code_write(self, cmd):
        try:
            import code_brain_pro
            handled = code_brain_pro.delegate_code_write(self, cmd)
        except Exception:
            handled = None
        if handled:
            self.say(handled)
            return
        filename = None
        m = re.search(r"\b(\w+\.(?:py|js|html|css|java|c|cpp|md|json|csv|xml))\b", cmd)
        if m:
            filename = m.group(1)
        topic = cmd
        for p in ["write code for", "write a code for", "write code in",
                    "save code to", "put code in", "paste code in",
                    "write a program for", "write program for",
                    "write a calculator in", "write calculator in",
                    "make a calculator in", "create a calculator in",
                    "write a calculator code in", "generate code for",
                    "write code", "write a code", "code a",
                    "develop a", "develop an", "develop",
                    "compose a", "compose an", "compose",
                    "draft a", "draft an", "draft",
                    "assemble a", "assemble an", "assemble",
                    "implement a", "implement an", "implement",
                    "design a", "design an", "design",
                    "build me a", "build me an", "build a", "build an",
                    "make me a", "make me an", "make a", "make an",
                    "create me a", "create me an", "create a", "create an",
                    "write me a", "write me an", "write a", "write an",
                    "generate a", "generate an", "generate"]:
            if p in topic:
                topic = re.sub(r"\b" + re.escape(p) + r"\b", " ", topic, flags=re.IGNORECASE)
                break
        topic = re.sub(r"\b(in|to|into|file|code|script|program|for|and|my|the|a|an|"
                       r"write|generate|create|save|put|build|develop|compose|draft|"
                       r"assemble|implement|design|python|javascript|html|java|c\+\+|"
                       r"that|which|please|sir|boss|me|your)\b",
                       " ", topic, flags=re.IGNORECASE)
        topic = " ".join(topic.split()).strip(" .,")
        if not filename:
            if topic:
                filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".py"
            else:
                filename = "generated_code.py"
            if re.search(r"\bjavascript|\.js\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".js"
            elif re.search(r"\bhtml\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".html"
            elif re.search(r"\bjava\b", cmd, re.I) and "javascript" not in cmd.lower():
                filename = filename.rsplit(".", 1)[0] + ".java"
            elif re.search(r"\bc\+\+|\.cpp\b", cmd, re.I):
                filename = filename.rsplit(".", 1)[0] + ".cpp"
        filename = self._safe_filepath(filename)
        self._set_state("thinking")
        self.say(f"Generating code for {topic or 'your request'} and saving to {filename}, sir.")
        lang = "Python" if filename.endswith(".py") else \
               "JavaScript" if filename.endswith(".js") else \
               "HTML" if filename.endswith(".html") else \
               "Java" if filename.endswith(".java") else \
               "C++" if filename.endswith(".cpp") else "code"
        content = self._ask_ai(
            f"Write complete, working {lang} code for: {topic or 'a general purpose program'}. "
            "Output ONLY the code, no explanation, no code fences, no markdown. "
            "Make it runnable and complete.")
        if not content:
            self.say("I could not generate the code, sir.")
            return
        code = content.strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
        code = self._strip_code_chatter(code)
        try:
            filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code + "\n")
            self.say(f"Code has been saved to {filename}, sir. File is at {filepath}.")
        except Exception as e:
            self.say(f"Could not write to {filename}, sir: {e}")

    def _is_build_website(self, cmd):
        return any(p in cmd for p in [
            "build me a website", "build a website", "make me a website",
            "make a website", "create me a website", "create a website",
            "build website", "make website", "create website",
            "website about", "website for",
            "build me an app", "build an app", "make me an app",
            "make an app", "create me an app", "create an app",
            "build app", "make app", "create app",
            "build me an application", "build an application",
            "make me an application", "make an application",
            "create me an application", "create an application",
            "build application", "make application", "create application",
            "app about", "app for", "application about", "application for",
            "build me android", "build android", "make me android",
            "make android", "create android", "build android app",
            "make android app", "create android app",
            "mobile app", "mobile application",
            "android app", "android application",
            "build me a mobile", "build a mobile", "make me a mobile",
            "make a mobile", "create a mobile",
        ])

    def _is_app_request(self, cmd):
        return any(p in cmd for p in [
            "app", "application", "android", "mobile",
        ]) and not any(p in cmd for p in [
            "website", "web", "site", "html", "webpage",
        ])

    def _website_topic(self, cmd):
        for p in ["build me a website", "make me a website", "create me a website",
                  "build a website", "make a website", "create a website",
                  "build me an app", "make me an app", "create me an app",
                  "build an app", "make an app", "create an app",
                  "build me an application", "make me an application",
                  "create me an application", "build an application",
                  "make an application", "create an application",
                  "build me android", "build android", "make me android",
                  "make android", "create android", "build android app",
                  "make android app", "create android app",
                  "build me a mobile", "build a mobile", "make me a mobile",
                  "make a mobile", "create a mobile",
                  "build me a", "make me a", "create me a",
                  "build a", "make a", "create a",
                  "build", "make", "create",
                  "website", "app", "application", "android"]:
            if p in cmd:
                cmd = cmd.replace(p, " ")
                break
        topic = " ".join(cmd.split()).strip(" .,")
        for w in ("about", "for", "on"):
            if topic == w or topic.startswith(w + " "):
                topic = topic[len(w):].strip()
        low = topic.lower()
        for art in ("a ", "an ", "the ", "n "):
            if low.startswith(art):
                topic = topic[len(art):].strip()
                low = topic.lower()
                break
        return topic or "yourself"

    def build_website(self, topic, kind=None):
        self._set_state("thinking")
        is_app = (kind == "app") if kind else self._is_app_request(topic)
        if is_app:
            self.say("Preparing an Android app prompt for Google AI Studio, sir.")
            prompt = self._app_prompt(topic)
        else:
            self.say("Preparing a prompt for Google AI Studio, sir.")
            prompt = self._website_prompt(topic)
        if not prompt:
            return
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except Exception:
            pass
        if is_app:
            self.say("Taking you to Google AI Studio to build this Android app, sir.")
        else:
            self.say("Taking you to Google AI Studio to build this, sir.")
        opened = open_aistudio_build(prompt, is_app)
        if not opened:
            self.say("I couldn't open the browser, sir. Your prompt is on the clipboard — "
                     "open aistudio.google.com, press New App, and paste it in.")
            return
        _short_wait(5)
        if is_app:
            if self._aistudio_automate_app(prompt):
                self.say("I've opened the Android app builder with your prompt, sir. "
                         "The preview is generating on the right now.")
            else:
                self.say("I've opened the Android app builder with your prompt pre-filled, sir. "
                         "Press Run prompt and the preview will appear.")
        else:
            if self._aistudio_automate(prompt, "web"):
                self.say("I've opened the app builder with your prompt, sir. "
                         "The preview is generating on the right now.")
            else:
                self.say("I've opened the app builder with your prompt pre-filled, sir. "
                         "Press Run prompt and the preview will appear.")

    def _ask_build_kind(self):
        try:
            answer = self.listen(timeout=2, phrase_limit=4)
        except Exception:
            answer = ""
        answer = (answer or "").lower()
        if any(w in answer for w in ("full", "application", "app")):
            if not any(w in answer for w in ("website", "web", "site")):
                return "app"
        return "web"

    def _default_website_prompt(self, topic):
        return (
            "Create a complete single-file HTML website about %s. Include embedded "
            "CSS and JavaScript, a modern responsive layout, tasteful colors, a "
            "navigation bar, a hero section, several content sections, and a "
            "contact/footer area. Make it professional, polished, and ready to use."
            % topic
        )

    def _website_prompt(self, topic):
        ask = (
            "Write a single detailed prompt to paste into Google AI Studio so Gemini "
            f"creates a polished website about {topic}. The prompt must request a "
            "complete single-file HTML page with embedded CSS and JavaScript, a modern "
            "responsive layout, tasteful colors, and a professional look. Output ONLY "
            "the prompt text itself, no quotes, no code fences, no explanation."
        )
        raw = self._ask_ai(ask)
        if raw == "__UNAUTHORIZED__":
            self.say("That key was rejected too, sir. Please double check it on groq dot com.")
            return self._default_website_prompt(topic)
        if raw is None:
            return self._default_website_prompt(topic)
        if raw.startswith("I hit an error"):
            return self._default_website_prompt(topic)
        raw = raw.strip().strip('"').strip("'")
        if len(raw) < 40 or not any(w in raw.lower() for w in
                                   ("website", "html", "page", "site")):
            return self._default_website_prompt(topic)
        return raw

    def _default_app_prompt(self, topic):
        return (
            "Create a complete, functional Android mobile application about %s. "
            "Include a modern Material Design UI with navigation, multiple screens, "
            "buttons, text fields, images, and proper layout. The app should be "
            "fully working with Kotlin or Java. Include all necessary activities, "
            "layouts, and resources. Make it professional and ready to run."
            % topic
        )

    def _app_prompt(self, topic):
        ask = (
            "Write a single detailed prompt to paste into Google AI Studio so Gemini "
            f"creates a polished Android mobile application about {topic}. The prompt "
            "must request a complete working Android app with Material Design, "
            "multiple screens, navigation, and all necessary code. Output ONLY "
            "the prompt text itself, no quotes, no code fences, no explanation."
        )
        raw = self._ask_ai(ask)
        if raw == "__UNAUTHORIZED__":
            self.say("That key was rejected too, sir. Please double check it on groq dot com.")
            return self._default_app_prompt(topic)
        if raw is None:
            return self._default_app_prompt(topic)
        if raw.startswith("I hit an error"):
            return self._default_app_prompt(topic)
        raw = raw.strip().strip('"').strip("'")
        if len(raw) < 40:
            return self._default_app_prompt(topic)
        return raw

    def _aistudio_js_type(self, kind):
        if kind == "app":
            labels = ("'full-stack app','full stack app','fullstack app',"
                      "'build a full-stack app','real app','build an app',"
                      "'full-stack','full stack','app'")
        else:
            labels = ("'web app','website','build a website','build a web app',"
                      "'create a website','web app preview','web'")
        js = ("const STEP='TYPE';(()=>{const labels=[" + labels + "];"
              "const els=document.querySelectorAll('button,a,[role=button],[role=radio],"
              "[role=tab],[role=menuitem],label');"
              "for(const el of els){const t=(el.getAttribute('aria-label')||el.textContent||'')"
              ".trim().toLowerCase();if(labels.indexOf(t)>=0&&el.offsetParent!==null)"
              "{el.click();return 'clicked';}}"
              "const all=document.querySelectorAll('div,span,button,a,[role=button]');"
              "for(const el of all){const t=(el.textContent||'').trim().toLowerCase();"
              "if(el.textContent.length<60&&el.offsetParent!==null"
              "&&labels.some(l=>t===l||t.indexOf(l+' ')==0)){el.click();return 'clicked-fuzzy';}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_automate(self, prompt, kind):
        self._activate_default_browser()
        _short_wait(5)
        for attempt in range(3):
            if self._aistudio_js_type(kind):
                break
            time.sleep(1.5)
        time.sleep(2)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)
        return False

    def _aistudio_js_click_android_build(self):
        js = ("const STEP='ANDROID';(()=>{const labels=["
              "'build an android app','build android app','android app',"
              "'build an app','build app','create an app',"
              "'build a full-stack app','full-stack app','fullstack app',"
              "'build a full-stack','full stack app','full stack',"
              "'build an application','build application',"
              "'mobile app','android','app'];"
              "const els=document.querySelectorAll('button,a,[role=button],"
              "[role=radio],[role=tab],[role=menuitem],label,div,span');"
              "for(const el of els){const t=(el.getAttribute('aria-label')"
              "||el.textContent||'').trim().toLowerCase();"
              "if(el.offsetParent!==null&&labels.some(l=>t===l||t.indexOf(l+' ')==0))"
              "{el.click();return 'clicked-'+t;}}"
              "return 'missing';})()")
        res = self._aistudio_js_exec(js)
        return bool(res and "clicked" in res)

    def _aistudio_automate_app(self, prompt):
        self._activate_default_browser()
        _short_wait(5)
        for attempt in range(3):
            if self._aistudio_js_click_android_build():
                break
            time.sleep(1.5)
        time.sleep(2)
        if self._aistudio_js_insert(prompt):
            time.sleep(0.8)
            for attempt in range(3):
                if self._aistudio_js_run():
                    return True
                time.sleep(1.5)
        return False

    # ================================================================
    # Command processing
    # ================================================================
    def _process(self, cmd):
        """Route commands through brain and AI."""
        self._set_state("thinking")
        self._show_toast("Processing...", duration=5000)
        try:
            cmd_lower = cmd.lower().strip()

            # --- Jarvis prefix stripping ---
            m_j = re.match(r"^(?:hey\s+)?jarvis\s*[,.!?\s]+\s*(.+)$", cmd_lower, re.I)
            if m_j:
                cmd_lower = m_j.group(1).strip()
                cmd = cmd_lower

            # --- Split compound commands ---
            clauses = self._split_commands(cmd_lower)
            if len(clauses) > 1:
                for c in clauses:
                    self._process(c)
                return
            cmd_lower = clauses[0]
            cmd = cmd_lower

            # Wake/sleep
            if re.search(r"\bwake(\s*up)?\b", cmd_lower) or \
                    re.fullmatch(r"\s*(hey\s+)?jarvis\s*[!.]?\s*", cmd_lower):
                self.awake = True
                self.say("Yes sir, I am awake. Now proceed.")
                return

            if any(w in cmd_lower for w in ["go to sleep", "sleep mode", "standby",
                                            "power down", "goodnight"]) \
                    or re.fullmatch(r"\s*sleep\s*[.!]?\s*", cmd_lower):
                self.awake = False
                self.say("Entering standby, sir. Say wake up jarvis when you need me.")
                return

            # Wake word toggle (always-on "Hey Jarvis" listening)
            wl = cmd_lower.strip()
            if "wake word" in wl or "hey jarvis mode" in wl or "hands free" in wl:
                if any(w in wl for w in ["off", "stop", "disable", "turn off"]):
                    self._stop_wake_word()
                    self.say("Wake word off, sir. Push-to-talk only.")
                elif any(w in wl for w in ["on", "start", "enable", "turn on"]):
                    self.wake_word_enabled = True
                    self._wake_thread = threading.Thread(
                        target=self._wake_listen_loop, daemon=True)
                    self._wake_thread.start()
                    self.say("Wake word on. Just say 'Hey Jarvis' and then your command.")
                else:
                    self._toggle_wake_word()
                return

            # Model picker (Clicky-style): "use model ..." / "switch model"
            if ("use model" in wl or "switch model" in wl or "set model" in wl
                    or "change model" in wl or "activate model" in wl
                    or wl.startswith("model ") or wl in ("list models",
                                                         "which model",
                                                         "what model")):
                self._set_model(wl)
                return

            # TTS voice picker: "change voice" / "use male/female voice"
            if "voice" in wl and any(w in wl for w in
                    ("change", "switch", "set", "use", "different", "male",
                     "female", "upper", "deep", "pick")):
                self._change_voice(wl)
                return

            # Future time intent (must precede general time intent)
            if self._future_time_intent(cmd_lower):
                self._handle_future_time(cmd_lower)
                return

            # Quick shortcuts
            if cmd_lower.strip() in ("history", "voice history", "command history"):
                self._show_voice_history()
                return
            if cmd_lower.strip() in ("help", "commands", "what can you do",
                                     "show commands", "list commands"):
                self._show_help()
                return

            # Time/date
            if self._time_intent(cmd_lower):
                self._handle_time(cmd_lower)
                return
            if self._date_intent(cmd_lower):
                now = datetime.datetime.now().strftime("%A, %B %d, %Y")
                self.say(f"Today is {now}.")
                return

            # Battery
            if self._battery_intent(cmd_lower):
                self._handle_battery(cmd_lower)
                return

            # Define
            if self._is_define(cmd_lower):
                self._handle_define(cmd_lower)
                return

            # System actions (volume, etc.)
            if self._system_action(cmd_lower):
                return

            # API key
            if self._is_api_key(cmd_lower):
                self.set_api_key()
                return

            # Clear memory
            if self._is_clear_memory(cmd_lower):
                if "all" in cmd_lower.split() and "clear all" in cmd_lower:
                    self._app_history.clear()
                    self.history.clear()
                    self.say("All per-app memory cleared, sir. I am running clean.")
                else:
                    app = self._frontmost_app_name()
                    self._app_history.pop(app, None)
                    self.history.clear()
                    self.say(f"Cleared memory for {app}, sir. I am running clean.")
                return

            # Repeat last
            if self._is_repeat(cmd_lower):
                if self.last_reply:
                    self.say(self.last_reply)
                else:
                    self.say("I have not said anything yet, sir.")
                return

            # App context (Clicky-style per-app memory)
            if any(p in cmd_lower for p in
                   ("what context", "which app", "what app am i in",
                    "what app am i on", "context", "where are we")):
                app = self._frontmost_app_name()
                turns = len(self._app_memory())
                self.say(f"I am tracking memory for {app}, with the last "
                         f"{turns * 2} of our conversation. Context stays "
                         f"separate per app, sir.")
                return

            # ========================================================
            # POWER FEATURES routing
            # ========================================================

            # Website/app building
            br = parse_build_request(cmd_lower)
            if br:
                self.build_website(br["topic"], br["kind"])
                return

            # Research write
            if self._is_research_write(cmd_lower):
                self._handle_research_write(cmd_lower)
                return

            # Code write
            if self._is_code_write(cmd_lower):
                self._handle_code_write(cmd_lower)
                return

            # List files (before brain priority so the brain's list_files skill
            # does not intercept this explicit command).
            if any(w in cmd_lower for w in ["list files", "show files", "what files"]):
                self._handle_list_files(cmd)
                return

            # Weather (exact-match shortcuts first, then rich weather intent)
            if cmd_lower.strip() in ("weather", "what's the weather",
                                     "whats the weather", "weather today",
                                     "current weather"):
                self._get_weather()
                return

            # Open something (bare app/website names and "go to X" included)
            if self._is_open(cmd_lower):
                self._handle_open(cmd)
                return

            # Brain skill match (priority)
            brain = self._get_brain()
            try:
                hit = brain.think(cmd, priority=True)
            except Exception:
                hit = None
            if hit:
                skill, ctx = hit
                self._set_state("thinking")
                try:
                    out = skill.execute(self, ctx)
                except Exception:
                    out = None
                if out and not self._is_placeholder_reply(out):
                    self.last_reply = out
                    mem = self._app_memory()
                    mem.append({"role": "user", "content": cmd_lower})
                    mem.append({"role": "assistant", "content": out})
                    self.say(out)
                    return

            if self._weather_intent(cmd_lower):
                self._handle_weather(cmd_lower)
                return

            # File operations (create / read / delete / rename)
            if re.search(r"\b(delete|remove)\s+(?:the\s+)?file\b", cmd_lower):
                self.file_delete(cmd)
                return
            if re.search(r"\brename\s+(?:the\s+)?file\b", cmd_lower):
                self.file_rename(cmd)
                return
            if re.search(r"\b(read|show|view|cat|open)\s+(?:the\s+)?"
                         r"(?:contents\s+of\s+)?(?:text\s+)?file\b", cmd_lower):
                self.file_read(cmd)
                return
            if re.search(r"\b(create|make)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?file\b"
                         r"|\bnew\s+file\b", cmd_lower):
                self.file_create(cmd)
                return

            # Code execution
            if re.search(r"\b(run|execute)\s+python\b", cmd_lower):
                self.run_python_code(cmd)
                return
            if re.search(r"\b(run|execute)\s+(?:the\s+)?script\b", cmd_lower):
                self.execute_script(cmd)
                return
            if re.search(r"\b(run|execute)\s+(?:a\s+|the\s+)?shell\s+(?:command|cmd)\b",
                         cmd_lower):
                self.run_shell_command(cmd)
                return

            # Reminders and calendar
            if re.search(r"\bremind me\b", cmd_lower):
                self.set_reminder(cmd)
                return
            if re.search(r"\badd\b.*\b(?:event|appointment|meeting)\b", cmd_lower) \
                    or re.search(r"\b(schedule|add)\s+(?:an?\s+)?(?:new\s+)?"
                                 r"(?:event|appointment|meeting)\b", cmd_lower):
                self.calendar_add(cmd)
                return
            if re.search(r"\bcalendar\b|\bmy (?:schedule|events)\b|\bupcoming events\b",
                         cmd_lower):
                self.calendar_list(cmd)
                return

            # Email drafting
            if re.search(r"\b(draft|compose|prepare|write)\s+me\s+(?:an?\s+)?email\b", cmd_lower):
                self.draft_email(cmd)
                return

            # Translation
            if re.search(r"\btranslate\b|\bhow (?:do|to|would) (?:you|i|we) say\b"
                         r"|\bwhat does\b.+\bmean\b", cmd_lower):
                self.translate_text(cmd)
                return

            # QR code generation
            if re.search(r"\bqr\s*-?\s*code\b", cmd_lower):
                self.generate_qr(cmd)
                return

            # Color tool
            if re.search(r"\bcolou?r\b", cmd_lower) \
                    or re.search(r"\b[0-9a-fA-F]{6}\b", cmd) \
                    or re.search(r"\b(?:nice|pretty|random)\s+(?:red|orange|yellow|green|"
                                 r"teal|cyan|blue|purple|pink|brown|gray|grey|black|white)\b",
                                 cmd_lower):
                res = self.color_info(cmd)
                if res:
                    self.say(res)
                    return

            # Search
            if self._is_search(cmd_lower):
                self._handle_search(cmd_lower)
                return

            # YouTube playback
            if self._play_youtube(cmd_lower):
                return

            # Calculator (richer pattern matching)
            if self._calc_intent(cmd_lower):
                return

            # Unit conversion (richer pattern matching)
            if self._convert_intent(cmd_lower):
                return

            # Timer / countdown
            if self._timer_intent(cmd_lower):
                self._handle_timer(cmd_lower)
                return

            # Fix screen commands
            if any(w in cmd_lower for w in ["fix this", "fix the error", "fix my screen",
                                             "fix what you see", "fix the screen",
                                             "fix the bug", "fix the issue",
                                             "help me fix", "can you fix"]):
                self._handle_fix_screen(cmd)
                return

            # Screen queries
            if any(w in cmd_lower for w in ["what's on my screen", "what is on my screen",
                                             "read my screen", "see my screen",
                                             "what am i looking at", "look at my screen",
                                             "screenshot", "take a screenshot",
                                             "describe my screen", "describe what you see",
                                             "read this page", "read the page",
                                             "look at this page", "analyze my screen",
                                             "analyze my display", "what do you see"]):
                self._handle_screen_query(cmd)
                return

            # Cursor pointing
            if any(w in cmd_lower for w in ["point to", "show me where", "find the",
                                             "where is", "click on", "locate"]):
                self._handle_point_query(cmd)
                return

            # Brain skill match (general)
            brain = self._get_brain()
            hit = brain.think(cmd)
            if hit:
                skill, ctx = hit
                out = skill.execute(self, ctx)
                if out and not self._is_placeholder_reply(out):
                    self.say(out)
                    return

            # LLM fallback
            reply = self._ask_ai_safely(cmd)
            if reply:
                sources = web_search(cmd) if _is_web_worthy(cmd) else []
                if sources:
                    self._say_cited(reply, sources)
                else:
                    self.say(reply)
            else:
                self.say("I could not process that, sir.")
        except Exception as e:
            print("BOT PROCESS ERROR:", e)
            self.say("Something went wrong handling that, sir.")
        finally:
            self._set_state("idle")

    @staticmethod
    def _is_placeholder_reply(out):
        """Detect skill replies that really mean 'I need the LLM for this'."""
        s = str(out).strip().lower()
        return s.startswith((
            "i could not reach my language model",
            "local_fallback",
            "that is beyond my local memory",
        ))

    # ================================================================
    # Screen vision
    # ================================================================
    def _take_screenshot(self):
        if privacy_guard_blocked():
            self._show_toast("🔒 Privacy guard: won't capture that window",
                             duration=3000)
            return None, None
        try:
            import pyautogui
            img = pyautogui.screenshot()
            self._last_screenshot = img
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return img, b64
        except Exception as e:
            self._show_toast(f"Screenshot failed: {e}", duration=3000)
            return None, None

    def _ask_vision(self, b64_image, question):
        api_key = load_api_key()
        if not api_key:
            return "I need an API key for vision, sir. Say 'set api key'."
        try:
            resp = requests.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_VISION_MODEL,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "text", "text": question},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{b64_image}"
                            }}
                        ]}
                    ],
                    "max_tokens": 1024,
                },
                timeout=30,
            )
            data = resp.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            return "Could not analyze the screen, sir."
        except Exception as e:
            return "Vision request failed: " + str(e)

    def _handle_screen_query(self, cmd):
        self._show_toast("📸 Capturing screen...", duration=3000)
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("Could not capture screen.")
            return
        low = (cmd or "").lower()
        if "read" in low and ("page" in low or "screen" in low):
            question = ("Read the text visible on this screen. Transcribe the main "
                        "content, then summarize what this page is in one sentence.")
        else:
            question = "Describe everything visible on this screen in detail."
        answer = self._ask_vision(b64, question)
        self.say(answer)

    def _handle_point_query(self, cmd):
        """Find a UI element on screen by text/description, show pointer, and optionally click.

        If the command starts with 'click on' or 'click', it will also click the element.
        Otherwise it just points to it.
        """
        cmd_lower = cmd.lower().strip()
        should_click = cmd_lower.startswith("click on ") or cmd_lower.startswith("click ")
        # Extract what to find
        target = cmd
        for prefix in ("click on ", "click ", "point to ", "show me where ",
                        "find the ", "where is ", "locate "):
            if cmd_lower.startswith(prefix):
                target = cmd[len(prefix):].strip()
                break
        if not target:
            self.say("What should I find, sir?")
            return
        self._show_toast(f"📸 Finding '{target}' on screen...", duration=3000)
        img, b64 = self._take_screenshot()
        if not b64:
            self.say("Could not capture screen.")
            return
        question = (f"Find the UI element: '{target}'. Return ONLY the approximate "
                     f"pixel coordinates (x, y) of its center, like: 450, 320")
        answer = self._ask_vision(b64, question)
        coords = re.findall(r"(\d{1,5})\s*,\s*(\d{1,5})", answer)
        if coords:
            x, y = int(coords[0][0]), int(coords[0][1])
            self._show_pointer(x, y)
            if should_click:
                self._click_at(x, y)
                self.say(f"Clicked '{target}' at {x}, {y}.")
            else:
                self.say(f"Found '{target}' at coordinates {x}, {y}.")
        else:
            self.say(answer)

    def _show_pointer(self, x, y):
        self._ui(lambda: self._show_pointer_ui(x, y))

    @staticmethod
    def _clamp_pointer_to_display(x, y, size=80):
        """Top-left for a *size* halo centered on (x, y), kept inside the
        display that owns the point.

        Uses ``multi_monitor.display_for_point`` when importable so the halo
        never straddles onto a neighbouring display or off-screen; without
        that module this is the historic unclamped placement.
        """
        px, py = int(x) - size // 2, int(y) - size // 2
        try:
            import multi_monitor
            disp = multi_monitor.display_for_point(x, y)
        except Exception:
            disp = None
        if not disp:
            return px, py
        try:
            dx = int(disp.get("x", 0))
            dy = int(disp.get("y", 0))
            dw = int(disp.get("width", 0))
            dh = int(disp.get("height", 0))
        except Exception:
            return px, py
        if dw <= 0 or dh <= 0:
            return px, py
        px = max(dx, min(px, dx + dw - size))
        py = max(dy, min(py, dy + dh - size))
        return px, py

    def _show_pointer_ui(self, x, y):
        if self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.85)
        size = 80
        px, py = self._clamp_pointer_to_display(x, y, size)
        win.geometry(f"{size}x{size}+{px}+{py}")
        c = None
        try:
            c = tk.Canvas(win, width=size, height=size, bg="",
                          highlightthickness=0)
        except Exception:
            # Some WMs reject an empty colour name; never lose the halo.
            c = tk.Canvas(win, width=size, height=size,
                          bg="#0d1117", highlightthickness=0)
        c.pack()
        c.create_oval(4, 4, size - 4, size - 4, outline="#ff4444", width=3)
        c.create_oval(14, 14, size - 14, size - 14, outline="#ff4444", width=2)
        c.create_text(size // 2, size // 2, text="X", fill="#ff4444",
                      font=("Helvetica Neue", 16, "bold"))
        self._overlay = win
        # Pulsing halo: Clicky-style ring that breathes while explaining.
        try:
            rings = [c.create_oval(4, 4, size - 4, size - 4,
                                   outline="#ff4444", width=3)]
            state = {"phase": 0}

            def _pulse():
                if not self._overlay is win:
                    return
                state["phase"] = (state["phase"] + 1) % 6
                r = 4 + state["phase"] * 2
                c.coords(rings[0], r, r, size - r, size - r)
                c.itemconfigure(rings[0],
                                width=5 - state["phase"] // 2)
                win.after(90, _pulse)

            _pulse()
        except Exception:
            pass
        win.after(6000, lambda: self._hide_pointer())

    def _hide_pointer(self):
        if self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None

    # ================================================================
    # File operations
    # ================================================================
    def _handle_file_write(self, cmd):
        self._show_toast("✍ Generating code...", duration=10000)
        m = re.search(r"(\w+\.(?:py|js|html|css|java|c|cpp|md|json|txt|csv|xml))", cmd)
        filename = m.group(1) if m else None
        prompt = (f"Write complete, working code for: {cmd}. "
                   "Output ONLY the code, no explanation, no markdown fences.")
        code = self._ask_ai(prompt)
        if not code:
            self.say("Could not generate code.")
            return
        code = code.strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\n?", "", code)
            code = re.sub(r"\n?```$", "", code)
        if not filename:
            topic = re.sub(r"\b(write|create|generate|code|make|build|in|to|file|program|"
                           r"for|and|my|the|a|an|python|javascript|html)\b", " ", cmd, flags=re.I)
            topic = " ".join(topic.split()).strip(" .,") or "generated_code"
            filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".py"
        filename = sanitize_filename(filename, default_ext=".py")
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code + "\n")
            self.say(f"Code saved to {filename}.")
        except Exception as e:
            self.say(f"Could not write file: {e}")

    def _handle_research(self, cmd):
        self._show_toast("🔍 Researching...", duration=10000)
        topic = re.sub(r"\b(research|write notes?|write about|research and write)\b",
                        " ", cmd, flags=re.I)
        topic = " ".join(topic.split()).strip(" .,")
        if not topic:
            self.say("What should I research about?")
            return
        prompt = (f"Write a comprehensive research report about {topic}. "
                   "Include key facts. At least 300 words.")
        content = self._ask_ai(prompt)
        if not content:
            self.say("Could not generate research.")
            return
        filename = re.sub(r"[^a-zA-Z0-9]+", "_", topic[:30]).strip("_").lower() + ".txt"
        filename = sanitize_filename(filename, default_ext=".txt")
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Research Report: {topic.title()}\n{'=' * 50}\n\n{content}\n")
            self.say(f"Research saved to {filename}.")
        except Exception as e:
            self.say(f"Could not write file: {e}")

    def _handle_build(self, cmd):
        """Handle voice 'build website/app' commands with full AI Studio automation."""
        self._show_toast("Preparing prompt...", duration=5000)
        cmd_lower = cmd.lower()
        is_app = any(w in cmd_lower for w in ["app", "application", "android", "mobile"]) \
            and not any(w in cmd_lower for w in ["website", "web", "site", "html"])
        if is_app:
            prompt = self._ask_ai(
                f"Write a detailed prompt to paste into Google AI Studio so Gemini "
                f"creates a polished Android mobile application for: {cmd}. "
                f"Output ONLY the prompt text."
            )
        else:
            prompt = self._ask_ai(
                f"Write a detailed prompt to paste into Google AI Studio so Gemini "
                f"creates a polished website for: {cmd}. Output ONLY the prompt text."
            )
        if not prompt:
            self.say("Could not generate prompt.")
            return
        try:
            import pyperclip
            pyperclip.copy(prompt)
        except Exception:
            pass
        self.say("Opening Google AI Studio, sir.")
        webbrowser.open("https://aistudio.google.com/")
        _short_wait(5)
        if self._smart_click_in_aistudio(prompt):
            self.say("Your prompt is on the clipboard and in Google AI Studio "
                     "building now, sir.")
        else:
            self.say("I have your prompt on the clipboard. Paste it into "
                     "Google AI Studio and press Enter.")

    def _handle_list_files(self, cmd):
        d = os.path.dirname(os.path.abspath(__file__))
        files = sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
        listing = ", ".join(files[:20])
        self.say(f"Files: {listing}")

    def _handle_open(self, cmd):
        """Open URLs or apps."""
        m = re.search(r"(https?://\S+)", cmd)
        if m:
            webbrowser.open(m.group(1))
            self.say("Opening link.")
            return
        m = re.search(r"(?:open|launch)\s+(.+)", cmd, re.I)
        if m:
            what = m.group(1).strip()
            # Known websites open directly in the browser
            target = re.sub(r"^(?:the|a|an)\s+", "", what,
                            flags=re.I).strip(" .,!").lower()
            if target in WEBSITES:
                self.say(f"Opening {target}.")
                webbrowser.open(WEBSITES[target])
                return
            for name, url in WEBSITES.items():
                if re.search(r"\b" + re.escape(name) + r"\b", what.lower()):
                    self.say(f"Opening {name}.")
                    webbrowser.open(url)
                    return
            # Known apps map to their real application names, exactly like
            # chat mode: "open calculator" must launch Calculator, not fall
            # through to a web search for the lowercase bundle name.
            for key, app_name in APP_MAP.items():
                if re.search(r"\b" + re.escape(key) + r"\b", what.lower()):
                    if open_app(app_name):
                        self.say(f"Opening {app_name}.")
                    else:
                        self.say(f"I could not find {app_name}, sir. "
                                 "Searching the web for it instead.")
                        webbrowser.open("https://www.google.com/search?q="
                                        + app_name.replace(" ", "+"))
                    return
            if open_app(what):
                self.say(f"Opening {what}.")
            else:
                self.say(f"I could not find {what}, sir. Searching the web for it instead.")
                webbrowser.open("https://www.google.com/search?q=" + what.replace(" ", "+"))
            return
        self.say("What should I open?")

    # ---------------- bare-name / "go to X" open targets (parity with chat) ----
    def _is_open(self, cmd):
        # "open X" or "go to X" at the start; or a bare website/app name
        if re.match(r"^(?:open|go\s+to|launch)\b", cmd):
            return True
        return self._bare_name(cmd) is not None

    def _bare_name(self, cmd):
        c = cmd.strip(" .,")
        if not c or c.lower() in ("open", "go to", "launch"):
            return None
        m = self._match_website(c)
        if m and m[0] == c:
            return ("website", m[0], m[1])
        for key, app in APP_MAP.items():
            if c == key:
                return ("app", key, app)
        return None

    def _open_target(self, kind, name, target):
        if kind == "website":
            self.say(f"Opening {name}.")
            webbrowser.open(target)
            return
        if open_app(target):
            self.say(f"Opening {target}.")
        else:
            self.say(f"I could not find {target}, sir.")

    def _fuzzy_target(self, rest):
        close_web = difflib.get_close_matches(rest, list(WEBSITES), n=1, cutoff=0.7)
        if close_web:
            name = close_web[0]
            return ("website", name, WEBSITES[name])
        close_app = difflib.get_close_matches(rest, list(APP_MAP), n=1, cutoff=0.7)
        if close_app:
            key = close_app[0]
            return ("app", key, APP_MAP[key])
        return None

    # ================================================================
    # POWER FEATURES — files, code exec, calendar, reminders,
    # translation, unit conversion, colors, QR codes, email drafts
    # ================================================================
    def _data_dir(self):
        return os.path.dirname(os.path.abspath(__file__))

    # ---------------- shared file helpers ----------------
    def _extract_filename(self, cmd):
        """Pull a filename out of a spoken command like 'read file notes.txt'."""
        m = re.search(r"\bfile\s+(?:called\s+|named\s+)?(.+?)\s*[.?!]*$", cmd, re.I)
        if m:
            name = m.group(1).strip().strip("\"'").strip()
        else:
            m2 = re.search(r"[\w.\-]+\.(?:txt|md|json|csv|py|js|ts|html|css|xml|"
                           r"yaml|yml|log|ini|cfg|sh)\b", cmd, re.I)
            name = m2.group(0).strip() if m2 else ""
        name = re.sub(r"\s+dot\s+", ".", name, flags=re.I)
        name = re.sub(r"\s+(please|now|for me)$", "", name, flags=re.I)
        return name or None

    def _resolve_file(self, name, default_ext=".txt"):
        """Turn a spoken filename into a safe path inside the project dir."""
        if not name:
            return None
        name = str(name).strip().strip("\"'`").strip()
        if not name:
            return None
        name = re.sub(r"\s+dot\s+", ".", name, flags=re.I)
        if "." not in os.path.basename(name) and default_ext:
            name += default_ext
        return os.path.join(self._data_dir(),
                            sanitize_filename(name, default_ext=default_ext))

    # ---------------- 1. file operations ----------------
    def file_create(self, cmd):
        """'create file notes.txt with content Hello'"""
        cm = re.search(r"\bwith\s+(?:the\s+)?content\s+(.+?)\s*$", cmd,
                       re.I | re.S)
        content = ""
        head = cmd
        if cm:
            content = cm.group(1).strip().strip("\"'")
            head = cmd[:cm.start()]
        path = self._resolve_file(self._extract_filename(head))
        if not path:
            self.say("What should I call the file, sir?")
            return
        try:
            if os.path.exists(path):
                self.say(f"{os.path.basename(path)} already exists, sir. Overwriting.")
            with open(path, "w", encoding="utf-8") as f:
                f.write((content + "\n") if content else "")
            if content:
                self.say(f"Created {os.path.basename(path)} with your content.")
            else:
                self.say(f"Created empty file {os.path.basename(path)}, sir.")
        except Exception as e:
            self.say(f"Could not create file: {e}")

    def file_read(self, cmd):
        """'read file notes.txt'"""
        path = self._resolve_file(self._extract_filename(cmd))
        if not path:
            self.say("Which file should I read, sir?")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            self.say(f"I could not find {os.path.basename(path)}, sir.")
            return
        except Exception as e:
            self.say(f"Could not read file: {e}")
            return
        if not text:
            self.say(f"{os.path.basename(path)} is empty.")
            return
        self._show_info_window(f"📖 {os.path.basename(path)}", text[:1800])
        spoken = text[:220].replace("\n", " ")
        self.say(f"{os.path.basename(path)} says: {spoken}"
                 + (" ..." if len(text) > 220 else ""))

    def file_delete(self, cmd):
        """'delete file notes.txt'"""
        path = self._resolve_file(self._extract_filename(cmd))
        if not path:
            self.say("Which file should I delete, sir?")
            return
        if not os.path.exists(path):
            self.say(f"{os.path.basename(path)} does not exist, sir.")
            return
        try:
            os.remove(path)
            self.say(f"Deleted {os.path.basename(path)}, sir.")
        except Exception as e:
            self.say(f"Could not delete file: {e}")

    def file_rename(self, cmd):
        """'rename file old.txt to new.txt'"""
        m = re.search(r"rename\s+(?:the\s+)?file\s+(.+?)\s+to\s+(.+?)\s*[.?!]*$",
                      cmd, re.I)
        if not m:
            self.say("Say: rename file old dot txt to new dot txt")
            return
        src = self._resolve_file(m.group(1))
        dst = self._resolve_file(m.group(2))
        if not src or not dst or src == dst:
            self.say("I need both the old and the new file name, sir.")
            return
        if not os.path.exists(src):
            self.say(f"{os.path.basename(src)} does not exist, sir.")
            return
        try:
            os.replace(src, dst)
            self.say(f"Renamed {os.path.basename(src)} to {os.path.basename(dst)}.")
        except Exception as e:
            self.say(f"Could not rename file: {e}")

    # ---------------- 2. code execution ----------------
    _DANGEROUS_SHELL = re.compile(
        r"\b(sudo|rm\s+(-rf|-fr|--recursive)|mkfs|diskutil\s+erase|dd\s+if="
        r"|shutdown|reboot|halt|killall|\bcurl\b[^|]*\|\s*(ba)?sh"
        r"|chmod\s+777\s+/)", re.I)

    def _run_subprocess(self, args, timeout=20):
        """Run a process safely; capture stdout/stderr."""
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout,
                cwd=self._data_dir())
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0:
                msg = err.splitlines()[-1][:200] if err \
                    else f"exit code {proc.returncode}"
                return None, msg
            return out, None
        except subprocess.TimeoutExpired:
            return None, f"timed out after {timeout} seconds"
        except FileNotFoundError:
            return None, "program not found"
        except Exception as e:
            return None, str(e)

    def run_python_code(self, cmd):
        """'run python code print(2+2)'"""
        m = re.search(r"(?:run|execute)\s+python(?:\s+code)?\s*:?\s*(.+?)\s*$",
                      cmd, re.I | re.S)
        code = m.group(1).strip() if m else ""
        if not code:
            self.say("What Python code shall I run, sir?")
            return
        self._show_toast("▶️ Running Python...", duration=4000)
        out, err = self._run_subprocess([sys.executable, "-c", code], timeout=15)
        if err:
            self.say(f"Python error: {err}")
            return
        self._show_info_window("🐍 Python output", out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("It ran cleanly with no output, sir.")

    def execute_script(self, cmd):
        """'execute script foo.py'"""
        m = re.search(r"(?:run|execute)\s+(?:the\s+)?script\s+(.+?)\s*[.?!]*$",
                      cmd, re.I)
        path = self._resolve_file(m.group(1), default_ext=".py") if m else None
        if not path or not os.path.exists(path):
            self.say("I could not find that script, sir.")
            return
        self._show_toast(f"▶️ Running {os.path.basename(path)}...", duration=4000)
        out, err = self._run_subprocess([sys.executable, path], timeout=30)
        if err:
            self.say(f"The script failed: {err}")
            return
        self._show_info_window(f"▶️ {os.path.basename(path)}", out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("The script ran with no output, sir.")

    def run_shell_command(self, cmd):
        """'run shell command ls' — parsed without a shell, denylisted, timed."""
        m = re.search(r"shell\s+(?:command|cmd)\s+(.+?)\s*$", cmd, re.I | re.S)
        raw = m.group(1).strip() if m else ""
        if not raw:
            self.say("Which shell command should I run, sir?")
            return
        if self._DANGEROUS_SHELL.search(raw):
            self.say("That command looks dangerous, sir. I must decline.")
            return
        try:
            args = shlex.split(raw)
        except ValueError:
            args = None
        if not args:
            self.say("I could not parse that command, sir.")
            return
        self._show_toast("$ " + " ".join(args), duration=4000)
        out, err = self._run_subprocess(args, timeout=15)
        if err:
            self.say(f"The command failed: {err}")
            return
        self._show_info_window("$ " + raw, out or "(no output)")
        if out:
            self.say(out[:280] + (" ..." if len(out) > 280 else ""))
        else:
            self.say("The command finished with no output, sir.")

    # ---------------- OS notifications ----------------
    def _notify(self, title, message):
        """Best-effort OS-level notification (macOS/Windows), silent fallback."""
        title = str(title).replace("\\", "").replace('"', "'")
        message = str(message).replace("\\", "").replace('"', "'")
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["osascript", "-e",
                                  f'display notification "{message}" '
                                  f'with title "{title}" sound name "Glass"'])
            elif platform.system() == "Windows":
                try:
                    from plyer import notification
                    notification.notify(title=title, message=message, timeout=8)
                except Exception:
                    pass
        except Exception:
            pass

    # ---------------- 6. reminders ----------------
    _REMINDER_UNITS = {"sec": 1, "secs": 1, "second": 1, "seconds": 1,
                       "min": 60, "mins": 60, "minute": 60, "minutes": 60,
                       "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
                       "day": 86400, "days": 86400}

    def set_reminder(self, cmd):
        """'remind me to call mom in 2 hours' / 'remind me to X at 5pm'"""
        m = re.search(r"remind\s+me\s+(?:to\s+)?(.+?)\s*[.?!]*$", cmd, re.I)
        if not m:
            self.say("Tell me what to remind you about, sir.")
            return
        body = m.group(1).strip()
        delay = None
        when_txt = ""
        dm = re.search(
            r"\bin\s+(\d+(?:\.\d+)?)\s*"
            r"(sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?|days?)\b", body, re.I)
        tm = re.search(
            r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", body, re.I)
        if dm:
            val = float(dm.group(1))
            unit = dm.group(2).lower()
            delay = val * self._REMINDER_UNITS.get(unit, 60)
            when_txt = f"in {dm.group(1)} {unit}" + ("s" if float(dm.group(1)) != 1 and not unit.endswith("s") else "")
        elif tm:
            now = datetime.datetime.now()
            hour = int(tm.group(1))
            minute = int(tm.group(2) or 0)
            ap = (tm.group(3) or "").replace(".", "").lower()
            if ap.startswith("p") and hour < 12:
                hour += 12
            if ap.startswith("a") and hour == 12:
                hour = 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += datetime.timedelta(days=1)
            delay = (target - now).total_seconds()
            when_txt = "at " + target.strftime("%I:%M %p").lstrip("0")
        if delay is None:
            self.say("When should I remind you, sir? For example: in 10 minutes "
                     "or at 5 pm.")
            return
        span = dm if dm else tm
        task = (body[:span.start()].strip() or body[span.end():].strip()
                or "your reminder").strip(" ,.")

        def _fire():
            try:
                self._active_timers.remove(t)
            except Exception:
                pass
            self.say(f"Reminder, sir: {task}.")
            self._show_toast(f"⏰ Reminder: {task}", duration=8000)
            self._notify("JARVIS Reminder", task)

        t = threading.Timer(max(1.0, delay), _fire)
        t.daemon = True
        self._active_timers.append(t)
        t.start()
        self.say(f"Noted, sir. I will remind you to {task} {when_txt}.")

    # ---------------- 5. calendar ----------------
    _WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                 "friday": 4, "saturday": 5, "sunday": 6}

    def _calendar_path(self):
        return os.path.join(self._data_dir(), "jarvis_calendar.json")

    def _load_events(self):
        try:
            with open(self._calendar_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
        except Exception:
            pass
        return []

    def _save_events(self, events):
        try:
            with open(self._calendar_path(), "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2)
        except Exception as e:
            print("CALENDAR SAVE ERROR:", e)

    def _parse_when(self, text):
        """Parse natural-language date/time -> (ISO date, HH:MM or None)."""
        tl = text.lower()
        day = datetime.date.today()
        if "day after tomorrow" in tl:
            day += datetime.timedelta(days=2)
        elif "tomorrow" in tl:
            day += datetime.timedelta(days=1)
        else:
            m = re.search(r"\bin\s+(\d+)\s*(day|week)s?\b", tl)
            if m:
                step = int(m.group(1)) * (7 if m.group(2) == "week" else 1)
                day += datetime.timedelta(days=step)
            else:
                for name, idx in self._WEEKDAYS.items():
                    if re.search(r"\b" + name + r"\b", tl):
                        day += datetime.timedelta(days=(idx - day.weekday()) % 7 or 7)
                        break
        tstr = None
        mtm = (re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?", tl)
               or re.search(r"\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?", tl))
        if mtm and mtm.group(1):
            hour = int(mtm.group(1))
            minute = int(mtm.group(2) or 0)
            ap = (mtm.group(3) or "").replace(".", "").lower()
            if ap.startswith("p") and hour < 12:
                hour += 12
            if ap.startswith("a") and hour == 12:
                hour = 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                tstr = f"{hour:02d}:{minute:02d}"
        return day.isoformat(), tstr

    def calendar_add(self, cmd):
        """'add event meeting at 3pm'"""
        text = re.sub(r"^\s*(?:hey\s+)?(?:jarvis[,:]\s*)?", "", cmd, flags=re.I)
        text = re.sub(r"\badd\s+(?:an?\s+)?(?:new\s+)?"
                      r"(?:event|appointment|meeting)\b[:\s]*", " ", text,
                      flags=re.I)
        text = re.sub(r"\b(?:to|on|in)\s+(?:my\s+)?calendar\b", " ", text, flags=re.I)
        text = re.sub(r"\s{2,}", " ", text).strip(" .,!") or "event"
        date_iso, tstr = self._parse_when(text)
        title = re.sub(r"\b(?:day after tomorrow|tomorrow|today|tonight)\b",
                       " ", text, flags=re.I)
        title = re.sub(r"\bin\s+\d+\s*(?:day|week)s?\b", " ", title, flags=re.I)
        title = re.sub(r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?",
                       " ", title, flags=re.I)
        title = re.sub(r"\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?", " ",
                       title, flags=re.I)
        for wd in self._WEEKDAYS:
            title = re.sub(r"\b" + wd + r"\b", " ", title, flags=re.I)
        title = re.sub(r"\s{2,}", " ", title).strip(" ,.-") or text
        events = self._load_events()
        events.append({"date": date_iso, "time": tstr or "", "title": title})
        events.sort(key=lambda e: (e.get("date", ""), e.get("time", "")))
        self._save_events(events)
        nice = date_iso
        try:
            d = datetime.date.fromisoformat(date_iso)
            nice = d.strftime("%B %d")
            if d.year != datetime.date.today().year:
                nice += f" {d.year}"
        except Exception:
            pass
        when = f"{nice} at {tstr}" if tstr else nice
        self.say(f"Scheduled '{title}' for {when}, sir.")

    def calendar_list(self, cmd):
        """'what's on my calendar'"""
        events = self._load_events()
        today_iso = datetime.date.today().isoformat()
        upcoming = sorted((e for e in events if e.get("date", "") >= today_iso),
                          key=lambda e: (e.get("date", ""), e.get("time", "")))
        if not upcoming:
            self.say("Your calendar is completely clear, sir.")
            return
        lines = [f"{i}. {e.get('date', '?')} "
                 f"{e.get('time') or '--:--'}  —  {e.get('title', '(untitled)')}"
                 for i, e in enumerate(upcoming, 1)]
        self._show_info_window("📅 Upcoming Events", "\n".join(lines) + "\n")
        nxt = upcoming[0]
        when = nxt.get("date", "") + (f" at {nxt['time']}" if nxt.get("time") else "")
        plural = "event" if len(upcoming) == 1 else "events"
        self.say(f"You have {len(upcoming)} upcoming {plural}, sir. "
                 f"Next is {nxt.get('title', 'an event')} on {when}.")

    # ---------------- 4. email draft ----------------
    def draft_email(self, cmd):
        """'draft an email to boss about meeting' -> LLM draft -> clipboard."""
        self._show_toast("✉️ Drafting email...", duration=8000)
        topic = re.sub(
            r"^\s*(?:please\s+)?(?:draft|compose|prepare|write)\s+(?:me\s+)?"
            r"(?:an?\s+)?(?:email\b)?", " ", cmd, flags=re.I)
        topic = topic.replace("email", " ").strip(" .,!") or "a general update"
        content = self._ask_ai(
            f'Draft a short professional email about: "{topic}". '
            "First line must be 'Subject: ...'. Then greeting, concise body, "
            "sign-off. Maximum 130 words. Output only the email.")
        if not content or self._is_placeholder_reply(content):
            content = (f"Subject: {topic.title()}\n\nHi,\n\n"
                       f"I wanted to follow up regarding {topic}. Please let me "
                       "know a good time to discuss.\n\nBest regards,")
        clipped = False
        try:
            import pyperclip
            pyperclip.copy(content)
            clipped = True
        except Exception:
            pass
        suffix = "  (copied to clipboard)" if clipped else ""
        self._show_info_window("✉️ Email Draft" + suffix, content)
        if clipped:
            self.say("Your email draft is ready and copied to the clipboard, sir.")
        else:
            self.say("Your email draft is ready, sir.")

    # ---------------- 7. translation ----------------
    _TRANSLATIONS = {
        "hello": {"spanish": "hola", "french": "bonjour", "german": "hallo",
                  "italian": "ciao", "hindi": "namaste", "japanese": "konnichiwa"},
        "thank you": {"spanish": "gracias", "french": "merci", "german": "danke",
                      "italian": "grazie", "hindi": "dhanyavaad",
                      "japanese": "arigatou"},
        "goodbye": {"spanish": "adiós", "french": "au revoir",
                    "german": "auf wiedersehen", "italian": "arrivederci"},
        "good morning": {"spanish": "buenos días", "french": "bonjour",
                         "german": "guten morgen", "italian": "buongiorno"},
        "good night": {"spanish": "buenas noches", "french": "bonne nuit",
                       "german": "gute nacht", "italian": "buonanotte"},
        "yes": {"spanish": "sí", "french": "oui", "german": "ja", "italian": "sì"},
        "no": {"spanish": "no", "french": "non", "german": "nein", "italian": "no"},
        "please": {"spanish": "por favor", "french": "s'il vous plaît",
                   "german": "bitte", "italian": "per favore"},
        "water": {"spanish": "agua", "french": "eau", "german": "wasser",
                  "italian": "acqua", "hindi": "paani"},
        "friend": {"spanish": "amigo", "french": "ami", "german": "freund",
                   "italian": "amico", "hindi": "dost"},
    }
    _FOREIGN_MEANINGS = {
        "bonjour": "hello (French)", "hola": "hello (Spanish)",
        "gracias": "thank you (Spanish)", "merci": "thank you (French)",
        "danke": "thank you (German)", "ciao": "hello or goodbye (Italian)",
        "namaste": "greetings (Hindi)", "arigato": "thank you (Japanese)",
        "adios": "goodbye (Spanish)", "auf wiedersehen": "goodbye (German)",
        "buenos dias": "good morning (Spanish)",
        "bonsoir": "good evening (French)",
    }
    _LANG_ALIASES = {
        "spanish": "spanish", "espanol": "spanish", "castilian": "spanish",
        "french": "french", "francais": "french", "german": "german",
        "deutsch": "german", "italian": "italian", "hindi": "hindi",
        "japanese": "japanese", "portuguese": "portuguese", "russian": "russian",
        "chinese": "chinese", "korean": "korean", "arabic": "arabic",
        "english": "english",
    }

    def translate_text(self, cmd):
        """'translate hello to Spanish' / 'what does bonjour mean'"""
        m = re.search(r"translate\s+(?:this\s+|that\s+|the\s+)?['\"“”]?(.+?)"
                      r"['\"“”]?\s+(?:to|into|in)\s+([a-zA-Z]+)", cmd, re.I)
        src = target = None
        if not m:
            m = re.search(r"how\s+(?:do|would)\s+(?:you|i|we)\s+say\s+"
                          r"['\"“”]?(.+?)['\"“”]?\s+in\s+([a-zA-Z]+)", cmd, re.I)
        if not m:
            m = re.search(r"what\s+does\s+['\"“”]?(.+?)['\"“”]?\s+mean"
                          r"(?:\s+in\s+([a-zA-Z]+))?", cmd, re.I)
            if m:
                src, target = m.group(1), (m.group(2) or "english")
        if m and src is None:
            src, target = m.group(1), m.group(2)
        if not src or not target:
            self.say("Say: translate hello to Spanish, sir.")
            return
        tlang = self._LANG_ALIASES.get(target.lower().strip(), target.lower().strip())
        key = src.lower().strip(" .?!")
        if tlang == "english":
            meaning = (self._FOREIGN_MEANINGS.get(key)
                       or next((v for k, v in self._FOREIGN_MEANINGS.items()
                                if key in k), None))
            if meaning:
                self.say(f"'{src}' means {meaning}, sir.")
                return
        entry = self._TRANSLATIONS.get(key)
        if entry and tlang in entry:
            self.say(f"'{src}' in {tlang.title()} is '{entry[tlang]}'.")
            return
        self._show_toast("🌍 Translating...", duration=6000)
        if tlang == "english":
            prompt = (f"What does '{src}' mean in English? Answer with one short "
                      "sentence that gives the translation and its language.")
        else:
            prompt = (f"Translate this text to {tlang.title()}: '{src}'. "
                      "Reply with ONLY the translation, nothing else.")
        reply = self._ask_ai(prompt)
        if reply:
            self.say(reply.strip())
        else:
            self.say(f"I could not translate '{src}' offline, sir.")

    # ---------------- 8. unit conversion ----------------
    UNITS = {
        "mm": ("length", 0.001), "millimeter": ("length", 0.001),
        "millimeters": ("length", 0.001),
        "cm": ("length", 0.01), "centimeter": ("length", 0.01),
        "centimeters": ("length", 0.01),
        "m": ("length", 1.0), "meter": ("length", 1.0), "meters": ("length", 1.0),
        "metre": ("length", 1.0), "metres": ("length", 1.0),
        "km": ("length", 1000.0), "kilometer": ("length", 1000.0),
        "kilometers": ("length", 1000.0), "kilometre": ("length", 1000.0),
        "kilometres": ("length", 1000.0),
        "mi": ("length", 1609.344), "mile": ("length", 1609.344),
        "miles": ("length", 1609.344),
        "ft": ("length", 0.3048), "foot": ("length", 0.3048),
        "feet": ("length", 0.3048),
        "in": ("length", 0.0254), "inch": ("length", 0.0254),
        "inches": ("length", 0.0254),
        "yd": ("length", 0.9144), "yard": ("length", 0.9144),
        "yards": ("length", 0.9144),
        "mg": ("mass", 1e-06), "milligram": ("mass", 1e-06),
        "milligrams": ("mass", 1e-06),
        "g": ("mass", 0.001), "gram": ("mass", 0.001), "grams": ("mass", 0.001),
        "kg": ("mass", 1.0), "kilogram": ("mass", 1.0),
        "kilograms": ("mass", 1.0), "kilo": ("mass", 1.0), "kilos": ("mass", 1.0),
        "lb": ("mass", 0.45359237), "lbs": ("mass", 0.45359237),
        "pound": ("mass", 0.45359237), "pounds": ("mass", 0.45359237),
        "oz": ("mass", 0.028349523125), "ounce": ("mass", 0.028349523125),
        "ounces": ("mass", 0.028349523125),
        "ton": ("mass", 907.18474), "tons": ("mass", 907.18474),
        "ml": ("volume", 0.001), "milliliter": ("volume", 0.001),
        "milliliters": ("volume", 0.001),
        "l": ("volume", 1.0), "liter": ("volume", 1.0), "liters": ("volume", 1.0),
        "litre": ("volume", 1.0), "litres": ("volume", 1.0),
        "gal": ("volume", 3.785411784), "gallon": ("volume", 3.785411784),
        "gallons": ("volume", 3.785411784),
        "cup": ("volume", 0.2365882365), "cups": ("volume", 0.2365882365),
        "mps": ("speed", 1.0), "m/s": ("speed", 1.0),
        "kmh": ("speed", 0.2777777777777778), "kph": ("speed", 0.2777777777777778),
        "km/h": ("speed", 0.2777777777777778),
        "kmph": ("speed", 0.2777777777777778),
        "mph": ("speed", 0.44704),
        "knot": ("speed", 0.5144444444444445),
        "knots": ("speed", 0.5144444444444445),
    }
    TEMPERATURE_UNITS = {"c": "celsius", "celsius": "celsius",
                         "f": "fahrenheit", "fahrenheit": "fahrenheit",
                         "k": "kelvin", "kelvin": "kelvin"}

    @staticmethod
    def _temp_convert(v, f_from, t_to):
        if f_from == t_to:
            return v
        if f_from == "celsius":
            c = v
        elif f_from == "fahrenheit":
            c = (v - 32) * 5 / 9
        else:
            c = v - 273.15
        if t_to == "celsius":
            return c
        if t_to == "fahrenheit":
            return c * 9 / 5 + 32
        return c + 273.15

    @staticmethod
    def _fmt_num(x):
        x = round(x, 4)
        if abs(x - round(x)) < 1e-9:
            return f"{int(round(x)):,}"
        return f"{x:,.4f}".rstrip("0").rstrip(".")

    def convert_units(self, cmd):
        """'convert 5 miles to km' / '100 fahrenheit in celsius'. Returns text."""
        m = re.search(
            r"(-?\d+(?:\.\d+)?)\s*(?:degrees?\s+|°\s*)?"
            r"([a-zA-Z°/]+?)\s+(?:to|into|in|as|=)\s+"
            r"(?:degrees?\s+|°\s*)?([a-zA-Z°/]+?)\s*[.?!,]*$", cmd.strip(), re.I)
        if not m:
            return None
        value = float(m.group(1))
        u_from = m.group(2).lower().rstrip(".")
        u_to = m.group(3).lower().rstrip(".")
        d_from, d_to = m.group(2), m.group(3)
        t_from = self.TEMPERATURE_UNITS.get(u_from)
        t_to = self.TEMPERATURE_UNITS.get(u_to)
        if t_from and t_to:
            result = self._temp_convert(value, t_from, t_to)
            return (f"{self._fmt_num(value)} degrees {t_from.title()} equals "
                    f"{self._fmt_num(result)} degrees {t_to.title()}, sir.")
        if t_from or t_to:
            return "I can only convert temperature into other temperature units, sir."
        a = self.UNITS.get(u_from)
        b = self.UNITS.get(u_to)
        if not a or not b:
            return None
        if a[0] != b[0]:
            return f"I cannot convert {a[0]} into {b[0]}, sir."
        result = value * a[1] / b[1]
        return (f"{self._fmt_num(value)} {d_from} equals "
                f"{self._fmt_num(result)} {d_to}, sir.")

    # ---------------- 9. color tool ----------------
    COLOR_PALETTE = [
        ("red", "#FF0000"), ("crimson", "#DC143C"), ("tomato", "#FF6347"),
        ("coral", "#FF7F50"), ("salmon", "#FA8072"), ("orange", "#FFA500"),
        ("gold", "#FFD700"), ("yellow", "#FFFF00"), ("khaki", "#F0E68C"),
        ("olive", "#808000"), ("lime", "#00FF00"), ("green", "#008000"),
        ("emerald", "#50C878"), ("mint", "#98FF98"), ("teal", "#008080"),
        ("turquoise", "#40E0D0"), ("cyan", "#00FFFF"), ("sky blue", "#87CEEB"),
        ("royal blue", "#4169E1"), ("blue", "#0000FF"), ("navy", "#000080"),
        ("indigo", "#4B0082"), ("purple", "#800080"), ("violet", "#EE82EE"),
        ("lavender", "#E6E6FA"), ("magenta", "#FF00FF"), ("pink", "#FFC0CB"),
        ("hot pink", "#FF69B4"), ("brown", "#A52A2A"), ("chocolate", "#D2691E"),
        ("beige", "#F5F5DC"), ("maroon", "#800000"), ("gray", "#808080"),
        ("silver", "#C0C0C0"), ("white", "#FFFFFF"), ("black", "#000000"),
    ]

    @staticmethod
    def _hex_to_rgb(hx):
        hx = hx.lstrip("#")
        return tuple(int(hx[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def _rgb_to_hsl(r, g, b):
        r_, g_, b_ = r / 255.0, g / 255.0, b / 255.0
        mx, mn = max(r_, g_, b_), min(r_, g_, b_)
        l = (mx + mn) / 2.0
        if mx == mn:
            return 0.0, 0.0, l * 100.0
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r_:
            h = ((g_ - b_) / d) % 6
        elif mx == g_:
            h = (b_ - r_) / d + 2
        else:
            h = (r_ - g_) / d + 4
        return h * 60.0, s * 100.0, l * 100.0

    def _nearest_color_name(self, rgb):
        best, best_d = None, float("inf")
        for name, hx in self.COLOR_PALETTE:
            pr = self._hex_to_rgb(hx)
            dist = sum((a - b) ** 2 for a, b in zip(rgb, pr))
            if dist < best_d:
                best_d, best = dist, name
        return best

    def color_info(self, cmd):
        """'what color is #FF5733' / 'show me a nice blue'. Returns text."""
        hm = re.search(r"#?\b([0-9a-fA-F]{6})\b", cmd)
        if hm:
            raw = hm.group(1)
            hx = "#" + raw.upper()
            rgb = self._hex_to_rgb(raw)
            h, s, l = self._rgb_to_hsl(*rgb)
            name = self._nearest_color_name(rgb)
            self._show_color_swatch(hx, f"{hx} · {name}")
            return (f"{hx} is red {rgb[0]}, green {rgb[1]}, blue {rgb[2]} — "
                    f"hue {int(h)} degrees, saturation {int(s)} percent, "
                    f"lightness {int(l)} percent. Closest named color: {name}.")
        fam = re.search(r"\b(nice|pretty|beautiful|good|random|dark|light|pastel)?\s*"
                        r"(red|orange|yellow|green|teal|cyan|blue|purple|pink|brown|"
                        r"gray|grey|black|white)s?\b", cmd, re.I)
        if fam:
            family = fam.group(2).lower()
            family = {"grey": "gray", "violet": "purple"}.get(family, family)
            picks = [(nm, hx) for nm, hx in self.COLOR_PALETTE if family in nm.lower()]
            if picks:
                name, hx = random.choice(picks)
                self._show_color_swatch(hx, f"{name} · {hx}")
                return f"A lovely {family} for you, sir: {name}, hex code {hx}."
        return None

    def _show_color_swatch(self, hex_color, label):
        self._ui(lambda: self._show_color_swatch_ui(hex_color, label))

    def _show_color_swatch_ui(self, hex_color, label):
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#161b22")
            frame = tk.Frame(win, bg="#161b22", padx=10, pady=10)
            frame.pack()
            sw = tk.Canvas(frame, width=150, height=60, highlightthickness=1,
                           highlightbackground="#30363d", bg=hex_color)
            sw.pack()
            tk.Label(frame, text=label, font=("Helvetica Neue", 10),
                     fg="#c9d1d9", bg="#161b22").pack(pady=(4, 0))
            x = max(8, self.root.winfo_x() - 190)
            y = max(8, self.root.winfo_y())
            win.geometry(f"+{x}+{y}")
            win.after(7000, win.destroy)
        except Exception:
            pass

    # ---------------- 10. QR codes ----------------
    def generate_qr(self, cmd):
        """'generate qr code for https://example.com'"""
        m = re.search(r"qr\s*-?\s*code\s*(?:for|of|with|containing)?\s*:?\s*"
                      r"(.+?)\s*[.?!]*$", cmd, re.I)
        data = m.group(1).strip().strip("\"'") if m else ""
        if not data:
            self.say("What should the QR code contain, sir?")
            return
        fname = "qr_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
        path = os.path.join(self._data_dir(), fname)
        try:
            import qrcode
            qrcode.make(data).save(path)
        except Exception:
            from urllib.parse import quote
            webbrowser.open("https://api.qrserver.com/v1/create-qr-code/"
                            f"?size=320x320&data={quote(data)}")
            self.say("I generated the QR code in your browser, sir.")
            return
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            elif platform.system() == "Windows":
                os.startfile(path)
            else:
                webbrowser.open("file://" + path)
        except Exception:
            pass
        self.say(f"QR code saved as {fname} and opened, sir.")

    # ---------------- menu launchers for power features ----------------
    def _ask_string(self, title, prompt):
        try:
            from tkinter import simpledialog
            self.root.attributes("-topmost", True)
            return simpledialog.askstring(title, prompt, parent=self.root)
        except Exception:
            return None

    def _menu_new_file(self):
        spec = self._ask_string("New File", "File name and optional content:\n"
                                "(e.g. notes.txt with content Hello)")
        if spec:
            self.file_create("create file " + spec)

    def _menu_read_file(self):
        name = self._ask_string("Read File", "File to read:")
        if name:
            self.file_read("read file " + name)

    def _menu_delete_file(self):
        name = self._ask_string("Delete File", "File to delete:")
        if name:
            self.file_delete("delete file " + name)

    def _menu_rename_file(self):
        spec = self._ask_string("Rename File", "Rename: old.txt to new.txt:")
        if spec:
            self.file_rename("rename file " + spec)

    def _menu_run_python(self):
        code = self._ask_string("Run Python", "Python code to run:\n(e.g. print(2+2))")
        if code:
            self.run_python_code("run python code " + code)

    def _menu_run_shell(self):
        raw = self._ask_string("Shell Command", "Command to run (e.g. ls):")
        if raw:
            self.run_shell_command("run shell command " + raw)

    def _menu_calendar(self):
        self.calendar_list("what's on my calendar")

    def _menu_add_event(self):
        spec = self._ask_string("Add Event", "Event and time:\n"
                                "(e.g. meeting tomorrow at 3pm)")
        if spec:
            self.calendar_add("add event " + spec)

    def _menu_reminder(self):
        spec = self._ask_string("Set Reminder", "Remind me to...\n"
                                "(e.g. call mom in 2 hours)")
        if spec:
            self.set_reminder("remind me to " + spec)

    def _menu_email(self):
        spec = self._ask_string("Draft Email", "Email topic:\n"
                                "(e.g. to boss about meeting)")
        if spec:
            self.draft_email("draft an email " + spec)

    def _menu_translate(self):
        spec = self._ask_string("Translate", "Translate what, to which language?\n"
                                "(e.g. hello to Spanish)")
        if spec:
            self.translate_text("translate " + spec)

    def _menu_convert(self):
        spec = self._ask_string("Unit Converter", "Conversion (e.g. 5 miles to km):")
        if spec:
            res = self.convert_units(spec)
            self.say(res or "I could not convert that, sir.")

    def _menu_color(self):
        spec = self._ask_string("Color Tool", "Hex code or color family:\n"
                                "(e.g. #FF5733 or nice blue)")
        if spec:
            res = self.color_info(spec)
            self.say(res or "Try a hex code like #33CCFF, or 'nice blue', sir.")

    def _menu_qr(self):
        spec = self._ask_string("Generate QR", "Content for the QR code:")
        if spec:
            self.generate_qr("generate qr code for " + spec)

    # ================================================================
    # Quick voice shortcuts
    # ================================================================
    def _start_timer(self, minutes):
        """Set a background timer that fires after N minutes."""
        label = f"{minutes} minute" + ("s" if minutes != 1 else "")

        def _fire():
            try:
                self._active_timers.remove(t)
            except Exception:
                pass
            self.say(f"Sir, your {label} timer has expired.")
            self._show_toast(f"⏰ Timer done ({label})!", duration=6000)

        t = threading.Timer(minutes * 60, _fire)
        t.daemon = True
        self._active_timers.append(t)
        t.start()
        self.say(f"Timer set for {label}, sir.")

    def _get_weather(self):
        """Fetch current weather from wttr.in."""
        self._show_toast("🌤 Fetching weather...", duration=5000)
        try:
            resp = requests.get(
                "https://wttr.in/?format=%l+:+%c+%t,+feels+like+%f,"
                "+humidity+%h,+wind+%w",
                timeout=8)
            if resp.status_code == 200 and resp.text.strip():
                self.say("Weather report: " + resp.text.strip())
                return
        except Exception:
            pass
        webbrowser.open("https://wttr.in")
        self.say("I could not fetch live weather, sir, so I opened it in your browser.")

    def _show_help(self):
        """List available voice commands."""
        body = ("🎤 Voice Commands\n\n"
                "• \"timer 5\" - five minute timer\n"
                "• \"weather\" - local weather\n"
                "• \"history\" - recent voice commands\n"
                "• \"read my screen\" / \"screenshot\"\n"
                "• \"point to [thing]\" - find on screen\n"
                "• \"write code for [x]\"\n"
                "• \"research [topic]\"\n"
                "• \"build me a website/app\"\n"
                "• \"open [app or url]\" · \"list files\"\n"
                "• \"create file notes.txt with content Hi\"\n"
                "• \"read file notes.txt\" · delete · rename file\n"
                "• \"run python code print(2+2)\"\n"
                "• \"run shell command ls\"\n"
                "• \"draft an email to boss about meeting\"\n"
                "• \"add event meeting at 3pm\"\n"
                "• \"what's on my calendar\"\n"
                "• \"remind me to call mom in 2 hours\"\n"
                "• \"translate hello to Spanish\"\n"
                "• \"convert 5 miles to km\"\n"
                "• \"100 fahrenheit in celsius\"\n"
                "• \"what color is #FF5733\"\n"
                "• \"generate qr code for example.com\"\n"
                "• \"go to sleep\" / \"wake up jarvis\"\n"
                "• \"set api key\" - Groq key\n\n"
                "🖱 Orb Controls\n\n"
                "• Double-click: start voice input\n"
                "• Single-click: quick tips toast\n"
                "• Hold: green talk pulse\n"
                "• Drag: move · Right-click: menu")
        self._show_info_window("Help", body)
        self._show_toast(body, duration=8000)
        self.say("Here is what I can do, sir.")

    def _show_voice_history(self):
        """Show the last 10 recognized voice commands."""
        if not self.voice_history:
            self._show_toast("No voice commands yet.", duration=2500)
            self.say("No voice commands yet, sir.")
            return
        lines = [f"{i}. {c}" for i, c in enumerate(reversed(self.voice_history), 1)]
        self._show_info_window("Voice Command History",
                               "\n".join(lines) + "\n")
        self.say(f"You have {len(self.voice_history)} recent commands, sir.")

    def _show_info_window(self, title, body):
        """Small popup panel near the orb (auto-dismisses). Thread-safe."""
        self._ui(lambda: self._show_info_window_ui(title, body))

    def _show_info_window_ui(self, title, body):
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#161b22")

        def _close():
            try:
                win.destroy()
            except Exception:
                pass

        x = max(0, self.root.winfo_x() - 360)
        y = self.root.winfo_y()
        frame = tk.Frame(win, bg="#161b22", padx=12, pady=10)
        frame.pack()
        tk.Label(frame, text=title, font=("Helvetica Neue", 12, "bold"),
                 fg="#00d4ff", bg="#161b22").pack(anchor="w")
        txt = tk.Text(frame, width=44, height=14, bg="#0d1117", fg="#c9d1d9",
                      font=("Helvetica Neue", 11), relief="flat", wrap="word",
                      highlightthickness=0)
        txt.insert("1.0", body)
        txt.config(state="disabled")
        txt.pack(pady=(6, 4))
        tk.Button(frame, text="Close", command=_close,
                  bg="#1f6feb", fg="white", relief="flat",
                  font=("Helvetica Neue", 10), cursor="hand2").pack(pady=2)
        win.geometry(f"+{x}+{y}")
        win.after(15000, _close)

    # ================================================================
    # State persistence (remember orb position across runs)
    # ================================================================
    def _state_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            self.STATE_FILE)

    def _load_state(self):
        """Restore last saved orb position, clamped to the screen."""
        try:
            with open(self._state_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            x = max(0, int(data["x"]))
            y = max(0, int(data["y"]))
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = min(x, sw - self.ORB_SIZE)
            y = min(y, sh - self.ORB_SIZE)
            self.root.geometry(f"+{x}+{y}")
        except Exception:
            pass  # first run or unreadable file -> keep default position

    def _save_state(self):
        try:
            with open(self._state_path(), "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(),
                           "y": self.root.winfo_y()}, f)
        except Exception:
            pass

    # ================================================================
    # Menu actions
    # ================================================================
    def _ask_about_screen(self):
        self._handle_screen_query("What's on my screen?")

    def _read_screen_aloud(self):
        """Clicky-grade '📖 Read Screen Aloud': transcribe + narrate the
        live screen without ever blocking the UI thread. Uses the
        ``live_screen_brain`` seams when available, else this bot's own."""
        threading.Thread(target=self._read_screen_aloud_work,
                         daemon=True).start()

    def _read_screen_aloud_work(self):
        try:
            import live_screen_brain as lsb
        except Exception:
            lsb = None

        b64 = None
        if lsb is not None and callable(getattr(lsb, "take_screenshot", None)):
            try:
                b64 = lsb.take_screenshot()
            except Exception:
                b64 = None
        if not b64:
            try:
                _img, b64 = self._take_screenshot()
            except Exception:
                b64 = None
        if not b64:
            self.say("My optics are dark at the moment, sir — no screenshot, "
                     "no reading.")
            return

        question = ("Transcribe the text visible on this screen, top to "
                    "bottom. Group it into blocks, skip images and icons.")
        answer = None
        ask = getattr(lsb, "ask_vision", None) if lsb is not None else None
        if callable(ask):
            try:
                answer = ask(self, b64, question)
            except Exception:
                answer = None
        if not (isinstance(answer, str) and answer.strip()):
            try:
                answer = self._ask_vision(b64, question)
            except Exception as exc:
                answer = "Vision request failed: " + str(exc)
        answer = (answer or "").strip()
        if not answer:
            self.say("I could not make out a single word on that screen, sir.")
            return

        spoken = self._speech_summary(answer)
        self._show_toast(f"📖 Reading your screen aloud, sir:\n\n"
                         f"{answer[:600]}", duration=9000)
        self._speak(spoken)

    @staticmethod
    def _speech_summary(text, limit=240):
        """Condense a transcription into a speakable summary: the first
        couple of sentences, trimmed on a word boundary."""
        flat = " ".join(str(text or "").split())
        if len(flat) <= limit:
            return flat
        cut = flat[:limit]
        for sep in (". ", "! ", "? ", "\n"):
            idx = cut.rfind(sep)
            if idx > limit // 3:
                return cut[:idx + 1].strip()
        return cut.rsplit(" ", 1)[0].rstrip(",;:") + "…"

    def _point_mode(self):
        self._show_toast("Say: 'point to [element name]'", duration=3000)

    # ------------------------------------------------------------------
    # Clicky-style cursor-following orb
    # ------------------------------------------------------------------
    FOLLOW_IDLE_PARK_SECONDS = 12.0  # still cursor -> glide home & rest

    def _toggle_follow_cursor(self):
        """Toggle the orb trailing the mouse cursor (like Clicky's buddy)."""
        self._follow_cursor = not getattr(self, "_follow_cursor", False)
        if self._follow_cursor:
            # Remember where the orb lived before it started trailing so a
            # long idle stretch can ease it back home. Nothing is persisted.
            try:
                self._follow_home = (self.root.winfo_x(), self.root.winfo_y())
            except Exception:
                self._follow_home = None
            self._follow_parked = False
            self._follow_idle_since = time.monotonic()
            try:
                import pyautogui
                mx, my = pyautogui.position()
                self._follow_last_mouse = (int(mx), int(my))
            except Exception:
                self._follow_last_mouse = None
            if not getattr(self, "_follow_started", False):
                self._follow_started = True
                try:
                    self.root.after(150, self._follow_cursor_loop)
                except Exception:
                    self._follow_started = False
                    self._follow_cursor = False
        else:
            self._follow_parked = False
        state = "now following your cursor" if self._follow_cursor \
            else "parked in place"
        self._show_toast(f"Orb {state}, sir.", duration=2500)

    def _follow_resume(self):
        """Menu/drag interaction (or fresh mouse movement) wakes a parked
        follower: trailing resumes from wherever the orb currently is."""
        if getattr(self, "_follow_parked", False):
            self._follow_parked = False
        if getattr(self, "_follow_cursor", False):
            self._follow_idle_since = time.monotonic()

    def _step_orb_toward(self, tx, ty):
        """Ease the orb halfway to an on-screen-clamped target (smooth tween)."""
        try:
            tx, ty = int(tx), int(ty)
            w = self.root.winfo_width() or self.ORB_SIZE
            h = self.root.winfo_height() or self.ORB_SIZE
            scr_w = self.root.winfo_screenwidth()
            scr_h = self.root.winfo_screenheight()
            tx = max(0, min(tx, scr_w - w))
            ty = max(0, min(ty, scr_h - h))
            cur_x = self.root.winfo_x()
            cur_y = self.root.winfo_y()
            if abs(cur_x - tx) > 3 or abs(cur_y - ty) > 3:
                nx = cur_x + (tx - cur_x) // 2
                ny = cur_y + (ty - cur_y) // 2
                self.root.geometry(f"+{nx}+{ny}")
        except Exception:
            pass

    def _follow_cursor_loop(self):
        if not getattr(self, "_follow_cursor", False) or not self.root.winfo_exists():
            return
        now = time.monotonic()
        try:
            import pyautogui
            mx, my = pyautogui.position()
            mx, my = int(mx), int(my)
        except Exception:
            mx = my = None
        if mx is not None:
            last = getattr(self, "_follow_last_mouse", None)
            if last is None or abs(mx - last[0]) >= 1 or abs(my - last[1]) >= 1:
                self._follow_last_mouse = (mx, my)
                self._follow_idle_since = now
                if getattr(self, "_follow_parked", False):
                    self._follow_parked = False  # hand is back: trail again
        idle_for = now - getattr(self, "_follow_idle_since", now)
        if idle_for >= self.FOLLOW_IDLE_PARK_SECONDS:
            self._follow_parked = True
        if getattr(self, "_follow_parked", False):
            home = getattr(self, "_follow_home", None)
            if home:
                self._step_orb_toward(home[0], home[1])
        elif mx is not None:
            ox, oy = int(mx + 34), int(my - 18)
            self._step_orb_toward(ox, oy)
        try:
            self.root.after(140, self._follow_cursor_loop)
        except Exception:
            pass

    def _write_mode(self):
        self._show_toast("Say: 'write code for [what]'", duration=3000)

    def _research_mode(self):
        self._show_toast("Say: 'research [topic]'", duration=3000)

    def _build_mode(self):
        self._show_toast("Say: 'build me a [website/app]'", duration=3000)

    def _list_files(self):
        self._handle_list_files("list files")

    def _show_settings(self):
        self._show_toast("Settings: Double-click orb for voice commands.", duration=3000)

    # ================================================================
    # Cleanup
    # ================================================================
    def _cancel_pending_click(self):
        if self._pending_single_click is not None:
            try:
                self.root.after_cancel(self._pending_single_click)
            except Exception:
                pass
            self._pending_single_click = None

    def _on_close(self):
        self.running.clear()
        self._stop_pulse()
        self._stop_hold_pulse()
        self._cancel_pending_click()
        for t in list(self._active_timers):
            try:
                t.cancel()
            except Exception:
                pass
        self._save_state()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _ptt_status_line(self):
        """Honest one-liner about global push-to-talk availability.

        Reflects what ``_start_global_ptt`` actually found: pynput present,
        macOS Accessibility granted, and PTT consented to in onboarding.
        """
        try:
            import hotkey_ptt
            have = bool(getattr(hotkey_ptt, "HAVE_PYNPUT", False))
            if have:
                try:
                    trusted = bool(hotkey_ptt.GlobalPTT.is_trusted())
                except Exception:
                    trusted = False
                if trusted:
                    try:
                        import ptt_onboarding
                        enabled = ptt_onboarding.is_enabled()
                    except Exception:
                        enabled = True
                    if enabled:
                        return "Ctrl+Alt global PTT: ready"
                    return ("Ctrl+Alt global PTT: off — double-click voice")
                return ("Ctrl+Alt global PTT: unavailable — double-click voice")
        except Exception:
            pass
        return "Ctrl+Alt global PTT: unavailable — double-click voice"

    def run(self):
        self._set_state("idle")
        self._start_global_ptt()
        self._show_toast("JARVIS Bot online.\n"
                         "Double-click: 🎤 voice\n"
                         "Single-click: quick tips\n"
                         "Hold: talk pulse · Drag: move\n"
                         f"{self._ptt_status_line()}\n"
                         "Right-click: menu", duration=5000)
        self.root.mainloop()

    def _start_global_ptt(self):
        """Clicky-style system-wide hold-to-talk (needs pynput + perms)."""
        try:
            import hotkey_ptt
            if not hotkey_ptt.HAVE_PYNPUT:
                return
            if not hotkey_ptt.GlobalPTT.is_trusted():
                self._show_toast("Global push-to-talk needs Accessibility "
                                 "permission (System Settings).\nFalling "
                                 "back to double-click voice.", duration=4500)
                return

            def _ptt_start():
                def fire():
                    try:
                        self.interrupt_speech()
                    except Exception:
                        pass
                    threading.Thread(target=self._do_voice,
                                     daemon=True).start()
                self._ui(fire)

            self._global_ptt = hotkey_ptt.acquire(
                on_start=_ptt_start, on_stop=lambda: None)
        except Exception:
            pass


# ============================================================================
# MODE SELECTOR — choose between Chat UI and Bot Mode
# ============================================================================

def _choose_mode():
    """Show a dialog asking the user to choose Chat Mode or Bot Mode."""
    import tkinter.messagebox as messagebox
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    result = messagebox.askyesnocancel(
        "JARVIS — Choose Mode",
        "Welcome to JARVIS, sir.\n\n"
        "YES = Bot Mode (floating screen-aware assistant)\n"
        "NO = Chat Mode (full UI with voice)\n"
        "CANCEL = Quit",
        icon="question",
    )
    root.destroy()
    if result is True:
        return "bot"
    elif result is False:
        return "chat"
    return "quit"


if __name__ == "__main__":
    if os.environ.get("JARVIS_TEST"):
        app = JarvisApp()
        app.engine = None
        app.root.after(800, app.quit_app)
        app.run()
    else:
        mode = _choose_mode()
        if mode == "quit":
            sys.exit(0)
        elif mode == "bot":
            bot = JarvisBot()
            bot.run()
        else:
            app = JarvisApp()
            app.run()
