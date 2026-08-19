# -*- coding: utf-8 -*-
"""APP DEV BRAIN: application scaffolder for JARVIS.

Two paths, mirroring the web twin:

* local   - complete offline templates written under
            PROJECT_DIR/generated_apps/<slug>/ (parents created; existing
            files preserved as <name>.bak before overwrite)
* online  - a full Groq build prompt is copied to the clipboard and Google
            AI Studio is opened so the user pastes it there
            (helper _handoff_to_aistudio(prompt), exposed for tests)

Registers eight skills into the main Brain via register(brain):
    ad_flask_api, ad_fastapi_service, ad_cli_tool, ad_tkinter_app,
    ad_react_scaffold, ad_electron_skeleton, ad_python_package,
    ad_docker_compose

Never imports main; talks to the LLM only through brain._llm.
Every executor reply is persona-safe and ends with ", sir."
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


try:
    from brain import _llm
except ImportError:  # pragma: no cover - standalone use
    def _llm(app, prompt):  # type: ignore[misc]
        return None


log = get_logger("app_dev_brain")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
GENERATED_APPS_DIR = os.path.join(PROJECT_DIR, "generated_apps")
AISTUDIO_URL = "https://aistudio.google.com/"


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _copy(text: str) -> bool:
    """Copy text to the system clipboard ('' -safe, never raises)."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    if platform.system() == "Darwin":
        try:
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE,
                                    text=True)
            proc.communicate(text, timeout=5)
            return True
        except Exception:
            return False
    return False


def _open(url: str) -> bool:
    """Open a URL in the default browser; False when unavailable."""
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _apps_root() -> str:
    """Root directory for generated apps (module attr so tests can patch)."""
    return GENERATED_APPS_DIR


def _handoff_to_aistudio(prompt: str) -> bool:
    """Copy the Groq prompt to the clipboard and open Google AI Studio."""
    copied = _copy(prompt)
    opened = bool(copied and _open(AISTUDIO_URL))
    log.info("aistudio handoff: copied=%s opened=%s", copied, opened)
    return opened


# ==========================================================================
# Shared helpers
# ==========================================================================

_TAIL_FILLER_RE = re.compile(
    r"\b(?:please|jarvis|thanks|thank\s+you|now|today|asap|for\s+me)\b"
    r"[\s,.!?:;-]*$", re.I)


