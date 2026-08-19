"""Tests for focus_pomodoro_brain.py — deterministic, sleep-free.

The engine's ``_now()``/``_today()`` seams are monkeypatched onto fake
clock/date objects, so phase transitions are driven by advancing the
fake clock and calling ``_tick()`` directly. One test exercises the real
background thread end-to-end (event-bounded, still under a second).
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import focus_pomodoro_brain as fp  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class RecorderApp:
    """Duck-typed app that records say() and _notify() traffic."""

    def __init__(self):
        self.said = []
        self.notified = []
        self.explode = False

    def say(self, text):
        if self.explode:
            raise RuntimeError("speakers unplugged")
        self.said.append(text)

    def _notify(self, title, message):
        if self.explode:
            raise RuntimeError("notification bus down")
        self.notified.append((title, message))


class DummyApp:
    pass


class FakeClock:
    def __init__(self, start=10_000.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


EXPECTED_SKILLS = {"fx_start", "fx_status", "fx_stop"}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    fp.register(b)
    return b


@pytest.fixture(autouse=True)
def fresh_manager(monkeypatch):
    """Fresh singleton per test; teardown always kills tracker threads."""
    mgr = fp.PomodoroManager(poll=0.005)
    monkeypatch.setattr(fp, "_MANAGER", mgr)
    yield mgr
    mgr.shutdown()
    for stray in _LIVE:                     # engine-local managers too
        stray.shutdown()
    _LIVE.clear()


_LIVE: list[fp.PomodoroManager] = []


def make_mgr(clock, **kw):
    """Engine-only manager with an injected fake clock (tracked for teardown)."""
    kw.setdefault("poll", 0.005)
    mgr = fp.PomodoroManager(**kw)
    mgr._now = clock
    _LIVE.append(mgr)
    return mgr


def clocked(mgr):
    """Attach a FakeClock to an existing manager; returns the clock."""
    clock = FakeClock()
    mgr._now = clock
    return clock


def finish_phase(mgr, clock):
    """Advance the fake clock exactly past the current phase's deadline."""
    remaining = mgr.status()["remaining"]
    assert remaining > 0
    clock.advance(remaining + 1)
    assert mgr._tick() is True
    return mgr.status()


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx), ctx


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_exactly_three_fx_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS
    for name, (_d, _e, prio) in brain.skills.items():
        assert name.startswith("fx_")
        assert prio is True          # explicit intents preempt advice text


def test_register_wires_detect_and_wrapped_execute(brain):
    for name, (detect, execute, _prio) in brain.skills.items():
        assert callable(detect) and callable(execute)
        assert execute.__name__ == f"safe_{name}"   # _wrap containment tag


def test_wrap_contains_executor_crashes(brain, monkeypatch):
    def boom():
        raise RuntimeError("engine seized")

    monkeypatch.setattr(fp, "get_manager", boom)
    reply, _ctx = run(brain, "fx_start", "start pomodoro")
    assert "misfired" in reply and reply.endswith(", sir.")


# ==========================================================================
# Detectors — positives, negatives, collision avoidance
# ==========================================================================

@pytest.mark.parametrize("cmd,name", [
    ("start a focus session", "fx_start"),
    ("start pomodoro", "fx_start"),
    ("begin deep work", "fx_start"),
    ("start focus mode", "fx_start"),
    ("launch a pomodoro session", "fx_start"),
    ("start a 50 minute focus session", "fx_start"),
    ("focus status", "fx_status"),
    ("pomodoro status", "fx_status"),
    ("status of my focus session", "fx_status"),
    ("how's my focus going", "fx_status"),
    ("end focus session", "fx_stop"),
    ("stop pomodoro", "fx_stop"),
    ("end focus", "fx_stop"),
    ("cancel the focus mode", "fx_stop"),
])
def test_detectors_fire_on_specific_phrases(brain, cmd, name):
    for other in EXPECTED_SKILLS - {name}:
        ctx = brain.skills[other][0](cmd)
        assert ctx is None, f"{other} collided with {cmd!r}"
    assert brain.skills[name][0](cmd) is not None


