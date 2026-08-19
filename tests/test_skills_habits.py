"""Tests for skills_habits.py — fully offline habit & streak tracker.

Every effect is local: storage goes through the module seams
(HABITS_FILE monkeypatched into tmp_path, _clock frozen for date
boundary math). No network, no subprocesses, no real time.
"""

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skills_habits as hh  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {"hb_add", "hb_done", "hb_skip", "hb_undo", "hb_remove",
                   "hb_list", "hb_streak", "hb_week", "hb_report"}


class FrozenClock:
    """Freezes hh._clock on a fixed local date; advance() rolls midnight."""

    def __init__(self, y, m, d):
        self.dt = datetime(y, m, d, 9, 0, 0)

    def __call__(self):
        return self.dt

    def advance(self, days=1):
        self.dt += timedelta(days=days)


@pytest.fixture()
def brain():
    b = RecorderBrain()
    hh.register(b)
    return b


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(hh, "HABITS_FILE",
                        str(tmp_path / ".jarvis_habits.json"))
    hh.reset_for_tests()
    yield hh
    hh.reset_for_tests()


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


def inject(env, name, day_marks, created=None):
    """Write marks straight into the ledger (simulates past history)."""
    state = env._load()
    entry = state["habits"].setdefault(
        name, {"created": created or env._today_str(), "days": {}})
    entry["days"].update(day_marks)
    env._save()


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_exactly_the_nine_habit_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


def test_executors_are_fail_soft_wrapped(brain):
    for name in EXPECTED_SKILLS:
        detect, execute, prio = brain.skills[name]
        assert callable(detect) and callable(execute)
        assert execute.__name__ == f"safe_{name}"
        assert prio is False          # domain keyword is unique; no rush


# ==========================================================================
# Detector positives — every skill hears its phrases
# ==========================================================================

def test_add_detector_positives(brain):
    d = brain.skills["hb_add"][0]
    for cmd, name in [("add habit meditate", "meditate"),
                      ("create a new habit called read 20 pages",
                       "read 20 pages"),
                      ("track habit gym", "gym"),
                      ("new habit: stretch", "stretch"),
                      ("start tracking habit journaling", "journaling")]:
        ctx = d(cmd)
        assert ctx is not None, f"hb_add missed {cmd!r}"
        assert ctx["name"].lower() == name, (cmd, ctx["name"])


def test_done_detector_positives(brain):
    d = brain.skills["hb_done"][0]
    for cmd, name in [("habit done meditate", "meditate"),
                      ("mark habit read as done", "read"),
                      ("completed habit read", "read"),
                      ("did my habit stretch", "stretch"),
                      ("checked off habit gym", "gym")]:
        ctx = d(cmd)
        assert ctx is not None, f"hb_done missed {cmd!r}"
        assert ctx["name"].lower() == name, (cmd, ctx["name"])


def test_done_detector_bare_forms_use_no_name(brain):
    d = brain.skills["hb_done"][0]
    for cmd in ["habit done", "mark the habit done", "did my habits"]:
        ctx = d(cmd)
        assert ctx is not None and ctx["name"] is None, cmd


@pytest.mark.parametrize("cmd,name", [
    ("skip habit gym", "gym"),
    ("habit skip gym", "gym"),
    ("mark habit gym skipped", "gym"),
])
def test_skip_detector_positives(brain, cmd, name):
    ctx = brain.skills["hb_skip"][0](cmd)
    assert ctx is not None and ctx["name"].lower() == name


@pytest.mark.parametrize("cmd,named", [
    ("undo habit meditate", True),
    ("undo my habit", False),
    ("habit undo", False),
])
def test_undo_detector_positives(brain, cmd, named):
    ctx = brain.skills["hb_undo"][0](cmd)
    assert ctx is not None
    assert bool(ctx.get("name")) is named


@pytest.mark.parametrize("cmd,name", [
    ("delete habit smoking", "smoking"),
    ("remove habit twitter scrolling", "twitter scrolling"),
])
def test_remove_detector_positives(brain, cmd, name):
    ctx = brain.skills["hb_remove"][0](cmd)
    assert ctx is not None and ctx["name"].lower() == name


@pytest.mark.parametrize("cmd,named", [
    ("habit streak", False),
    ("what's my habit streak", False),
    ("habit streak for meditate", True),
    ("streak of the habit read", True),
    ("meditate habit streak", True),
    ("how long is my habit streak", False),
])
def test_streak_detector_positives(brain, cmd, named):
    ctx = brain.skills["hb_streak"][0](cmd)
    assert ctx is not None, f"hb_streak missed {cmd!r}"
    assert bool(ctx.get("name")) is named, (cmd, ctx.get("name"))