def _slugify(topic: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", topic.lower()).strip("_")
    return slug or "my_app"


def _clean_topic(raw: str) -> str | None:
    t = re.sub(r"^(?:a|an|the)\s+", "", raw.strip(), flags=re.I)
    t = _TAIL_FILLER_RE.sub("", t).strip(" \t.,!?;:-\"'")
    return t or None


def _extract_topic(cmd: str, m: re.Match) -> str | None:
    rest = cmd[m.end():]
    mm = re.search(r"\b(?:for|about|to\s+manage|managing)\s+(.+)$", rest,
                   re.I)
    raw = mm.group(1) if mm else rest
    if not raw.strip():
        return None
    return _clean_topic(raw)


def _persona_safe(reply: str) -> str:
    """Guarantee the Jarvis persona: every reply ends with ', sir.'"""
    r = (reply or "").rstrip()
    if re.search(r"\bsir\b[\s.?!]*$", r, re.I):
        return r
    if r.endswith((".", "!", "?")):
        return r[:-1].rstrip() + ", sir" + r[-1:]
    return r + ", sir."


def _write_file(root: str, relpath: str, content: str) -> tuple[str, bool]:
    """Write root/relpath (parents created); back up any existing file .bak."""
    full = os.path.join(root, relpath)
    parent = os.path.dirname(full)
    if parent:
        os.makedirs(parent, exist_ok=True)
    backed_up = False
    if os.path.exists(full):
        try:
            os.replace(full, full + ".bak")
            backed_up = True
        except OSError as exc:
            log.warning("could not back up %s: %s", full, exc)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(content)
    return relpath, backed_up


# ==========================================================================
# Detect factory
# ==========================================================================

def _detect(pattern: str, kind: str, label: str):
    def detect(cmd: str):
        m = re.search(pattern, cmd, re.I)
        if not m:
            return None
        topic = _extract_topic(cmd, m)
        return {"kind": kind, "label": label,
                "topic": topic, "trigger": cmd[:m.end()].strip()}
    return detect


# ==========================================================================
# Templates: each builder returns (files, run_cmd) where files is a list of
# (relative_path, content). Markers like Flask( / FastAPI( live in content.
# ==========================================================================

def _readme(title: str, kind_label: str, body: str) -> str:
    return ("# %s\n\n%s scaffolded by JARVIS.\n\n%s\n" %
            (title, kind_label, body))


def _flask_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    app_py = '''"""@TITLE@ - Flask REST API (scaffolded by JARVIS)."""
from flask import Flask, Blueprint, jsonify, request

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.get("/health")
def health():
    return jsonify(status="ok", service="@SLUG@")


@api_bp.get("/items")
def list_items():
    return jsonify(items=[])


@api_bp.post("/items")
def create_item():
    payload = request.get_json(silent=True) or {}
    return jsonify(created=True, item=payload), 201


app = Flask(__name__)
app.register_blueprint(api_bp)


@app.errorhandler(404)
def not_found(err):
    return jsonify(error="not found"), 404


@app.errorhandler(400)
def bad_request(err):
    return jsonify(error="bad request"), 400


@app.errorhandler(500)
def server_error(err):
    return jsonify(error="internal server error"), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
'''.replace("@TITLE@", topic.title()).replace("@SLUG@", slug)
    reqs = "flask>=3.0\n"
    readme = _readme(
        topic.title(), "Flask REST API",
        "## Run\n\n```\npip install -r requirements.txt\n"
        "python app.py\n```\n\nEndpoints: /api/health, "
        "/api/items (GET, POST).\n")
    files = [("app.py", app_py),
             ("requirements.txt", reqs),
             ("README.md", readme)]
    run = ("cd generated_apps/%s && pip install -r requirements.txt && "
           "python app.py" % slug)
    return files, run


def _fastapi_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    main_py = '''"""@TITLE@ - FastAPI service (scaffolded by JARVIS)."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()
app.title = "@TITLE@"
app.version = "0.1.0"


class Item(BaseModel):
    id: int | None = Field(default=None)
    name: str
    description: str | None = None


DB: dict[int, Item] = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "@SLUG@"}


@app.get("/items")
def list_items():
    return [item for _, item in sorted(DB.items())]


@app.post("/items", status_code=201)
def create_item(item: Item):
    item_id = item.id if item.id is not None else len(DB) + 1
    if item_id in DB:
        raise HTTPException(status_code=409, detail="id already exists")
    DB[item_id] = item.model_copy(update={"id": item_id})
    return DB[item_id]


@app.delete("/items/{item_id}")
def delete_item(item_id: int):
    if item_id not in DB:
        raise HTTPException(status_code=404, detail="item not found")
    del DB[item_id]
    return {"deleted": item_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
'''.replace("@TITLE@", topic.title()).replace("@SLUG@", slug)
    reqs = "fastapi>=0.115\nuvicorn>=0.30\npydantic>=2.7\n"
    readme = _readme(
        topic.title(), "FastAPI Service",
        "## Run\n\n```\npip install -r requirements.txt\n"
        "uvicorn main:app --reload\n```\n\nDocs at "
        "http://127.0.0.1:8000/docs.\n")
    files = [("main.py", main_py),
             ("requirements.txt", reqs),
             ("README.md", readme)]
    run = ("cd generated_apps/%s && pip install -r requirements.txt && "
           "uvicorn main:app --reload" % slug)
    return files, run


def _cli_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    cli_py = '''"""@TITLE@ - command line tool (scaffolded by JARVIS)."""
import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="@SLUG@", description="@TITLE@")
    parser.add_argument("--verbose", action="store_true",
                        help="chatty output")
    sub = parser.add_subparsers(dest="command")
    greet = sub.add_parser("greet", help="print a greeting")
    greet.add_argument("--name", default="world")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "greet":
        print("Hello, %s!" % args.name)
        return 0
    print("No command given; try --help")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''.replace("@TITLE@", topic.title()).replace("@SLUG@", slug)
    init_py = ('"""%s CLI package."""\n\n__version__ = "0.1.0"\n'
               % topic.title())
    test_cli = '''"""Smoke tests for @SLUG@ CLI."""
from cli import main


def test_greet_defaults(capsys):
    assert main(["greet"]) == 0
    assert "Hello, world!" in capsys.readouterr().out


def test_greet_named(capsys):
    assert main(["greet", "--name", "sir"]) == 0
    assert "Hello, sir!" in capsys.readouterr().out


def test_no_command_returns_one():
    assert main([]) == 1
'''.replace("@SLUG@", slug)
    readme = _readme(
        topic.title(), "CLI Tool",
        "## Run\n\n```\npython cli.py --help\n"
        "python cli.py greet --name sir\n```\n\nTests: run `pytest`.\n")
    files = [("cli.py", cli_py),
             ("__init__.py", init_py),
             ("tests/test_cli.py", test_cli),
             ("README.md", readme)]
    run = "cd generated_apps/%s && python cli.py --help && pytest" % slug
    return files, run


def _tkinter_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    app_py = '''"""@TITLE@ - Tkinter desktop app (scaffolded by JARVIS)."""
import tkinter as tk
from tkinter import filedialog, messagebox


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("@TITLE@")
        self.geometry("720x480")
        self._build_menu()
        self._build_statusbar()

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open...", command=self.on_open)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About", command=self.on_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _build_statusbar(self):
        self.status = tk.Label(self, text="Ready", anchor="sw",
                               relief=tk.SUNKEN, padx=6)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

    def on_open(self):
        path = filedialog.askopenfilename()
        if path:
            self.set_status("Opened %s" % path)

    def on_about(self):
        messagebox.showinfo("About", "@TITLE@")

    def set_status(self, text):
        self.status.config(text=text)


if __name__ == "__main__":
    App().mainloop()
'''.replace("@TITLE@", topic.title())
    readme = _readme(
        topic.title(), "Tkinter Desktop App",
        "## Run\n\n```\npython app.py\n```\n\nNo third-party dependencies; "
        "tkinter ships with Python.\n")
    files = [("app.py", app_py), ("README.md", readme)]
    run = "cd generated_apps/%s && python app.py" % slug
    return files, run


def _react_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    pkg = {
        "name": slug,
        "private": True,
        "version": "0.1.0",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
        },
        "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
        "devDependencies": {
            "@vitejs/plugin-react": "^4.3.1",
            "vite": "^5.4.0",
        },
    }
    vite_cfg = ('import { defineConfig } from "vite";\n'
                'import react from "@vitejs/plugin-react";\n\n'
                "export default defineConfig({\n"
                '  plugins: [react()],\n'
                "});\n")
    index_html = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n'
                  '  <meta charset="UTF-8" />\n'
                  '  <meta name="viewport" content="width=device-width, '
                  'initial-scale=1.0" />\n'
                  "  <title>%s</title>\n</head>\n<body>\n"
                  '  <div id="root"></div>\n'
                  '  <script type="module" src="/src/main.jsx"></script>\n'
                  "</body>\n</html>\n" % topic.title())
    main_jsx = ('import React from "react";\n'
                'import ReactDOM from "react-dom/client";\n'
                'import App from "./App.jsx";\n\n'
                'ReactDOM.createRoot(document.getElementById("root"))'
                '.render(\n'
                '  <React.StrictMode>\n    <App />\n  </React.StrictMode>,\n'
                ");\n")
    app_jsx = ('export default function App() {\n'
               '  return (\n    <main style={{ fontFamily: "sans-serif", '
               'padding: 24 }}>\n'
               "      <h1>%s</h1>\n      <p>Scaffolded by JARVIS.</p>\n"
               "    </main>\n  );\n}\n" % topic.title())
    readme = _readme(topic.title(), "React + Vite App",
                     "## Run\n\n```\nnpm install\nnpm run dev\n```\n")
    files = [("package.json", json.dumps(pkg, indent=2) + "\n"),
             ("vite.config.js", vite_cfg),
             ("index.html", index_html),
             ("src/main.jsx", main_jsx),
             ("src/App.jsx", app_jsx),
             ("README.md", readme)]
    run = "cd generated_apps/%s && npm install && npm run dev" % slug
    return files, run


def _electron_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    pkg = {
        "name": slug,
        "version": "0.1.0",
        "description": "%s - Electron desktop app scaffolded by JARVIS"
                       % topic.title(),
        "main": "main.js",
        "scripts": {"start": "electron ."},
        "devDependencies": {"electron": "^31.0.0"},
    }
    main_js = ('const { app, BrowserWindow } = require("electron");\n'
               'const path = require("path");\n\n'
               "function createWindow() {\n"
               "  const win = new BrowserWindow({\n"
               "    width: 900,\n    height: 640,\n"
               '    title: "%s",\n    webPreferences: {\n'
               '      preload: path.join(__dirname, "preload.js"),\n'
               '      contextIsolation: true,\n'
               '      nodeIntegration: false,\n    },\n  });\n'
               '  win.loadFile("index.html");\n}\n\n'
               'app.whenReady().then(() => {\n  createWindow();\n'
               '  app.on("activate", () => {\n'
               '    if (BrowserWindow.getAllWindows().length === 0) '
               'createWindow();\n  });\n});\n\n'
               'app.on("window-all-closed", () => {\n'
               '  if (process.platform !== "darwin") app.quit();\n});\n'
               % topic.title())
    preload_js = ('const { contextBridge } = require("electron");\n\n'
                  'contextBridge.exposeInMainWorld("jarvisAPI", {\n'
                  '  ping: () => "pong",\n});\n')
    index_html = ('<!DOCTYPE html>\n<html>\n<body>\n'
                  "  <h1>%s</h1>\n"
                  "  <p>Electron skeleton scaffolded by JARVIS.</p>\n"
                  "</body>\n</html>\n" % topic.title())
    readme = _readme(topic.title(), "Electron Desktop App",
                     "## Run\n\n```\nnpm install\nnpm start\n```\n")
    files = [("main.js", main_js),
             ("preload.js", preload_js),
             ("index.html", index_html),
             ("package.json", json.dumps(pkg, indent=2) + "\n"),
             ("README.md", readme)]
    run = "cd generated_apps/%s && npm install && npm start" % slug
    return files, run


def _python_package_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    pkg_mod = slug.replace("_", "-")
    pyproject = ('[build-system]\nrequires = ["setuptools>=68"]\n'
                 'build-backend = "setuptools.build_meta"\n\n'
                 "[project]\nname = \"%s\"\nversion = \"0.1.0\"\n"
                 "description = \"%s - python package scaffolded by JARVIS\"\n"
                 "requires-python = \">=3.10\"\n"
                 "dependencies = []\n\n"
                 "[project.scripts]\n%s = \"%s.core:run\"\n"
                 % (pkg_mod, topic.title(), slug, slug))
    init_py = ('"""%s package."""\n\n__version__ = "0.1.0"\n'
               % topic.title())
    core_py = ('"""Core helpers for %s."""\n\n\ndef run():\n'
               '    print("%s ready")\n    return 0\n'
               % (topic.title(), pkg_mod))
    test_core = ('from %s.core import run\n\n\ndef test_run(capsys):\n'
                 '    assert run() == 0\n' % slug)
    pytest_ini = "[pytest]\ntestpaths = tests\naddopts = -q\n"
    readme = _readme(topic.title(), "Python Package",
                     "## Install & test\n\n```\npip install -e .\n"
                     "pytest\n```\n")
    files = [("pyproject.toml", pyproject),
             ("pytest.ini", pytest_ini),
             ("src/%s/__init__.py" % slug, init_py),
             ("src/%s/core.py" % slug, core_py),
             ("tests/test_core.py", test_core),
             ("README.md", readme)]
    run = ("cd generated_apps/%s && pip install -e . && pytest" % slug)
    return files, run


def _compose_files(topic: str) -> tuple[list, str]:
    slug = _slugify(topic)
    compose_yml = (
        "# %s - docker compose stack scaffolded by JARVIS\n"
        "services:\n"
        "  %s:\n"
        "    build: .\n"
        "    ports:\n      - \"8000:8000\"\n"
        "    environment:\n      - ENV=production\n"
        "    restart: unless-stopped\n" % (topic.title(), slug))
    dockerfile = (
        "# %s - generic python service image\n"
        "FROM python:3.12-slim\n\nWORKDIR /app\n\n"
        "COPY requirements.txt .\nRUN pip install --no-cache-dir -r "
        "requirements.txt\n\nCOPY . .\n\n"
        'CMD ["python", "main.py"]\n' % topic.title())
    main_py = ('"""%s - minimal python service entry point."""\n\n'
               'if __name__ == "__main__":\n    print("%s service running")\n'
               % (topic.title(), slug))
    reqs = "requests>=2.31\n"
    readme = _readme(topic.title(), "Docker Compose Service",
                     "## Run\n\n```\ndocker compose up --build\n```\n")
    files = [("docker-compose.yml", compose_yml),
             ("Dockerfile", dockerfile),
             ("main.py", main_py),
             ("requirements.txt", reqs),
             ("README.md", readme)]
    run = "cd generated_apps/%s && docker compose up --build" % slug
    return files, run


_BUILDERS = {
    "flask_api": (_flask_files, "Flask REST API"),
    "fastapi_service": (_fastapi_files, "FastAPI service"),
    "cli_tool": (_cli_files, "Python CLI tool"),
    "tkinter_app": (_tkinter_files, "Tkinter desktop app"),
    "react_scaffold": (_react_files, "React + Vite app"),
    "electron_skeleton": (_electron_files, "Electron desktop app"),
    "python_package": (_python_package_files, "Python package"),
    "docker_compose": (_compose_files, "Docker Compose service"),
}


def _groq_prompt(kind_label: str, topic: str) -> str:
    """Full build brief handed to Groq / pasted into AI Studio."""
    return (
        "You are a senior software engineer. Generate a complete, "
        "production-ready %s for: %s.\n\n"
        "Requirements:\n"
        "- Return ONLY complete files, each preceded by its relative path.\n"
        "- Idiomatic structure, docstrings/comments where useful, no TODOs.\n"
        "- Include dependency manifests and run instructions.\n"
        "- The project should run immediately after standard setup.\n\n"
        "Begin now."
        % (kind_label, topic))


# ==========================================================================
# Executor core (two paths: local templates OR aistudio handoff)
# ==========================================================================

def _ask_topic(label: str) -> str:
    return ("What should the %s handle? Give me a topic, like 'flask api "
            "for inventory management'?" % label)


def _execute_scaffold(app, ctx) -> str:
    kind = ctx["kind"]
    label = ctx["label"]
    topic = ctx["topic"]
    builder, _ = _BUILDERS[kind]

    if not topic:
        return _ask_topic(label)

    slug = _slugify(topic)

    # Path 2 (online): Groq available -> craft prompt, clipboard, AI Studio.
    groq_prompt = _groq_prompt(label, topic)
    reply = None
    try:
        reply = _llm(app, groq_prompt)
    except Exception as exc:  # defensive: never let LLM seams explode
        log.warning("_llm probe failed: %s", exc)
        reply = None
    if reply:
        if _handoff_to_aistudio(groq_prompt):
            return ("My Groq brain is standing by, so I put a complete %s "
                    "build prompt on your clipboard and opened Google AI "
                    "Studio. Paste it into the prompt box to generate the "
                    "code, then drop the files into generated_apps/%s/"
                    % (label, slug))
        log.info("aistudio handoff unavailable; using local template")

    # Path 1 (local): complete offline template tree under generated_apps/.
    files, run_cmd = builder(topic)
    root = os.path.join(_apps_root(), slug)
    created, backups = [], []
    for relpath, content in files:
        rel, did_backup = _write_file(root, relpath, content)
        created.append(rel)
        if did_backup:
            backups.append(rel + ".bak")
    lines = ["Scaffolded a %s for '%s':" % (label, topic)]
    lines += ["  generated_apps/%s/%s" % (slug, rel) for rel in created]
    if backups:
        lines.append("Previous versions kept as: %s"
                     % ", ".join(sorted(set(backups))))
    lines.append("Run it with: %s" % run_cmd)
    return "\n".join(lines)


def _executor(name: str):
    def execute(app, ctx) -> str:
        try:
            return _persona_safe(_execute_scaffold(app, ctx))
        except Exception as exc:
            log.exception("skill %s failed", name)
            return _persona_safe("I could not finish that scaffold (%s)"
                                 % exc)
    execute.__name__ = name
    return execute


# ==========================================================================
# Skill table
# ==========================================================================

SKILLS = [
    ("ad_flask_api",
     _detect(r"\bflask\s+(?:rest(?:ful)?\s+)?api\b", "flask_api",
             "Flask REST API"),
     _executor("ad_flask_api"), False),

    ("ad_fastapi_service",
     _detect(r"\bfastapi\s+(?:service|microservice|api|backend)\b",
             "fastapi_service", "FastAPI service"),
     _executor("ad_fastapi_service"), False),

    ("ad_cli_tool",
     _detect(r"\b(?:cli|command[- ]line)\s+(?:tool|utility|app)\b",
             "cli_tool", "Python CLI tool"),
     _executor("ad_cli_tool"), False),

    ("ad_tkinter_app",
     _detect(r"\b(?:tkinter|tk)\s+(?:app|application|gui|window|program)\b",
             "tkinter_app", "Tkinter desktop app"),
     _executor("ad_tkinter_app"), False),

    ("ad_react_scaffold",
     _detect(r"(?:\breact\b[^\n]{0,30}\b(?:scaffold|app|project)\b|"
             r"\bscaffold\b[^\n]{0,30}\breact\b)",
             "react_scaffold", "React + Vite app"),
     _executor("ad_react_scaffold"), False),

    ("ad_electron_skeleton",
     _detect(r"\belectron\b[^\n]{0,30}\b(?:skeleton|boilerplate|app)\b",
             "electron_skeleton", "Electron desktop app"),
     _executor("ad_electron_skeleton"), False),

    ("ad_python_package",
     _detect(r"\b(?:python|pypi)\s+package\b",
             "python_package", "Python package"),
     _executor("ad_python_package"), False),

    ("ad_docker_compose",
     _detect(r"\bdocker\s+compose\b",
             "docker_compose", "Docker Compose service"),
     _executor("ad_docker_compose"), False),
]


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    for name, detect, execute, priority in SKILLS:
        brain.register(name, detect, execute, priority=priority)


register_extra = register
