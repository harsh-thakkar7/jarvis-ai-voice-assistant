"""Tests for app_dev_brain.py — offline; clipboard/browser/LLM are mocked."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_dev_brain as adb  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


SKILL_NAMES = {
    "ad_flask_api", "ad_fastapi_service", "ad_cli_tool", "ad_tkinter_app",
    "ad_react_scaffold", "ad_electron_skeleton", "ad_python_package",
    "ad_docker_compose",
}


# ==========================================================================
# Fixtures / helpers
# ==========================================================================

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Redirect every filesystem/clipboard/browser seam into tmp_path."""
    apps_dir = tmp_path / "generated_apps"
    monkeypatch.setattr(adb, "PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(adb, "GENERATED_APPS_DIR", str(apps_dir))
    copied, opened = [], []

    def fake_copy(text):
        copied.append(text)
        return True

    def fake_open(url):
        opened.append(url)
        return True

    monkeypatch.setattr(adb, "_copy", fake_copy)
    monkeypatch.setattr(adb, "_open", fake_open)
    return {"tmp": tmp_path, "apps": apps_dir,
            "copied": copied, "opened": opened}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    adb.register(b)
    return b


def invoke(brain, cmd):
    """Return (skill_name, ctx, reply) for the first matching skill."""
    for name, (detect, execute, _prio) in brain.skills.items():
        ctx = detect(cmd)
        if ctx is not None:
            return name, ctx, execute(DummyApp(), ctx)
    return None, None, None


def read(env, *parts):
    with open(os.path.join(str(env["apps"]), *parts),
              encoding="utf-8") as fh:
        return fh.read()


# ==========================================================================
# Registration
# ==========================================================================

def test_registers_exactly_the_eight_scaffolder_skills(brain):
    assert set(brain.skills) == SKILL_NAMES
    assert len(brain.skills) == 8


def test_all_skills_register_with_default_priority(brain):
    assert all(prio is False
               for _d, _e, prio in brain.skills.values())


def test_skill_names_follow_ad_prefix_convention(brain):
    assert all(name.startswith("ad_") for name in brain.skills)


# ==========================================================================
# Local template path: each scaffold creates its expected tree + markers
# ==========================================================================

def jsonify_marker(text):
    return "jsonify" in text


def test_flask_api_scaffold(env, brain):
    name, ctx, reply = invoke(brain, "flask api for inventory management")
    assert name == "ad_flask_api"
    assert ctx["topic"] == "inventory management"
    app_py = read(env, "inventory_management", "app.py")
    assert "Flask(" in app_py
    assert "Blueprint" in app_py
    assert "errorhandler" in app_py
    assert "jsonify" in app_py
    assert "flask" in read(env, "inventory_management",
                           "requirements.txt").lower()
    assert (env["apps"] / "inventory_management" / "README.md").exists()
    assert reply.endswith(", sir.")
    assert "generated_apps/inventory_management/app.py" in reply
    assert "pip install" in reply


def test_fastapi_service_scaffold(env, brain):
    _, _, reply = invoke(brain, "fastapi service for user accounts")
    main_py = read(env, "user_accounts", "main.py")
    assert "FastAPI()" in main_py
    assert "BaseModel" in main_py
    assert "pydantic" in main_py
    assert "uvicorn.run" in main_py
    assert "uvicorn main:app --reload" in reply
    assert reply.endswith(", sir.")


def test_cli_tool_package_layout(env, brain):
    _, _, reply = invoke(brain, "cli tool for log crunching")
    cli_py = read(env, "log_crunching", "cli.py")
    assert "argparse" in cli_py
    assert "add_subparsers" in cli_py
    init_py = read(env, "log_crunching", "__init__.py")
    assert "__version__" in init_py
    test_cli = read(env, "log_crunching", "tests", "test_cli.py")
    assert "def test_" in test_cli
    assert "--help" in reply


def test_tkinter_app_runnable_window_skeleton(env, brain):
    _, _, reply = invoke(brain, "tkinter app for habit tracking")
    app_py = read(env, "habit_tracking", "app.py")
    assert "import tkinter" in app_py
    assert "Menu(" in app_py
    assert "statusbar" in app_py.lower() or "SUNKEN" in app_py
    assert "mainloop()" in app_py
    assert reply.endswith(", sir.")


def test_react_scaffold_minimal_vite_tree(env, brain):
    _, _, reply = invoke(brain, "react app scaffold for a kanban board")
    pkg = json.loads(read(env, "kanban_board", "package.json"))
    assert pkg["scripts"]["dev"] == "vite"
    assert "react" in pkg["dependencies"]
    vite_cfg = read(env, "kanban_board", "vite.config.js")
    assert "vite" in vite_cfg and "@vitejs/plugin-react" in vite_cfg
    app_jsx = read(env, "kanban_board", "src", "App.jsx")
    assert "export default function App()" in app_jsx
    index_html = read(env, "kanban_board", "index.html")
    assert '<div id="root"></div>' in index_html
    assert "npm run dev" in reply


def test_electron_skeleton_files(env, brain):
    _, _, reply = invoke(brain, "electron app for markdown notes")
    main_js = read(env, "markdown_notes", "main.js")
    assert "BrowserWindow" in main_js
    assert "contextIsolation" in main_js
    preload_js = read(env, "markdown_notes", "preload.js")
    assert "contextBridge" in preload_js
    pkg = json.loads(read(env, "markdown_notes", "package.json"))
    assert pkg["main"] == "main.js"
    assert "npm start" in reply


def test_python_package_src_layout(env, brain):
    _, _, reply = invoke(brain, "python package for pdf merging")
    pyproject = read(env, "pdf_merging", "pyproject.toml")
    assert "[project]" in pyproject
    assert 'name = "pdf-merging"' in pyproject
    assert "__version__" in read(env, "pdf_merging", "src", "pdf_merging",
                                 "__init__.py")
    assert "def test_" in read(env, "pdf_merging", "tests", "test_core.py")
    assert "testpaths" in read(env, "pdf_merging", "pytest.ini")


def test_docker_compose_stack(env, brain):
    _, _, reply = invoke(brain, "docker compose for a worker queue")
    compose = read(env, "worker_queue", "docker-compose.yml")
    assert "services:" in compose
    assert "build: ." in compose
    dockerfile = read(env, "worker_queue", "Dockerfile")
    assert "FROM python" in dockerfile
    assert "docker compose up --build" in reply


# ==========================================================================
# Filesystem behaviour: parents, overwrite -> .bak, patched roots honoured
# ==========================================================================

def test_files_land_under_patched_generated_apps_dir(env, brain):
    _, _, _ = invoke(brain, "flask api for cats")
    target = env["apps"] / "cats"
    assert str(target).startswith(str(env["tmp"]))
    assert (target / "app.py").exists()


def test_overwrite_keeps_previous_version_as_bak(env, brain):
    target_dir = env["apps"] / "cats"
    target_dir.mkdir(parents=True)
    (target_dir / "app.py").write_text("# OLD VERSION\n", encoding="utf-8")
    _, _, reply = invoke(brain, "flask api for cats")
    assert "# OLD VERSION\n" == read(env, "cats", "app.py.bak")
    assert "Flask(" in read(env, "cats", "app.py")
    assert ".bak" in reply


def test_second_scaffold_without_prior_files_creates_no_bak(env, brain):
    name, ctx, reply = invoke(brain, "flask api for dogs")
    assert (env["apps"] / "dogs" / "app.py").exists()
    assert not (env["apps"] / "dogs" / "app.py.bak").exists()
    assert ".bak" not in reply


def test_slug_sanitisation(env, brain):
    invoke(brain, "flask api for Inventory Management! v2")
    assert (env["apps"] / "inventory_management_v2" / "app.py").exists()


def test_deep_parent_directories_created(env, brain):
    _, _, _ = invoke(brain, "python package for zip tools")
    assert (env["apps"] / "zip_tools" / "src" / "zip_tools" /
            "core.py").exists()
    assert (env["apps"] / "zip_tools" / "tests").is_dir()


# ==========================================================================
# Online path: Groq prompt -> clipboard -> AI Studio handoff
# ==========================================================================

def test_handoff_when_llm_available(env, brain, monkeypatch):
    monkeypatch.setattr(adb, "_llm", lambda app, prompt: "canned code")
    name, _, reply = invoke(brain, "flask api for tea inventory")
    assert name == "ad_flask_api"
    assert len(env["copied"]) == 1
    prompt = env["copied"][0]
    assert "tea inventory" in prompt
    assert "Flask REST API" in prompt
    assert env["opened"] == [adb.AISTUDIO_URL]
    assert "Google AI Studio" in reply
    assert reply.endswith(", sir.")
    # handoff writes nothing locally
    assert not env["apps"].exists() or not list(env["apps"].iterdir())


def test_handoff_prompt_is_full_engineering_brief(env, brain, monkeypatch):
    monkeypatch.setattr(adb, "_llm", lambda app, prompt: "ok")
    invoke(brain, "docker compose for payment workers")
    prompt = env["copied"][0]
    assert "senior software engineer" in prompt
    assert "payment workers" in prompt
    assert "Docker Compose service" in prompt


def test_handoff_falls_back_to_local_template_when_clipboard_fails(
        env, brain, monkeypatch):
    monkeypatch.setattr(adb, "_llm", lambda app, prompt: "canned code")

    def refuse(_text):
        return False

    monkeypatch.setattr(adb, "_copy", refuse)
    _, _, reply = invoke(brain, "fastapi service for billing")
    assert "FastAPI()" in read(env, "billing", "main.py")
    assert "Scaffolded" in reply
    assert env["opened"] == []  # never opens the browser if copy failed


def test_handoff_to_aistudio_helper_truth_table(monkeypatch):
    monkeypatch.setattr(adb, "_copy", lambda t: True)
    monkeypatch.setattr(adb, "_open", lambda u: True)
    assert adb._handoff_to_aistudio("prompt") is True
    monkeypatch.setattr(adb, "_open", lambda u: False)
    assert adb._handoff_to_aistudio("prompt") is False


def test_llm_probe_failure_still_scaffolds_locally(env, brain,
                                                   monkeypatch):
    def boom(_app, _prompt):
        raise RuntimeError("groq down")

    monkeypatch.setattr(adb, "_llm", boom)
    _, _, reply = invoke(brain, "cli tool for backups")
    assert "argparse" in read(env, "backups", "cli.py")
    assert reply.endswith(", sir.")


# ==========================================================================
# Detect discipline: noise passes through, vague requests ask for a topic
# ==========================================================================

NOISE_COMMANDS = [
    "tell me a joke",
    "what is love",
    "build a website about cats",
    "docker ps",
    "git status",
    "make me a sandwich",
    "generate python code for sorting",
    "weather tomorrow",
    "flip a coin",
]


@pytest.mark.parametrize("cmd", NOISE_COMMANDS)
def test_noise_detector_returns_none_for_every_skill(cmd):
    for name, detect, _execute, _prio in adb.SKILLS:
        assert detect(cmd) is None, f"{name} wrongly fired on {cmd!r}"


@pytest.mark.parametrize("cmd", ["flask api", "fastapi service",
                                 "cli tool", "docker compose"])
def test_missing_topic_asks_instead_of_scaffolding(env, brain, cmd):
    name, ctx, reply = invoke(brain, cmd)
    assert name is not None
    assert ctx["topic"] is None
    assert "?" in reply
    assert reply.endswith(", sir?")
    assert not env["apps"].exists() or not list(env["apps"].iterdir())


def test_detect_context_carries_kind_and_label():
    ctx = adb.SKILLS[2][1]("cli tool for invoicing")
    assert ctx["kind"] == "cli_tool"
    assert ctx["label"] == "Python CLI tool"
    assert ctx["topic"] == "invoicing"


def test_near_miss_triggers_do_not_cross_fire():
    kinds = {}
    for name, detect, _execute, _prio in adb.SKILLS:
        for cmd in ("flask api for x", "fastapi service for x",
                    "cli tool for x", "tkinter app for x",
                    "react app scaffold for x",
                    "electron app for x", "python package for x",
                    "docker compose for x"):
            ctx = detect(cmd)
            if ctx is not None:
                kinds.setdefault(name, set()).add(ctx["kind"])
    assert kinds == {
        "ad_flask_api": {"flask_api"},
        "ad_fastapi_service": {"fastapi_service"},
        "ad_cli_tool": {"cli_tool"},
        "ad_tkinter_app": {"tkinter_app"},
        "ad_react_scaffold": {"react_scaffold"},
        "ad_electron_skeleton": {"electron_skeleton"},
        "ad_python_package": {"python_package"},
        "ad_docker_compose": {"docker_compose"},
    }


# ==========================================================================
# Persona safety
# ==========================================================================

def test_every_local_reply_is_persona_safe(env, brain):
    cmds = [
        "flask api for a", "fastapi service for b", "cli tool for c",
        "tkinter app for d", "react app scaffold for e",
        "electron app for f", "python package for g",
        "docker compose for h",
    ]
    for cmd in cmds:
        _name, _ctx, reply = invoke(brain, cmd)
        assert reply.rstrip().endswith("sir."), cmd
        assert "Run it with:" in reply


def test_persona_safe_leaves_existing_sir_alone():
    assert adb._persona_safe("Done already, sir.") == "Done already, sir."
    assert adb._persona_safe("Ready.") == "Ready, sir."
    assert adb._persona_safe("Which kind?") == "Which kind, sir?"


# ==========================================================================
# Groq prompt builder
# ==========================================================================

def test_groq_prompt_mentions_topic_and_deliverables():
    prompt = adb._groq_prompt("Flask REST API", "library loans")
    assert "library loans" in prompt
    assert "Flask REST API" in prompt
    assert "complete files" in prompt
    assert "run instructions" in prompt