@pytest.mark.parametrize("cmd", [
    "habit report", "monthly habit report", "how am i doing with my habits",
    "habit stats", "report on my habits",
])
def test_report_detector_positives(brain, cmd):
    assert brain.skills["hb_report"][0](cmd) is not None


@pytest.mark.parametrize("cmd", [
    "habit week", "habit grid", "show my habits week", "habits last 7 days",
])
def test_week_detector_positives(brain, cmd):
    assert brain.skills["hb_week"][0](cmd) is not None


@pytest.mark.parametrize("cmd", [
    "show my habits", "list habits", "what are my habits", "my habits",
    "habit status today",
])
def test_list_detector_positives(brain, cmd):
    assert brain.skills["hb_list"][0](cmd) is not None


# ==========================================================================
# Detector negatives — never shadow todo_/task/goal/other domains
# ==========================================================================

NOISE = [
    "what time is it", "tell me a joke", "flip a coin", "open youtube",
    "send an email to dad saying hi", "what is habitat",
]

TODO_SHADOWS = [
    "add a todo buy eggs", "add task fix the bug", "show my todos",
    "mark todo 2 done", "remove todo 1", "todo: buy milk",
    "delete task 3", "add item to shopping list",
]

DOMAIN_COLLISIONS = [
    "im done with work", "skip this song", "skip intro",
    "undo typing", "undo that", "delete todo 4", "remove file old.txt",
    "winning streak in fifa", "calendar week view", "weekly report",
    "expense report", "weather report", "list files", "show my todos",
    "what are my goals", "new playlist", "add milk to shopping list",
]


@pytest.mark.parametrize("cmd", NOISE + TODO_SHADOWS + DOMAIN_COLLISIONS)
def test_no_detector_fires_on_foreign_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


# ==========================================================================
 # Streak math — pure functions, grace days, skip bridges, boundaries
# ==========================================================================

def test_current_streak_empty_log_is_zero():
    assert hh.current_streak({}, "2026-08-24") == 0


def test_current_streak_counts_today_and_history():
    assert hh.current_streak({"2026-08-24": "done"}, "2026-08-24") == 1
    assert hh.current_streak({"2026-08-23": "done",
                              "2026-08-24": "done"}, "2026-08-24") == 2


def test_pending_today_keeps_yesterdays_streak_alive():
    days = {"2026-08-22": "done", "2026-08-23": "done"}
    assert hh.current_streak(days, "2026-08-24") == 2   # grace pass


def test_missed_day_breaks_streak():
    days = {"2026-08-21": "done"}                        # 22 missed
    assert hh.current_streak(days, "2026-08-24") == 0


def test_skip_bridges_but_does_not_extend():
    days = {"2026-08-20": "done", "2026-08-21": "skip",
            "2026-08-22": "done", "2026-08-23": "done"}
    assert hh.current_streak(days, "2026-08-24") == 3    # skip bridged


def test_best_streak_finds_longest_run_and_ignores_gaps():
    days = {f"2026-08-{d:02d}": "done" for d in range(1, 6)}     # run of 5
    days.update({f"2026-08-{d:02d}": "done" for d in range(10, 14)})  # 4
    best = hh.best_streak(days, "2026-08-01", "2026-08-24")
    assert best == 5
    assert hh.best_streak({}, "2026-08-01", "2026-08-24") == 0


def test_pending_day_never_kills_chain_across_midnight(monkeypatch):
    clock = FrozenClock(2026, 8, 24)
    monkeypatch.setattr(hh, "_clock", clock)
    days = {"2026-08-24": "done"}          # marked today, nothing before
    assert hh.current_streak(days, hh._today_str()) == 1
    clock.advance()                        # midnight: today now pending
    assert hh.current_streak(days, hh._today_str()) == 1   # grace holds
    clock.advance()                        # a full missed day: chain dies
    assert hh.current_streak(days, hh._today_str()) == 0


def test_month_stats_math_from_creation_or_month_start():
    days = {f"2026-08-{d:02d}": "done" for d in range(1, 13)}    # 12 done
    st = hh.month_stats(days, "2026-07-01", "2026-08-24")
    assert st["eligible"] == 24 and st["done"] == 12 and st["pct"] == 50
    st2 = hh.month_stats({f"2026-08-{d:02d}": "done"
                          for d in range(10, 25)},
                         "2026-08-10", "2026-08-24")
    assert st2["eligible"] == 15 and st2["done"] == 15 and st2["pct"] == 100


# ==========================================================================
# Skill behaviour end-to-end (with frozen clock)
# ==========================================================================