@pytest.mark.parametrize("cmd", [
    "set a timer",
    "timer",
    "set a timer for 5 minutes",
    "stopwatch",
    "start the stopwatch",
    "remind me to call mom",
    "set a reminder for 6 pm",
    "focus",                      # bare "focus" must NOT fire
    "i need to focus on work",
    "stop the stopwatch please",
    "what time is it",
    "tell me a joke",
])
def test_detectors_ignore_collisions_and_bare_focus(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


# ==========================================================================
# Duration parsing
# ==========================================================================

@pytest.mark.parametrize("cmd,seconds", [
    ("start a 50 minute focus session", 3000),
    ("start a 90 minute pomodoro", 5400),
    ("start a half hour focus session", 1800),
    ("start a quarter hour deep work", 900),
    ("start a 1 hour focus session", 3600),
    ("start pomodoro", None),
])
def test_duration_parsing(brain, cmd, seconds):
    _reply, ctx = run(brain, "fx_start", cmd)
    assert ctx["work_s"] == seconds


def test_duration_clamped_to_bounds(brain):
    _reply, ctx = run(brain, "fx_start",
                      "start a 9999 minute focus session")
    assert ctx["work_s"] == 599940                   # raw parse
    snap = fp.get_manager().status()
    assert snap["running"]
    assert snap["phase_len"] == fp.MAX_WORK_S        # engine clamps


# ==========================================================================
# Lifecycle: start / status / stop
# ==========================================================================

def test_start_confirms_and_engine_runs(brain):
    reply, _ctx = run(brain, "fx_start", "start pomodoro")
    assert "started" in reply.lower() and reply.endswith(", sir.")
    snap = fp.get_manager().status()
    assert snap["running"] and snap["phase"] == "work"
    assert snap["round"] == 1 and snap["remaining"] == 1500


def test_default_durations_are_classic_pomodoro():
    mgr = fp.PomodoroManager()
    assert (mgr.work_s, mgr.short_s, mgr.long_s,
            mgr.rounds_per_long) == (1500, 300, 900, 4)


def test_custom_duration_reaches_engine(brain):
    run(brain, "fx_start", "start a 50 minute focus session")
    snap = fp.get_manager().status()
    assert snap["phase_len"] == 3000 and snap["remaining"] == 3000


def test_status_idle_persona(brain):
    reply, _ctx = run(brain, "fx_status", "focus status")
    assert "no focus session" in reply.lower()
    assert reply.endswith(", sir.")


def test_status_running_reports_phase_round_remaining_today(brain):
    mgr = fp.get_manager()
    clock = clocked(mgr)
    mgr.start_session(app=None)
    clock.advance(1200)
    reply = brain.skills["fx_status"][1](DummyApp(), {"cmd": "x"})
    assert "round 1" in reply and "deep work" in reply
    assert "5m 00s" in reply and "0 session(s)" in reply
    assert reply.endswith(", sir.")


def test_double_start_is_protected(brain):
    first, _c1 = run(brain, "fx_start", "start pomodoro")
    second, _c2 = run(brain, "fx_start", "start a 90 minute pomodoro")
    assert "started" in first.lower()
    assert "already underway" in second.lower()
    snap = fp.get_manager().status()
    assert snap["running"] and snap["remaining"] == 1500   # original kept


def test_end_without_session_persona(brain):
    reply, _ctx = run(brain, "fx_stop", "end focus session")
    assert "no focus session to end" in reply.lower()
    assert reply.endswith(", sir.")


def test_stop_reports_stats(brain):
    mgr = fp.get_manager()
    clock = clocked(mgr)
    mgr.start_session(app=None)
    finish_phase(mgr, clock)               # round 1 complete -> short break
    reply, _ctx = run(brain, "fx_stop", "end focus session")
    assert "1 round" in reply and "ended early" in reply.lower()
    assert "25 minute(s)" in reply         # 1500s of deep work banked
    assert reply.endswith(", sir.")
    assert fp.get_manager().status()["running"] is False


# ==========================================================================
# Phase transitions (fake clock, no sleeps)
# ==========================================================================

def test_work_rolls_to_short_break_then_back(brain):
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=60, short_s=15, long_s=45)
    app = RecorderApp()
    mgr.start_session(app=app)

    clock.advance(61)
    assert mgr._tick() is True
    snap = mgr.status()
    assert snap["phase"] == "short_break" and snap["round"] == 1
    assert snap["completed_today"] == 1

    clock.advance(16)
    mgr._tick()
    snap = mgr.status()
    assert snap["phase"] == "work" and snap["round"] == 2
    assert len(app.said) >= 2      # both transitions announced


def test_long_break_after_every_four_rounds():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=10, short_s=5, long_s=30)
    mgr.start_session(app=None)
    snap = mgr.status()
    for i in range(1, 5):
        snap = finish_phase(mgr, clock)          # complete work round i
        assert snap["completed_today"] == i
        want = "long_break" if i % 4 == 0 else "short_break"
        assert snap["phase"] == want
        if want != "long_break":
            snap = finish_phase(mgr, clock)      # burn the short break
            assert snap["phase"] == "work" and snap["round"] == i + 1
            assert snap["completed_today"] == i
    snap = finish_phase(mgr, clock)              # burn the long break
    assert snap["phase"] == "work" and snap["round"] == 5
    assert snap["completed_today"] == 4


