# -*- coding: utf-8 -*-
"""Web-dev brain: chat skills that generate websites two ways.

(A) OFFLINE — curated, complete, inline-CSS responsive templates written to
    generated_websites/<slug>.html (or a PWA trio) and opened in the browser.
(B) ONLINE — if brain._llm returns a prompt for the request, it is copied to
    the clipboard via pbcopy and Google AI Studio is opened so sir can paste.
"""

import json
import os
import platform
import re
import subprocess

from jarvis_logging import get_logger
from brain import _llm

log = get_logger("web_dev_brain")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated_websites")
AI_STUDIO_URL = "https://aistudio.google.com/"


def _clean_topic(raw):
    t = re.sub(r"\s+", " ", str(raw or "")).strip(" \t\n\r.,!?;:\"'()[]-")
    fillers = ("thank you", "thanks", "please", "for me", "asap", "today",
               "now")
    changed = True
    while changed:
        changed = False
        low = t.lower()
        for f in fillers:
            if low == f:
                t = ""
                changed = True
                break
            if low.endswith(" " + f):
                t = t[: -(len(f) + 1)].rstrip(" ,.")
                changed = True
                break
        low = t.lower()
    return t


def _slugify(topic):
    s = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return s or "site"


def _esc(text):
    return (str(text).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _pascal(topic):
    parts = re.findall(r"[A-Za-z0-9]+", topic)
    name = "".join(p[:1].upper() + p[1:] for p in parts)
    return (name or "MySite")[:48]


def _detector(*triggers):
    patts = [(t, re.compile(r"\b" + re.escape(t) + r"\b", re.I))
             for t in triggers]

    def detect(cmd):
        if not isinstance(cmd, str):
            return None
        for trig, rx in patts:
            m = rx.search(cmd)
            if not m:
                continue
            after = cmd[m.end():]
            ma = re.match(
                r"^[\s,.:;!?\-]*(?:about|for|on|covering|featuring)\s+(.+?)\s*$",
                after, re.I | re.S)
            if ma:
                return {"topic": _clean_topic(ma.group(1)), "trigger": trig}
            mb = re.search(
                r"\b(?:about|for|on)\s+([A-Za-z0-9'&.,!:()\-\s]+?)\s*$",
                cmd[:m.start()], re.I)
            if mb and _clean_topic(mb.group(1)):
                return {"topic": _clean_topic(mb.group(1)), "trigger": trig}
            return {"topic": "", "trigger": trig}
        return None

    return detect


def _copy_clipboard(text):
    try:
        if platform.system() == "Darwin":
            r = subprocess.run(["pbcopy"], input=text.encode("utf-8"),
                               check=False)
            return r.returncode == 0
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard copy failed")
        return False


def _open_in_browser(path):
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", path], check=False)
            return True
        import webbrowser
        return bool(webbrowser.open("file://" + path))
    except Exception:
        log.exception("browser open failed")
        return False


def _open_ai_studio():
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", AI_STUDIO_URL], check=False)
            return True
        import webbrowser
        return bool(webbrowser.open(AI_STUDIO_URL))
    except Exception:
        log.exception("AI Studio open failed")
        return False


_META_TMPL = (
    "Write a single detailed prompt to paste into Google AI Studio so Gemini "
    "creates a polished %s about \"%s\". The prompt must request a complete, "
    "production-ready result with a modern responsive layout, tasteful "
    "colors, embedded styling, and professional polish. Output ONLY the "
    "prompt text itself, no quotes, no code fences, no explanation."
)


def _try_handoff(app, kind_label, topic):
    try:
        prompt = _llm(app, _META_TMPL % (kind_label, topic))
    except Exception:
        prompt = None
    if not prompt:
        return None
    copied = _copy_clipboard(prompt)
    opened = _open_ai_studio()
    head = ("Sir, I've drafted a %s prompt for \"%s\"" % (kind_label, topic))
    if copied:
        msg = (head + " and copied it to your clipboard. Google AI Studio is "
               "opening now, sir — paste the prompt into the chat box and "
               "press Enter.")
    else:
        msg = (head + ", though my clipboard charm misfired, sir. Google AI "
               "Studio is opening — here is the prompt:\n\n" + prompt)
    if not opened:
        msg += "\n(Do open https://aistudio.google.com/ manually, sir.)"
    return msg


def _tag_sanity(html):
    warns = []
    opens = len(re.findall(r"<div\b", html))
    closes = len(re.findall(r"</div\s*>", html))
    if opens != closes:
        warns.append("A gentle heads-up, sir — the <div> tags look uneven "
                     "(%d opened, %d closed); a quick glance wouldn't hurt."
                     % (opens, closes))
    if "</html>" not in html.lower():
        warns.append("The closing </html> seems missing, sir — worth a peek.")
    return "\n".join(warns)


def _backup(path):
    if os.path.exists(path):
        try:
            os.replace(path, path + ".bak")
        except OSError:
            pass


def _write_file(path, content):
    _backup(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


_PAGE_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root{--bg:#0f1220;--panel:#181d33;--line:#272d4d;--ink:#eef1ff;--mut:#9aa3c7;--acc:#6c8cff;--acc2:#8f6cff}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:"Segoe UI",system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--ink);line-height:1.65}
a{color:var(--acc);text-decoration:none}
.wrap{width:min(1080px,92%);margin:0 auto}
header{position:sticky;top:0;z-index:9;background:rgba(15,18,32,.94);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;justify-content:space-between;padding:14px 0;flex-wrap:wrap;gap:10px}
.logo{font-size:1.15rem;font-weight:800;letter-spacing:.5px}
.logo span{color:var(--acc)}
nav ul{display:flex;gap:20px;list-style:none;flex-wrap:wrap}
.hero{padding:84px 0;text-align:center;background:radial-gradient(1000px 420px at 50% -80px,#232a55,transparent)}
.hero h1{font-size:clamp(2rem,5vw,3.2rem);margin-bottom:14px}
.hero p{color:var(--mut);max-width:640px;margin:0 auto 26px}
.btn{display:inline-block;background:linear-gradient(90deg,var(--acc),var(--acc2));color:#fff;padding:12px 28px;border-radius:999px;font-weight:700;border:none;cursor:pointer}
.btn:hover{filter:brightness(1.1)}
section{padding:56px 0}
.sec-title{text-align:center;font-size:1.7rem;margin-bottom:8px}
.sec-sub{text-align:center;color:var(--mut);margin-bottom:36px}
.grid{display:grid;gap:22px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px}
.card h3{margin-bottom:8px}
.card p,.hero .mut{color:var(--mut)}
.band{background:linear-gradient(90deg,var(--acc),var(--acc2));border-radius:18px;text-align:center;padding:44px 24px;margin:20px 0}
footer{border-top:1px solid var(--line);padding:26px 0;color:var(--mut);font-size:.92rem;text-align:center}
form{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:28px;max-width:560px;margin:0 auto;display:grid;gap:14px}
label{font-weight:600;font-size:.95rem}
input,textarea{width:100%;padding:11px 13px;border-radius:9px;border:1px solid var(--line);background:#10142a;color:var(--ink);font:inherit}
input:focus,textarea:focus{outline:2px solid var(--acc)}
.stats{display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:34px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}
.stat b{font-size:1.6rem;display:block}
.stat small{color:var(--mut)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:26px}
.bars{display:flex;align-items:flex-end;gap:14px;height:190px;padding-top:10px}
.bars i{flex:1;background:linear-gradient(180deg,var(--acc),var(--acc2));border-radius:6px 6px 0 0;display:inline-block}
table{width:100%;border-collapse:collapse;font-size:.95rem}
th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mut);font-weight:600}
.post{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:26px;margin-bottom:20px}
.meta{color:var(--mut);font-size:.88rem;margin-bottom:10px}
@media(max-width:640px){.bar{justify-content:center}}
</style>
</head>
<body>
%%BODY%%
</body>
</html>
"""


def _fill(template, topic):
    reps = {"%%TOPIC%%": _esc(topic),
            "%%BRAND%%": _esc(topic.title()),
            "%%SLUG%%": _slugify(topic)}
    out = template
    for k, v in reps.items():
        out = out.replace(k, v)
    return out


_NAV = """<header><div class="wrap"><div class="bar">
<div class="logo">%%BRAND%%<span>.</span></div>
<nav><ul><li><a href="#features">Features</a></li><li><a href="#story">Why Us</a></li><li><a href="#start">Get Started</a></li></ul></nav>
</div></div></header>"""

_LANDING_BODY = """%%NAV%%
<section class="hero" id="top"><div class="wrap"><h1>Welcome to %%TOPIC%%</h1><p class="mut">A crisp, modern introduction to %%TOPIC%% — bold ideas, clean execution, and everything you need gathered in one place.</p><a class="btn" href="#features">Dive In</a></div></section>
<section id="features"><div class="wrap"><h2 class="sec-title">Features</h2><p class="sec-sub">What makes %%TOPIC%% shine</p><div class="grid"><div class="card"><h3>Built for Speed</h3><p>Loads instantly and stays smooth on any device, big or small.</p></div><div class="card"><h3>Beautifully Simple</h3><p>A clean layout that puts your story front and centre.</p></div><div class="card"><h3>Fully Responsive</h3><p>Looks sharp on phones, tablets, and widescreen displays alike.</p></div></div></div></section>
<section id="story"><div class="wrap"><div class="band"><h2>The %%TOPIC%% Promise</h2><p>Quality craftsmanship with attention paid to every last pixel, sir.</p></div></div></section>
<section id="start"><div class="wrap"><h2 class="sec-title">Get Started</h2><p class="sec-sub">Join %%TOPIC%% today — no strings attached</p><div style="text-align:center"><a class="btn" href="#top">Back to Top</a></div></div></section>
<footer><div class="wrap">&copy; 2026 %%TOPIC%% &mdash; crafted with care.</div></footer>"""

_PORTFOLIO_BODY = """<header><div class="wrap"><div class="bar">
<div class="logo">%%BRAND%%<span>.</span></div>
<nav><ul><li><a href="#work">Work</a></li><li><a href="#skills">Skills</a></li><li><a href="#contact">Contact</a></li></ul></nav>
</div></div></header>
<section class="hero"><div class="wrap"><h1>%%TOPIC%%</h1><p class="mut">The portfolio of %%TOPIC%% — selected works, hard-won craft, and a fondness for elegant details.</p><a class="btn" href="#work">View Work</a></div></section>
<section id="work"><div class="wrap"><h2 class="sec-title">Selected Work</h2><p class="sec-sub">Recent projects by %%TOPIC%%</p><div class="grid"><div class="card"><h3>Project Aurora</h3><p>An interactive data story told through scroll-driven visuals.</p></div><div class="card"><h3>Project Borealis</h3><p>A brand identity system with typography doing the heavy lifting.</p></div><div class="card"><h3>Project Cinder</h3><p>A mobile experience praised for its restraint and rhythm.</p></div></div></div></section>
<section id="skills"><div class="wrap"><h2 class="sec-title">Toolbox</h2><p class="sec-sub">Instruments of the trade</p><div class="grid"><div class="card"><h3>Design</h3><p>Figma, motion studies, and unreasonably careful kerning.</p></div><div class="card"><h3>Code</h3><p>Semantic HTML, modern CSS, and honest JavaScript.</p></div><div class="card"><h3>Strategy</h3><p>Research, positioning, and roadmaps that survive contact with reality.</p></div></div></div></section>
<section id="contact"><div class="wrap"><div class="band"><h2>Let's Build Something</h2><p>Currently accepting new commissions, sir.</p></div></div></section>
<footer><div class="wrap">&copy; 2026 %%TOPIC%%</div></footer>"""

_BLOG_BODY = """<header><div class="wrap"><div class="bar">
<div class="logo">%%BRAND%%<span>.</span></div>
<nav><ul><li><a href="#latest">Latest</a></li><li><a href="#latest">Archive</a></li><li><a href="#latest">About</a></li></ul></nav>
</div></div></header>
<section class="hero" style="padding:64px 0"><div class="wrap"><h1>The %%TOPIC%% Journal</h1><p class="mut">Notes, essays, and dispatches about %%TOPIC%% — fresh from the desk.</p></div></section>
<section id="latest"><div class="wrap">
<article class="post"><h2>Getting Started with %%TOPIC%%</h2><p class="meta">12 Aug 2026 &middot; 6 min read</p><p>Every journey begins with a single step, and this one begins with a comfortable chair. An opening survey of %%TOPIC%% for the curious newcomer.</p></article>
<article class="post"><h2>Deep Dive: %%TOPIC%% in Practice</h2><p class="meta">03 Aug 2026 &middot; 9 min read</p><p>Theory is cheap; practice is where %%TOPIC%% earns its keep. Field notes, false starts, and what actually worked.</p></article>
<article class="post"><h2>Five Lessons from %%TOPIC%%</h2><p class="meta">21 Jul 2026 &middot; 4 min read</p><p>Hard-won wisdom, distilled to five tidy paragraphs you can read over tea.</p></article>
</div></section>
<footer><div class="wrap">&copy; 2026 The %%TOPIC%% Journal &mdash; published with pride.</div></footer>"""

_DASH_BODY = """<header><div class="wrap"><div class="bar">
<div class="logo">%%BRAND%% <span>Ops Console</span></div>
<nav><ul><li><a href="#overview">Overview</a></li><li><a href="#overview">Reports</a></li><li><a href="#overview">Settings</a></li></ul></nav>
</div></div></header>
<section id="overview"><div class="wrap">
<h2 class="sec-title" style="text-align:left">%%TOPIC%% Dashboard</h2>
<p class="sec-sub" style="text-align:left;margin-bottom:26px">Live overview for %%TOPIC%%</p>
<div class="stats">
<div class="stat"><small>Visitors</small><b>12,480</b></div>
<div class="stat"><small>Sessions</small><b>8,214</b></div>
<div class="stat"><small>Conversion</small><b>4.7%</b></div>
<div class="stat"><small>Uptime</small><b>99.98%</b></div>
</div>
<div class="panel"><h3>Traffic This Week</h3><div class="bars"><i style="height:40%"></i><i style="height:65%"></i><i style="height:52%"></i><i style="height:78%"></i><i style="height:95%"></i></div></div>
<div class="panel"><h3>Latest Entries</h3><table><thead><tr><th>Item</th><th>Status</th><th>Value</th></tr></thead><tbody><tr><td>Alpha</td><td>Active</td><td>1,204</td></tr><tr><td>Bravo</td><td>Pending</td><td>867</td></tr><tr><td>Charlie</td><td>Active</td><td>2,310</td></tr><tr><td>Delta</td><td>Paused</td><td>512</td></tr></tbody></table></div>
</div></section>
<footer><div class="wrap">&copy; 2026 %%BRAND%% Ops Console &mdash; numbers refreshed hourly.</div></footer>"""

_FORM_BODY = """<header><div class="wrap"><div class="bar">
<div class="logo">%%BRAND%%<span>.</span></div>
<nav><ul><li><a href="#contact-form">Home</a></li><li><a href="#contact-form">Services</a></li><li><a href="#contact-form">Contact</a></li></ul></nav>
</div></div></header>
<section class="hero" style="padding:56px 0"><div class="wrap"><h1>Contact %%TOPIC%%</h1><p class="mut">Drop us a line about %%TOPIC%% and we shall respond within one business day, sir.</p></div></section>
<section><div class="wrap">
<form id="contact-form" onsubmit="return wdValidate()">
<label for="wd-name">Name</label>
<input id="wd-name" type="text" placeholder="Ada Lovelace" required>
<label for="wd-email">Email</label>
<input id="wd-email" type="email" placeholder="ada@example.com" required>
<label for="wd-message">Message</label>
<textarea id="wd-message" rows="5" placeholder="How may we help, sir?" required></textarea>
<button class="btn" type="submit">Send Message</button>
<p id="wd-note" style="color:var(--mut);font-size:.9rem;text-align:center"></p>
</form>
<script>
function wdValidate(){
var n=document.getElementById('wd-name').value.trim();
var e=document.getElementById('wd-email').value.trim();
var m=document.getElementById('wd-message').value.trim();
if(!n||!e||!m){document.getElementById('wd-note').textContent='Please fill in every field, sir.';return false;}
document.getElementById('wd-note').textContent='Thank you, sir — your message is ready to send.';
return false;}
</script>
</div></section>
<footer><div class="wrap">&copy; 2026 %%TOPIC%% &mdash; we read everything, sir.</div></footer>"""

_PWA_INDEX = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#6c8cff">
<title>%%TOPIC%% — PWA</title>
<style>
body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:#0f1220;color:#eef1ff;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;line-height:1.6}
.shell{max-width:520px;padding:40px 28px;border:1px solid #272d4d;border-radius:18px;background:#181d33}
h1{margin:0 0 10px}
button{margin:18px 0;padding:12px 30px;border:none;border-radius:999px;font-weight:700;color:#fff;background:linear-gradient(90deg,#6c8cff,#8f6cff);cursor:pointer}
#state{color:#9aa3c7;font-size:.9rem}
</style>
</head>
<body>
<main class="shell">
<h1>%%TOPIC%%</h1>
<p>Your progressive web app scaffold is live, sir — installable and offline-ready.</p>
<button onclick="wdNotify()">Tap Me</button>
<p id="state">Service worker: checking&hellip;</p>
</main>
<script>
if('serviceWorker' in navigator){
navigator.serviceWorker.register('sw.js')
.then(function(){document.getElementById('state').textContent='Service worker: registered';})
.catch(function(){document.getElementById('state').textContent='Service worker: unavailable';});
}else{
document.getElementById('state').textContent='Service workers unsupported here';
}
function wdNotify(){alert('%%TOPIC%% says hello, sir');}
</script>
</body>
</html>
"""

_PWA_SW = """const CACHE = '%%SLUG%%-pwa-v1';
const ASSETS = ['./', './index.html', './manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request))
  );
});
"""

_REACT_TPL = """import React, {{ useMemo, useState }} from "react";

const SEED_ITEMS = [
  {{ id: 1, title: "First %%TOPIC%% entry", detail: "Kick things off with a flourish." }},
  {{ id: 2, title: "Second %%TOPIC%% entry", detail: "Momentum builds nicely." }},
  {{ id: 3, title: "Third %%TOPIC%% entry", detail: "Finishing strong, sir." }},
];

export default function %%COMP%%() {{
  const [items, setItems] = useState(SEED_ITEMS);
  const [draft, setDraft] = useState("");
  const visible = useMemo(
    () => items.filter((it) =>
      it.title.toLowerCase().includes(draft.toLowerCase())),
    [items, draft]
  );

  function addItem() {{
    const title = draft.trim();
    if (!title) return;
    setItems([
      {{ id: Date.now(), title, detail: "Added from %%COMP%%" }},
      ...items,
    ]);
    setDraft("");
  }}

  return (
    <section className="%%SLUG%%-panel">
      <h2>%%TOPIC%% Explorer</h2>
      <input
        value={{draft}}
        onChange={{(e) => setDraft(e.target.value)}}
        placeholder="Filter %%TOPIC%%…"
      />
      <button onClick={{addItem}}>Add</button>
      <ul>
        {{visible.map((it) => (
          <li key={{it.id}}>
            <strong>{{it.title}}</strong> — {{it.detail}}
          </li>
        ))}}
      </ul>
      {{visible.length === 0 && (
        <p>No matches yet — try another phrase, sir.</p>
      )}}
    </section>
  );
}}
"""

_TAILWIND_TPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TOPIC%% — Tailwind Edition</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 font-sans">
<header class="sticky top-0 z-10 backdrop-blur bg-slate-900/80 border-b border-slate-800">
  <div class="max-w-5xl mx-auto px-5 py-4 flex items-center justify-between">
    <span class="font-extrabold tracking-wide">%%TOPIC%%<span class="text-indigo-400">.</span></span>
    <nav class="hidden sm:flex gap-6 text-sm text-slate-300">
      <a class="hover:text-white" href="#features">Features</a>
      <a class="hover:text-white" href="#cta">Contact</a>
    </nav>
  </div>
</header>
<section class="py-20 text-center px-5">
  <h1 class="text-4xl sm:text-5xl font-black mb-4">Welcome to %%TOPIC%%</h1>
  <p class="text-slate-400 max-w-xl mx-auto mb-8">A responsive Tailwind-powered page about %%TOPIC%% — utility-first and ready to ship, sir.</p>
  <a href="#cta" class="inline-block px-7 py-3 rounded-full bg-gradient-to-r from-indigo-500 to-fuchsia-500 font-bold hover:brightness-110">Get Started</a>
</section>
<section id="features" class="pb-20 px-5">
  <div class="max-w-5xl mx-auto grid gap-6 sm:grid-cols-3">
    <div class="rounded-xl border border-slate-800 bg-slate-900 p-6"><h3 class="font-bold mb-2">Swift</h3><p class="text-slate-400 text-sm">Ships in seconds with the Play CDN.</p></div>
    <div class="rounded-xl border border-slate-800 bg-slate-900 p-6"><h3 class="font-bold mb-2">Responsive</h3><p class="text-slate-400 text-sm">Mobile-first utilities throughout.</p></div>
    <div class="rounded-xl border border-slate-800 bg-slate-900 p-6"><h3 class="font-bold mb-2">Polished</h3><p class="text-slate-400 text-sm">Gradient accents applied tastefully.</p></div>
  </div>
</section>
<footer id="cta" class="border-t border-slate-800 py-8 text-center text-slate-500 text-sm">&copy; 2026 %%TOPIC%%</footer>
</body>
</html>
"""


def _page(body_tpl, kind_title, topic):
    body = _fill(body_tpl.replace("%%NAV%%", _NAV), topic)
    return (_PAGE_SHELL.replace("%%BODY%%", body)
            .replace("%%TITLE%%", _esc("%s — %s" % (topic.title(), kind_title))))


def _serve_local(kind_label, topic, html):
    slug = _slugify(topic)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    path = os.path.abspath(os.path.join(GENERATED_DIR, slug + ".html"))
    _write_file(path, html)
    warn = _tag_sanity(html)
    _open_in_browser(path)
    reply = ("Your %s about %s is ready, sir — saved to generated_websites/"
             "%s.html and opening in your browser now."
             % (kind_label, topic, slug))
    if warn:
        reply += "\n" + warn
    return reply


def _offline_landing(topic):
    return _serve_local("landing page", topic,
                        _page(_LANDING_BODY, "Landing Page", topic))


def _offline_portfolio(topic):
    return _serve_local("portfolio site", topic,
                        _page(_PORTFOLIO_BODY, "Portfolio", topic))


def _offline_blog(topic):
    return _serve_local("blog site", topic,
                        _page(_BLOG_BODY, "Journal", topic))


def _offline_dashboard(topic):
    return _serve_local("dashboard UI", topic,
                        _page(_DASH_BODY, "Dashboard", topic))


def _offline_form(topic):
    return _serve_local("contact form page", topic,
                        _page(_FORM_BODY, "Contact", topic))


def _pwa_manifest(topic, slug):
    return json.dumps({
        "name": topic,
        "short_name": topic[:12],
        "description": "Progressive web app scaffold about %s." % topic,
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "background_color": "#0f1220",
        "theme_color": "#6c8cff",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, indent=2) + "\n"


def _offline_pwa(topic):
    slug = _slugify(topic)
    folder = os.path.join(GENERATED_DIR, slug + "_pwa")
    os.makedirs(folder, exist_ok=True)
    index_html = _fill(_PWA_INDEX, topic)
    files = {
        "index.html": index_html,
        "manifest.json": _pwa_manifest(topic, slug),
        "sw.js": _PWA_SW.replace("%%SLUG%%", slug),
    }
    for fname, content in sorted(files.items()):
        _write_file(os.path.join(folder, fname), content)
    warn = _tag_sanity(index_html)
    _open_in_browser(os.path.abspath(os.path.join(folder, "index.html")))
    reply = ("Your progressive web app for %s is scaffolded, sir — index.html,"
             " manifest.json and sw.js now sit in generated_websites/%s_pwa/, "
             "and the index is opening in your browser." % (topic, slug))
    if warn:
        reply += "\n" + warn
    return reply


def _offline_react(topic):
    code = (_REACT_TPL.replace("{{", "\x00").replace("}}", "\x01")
            .replace("%%COMP%%", _pascal(topic))
            .replace("%%TOPIC%%", topic)
            .replace("%%SLUG%%", _slugify(topic))
            .replace("\x00", "{").replace("\x01", "}"))
    return ("Here is a React component for %s, sir — hot from the workshop:\n\n"
            "```jsx\n%s```\nDrop it beside your app entry point and import at "
            "will, sir." % (topic, code))


def _offline_tailwind(topic):
    html = _fill(_TAILWIND_TPL, topic)
    return ("Here is a Tailwind page for %s, sir — utility-first and ready to "
            "paste:\n\n```html\n%s```\nIt leans on the Tailwind Play CDN, so "
            "it runs with zero build step, sir." % (topic, html))


_KINDS = [
    ("landing page", "landing_page", _detector("landing page"),
     _offline_landing),
    ("portfolio site", "portfolio",
     _detector("portfolio site", "portfolio website", "portfolio"),
     _offline_portfolio),
    ("blog site", "blog", _detector("blog site", "blog"), _offline_blog),
    ("dashboard UI", "dashboard",
     _detector("dashboard ui", "admin dashboard", "dashboard"),
     _offline_dashboard),
    ("contact form page", "form_page",
     _detector("contact form page", "contact form", "feedback form"),
     _offline_form),
    ("progressive web app", "pwa_scaffold",
     _detector("pwa scaffold", "progressive web app", "pwa"),
     _offline_pwa),
    ("React component", "react_component",
     _detector("react component", "jsx component"), _offline_react),
    ("Tailwind page", "tailwind_page",
     _detector("tailwind page", "tailwind"), _offline_tailwind),
]


def _make_executor(kind_label, offline):
    def execute(app, ctx):
        try:
            topic = _clean_topic(ctx.get("topic"))
            if not topic:
                return ("With pleasure, sir — which topic should this %s "
                        "cover?" % kind_label)
            handed = _try_handoff(app, kind_label, topic)
            if handed:
                return handed
            return offline(topic)
        except Exception as exc:
            log.exception("%s stumbled", kind_label)
            return ("I'm terribly sorry, sir — the %s workshop stumbled: %s"
                    % (kind_label, exc))

    return execute


SKILLS = [
    ("wd_%s" % slug, detect, _make_executor(kind, offline), False)
    for kind, slug, detect, offline in _KINDS
]


def register(brain):
    for name, detect, execute, priority in SKILLS:
        brain.register(name, detect, execute, priority=priority)


register_extra = register
