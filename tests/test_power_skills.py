"""Tests for power_skills.py — offline; network & subprocesses mocked."""

import json
import os
import sqlite3
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import power_skills as ps  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute)


class DummyApp:
    pass


@pytest.fixture()
def brain():
    b = RecorderBrain()
    ps.register(b)
    return b


def run(brain, name, cmd):
    detect, execute = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


# ==========================================================================
# Registration
# ==========================================================================

def test_registers_all_24_skills(brain):
    assert len(brain.skills) == 24
    expected = {"ps_git_status", "ps_git_commit", "ps_docker_ps",
                "ps_wikipedia", "ps_define", "ps_news", "ps_solve_equation",
                "ps_derivative", "ps_api_test", "ps_sqlite_query",
                "ps_clipboard_history"}
    assert expected <= set(brain.skills)


# ==========================================================================
# Math solver
# ==========================================================================

def test_linear_solution_steps(brain):
    reply = run(brain, "ps_solve_equation", "solve 2x + 5 = 13")
    assert "x = 4" in reply
    assert "Check: left = right = 13" in reply


def test_quadratic_two_roots(brain):
    reply = run(brain, "ps_solve_equation", "solve x^2 - 5x + 6 = 0")
    assert "x = 3 or x = 2" in reply


def test_quadratic_repeated_root(brain):
    reply = run(brain, "ps_solve_equation", "solve x^2 + 4x + 4 = 0")
    assert "-2" in reply


def test_quadratic_complex_roots(brain):
    reply = run(brain, "ps_solve_equation", "solve x^2 + x + 1 = 0")
    assert "complex conjugate" in reply


def test_no_solution_contradiction(brain):
    reply = run(brain, "ps_solve_equation", "solve 2x + 3 = 2x + 8")
    assert "no solution" in reply


def test_infinite_solutions(brain):
    reply = run(brain, "ps_solve_equation", "solve 2x + 3 = 2x + 3")
    assert "infinite solutions" in reply


def test_derivative_power_rule(brain):
    reply = run(brain, "ps_derivative", "derivative of 3x^3 + 2x")
    assert "9x^2 + 2" in reply


def test_integral_power_rule(brain):
    reply = run(brain, "ps_integral", "integral of 3x^2 + 4x")
    assert "x^3 + 2x^2" in reply and "+ C" in reply


def test_degree_three_rejected_by_solver(brain):
    reply = run(brain, "ps_solve_equation", "solve x^3 - 8 = 0")
    assert "exceeds my local solver" in reply


def test_garbage_polynomial_persona(brain):
    reply = run(brain, "ps_derivative", "derivative of ???")
    assert "polynomial" in reply.lower()


# ==========================================================================
# Git
# ==========================================================================

@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "PROJECT_DIR", str(tmp_path))
    env_ok = subprocess.run(["git", "--version"], capture_output=True)
    if env_ok.returncode != 0:
        pytest.skip("git not installed")
    for args in (("init",), ("config", "user.email", "j@j"),
                 ("config", "user.name", "J")):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True,
                       check=True)
    (tmp_path / "hello.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"],
                   cwd=tmp_path, capture_output=True)
    (tmp_path / "world.txt").write_text("w\n")  # unstaged change
    return tmp_path


def test_git_status_clean_and_dirty(git_repo, brain):
    dirty = run(brain, "ps_git_status", f"git status in {git_repo}")
    assert "1 change(s)" in dirty and "world.txt" in dirty
    subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
    staged = run(brain, "ps_git_status", f"git status in {git_repo}")
    assert "1 change(s)" in staged  # staged still counts as a change


def test_git_commit_flow(git_repo, brain):
    run(brain, "ps_git_add", f"git add . in {git_repo}")
    reply = run(brain, "ps_git_commit",
                f'git commit with message "second" in {git_repo}')
    assert "Committed" in reply and "second" in reply
    log_reply = run(brain, "ps_git_log", f"git log in {git_repo}")
    assert "second" in log_reply and "first" in log_reply


def test_git_branches(git_repo, brain):
    reply = run(brain, "ps_git_branches", f"git branches in {git_repo}")
    assert "master" in reply or "main" in reply


def test_git_not_a_repo(tmp_path, monkeypatch, brain):
    monkeypatch.setattr(ps, "PROJECT_DIR", str(tmp_path))
    empty = tmp_path / "empty"
    empty.mkdir()
    reply = run(brain, "ps_git_status", f"git status in {empty}")
    assert "not a git repository" in reply


def test_git_diff_stat(git_repo, brain):
    (git_repo / "hello.txt").write_text("changed\n")
    reply = run(brain, "ps_git_diff", f"git diff in {git_repo}")
    assert "Unstaged changes" in reply
    assert "hello.txt" in reply


