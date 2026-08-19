"""Tests for bot_status_panel.py — pure logic only, zero tkinter windows.

Covers gather_status against fake bots (timers, pomodoro absent/running,
psutil missing/faked, jarvis_memory.json missing/corrupt/valid, network
probe monkeypatched both ways, empty command history), render_rows
sanity, the runtime menu append via a fake menu object, the idempotent
attach guard, off-main-thread command dispatch, and an offline check that
every clickable row's command really routes through Brain.think.
"""

import builtins
import io
import json
import os
import subprocess
import sys
import threading
from collections import deque
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot_status_panel as bsp  # noqa: E402

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==========================================================================
# Fakes
# ==========================================================================

class FakeMenu:
    def __init__(self):
        self.commands = []

    def add_command(self, label="", command=None):
        self.commands.append((label, command))


class FakeBot:
    def __init__(self):
        self.menu = FakeMenu()
        self._active_timers = []
        self.voice_history = deque(maxlen=10)
        self.calls = []
        self.call_threads = []

    def _process(self, cmd):
        self.calls.append(cmd)
        self.call_threads.append(threading.current_thread())


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture(scope="module")
def brain():
    from brain import Brain

    return Brain(app=None)


# ==========================================================================
# Import hygiene: module imports clean with no tkinter loaded
# ==========================================================================

def test_module_imports_without_tk():
    code = ("import sys; sys.path.insert(0, 'jarvis'); "
            "import bot_status_panel; "
            "assert 'tkinter' not in sys.modules, 'tk leaked at import'")
    proc = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_DIR,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr


# ==========================================================================
# attach(): menu append + idempotency guard
# ==========================================================================

def test_attach_appends_menu_item_once_and_is_idempotent(bot):
    ctl = bsp.attach(bot)
    assert len(bot.menu.commands) == 1
    label, cmd = bot.menu.commands[0]
    assert "Status Panel" in label
    assert callable(cmd)

    again = bsp.attach(bot)
    assert again is ctl
    assert len(bot.menu.commands) == 1  # never duplicated, never rebuilt

    ctl.detach()
    assert getattr(bot, "_clicky_status", None) is None


def test_attach_survives_bot_without_menu():
    class BareBot:
        pass

    bare = BareBot()
    ctl = bsp.attach(bare)  # fail-soft: no menu attr at all
    assert ctl is not None
    ctl.detach()


# ==========================================================================
# gather_status rows
# ==========================================================================

def _values(bot):
    return {label: value for _icon, label, value, _cmd
            in bsp.gather_status(bot)}


def test_row_order_and_labels(bot):
    rows = bsp.gather_status(bot)
    labels = [r[1] for r in rows]
    icons = [r[0] for r in rows]
    assert labels == ["Timers", "Focus", "Power", "Net", "Todos",
                      "Last cmd"]
    assert len(set(icons)) == len(icons) and all(icons)


def test_timers_count_and_total_minutes(bot):
    t1 = threading.Timer(600, lambda: None)   # not started -> no thread
    t2 = threading.Timer(300, lambda: None)
    try:
        bot._active_timers = [t1, t2, object()]  # object() lacks .interval
        val = _values(bot)["Timers"]
        assert val == "3 · 15m"

        bot._active_timers = []
        assert _values(bot)["Timers"] == "0"
    finally:
        for t in (t1, t2):
            t.cancel()


def test_pomodoro_module_absent_falls_back_to_idle(bot, monkeypatch):
    monkeypatch.setitem(sys.modules, "focus_pomodoro_brain", None)
    assert _values(bot)["Focus"] == "idle"


def test_pomodoro_idle_when_no_session(bot, monkeypatch):
    import focus_pomodoro_brain as fp
    mgr = SimpleNamespace(status=lambda: {"running": False,
                                          "completed_today": 1})
    monkeypatch.setattr(fp, "get_manager", lambda: mgr)
    assert _values(bot)["Focus"] == "idle"


def test_pomodoro_running_shows_phase_and_clock(bot, monkeypatch):
    import focus_pomodoro_brain as fp
    snap = {"running": True, "phase": "work", "round": 2,
            "remaining": 1500, "phase_len": 2700, "completed_today": 3,
            "rounds_this_session": 1}
    mgr = SimpleNamespace(status=lambda: snap)
    monkeypatch.setattr(fp, "get_manager", lambda: mgr)
    val = _values(bot)["Focus"]
    assert "deep work" in val and "25:00" in val
    mgr_broken = SimpleNamespace(status=lambda: (_ for _ in ()).throw(
        RuntimeError("boom")))
    monkeypatch.setattr(fp, "get_manager", lambda: mgr_broken)
    assert _values(bot)["Focus"] == "idle"


def test_psutil_missing_fallback_string(monkeypatch):
    monkeypatch.setattr(bsp, "psutil", None)
    assert bsp._power_value() == "n/a"


