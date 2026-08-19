import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import web_dev_brain as wdb


class DummyApp:
    pass


class DummyBrain:
    def __init__(self):
        self.registered = []

    def register(self, name, detect, execute, priority=False):
        self.registered.append((name, priority))


def invoke(cmd):
    for name, detect, execute, _prio in wdb.SKILLS:
        ctx = detect(cmd)
        if ctx is not None:
            return name, execute(DummyApp(), ctx)
    return None, None


@pytest.fixture
def env(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(wdb, "GENERATED_DIR", str(tmp_path))
    monkeypatch.setattr(wdb, "_open_in_browser",
                        lambda path: opened.append(path) or True)
    monkeypatch.setattr(wdb, "_llm", lambda app, prompt: None)
    return types.SimpleNamespace(tmp=tmp_path, opened=opened)


def test_register_registers_all_eight():
    brain = DummyBrain()
    wdb.register(brain)
    names = [n for n, _p in brain.registered]
    assert names == [
        "wd_landing_page", "wd_portfolio", "wd_blog", "wd_dashboard",
        "wd_form_page", "wd_pwa_scaffold", "wd_react_component",
        "wd_tailwind_page",
    ]
    assert all(p is False for _n, p in brain.registered)


@pytest.mark.parametrize("cmd,skill,topic,slug", [
    ("build a landing page about artisan coffee",
     "wd_landing_page", "artisan coffee", "artisan-coffee"),
    ("portfolio site for jane doe", "wd_portfolio", "jane doe", "jane-doe"),
    ("blog site about mountain biking",
     "wd_blog", "mountain biking", "mountain-biking"),
    ("dashboard ui for sales metrics",
     "wd_dashboard", "sales metrics", "sales-metrics"),
    ("build a contact form page for bakery orders",
     "wd_form_page", "bakery orders", "bakery-orders"),
])
def test_template_skills_write_local_pages(env, cmd, skill, topic, slug):
    name, reply = invoke(cmd)
    assert name == skill
    path = env.tmp / (slug + ".html")
    assert path.exists()
    html = path.read_text(encoding="utf-8")
    assert slug in str(path)
    assert "</html>" in html
    assert topic.lower() in html.lower()
    assert "sir" in reply
    assert env.opened == [str(path)]


def test_overwrite_creates_bak_backup(env):
    target = env.tmp / "tea.html"
    target.write_text("<html>old draft</html>", encoding="utf-8")
    _, reply = invoke("build a landing page about tea")
    assert target.exists()
    assert (env.tmp / "tea.html.bak").exists()
    assert "old draft" in (env.tmp / "tea.html.bak").read_text(encoding="utf-8")
    assert "sir" in reply


def test_tag_imbalance_warning():
    warn = wdb._tag_sanity("<html><div><div></div><p>hi</p></html>")
    assert "uneven" in warn and "sir" in warn
    assert wdb._tag_sanity("<html><div></div></html>") == ""


def test_pwa_scaffold_writes_trio(env):
    name, reply = invoke("pwa scaffold for fitness tracker")
    assert name == "wd_pwa_scaffold"
    folder = env.tmp / "fitness-tracker_pwa"
    assert folder.is_dir()
    for fname in ("index.html", "manifest.json", "sw.js"):
        assert (folder / fname).exists(), fname
    index = (folder / "index.html").read_text(encoding="utf-8")
    assert "</html>" in index and "fitness tracker" in index.lower()
    manifest = (folder / "manifest.json").read_text(encoding="utf-8")
    assert "standalone" in manifest
    sw = (folder / "sw.js").read_text(encoding="utf-8")
    assert "addEventListener" in sw
    assert env.opened == [str(folder / "index.html")]
    assert "sir" in reply


def test_react_component_returns_fenced_jsx(env):
    name, reply = invoke("react component for star ratings")
    assert name == "wd_react_component"
    assert "```jsx" in reply
    assert "export default function StarRatings()" in reply
    assert "star ratings" in reply
    assert list(env.tmp.iterdir()) == []


def test_tailwind_page_returns_fenced_html(env):
    name, reply = invoke("tailwind page for a bakery")
    assert name == "wd_tailwind_page"
    assert "```html" in reply
    assert "cdn.tailwindcss.com" in reply
    assert "bakery" in reply.lower()
    assert list(env.tmp.iterdir()) == []


def test_online_handoff_copies_prompt_and_opens_ai_studio(
        env, monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((list(args), kwargs.get("input")))
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(wdb.subprocess, "run", fake_run)
    monkeypatch.setattr(wdb, "_llm", lambda app, prompt: "PROMPT TEXT")

    name, reply = invoke("build a landing page about space exploration")

    assert name == "wd_landing_page"
    copied = [inp for args, inp in calls if args[0] == "pbcopy"]
    assert copied and copied[0].decode("utf-8") == "PROMPT TEXT"
    opens = [args[1] for args, _inp in calls
             if args[0] == "open" and len(args) > 1]
    assert wdb.AI_STUDIO_URL in opens
    assert not list(env.tmp.iterdir())
    assert env.opened == []
    assert "clipboard" in reply and "AI Studio" in reply
    assert "space exploration" in reply


def test_missing_topic_asks_persona_question(env):
    for cmd in ("build a landing page about", "portfolio site for",
                "blog site about   ", "pwa scaffold for"):
        name, reply = invoke(cmd)
        assert name is not None
        assert "sir" in reply and "?" in reply
        assert list(env.tmp.iterdir()) == []
        assert env.opened == []


@pytest.mark.parametrize("noise", [
    "what time is it", "tell me a joke", "flip a coin", "open youtube",
])
def test_detectors_ignore_noise(noise):
    for _name, detect, _execute, _prio in wdb.SKILLS:
        assert detect(noise) is None, noise


def test_executor_failure_returns_persona_error(env, monkeypatch):
    blocker = env.tmp / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(wdb, "GENERATED_DIR", str(blocker))
    name, reply = invoke("build a landing page about tea")
    assert name == "wd_landing_page"
    assert reply.startswith("I'm terribly sorry, sir")


def test_detector_topic_cleanup(env):
    ctx = wdb.SKILLS[0][1]("build a landing page about coffee, please!")
    assert ctx["topic"] == "coffee"