# ==========================================================================
# Docker
# ==========================================================================

def test_docker_missing_binary(monkeypatch, brain):
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda name: None)
    reply = run(brain, "ps_docker_ps", "docker ps")
    assert "not installed" in reply


def test_docker_ps_parses(monkeypatch, brain):
    import shutil as _shutil
    real_which = _shutil.which
    monkeypatch.setattr(_shutil, "which",
                        lambda name: real_which(name) if name == "docker"
                        else "/usr/bin/docker")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[:2] == ["docker", "ps"]:
            return 0, "web\tnginx:latest\tUp 2 hours\napi\tflask\tUp"
        return 1, ""

    monkeypatch.setattr(ps, "_run", fake_run)
    reply = run(brain, "ps_docker_ps", "docker ps running containers")
    assert "2 container(s)" in reply and "nginx" in reply


# ==========================================================================
# Clipboard history (thread disabled under JARVIS_TEST)
# ==========================================================================

@pytest.fixture()
def clip_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TEST", "1")
    monkeypatch.setattr(ps, "CLIPBOARD_FILE", str(tmp_path / "clip.json"))
    ps._clip_history.clear()
    yield
    ps._clip_history.clear()


def test_clipboard_history_roundtrip(clip_env, monkeypatch, brain):
    monkeypatch.setattr(ps, "_clip_text",
                        lambda: "line one\nline two")
    reply = run(brain, "ps_clipboard_history", "what is on my clipboard")
    assert "line one" in reply  # first capture recorded on demand
    second = run(brain, "ps_clipboard_history", "clipboard history")
    assert "1." in second and "line one" in second


def test_clipboard_paste_item(clip_env, monkeypatch, brain):
    copied = {}
    monkeypatch.setattr(ps, "_record_clipboard", lambda t: None)
    with ps._clip_lock:
        ps._clip_history.append("older text")
        ps._clip_history.append("newest payload")

    def fake_copy(text):
        copied["t"] = text
        return True

    monkeypatch.setattr(ps, "_copy_text", fake_copy)
    reply = run(brain, "ps_clipboard_paste", "paste item 1")
    assert "newest payload" in reply
    assert copied["t"] == "newest payload"


def test_clipboard_clear(clip_env, brain):
    with ps._clip_lock:
        ps._clip_history.append("secret")
    reply = run(brain, "ps_clipboard_clear", "clear clipboard history")
    assert "wiped" in reply
    assert len(ps._clip_history) == 0


def test_clipboard_copy_to(clip_env, monkeypatch, brain):
    monkeypatch.setattr(ps, "_copy_text", lambda t: True)
    recorded = []
    monkeypatch.setattr(ps, "_record_clipboard", lambda t: recorded.append(t))
    reply = run(brain, "ps_clipboard_copy", "copy hello jarvis to clipboard")
    assert "Copied" in reply and recorded == ["hello jarvis"]


# ==========================================================================
# System report
# ==========================================================================

def test_system_report_with_psutil(brain):
    reply = run(brain, "ps_system_report", "system report")
    assert "System report" in reply
    assert ("CPU" in reply) or ("telemetry" in reply)


def test_system_report_all_sensors_fail(monkeypatch, brain):
    monkeypatch.setattr(ps, "_cpu_percent_psutil", lambda: None)
    monkeypatch.setattr(ps, "_mem_stats", lambda: (None, None))
    monkeypatch.setattr(ps, "_disk_stats",
                        lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(ps, "_uptime_days", lambda: None)
    monkeypatch.setattr(ps, "_battery_line", lambda: "")
    monkeypatch.setattr(ps, "_top_process", lambda: "")
    reply = run(brain, "ps_system_report", "how is my system")
    assert "telemetry" in reply


# ==========================================================================
# Wikipedia / dictionary / news (network mocked)
# ==========================================================================

class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"content-type": "application/json"}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_wikipedia_summary(monkeypatch, brain):
    payload = {"title": "Alan Turing", "extract":
               "Alan Turing was a mathematician. He founded computer science. "
               "He also broke the Enigma. More sentences follow."}
    monkeypatch.setattr(ps, "_net_get",
                        lambda url, timeout=6, **kw: FakeResponse(payload))
    reply = run(brain, "ps_wikipedia", "wikipedia alan turing")
    assert "Alan Turing" in reply and "Enigma" in reply
    assert "More sentences" not in reply  # capped at three sentences


def test_wikipedia_offline_persona(monkeypatch, brain):
    def boom(url, timeout=6, **kw):
        raise ConnectionError("down")
    monkeypatch.setattr(ps, "_net_get", boom)
    reply = run(brain, "ps_wikipedia", "wiki grace hopper")
    assert "could not reach Wikipedia" in reply