def test_psutil_battery_and_cpu(monkeypatch):
    fake_psutil = SimpleNamespace(
        sensors_battery=lambda: SimpleNamespace(percent=87.4,
                                                power_plugged=True),
        cpu_percent=lambda interval=None: 12.3)
    monkeypatch.setattr(bsp, "psutil", fake_psutil)
    val = bsp._power_value()
    assert "87%" in val and "⚡" in val and "CPU 12%" in val

    fake_psutil = SimpleNamespace(
        sensors_battery=lambda: SimpleNamespace(percent=50.0,
                                                power_plugged=False),
        cpu_percent=lambda interval=None: 7.0)
    monkeypatch.setattr(bsp, "psutil", fake_psutil)
    val = bsp._power_value()
    assert "50%" in val and "⚡" not in val

    broken = SimpleNamespace(sensors_battery=lambda: (_ for _ in ()).throw(
        Exception("no battery")), cpu_percent=lambda interval=None: 3.0)
    monkeypatch.setattr(bsp, "psutil", broken)
    assert _values(FakeBot())["Power"].startswith("CPU")


def test_net_online(monkeypatch):
    calls = []

    def fake_connect(addr, timeout=None):
        calls.append((addr, timeout))
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(bsp, "socket",
                        SimpleNamespace(create_connection=fake_connect))
    assert bsp._net_value() == "Online"
    assert calls and calls[0][0] == ("1.1.1.1", 443)
    assert calls[0][1] <= 1.0


def test_net_offline(monkeypatch):
    def refused(addr, timeout=None):
        raise OSError("network unreachable")

    monkeypatch.setattr(bsp, "socket",
                        SimpleNamespace(create_connection=refused))
    assert bsp._net_value() == "Offline"


def test_todos_missing_file_counts_zero(bot, monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("no memory file")

    monkeypatch.setattr(builtins, "open", boom)
    assert _values(bot)["Todos"] == "none"


def test_todos_corrupt_json_counts_zero(bot, monkeypatch):
    monkeypatch.setattr(builtins, "open",
                        lambda *a, **k: io.StringIO("{not json!!"))
    assert _values(bot)["Todos"] == "none"


def test_todos_counts_only_incomplete(bot, monkeypatch):
    data = json.dumps({"todos": [
        {"text": "a", "done": False},
        {"text": "b", "done": True},
        {"text": "c", "done": False},
    ]})
    monkeypatch.setattr(builtins, "open",
                        lambda *a, **k: io.StringIO(data))
    assert _values(bot)["Todos"] == "2 open"


def test_last_cmd_empty_history_and_populated(bot):
    assert _values(bot)["Last cmd"] == bsp.EMPTY
    bot.voice_history.append("what time is it")
    val = _values(bot)["Last cmd"]
    assert "what time" in val
    bot.voice_history.append("x" * 80)
    assert len(_values(bot)["Last cmd"]) <= 30


# ==========================================================================
# render_rows
# ==========================================================================

def test_render_rows_sanity():
    rows = [("⏱", "Timers", "2 · 15m", None),
            ("🌐", "Net", "Online", "run a speed test")]
    lines = bsp.render_rows(rows)
    assert len(lines) == len(rows)
    assert lines[0].startswith("⏱") and "Timers" in lines[0]
    assert "2 · 15m" in lines[0]
    assert "Online" in lines[1]
    assert all(isinstance(l, str) and l.strip() for l in lines)
    assert bsp.render_rows([]) == []
    assert bsp.render_rows(None) == []


# ==========================================================================
# Click wiring: commands route through Brain.think (verified offline)
# ==========================================================================

def test_click_commands_route_through_brain(brain, bot):
    routed = {
        "focus status": "fx_status",
        "run a speed test": "nd_speed_test",
        "show my todos": "todo_show",
    }
    for cmd, expected_skill in routed.items():
        hit = brain.think(cmd)
        assert hit is not None, "%r does not route" % cmd
        skill, _ctx = hit
        assert skill.name == expected_skill

    cmds = {label: cmd for _i, label, _v, cmd in bsp.gather_status(bot)}
    for row_label, cmd in (("Focus", "focus status"),
                           ("Net", "run a speed test"),
                           ("Todos", "show my todos")):
        assert cmds[row_label] == cmd
        assert cmds[row_label] in routed
    for inert in ("Timers", "Power", "Last cmd"):
        assert cmds[inert] is None


def test_row_click_dispatch_runs_off_main_thread(bot):
    done = threading.Event()
    original_process = bot._process

    def spy(cmd):
        original_process(cmd)
        done.set()

    bot._process = spy
    ctl = bsp.attach(bot)
    try:
        ctl.dispatch("show my todos")
        assert done.wait(timeout=5), "command never reached the pipeline"
        assert bot.calls == ["show my todos"]
        worker = bot.call_threads[0]
        assert worker is not threading.main_thread()
        assert "status-panel-cmd" in (worker.name or "")
        assert bot.voice_history[-1] == "show my todos"
    finally:
        ctl.detach()


def test_dispatch_fail_soft_on_bot_without_pipeline():
    class MuteBot:
        voice_history = deque()

    mute = MuteBot()
    bsp._dispatch_text(mute, "focus status")  # must not raise