def test_single_tick_catches_up_multiple_due_phases():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=10, short_s=5, long_s=30)
    mgr.start_session(app=None)
    clock.advance(10 + 5 + 10 + 5)          # two full rounds due at once
    assert mgr._tick() is True
    snap = mgr.status()
    assert snap["phase"] == "work" and snap["round"] == 3


def test_tick_before_deadline_is_noop():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=60)
    mgr.start_session(app=None)
    clock.advance(59)
    assert mgr._tick() is False
    assert mgr.status()["phase"] == "work"


def test_daily_counter_resets_on_new_day():
    clock = FakeClock()
    mgr = make_mgr(clock)
    day = [object()]
    mgr._today = lambda: day[0]
    mgr.start_session(app=None)
    finish_phase(mgr, clock)                # complete a work round
    assert mgr.status()["completed_today"] == 1
    day[0] = object()                       # calendar rolled over
    snap = finish_phase(mgr, clock)         # burn the break -> round 2
    assert snap["completed_today"] == 0 and snap["round"] == 2


# ==========================================================================
# Notifications on transition
# ==========================================================================

def test_transition_notifies_via_say_then_notify():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=60, short_s=15)
    app = RecorderApp()
    mgr.start_session(app=app)
    clock.advance(61)
    mgr._tick()
    assert len(app.said) == 1 and "break" in app.said[0].lower()
    assert app.notified and app.notified[0][0] == "JARVIS Focus"
    assert app.notified[0][1] == app.said[0]
    assert app.said[0].endswith(".")


def test_transition_survives_exploding_app():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=60)
    app = RecorderApp()
    app.explode = True
    mgr.start_session(app=app)
    clock.advance(61)
    try:
        assert mgr._tick() is True          # must not raise
    except Exception as exc:                # pragma: no cover
        pytest.fail(f"transition crashed: {exc}")
    assert mgr.status()["phase"] == "short_break"


def test_announce_handles_missing_app_methods():
    class Bare:
        pass

    fp._announce(Bare(), "hello")           # no attributes: silent no-op
    fp._announce(None, "hello")


def test_announce_falls_back_to_one_arg_notify():
    seen = []

    class OneArgApp:
        def _notify(self, text):            # duck type without title
            seen.append(text)

    fp._announce(OneArgApp(), "phase change")
    assert seen == ["phase change"]


# ==========================================================================
# Background thread (the only place real waiting happens; event-bounded)
# ==========================================================================

def test_background_thread_transitions_and_shutdown():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=40, poll=0.002)
    app = RecorderApp()
    broke = threading.Event()

    def noting_say(text):
        app.said.append(text)
        if "break" in text.lower():
            broke.set()

    app.say = noting_say
    mgr.start_session(app=app)
    assert mgr.tracker_alive
    clock.advance(41)
    assert broke.wait(timeout=2.0), "tracker never announced the break"
    mgr.shutdown()
    assert not mgr.tracker_alive


def test_thread_survives_internal_errors():
    clock = FakeClock()
    mgr = make_mgr(clock, work_s=40, poll=0.002)
    calls = []

    def exploding_tick():
        calls.append(1)
        raise RuntimeError("tick exploded")

    mgr._tick = exploding_tick
    mgr.start_session(app=None)
    import time as _time
    deadline = _time.time() + 2.0
    while _time.time() < deadline and len(calls) < 3:
        _time.sleep(0.01)
    mgr.shutdown()
    assert len(calls) >= 3                  # loop kept ticking past errors
    assert not mgr.tracker_alive


def test_executor_returns_immediately(brain):
    import time as _time

    t0 = _time.monotonic()
    reply, _ctx = run(brain, "fx_start", "start pomodoro")
    elapsed = _time.monotonic() - t0
    assert elapsed < 0.5                    # never blocks on the clock
    assert "started" in reply.lower()


# ==========================================================================
# Persona
# ==========================================================================

@pytest.mark.parametrize("name,cmd", [
    ("fx_start", "start pomodoro"),
    ("fx_status", "pomodoro status"),
    ("fx_stop", "stop pomodoro"),
])
def test_replies_keep_the_persona(brain, name, cmd):
    reply, _ctx = run(brain, name, cmd)
    assert reply.rstrip().endswith(", sir.")
