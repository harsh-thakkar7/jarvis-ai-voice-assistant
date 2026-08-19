"""Tests for memory_core.py — persistence, eviction, skills."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory_core as mc  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}
        self.superseded = []

    def register(self, name, detect, execute, priority=False, supersedes=()):
        self.skills[name] = (detect, execute)
        if supersedes:
            self.superseded.extend(supersedes)


@pytest.fixture()
def mem(tmp_path):
    mc.reset_for_tests()
    mc.MEMORY_FILE = str(tmp_path / "mem.json")
    yield mc
    mc.reset_for_tests()


def run(mem, name, cmd, brain=None):
    b = brain or RecorderBrain()
    if name not in b.skills:
        mem.register(b)
    d, e = b.skills[name]
    ctx = d(cmd)
    assert ctx is not None, f"{name} missed {cmd!r}"
    return e(None, ctx)


# --------------------------------------------------------------------------
# Core API
# --------------------------------------------------------------------------

def test_remember_recall_roundtrip(mem):
    mem.remember("laptop", "MacBook Pro M4")
    assert mem.recall("LAPTOP ") == "MacBook Pro M4"
    assert mem.recall("nothing") is None


def test_persistence_across_reload(mem, tmp_path):
    mem.remember("wifi", "hunter2")
    mc.reset_for_tests()  # simulate restart
    assert mem.recall("wifi") == "hunter2"


def test_atomic_save_no_tmp_leftover(mem):
    mem.remember("a", "b")
    assert not os.path.exists(mem.MEMORY_FILE + ".tmp")
    data = json.load(open(mem.MEMORY_FILE))
    assert data["facts"]["a"]["text"] == "b"


def test_eviction_cap(mem):
    for i in range(mem.FACTS_CAP + 5):
        mem.remember(f"topic{i}", f"value {i}")
    facts = mem.all_facts()
    assert len(facts) == mem.FACTS_CAP
    assert "topic0" not in facts          # oldest evicted
    assert "topic9" in facts


def test_suggest_topics_nearest(mem):
    mem.remember("my laptop", "mac")
    mem.remember("my laptimer", "timer")
    near = mem.suggest_topics("my laptopx")
    assert near and ("my laptop" in near or "my laptimer" in near)


# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------

def test_mm_remember_topic_is_form(mem):
    reply = run(mem, "mm_remember",
                "remember that my editor is pycharm")
    assert "memory" in reply.lower()
    assert mem.recall("my editor") == "pycharm"


def test_mm_remember_freeform(mem):
    run(mem, "mm_remember", "remember: I take my coffee at 7am sharp")
    fact = mem.recall("i take my")
    assert fact and "coffee" in fact


def test_mm_recall_hit_and_miss(mem):
    mem.remember("project jarvis", "voice assistant upgrade")
    hit = run(mem, "mm_recall", "what did i say about project jarvis")
    assert "voice assistant upgrade" in hit
    miss = run(mem, "mm_recall", "recall quantum toasters")
    assert "no memory" in miss.lower() or "nothing" in miss.lower()


def test_mm_forget(mem):
    mem.remember("gym plan", "push pull legs")
    out = run(mem, "mm_forget_fact", "forget about gym plan")
    assert "erased" in out.lower()
    assert mem.recall("gym plan") is None
    out2 = run(mem, "mm_forget_fact", "forget about ghost topic")
    assert "never had" in out2.lower()


def test_mm_about_me_digest(mem):
    mem.remember("name", "Harsh")
    out = run(mem, "mm_about_me", "what do you know about me")
    assert "Harsh" in out
    empty = run(mem, "mm_about_me", "what do you know about me")
    assert isinstance(empty, str)


def test_mm_recent_log(mem):
    mem.log_turn("YOU", "write code for fibonacci")
    mem.log_turn("JARVIS", "Built locally, sir")
    out = run(mem, "mm_recent", "what did we discuss")
    assert "fibonacci" in out and "Built locally" in out


def test_register_adds_five_skills():
    b = RecorderBrain()
    mc.register(b)
    assert set(b.skills) == {"mm_remember", "mm_recall", "mm_forget_fact",
                             "mm_about_me", "mm_recent"}


def test_detector_noise():
    b = RecorderBrain()
    mc.register(b)
    noise = ["what time is it", "tell me a joke", "flip a coin",
             "open youtube"]
    for name, (d, _) in b.skills.items():
        for cmd in noise:
            assert d(cmd) is None, f"{name} fired on {cmd!r}"


def test_executor_exception_contained(mem, monkeypatch):
    b = RecorderBrain()
    mem.register(b)
    monkeypatch.setattr(mem, "remember",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    d, e = b.skills["mm_remember"]
    ctx = d("remember that test fails hard")
    out = e(None, ctx)
    assert "misfired" in out.lower()


def test_supersedes_legacy_remember_recall():
    b = RecorderBrain()
    mc.register(b)
    assert set(b.superseded) == {"remember", "recall"}