def test_add_then_done_full_cycle(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    reply = run(brain, "hb_add", "add habit Meditate")
    assert "Meditate" in reply and reply.rstrip().endswith(".")
    data = json.load(open(env.HABITS_FILE))
    assert data["habits"]["Meditate"]["created"] == "2026-08-24"

    done_reply = run(brain, "hb_done", "habit done meditate")
    assert "Logged" in done_reply and "1 day" in done_reply
    # same-day double-marking is idempotent
    again = run(brain, "hb_done", "habit done meditate")
    assert "Already chalked up" in again and "1 day" in again
    data = json.load(open(env.HABITS_FILE))
    assert data["habits"]["Meditate"]["days"] == {"2026-08-24": "done"}


def test_duplicate_add_rejected(brain, env):
    run(brain, "hb_add", "add habit meditate")
    dup = run(brain, "hb_add", "new habit called MEDITATE")
    assert "already" in dup.lower()
    assert len(env.get_habits()) == 1


def test_streak_survives_midnight_then_dies_after_missed_day(
        brain, env, monkeypatch):
    clock = FrozenClock(2026, 8, 24)
    monkeypatch.setattr(env, "_clock", clock)
    run(brain, "hb_add", "add habit meditate")
    inject(env, "meditate", {"2026-08-22": "done", "2026-08-23": "done"},
           created="2026-08-22")

    before = run(brain, "hb_streak", "habit streak meditate")
    assert "2 days" in before                     # yesterday-based chain

    marked = run(brain, "hb_done", "habit done meditate")
    assert "3 days" in marked

    clock.advance()                               # 2026-08-25, unmarked
    still = run(brain, "hb_streak", "habit streak meditate")
    assert "3 days" in still                      # grace pass holds

    clock.advance()                               # 2026-08-26, 25th missed
    broken = run(brain, "hb_streak", "habit streak meditate")
    assert "0 days" in broken


def test_skip_then_upgrade_to_done(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    inject(env, "Gym", {"2026-08-23": "done"}, created="2026-08-01")
    skip_reply = run(brain, "hb_skip", "skip habit gym")
    assert "excused skip" in skip_reply.lower()
    up = run(brain, "hb_done", "habit done gym")
    assert "Upgraded today from skip to done" in up
    data = json.load(open(env.HABITS_FILE))
    assert data["habits"]["Gym"]["days"]["2026-08-24"] == "done"


def test_undo_erases_todays_mark_only(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    inject(env, "Read", {"2026-08-23": "done"}, created="2026-08-01")
    run(brain, "hb_done", "habit done read")
    out = run(brain, "hb_undo", "undo habit read")
    assert "erased" in out.lower()
    data = json.load(open(env.HABITS_FILE))
    assert "2026-08-24" not in data["habits"]["Read"]["days"]
    assert data["habits"]["Read"]["days"]["2026-08-23"] == "done"
    again = run(brain, "hb_undo", "undo habit read")
    assert "nothing logged" in again.lower()


def test_remove_deletes_and_unknown_name_gets_suggestions(
        brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    run(brain, "hb_add", "add habit meditate")
    run(brain, "hb_add", "add habit journaling")
    out = run(brain, "hb_remove", "delete habit meditate")
    assert "deleted" in out.lower()
    assert set(env.get_habits()) == {"journaling"}
    miss = run(brain, "hb_done", "habit done meditate")
    assert "no habit" in miss.lower() or "nearest" in miss.lower()


def test_fuzzy_resolution_marks_close_name(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    run(brain, "hb_add", "add habit drink water")
    reply = run(brain, "hb_done", "habit done drink watter")
    assert "Logged" in reply
    assert env.get_habits()["drink water"]["days"]["2026-08-24"] == "done"


def test_done_without_name_targets_solo_habit_or_asks(brain, env,
                                                      monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    empty = run(brain, "hb_done", "habit done")
    assert "empty" in empty.lower()
    run(brain, "hb_add", "add habit stretch")
    solo = run(brain, "hb_done", "mark the habit done")
    assert "Logged" in solo
    run(brain, "hb_add", "add habit read")
    ambiguous = run(brain, "hb_done", "did my habits")
    assert "which habit" in ambiguous.lower()


def test_list_shows_mixed_statuses(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    inject(env, "Alpha", {"2026-08-24": "done"}, created="2026-08-01")
    inject(env, "Beta", {"2026-08-24": "skip"}, created="2026-08-01")
    inject(env, "Gamma", {}, created="2026-08-01")
    out = run(brain, "hb_list", "show my habits")
    assert "[done today]" in out and "[skipped today]" in out
    assert "[pending today]" in out
    assert "sir" in out.lower()


def test_empty_ledger_personas_on_viewers(brain, env):
    for name, cmd in [("hb_list", "show my habits"),
                      ("hb_streak", "habit streak"),
                      ("hb_week", "habit week"),
                      ("hb_report", "habit report")]:
        out = run(brain, name, cmd)
        assert isinstance(out, str) and out.strip(), name
        assert re.search(r"add (a )?habits?\b", out.lower()), name


def test_week_grid_renders_last_seven_days(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 19))  # Wed
    inject(env, "Yoga", {"2026-08-18": "done", "2026-08-17": "skip"},
           created="2026-08-19")
    out = run(brain, "hb_week", "habit week")
    assert "Habit grid - last 7 days" in out
    assert "Yoga" in out
    row = next(l for l in out.splitlines() if "Yoga" in l)
    assert "#" in row and "s" in row and "-" in row
    assert "Mo" in out.splitlines()[1]            # weekday header present
    assert "Legend:" in out


def test_monthly_report_percentages_and_best_worst(brain, env,
                                                   monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    med_days = {f"2026-08-{d:02d}": "done" for d in range(1, 13)}
    inject(env, "Meditate", med_days, created="2026-07-01")
    read_days = {f"2026-08-{d:02d}": "done" for d in range(10, 25)}
    inject(env, "Read", read_days, created="2026-08-10")
    out = run(brain, "hb_report", "monthly habit report")
    assert "August 2026" in out
    assert "50%" in out and "100%" in out
    assert "Best: Read" in out and "Worst: Meditate" in out
    assert "Month average: 75%" in out
    assert out.rstrip().endswith(".")


# ==========================================================================
# Persistence, atomicity, corruption recovery, containment, concurrency
# ==========================================================================

def test_persistence_roundtrip_across_restart(brain, env, monkeypatch):
    monkeypatch.setattr(env, "_clock", FrozenClock(2026, 8, 24))
    run(brain, "hb_add", "add habit journaling")
    run(brain, "hb_done", "habit done journaling")
    env.reset_for_tests()                          # simulate app restart
    out = run(brain, "hb_list", "show my habits")
    assert "journaling" in out and "[done today]" in out
    assert "1 day" in out or "streak 1" in out


def test_atomic_save_leaves_no_tmp_and_valid_json(brain, env):
    run(brain, "hb_add", "add habit hydrate")
    assert not os.path.exists(env.HABITS_FILE + ".tmp")
    data = json.load(open(env.HABITS_FILE))
    assert "hydrate" in data["habits"]


def test_corrupt_file_starts_fresh_never_crashes(brain, env):
    with open(env.HABITS_FILE, "w", encoding="utf-8") as fh:
        fh.write("{ this is not json {{{")
    out = run(brain, "hb_list", "show my habits")
    assert "empty" in out.lower()                  # fresh, no crash
    add = run(brain, "hb_add", "add habit recovery drill")
    assert "recovery drill" in add
    data = json.load(open(env.HABITS_FILE))         # file healed on save
    assert "recovery drill" in data["habits"]


def test_wrong_typed_json_sanitized(brain, env):
    with open(env.HABITS_FILE, "w", encoding="utf-8") as fh:
        json.dump({"habits": {"Ghost": "not-a-dict",
                              "Ok": {"created": "2026-08-01",
                                     "days": {"2026-08-01": "done",
                                              "bogus": "weird"}}}},
                  fh)
    habits = env.get_habits()
    assert "Ghost" not in habits
    assert habits["Ok"]["days"] == {"2026-08-01": "done"}


def test_wrap_contains_executor_crashes_in_persona(brain, env,
                                                   monkeypatch):
    def boom(name):
        raise RuntimeError("ledger on fire")

    monkeypatch.setattr(env, "add_habit", boom)
    reply = run(brain, "hb_add", "add habit explode")
    assert "misfired" in reply.lower() and reply.endswith(", sir.")


def test_concurrent_mutations_keep_file_consistent(brain, env):
    n = 8
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        ok, canon = env.add_habit(f"habit {i}")
        assert ok
        key, prev, streak = env.mark_habit(canon, "done")
        assert key and prev is None and streak == 1

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    data = json.load(open(env.HABITS_FILE))        # valid JSON after storm
    assert len(data["habits"]) == n
    assert all(e["days"] for e in data["habits"].values())


def test_module_import_is_clean():
    import skills_habits as mod
    # PROJECT_DIR resolves to the project ROOT even though the module
    # lives in the jarvis/ package folder.
    assert mod.PROJECT_DIR.endswith("PythonProject8")
    assert mod.HABITS_FILE.endswith(".jarvis_habits.json")