def test_define_word(monkeypatch, brain):
    entry = [{"word": "serendipity",
              "phonetics": [{"text": "/ˌsɛrənˈdɪpɪti/"}],
              "meanings": [{"partOfSpeech": "noun",
                            "definitions": [
                                {"definition": "A happy accident.",
                                 "example": "Finding it was serendipity."}]}]}]
    monkeypatch.setattr(ps, "_net_get",
                        lambda url, timeout=6, **kw: FakeResponse(entry))
    reply = run(brain, "ps_define", "define serendipity")
    assert "happy accident" in reply and "/ˌsɛrənˈdɪpɪti/" in reply


def test_synonyms(monkeypatch, brain):
    entry = [{"word": "fast",
              "meanings": [{"partOfSpeech": "adjective",
                            "synonyms": [{"word": "quick"},
                                         {"word": "rapid"},
                                         {"word": "fast"}],
                            "antonyms": []}]}]
    monkeypatch.setattr(ps, "_net_get",
                        lambda url, timeout=6, **kw: FakeResponse(entry))
    reply = run(brain, "ps_synonyms", "synonyms of fast")
    assert "quick" in reply and "Synonyms" in reply


def test_news_headlines(monkeypatch, brain):
    def fake_get(url, timeout=6, **kw):
        if url.endswith("topstories.json"):
            return FakeResponse([101, 102])
        if "101" in url:
            return FakeResponse({"title": "Rust hits 1.0 again",
                                 "score": 900, "url":
                                 "https://www.rust-lang.org/x"})
        return FakeResponse({"title": "Python 4 announced", "score": 800,
                             "url": ""})
    monkeypatch.setattr(ps, "_net_get", fake_get)
    reply = run(brain, "ps_news", "tech news headlines")
    assert "Rust hits 1.0" in reply and "900 pts" in reply


def test_news_offline(monkeypatch, brain):
    monkeypatch.setattr(ps, "_net_get",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError()))
    reply = run(brain, "ps_news", "hacker news")
    assert "network request failed" in reply


# ==========================================================================
# API testing
# ==========================================================================

def test_api_test_healthy(monkeypatch, brain):
    resp = FakeResponse({"ok": True})
    resp.headers = {"content-type": "application/json"}
    resp.content = b'{"ok": true}'

    class R:
        status_code = 200

    fake = FakeResponse(None)
    fake.status_code = 200
    fake.headers = {"content-type": "application/json"}
    fake.content = b'{"ok": true}'
    monkeypatch.setattr(ps, "_net_get", lambda url, timeout=8, **kw: fake)
    reply = run(brain, "ps_api_test", "test the api https://example.com/health")
    assert "healthy" in reply and "valid JSON confirmed" in reply


def test_api_test_down(monkeypatch, brain):
    def boom(url, timeout=8, **kw):
        raise ConnectionError()
    monkeypatch.setattr(ps, "_net_get", boom)
    reply = run(brain, "ps_api_test", "ping the api https://dead.example.com")
    assert "did not respond" in reply


# ==========================================================================
# SQLite
# ==========================================================================

def test_sqlite_select_roundtrip(tmp_path, monkeypatch, brain):
    db = tmp_path / "data.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE users (id INTEGER, name TEXT)")
    conn.executemany("INSERT INTO users VALUES (?, ?)",
                     [(1, "harsh"), (2, "pepper")])
    conn.commit()
    conn.close()
    monkeypatch.setattr(ps, "PROJECT_DIR", str(tmp_path))
    reply = run(brain, "ps_sqlite_query",
                f'sqlite query data.db select id, name from users')
    assert "harsh" in reply and "2 row(s)" in reply


def test_sqlite_rejects_mutation(tmp_path, monkeypatch, brain):
    db = tmp_path / "data.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(ps, "PROJECT_DIR", str(tmp_path))
    reply = run(brain, "ps_sqlite_query",
                f"sqlite query data.db drop table users")
    assert "Read-only" in reply


def test_sqlite_missing_file(brain, tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "PROJECT_DIR", str(tmp_path))
    reply = run(brain, "ps_sqlite_query", "sqlite query nope.db select 1")
    assert "No database file" in reply


# ==========================================================================
# Detector hygiene
# ==========================================================================

def test_detectors_do_not_fire_on_chit_chat(brain):
    noise = ["what time is it", "tell me a joke", "open youtube",
             "play some music", "flip a coin"]
    for name, (detect, _) in brain.skills.items():
        for cmd in noise:
            assert detect(cmd) is None, \
                f"{name} falsely matched {cmd!r}"
