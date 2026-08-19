"""Tests for agent_loop.py — background agent jobs, checkpointing, skills.

Offline & deterministic: the STEP_RUNNERS registry is monkeypatched with
fake recording runners; brain._llm is patched to None or a stub.
"""

import json
import os
import sys
import threading
import time
from queue import Queue
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_loop as al  # noqa: E402

DEADLINE = 5.0


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute)


def make_runner(recorder, name, out="ok", gate=None, err=None):
    def runner(app, payload):
        recorder.calls.append((name, payload))
        if gate is not None:
            recorder.started.set()
            assert gate.wait(DEADLINE), f"{name} gate never opened"
        if err is not None:
            raise err
        return out
    runner.__name__ = f"fake_{name}"
    return runner


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(al, "GENERATED_DIR", str(tmp_path / "generated"))
    monkeypatch.setattr(al, "_loaded", False)
    monkeypatch.setattr(al, "_llm", None)
    monkeypatch.setattr(al, "ON_JOB_DONE", None)
    al._notified_jobs.clear()
    al.AGENT_JOBS.clear()
    with al._run_cond:
        al._active = 0
    box = SimpleNamespace(tmp=tmp_path,
                          jobs_file=tmp_path / "jobs.json",
                          calls=[], started=threading.Event())
    yield box
    with al._run_cond:
        al._active = 0


def wait_until(pred, timeout=DEADLINE):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def checkpoint_state(path, jid):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["jobs"][jid]


# ==========================================================================
# Planning
# ==========================================================================

def test_plan_fallback_without_llm(env):
    steps = al.plan_task("write a mars report")
    assert [s["name"] for s in steps] == \
        ["research", "summarize", "write_file"]
    assert all(s["status"] == "pending" for s in steps)
    assert steps[0]["args"]["topic"] == "write a mars report"
    assert steps[1]["args"]["source"] == "research"
    assert steps[2]["args"]["content_from"] == "summarize"


def test_plan_llm_json_parsed_and_constrained(env, monkeypatch):
    raw = ('Sure! Here is the plan:\n```json\n'
           '[{"tool": "research", "args": {"topic": "quantum dots"}},'
           ' {"tool": "hack_the_planet"},'
           ' {"tool": "list_files", "args": {"dir": "/tmp"}},'
           ' {"tool": "summarize", "args": {"source": "research"}}]\n'
           '```')
    monkeypatch.setattr(al, "_llm", lambda app, prompt: raw)
    steps = al.plan_task("study quantum dots")
    assert [s["name"] for s in steps] == ["research", "list_files", "summarize"]
    assert steps[0]["args"]["topic"] == "quantum dots"


def test_plan_llm_garbage_falls_back(env, monkeypatch):
    monkeypatch.setattr(al, "_llm", lambda app, prompt: "no arrays here, sorry")
    steps = al.plan_task("anything")
    assert [s["name"] for s in steps] == \
        ["research", "summarize", "write_file"]


# ==========================================================================
# Happy path + mid-way checkpoint persistence
# ==========================================================================

def test_full_happy_run_persists_checkpoint_midway(env, monkeypatch):
    release = threading.Event()

    def gated_summarize(app, text):
        env.calls.append(("summarize", text))
        env.started.set()          # step 1 (research) already done
        release.wait(DEADLINE)
        return "SUMMARY"

    registry = {
        "research": make_runner(env, "research", out="brief on mars"),
        "summarize": gated_summarize,
        "write_file": make_runner(env, "write_file", out="Wrote 7 chars to x"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)

    job = al.create_job("study mars", app=None)
    th = al.launch_job(job["id"], None)

    # Step 1 completes while the job is still running...
    assert wait_until(
        lambda: os.path.exists(env.jobs_file)
        and checkpoint_state(env.jobs_file, job["id"])["steps"][0]["status"]
        == "done"), "checkpoint missing after step 1"
    assert env.started.wait(DEADLINE)          # now parked mid-step-2
    snap = checkpoint_state(env.jobs_file, job["id"])
    assert snap["state"] == "running"          # persisted MID-way
    assert snap["steps"][1]["status"] in {"pending", "done"}

    release.set()
    th.join(DEADLINE)
    final = al.AGENT_JOBS[job["id"]]
    assert final["state"] == "done"
    assert all(s["status"] == "done" for s in final["steps"])
    assert checkpoint_state(env.jobs_file, job["id"])["state"] == "done"
    assert ("summarize", "brief on mars") in env.calls


# ==========================================================================
# Failure continuation rules
# ==========================================================================

def test_failed_step_continues_but_marks_job_failed(env, monkeypatch):
    registry = {
        "research": make_runner(env, "research", err=RuntimeError("net down")),
        "summarize": make_runner(env, "summarize", out="partial summary"),
        "write_file": make_runner(env, "write_file",
                                  out="Wrote 3 chars to f.txt"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("task a", app=None)
    report = al.run_job(job["id"], None)

    st = {s["name"]: s for s in job["steps"]}
    assert st["research"]["status"] == "failed"
    assert "net down" in st["research"]["note"]
    assert st["summarize"]["status"] == "done"      # execution CONTINUED
    assert st["write_file"]["status"] == "done"     # summarize still fed it
    assert job["state"] == "failed"                 # but overall failed
    assert "FAIL research" in report or "[FAIL] research" in report


def test_write_file_skipped_when_its_source_failed(env, monkeypatch):
    registry = {
        "research": make_runner(env, "research", err=RuntimeError("boom")),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="should not run"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("task b", app=None)
    job["steps"][2]["args"]["content_from"] = "research"  # depend on failure
    al.run_job(job["id"], None)

    st = {s["name"]: s for s in job["steps"]}
    assert st["write_file"]["status"] == "skipped"
    assert "research" in st["write_file"]["note"]
    assert not any(c[0] == "write_file" for c in env.calls)


def test_unknown_tool_fails_step_without_killing_job(env, monkeypatch):
    registry = {"research": make_runner(env, "research", out="r")}
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("task c", app=None)
    job["steps"] = [
        {"name": "teleport", "args": {}, "status": "pending", "note": ""},
        {"name": "research", "args": {}, "status": "pending", "note": ""},
    ]
    al.run_job(job["id"], None)
    assert job["steps"][0]["status"] == "failed"
    assert "unknown tool" in job["steps"][0]["note"]
    assert job["steps"][1]["status"] == "done"
    assert job["state"] == "failed"


# ==========================================================================
# Cancellation
# ==========================================================================

def test_cancel_running_job_skips_rest(env, monkeypatch):
    release = threading.Event()
    registry = {
        "research": make_runner(env, "research", out="R", gate=release),
        "summarize": make_runner(env, "summarize", out="S"),
        "write_file": make_runner(env, "write_file", out="W"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("long task", app=None)
    th = al.launch_job(job["id"], None)

    assert env.started.wait(DEADLINE)          # research is running
    msg = al.cancel_job(job["id"])
    assert "cancelling agent job" in msg.lower() and job["id"] in msg
    release.set()
    th.join(DEADLINE)

    assert job["state"] == "failed"
    assert "cancel" in (job["note"] or "").lower()
    statuses = {s["name"]: s["status"] for s in job["steps"]}
    assert statuses["summarize"] == "skipped"
    assert statuses["write_file"] == "skipped"
    assert not any(c[0] in {"summarize", "write_file"} for c in env.calls)


def test_cancel_queued_job_runs_nothing(env, monkeypatch):
    gates = [threading.Event(), threading.Event(), threading.Event()]
    calls = []
    lock = threading.Lock()

    def routed_research(app, topic):
        idx = int(str(topic).split()[-1])
        with lock:
            calls.append(topic)
        gates[idx].wait(DEADLINE)
        return f"x{idx}"

    registry = {"research": routed_research,
                "summarize": lambda a, t: "s",
                "write_file": lambda a, args_: "w",
                "list_files": lambda a, d: ""}
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)

    jobs = [al.create_job(f"queued test {i}", app=None) for i in range(3)]
    threads = [al.launch_job(j["id"], None) for j in jobs]
    try:
        # cap is 2 -> exactly two start; the third stays queued
        assert wait_until(lambda: len(calls) == 2)
        time.sleep(0.15)
        assert len(calls) == 2
        reply = al.cancel_job(jobs[2]["id"])
        assert "cancelling agent job" in reply.lower()
        for g in gates[:2]:
            g.set()
        for th in threads:
            th.join(DEADLINE)
        assert wait_until(lambda: jobs[2]["state"] != "running")
        assert jobs[2]["state"] == "failed"
        assert all(s["status"] == "skipped" for s in jobs[2]["steps"])
        assert all(not t.endswith("2") for t in calls)
    finally:
        for g in gates:
            g.set()


# ==========================================================================
# Concurrency cap
# ==========================================================================

def test_max_two_concurrent_jobs_others_queue(env, monkeypatch):
    gates = [threading.Event(), threading.Event(), threading.Event()]
    started = []
    lock = threading.Lock()

    def mk_blocker(i):
        def blocker(app, payload):
            with lock:
                started.append(i)
            gates[i].wait(DEADLINE)
            return f"done{i}"
        return blocker

    registry = {
        "research": None,  # filled per-job below via payload routing
        "summarize": lambda a, t: "s",
        "write_file": lambda a, args_: "w",
        "list_files": lambda a, d: "",
    }

    def routed_research(app, topic):
        idx = int(str(topic).split()[-1])
        return mk_blocker(idx)(app, topic)

    registry["research"] = routed_research
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)

    threads = []
    jobs = []
    for i in range(3):
        j = al.create_job(f"job number {i}", app=None)
        jobs.append(j)
        threads.append(al.launch_job(j["id"], None))

    assert wait_until(lambda: len(started) == 2), "two jobs should start"
    time.sleep(0.15)                            # confirm cap holds
    assert len(started) == 2                    # third stays queued
    assert jobs[2]["state"] == "running"        # queued jobs look 'running'

    gates[0].set()
    gates[1].set()
    assert wait_until(lambda: len(started) == 3)
    gates[2].set()
    for th in threads:
        th.join(DEADLINE)
    assert all(j["state"] == "done" for j in jobs)


# ==========================================================================
# Noise tolerance / persona safety
# ==========================================================================

def test_runners_returning_none_are_handled(env, monkeypatch):
    registry = {
        "research": lambda a, t: None,
        "summarize": lambda a, t: None,
        "write_file": lambda a, args_: None,
        "list_files": lambda a, d: None,
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("quiet task", app=None)
    rep = al.run_job(job["id"], None)
    assert job["state"] == "done"              # noise-Nones don't sink the job
    st = {s["name"]: s for s in job["steps"]}
    assert st["research"]["status"] == "done"
    assert st["summarize"]["status"] == "done"
    assert st["write_file"]["note"].startswith("skipped")  # honest about it
    assert st["write_file"]["status"] == "skipped"
    assert isinstance(rep, str) and rep.strip().endswith("sir.")


def test_builtin_persona_safe_wrapper_never_raises():
    def bad(app, payload):
        raise ValueError("kaboom")

    wrapped = al._persona_safe(bad)
    out = wrapped(object(), "x")
    assert isinstance(out, str)
    assert "snag" in out and out.endswith("sir.")
    assert al._persona_safe(lambda a, p: None)(None, None) == ""


# ==========================================================================
# Real write_file runner (path safety + .bak)
# ==========================================================================

def test_real_write_file_sanitizes_and_backs_up(env, monkeypatch):
    first = al._do_write_file(None, {"path": "../../evil.txt",
                                     "content": "v1"})
    target = os.path.join(env.tmp, "generated", "evil.txt")
    assert "evil.txt" in first and os.path.exists(target)
    second = al._do_write_file(None, {"path": "evil.txt", "content": "v2"})
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "v2"
    with open(target + ".bak", encoding="utf-8") as fh:
        assert fh.read() == "v1"
    assert ".bak" in second


# ==========================================================================
# Checkpoint recovery after crash
# ==========================================================================

def test_load_jobs_recovers_interrupted_running_job(env):
    saved = {"version": 1, "saved": 0.0, "jobs": {
        "job-dead01": {
            "id": "job-dead01", "task": "crashed task",
            "steps": [
                {"name": "research", "args": {}, "status": "done",
                 "note": "partial output preserved"},
                {"name": "summarize", "args": {}, "status": "pending",
                 "note": ""},
            ],
            "state": "running", "created": 1.0, "updated": 2.0,
            "note": "", "cancel": False,
        }}}
    with open(env.jobs_file, "w", encoding="utf-8") as fh:
        json.dump(saved, fh)
    al.load_jobs()
    job = al.AGENT_JOBS["job-dead01"]
    assert job["state"] == "failed"
    assert "interrupted by restart" in job["note"]
    assert job["steps"][0]["status"] == "done"       # progress kept
    assert job["steps"][0]["note"] == "partial output preserved"
    assert job["steps"][1]["status"] == "skipped"


def test_checkpoint_saved_after_every_step(env, monkeypatch):
    n = {"writes": 0}
    real_replace = os.replace

    def counting_replace(src, dst):
        if str(dst) == str(env.jobs_file):
            n["writes"] += 1
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", counting_replace)
    registry = {
        "research": make_runner(env, "research", out="r"),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("counted", app=None)
    al.run_job(job["id"], None)
    # create + started + 3 steps + finalize >= 5 saves
    assert n["writes"] >= 5


# ==========================================================================
# Skills
# ==========================================================================

@pytest.fixture()
def brain():
    b = RecorderBrain()
    al.register(b)
    return b


def test_registers_four_agent_skills(brain):
    assert set(brain.skills) == \
        {"ag_start", "ag_status", "ag_result", "ag_cancel"}
    assert len(brain.skills) == 4


def test_start_detect_variants(brain):
    detect, _ = brain.skills["ag_start"]
    for cmd, task in [
        ("jarvis agent: research rust compilers", "research rust compilers"),
        ("background agent write the quarterly report",
         "write the quarterly report"),
        ("agent task: compile competitor list", "compile competitor list"),
    ]:
        ctx = detect(cmd)
        assert ctx is not None, cmd
        assert ctx["task"] == task
    assert detect("what is an agent") is None
    assert detect("agent status") is None
    assert detect("jarvis agent:") is None


def test_start_reply_is_immediate_and_non_blocking(brain, env, monkeypatch):
    release = threading.Event()
    registry = {
        "research": make_runner(env, "research", out="r", gate=release),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    detect, execute = brain.skills["ag_start"]

    ctx = detect("jarvis agent: deep dive on kelp")
    reply = execute(None, ctx)                 # returns while blocked
    assert "sir." in reply
    assert "Agent job job-" in reply
    assert "research -> summarize -> write_file" in reply
    jid = reply.split("Agent job ")[1].split()[0]
    assert al.AGENT_JOBS[jid]["state"] == "running"
    release.set()
    assert wait_until(lambda: al.AGENT_JOBS[jid]["state"] == "done")


def test_status_lists_each_job_line(brain, env, monkeypatch):
    registry = {"research": lambda a, t: "r",
                "summarize": lambda a, t: "s",
                "write_file": lambda a, args_: "w",
                "list_files": lambda a, d: ""}
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    j1 = al.create_job("alpha mission", app=None)
    j2 = al.create_job("beta mission", app=None)
    al.run_job(j1["id"], None)
    detect, execute = brain.skills["ag_status"]
    ctx = detect("agent status")
    reply = execute(None, ctx)
    assert "sir." in reply
    assert j1["id"] in reply and j2["id"] in reply
    assert "done" in reply and "running" in reply
    single = execute(None, detect(f"job status {j1['id']}"))
    assert j1["id"] in single and j2["id"] not in single


def test_result_reports_last_finished_with_paths(brain, env, monkeypatch):
    registry = {
        "research": make_runner(env, "research", out="facts gathered"),
        "summarize": make_runner(env, "summarize", out="tight summary"),
        "write_file": make_runner(
            env, "write_file", out=f"Wrote 12 chars to {env.tmp}/out.md"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    detect, execute = brain.skills["ag_result"]
    empty = execute(None, detect("what did the agent find"))
    assert "No finished agent jobs" in empty and empty.endswith("sir.")

    job = al.create_job("report run", app=None)
    al.run_job(job["id"], None)
    rep = execute(None, detect("agent result"))
    assert job["id"] in rep and "done" in rep
    assert "facts gathered" in rep and "tight summary" in rep
    assert f"{env.tmp}/out.md" in rep          # write_file path included
    assert rep.endswith("sir.")


def test_result_prefers_most_recent_finished(brain, env, monkeypatch):
    ok = {"research": lambda a, t: "r", "summarize": lambda a, t: "s",
          "write_file": lambda a, args_: "w", "list_files": lambda a, d: ""}
    monkeypatch.setattr(al, "STEP_RUNNERS", ok)
    j1 = al.create_job("older win", app=None)
    j1["updated"] -= 10
    al.run_job(j1["id"], None)
    bad = {"research": lambda a, t: (_ for _ in ()).throw(RuntimeError("x")),
           "summarize": lambda a, t: "s",
           "write_file": lambda a, args_: "w", "list_files": lambda a, d: ""}
    monkeypatch.setattr(al, "STEP_RUNNERS", bad)
    j2 = al.create_job("newer fail", app=None)
    al.run_job(j2["id"], None)
    _, execute = brain.skills["ag_result"]
    rep = execute(None, {"_": True})
    assert j2["id"] in rep                     # newest finished wins
    assert "FAIL" in rep


def test_cancel_skill(brain, env, monkeypatch):
    release = threading.Event()
    registry = {
        "research": make_runner(env, "research", out="r", gate=release),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("to be cancelled", app=None)
    th = al.launch_job(job["id"], None)
    assert env.started.wait(DEADLINE)

    detect, execute = brain.skills["ag_cancel"]
    reply = execute(None, detect(f"cancel agent job {job['id']}"))
    assert "cancelling agent job" in reply.lower() and reply.endswith("sir.")
    release.set()
    th.join(DEADLINE)
    assert job["state"] == "failed"

    none_reply = execute(None, {"job_id": "job-zzzzzz"})
    assert "sir." in none_reply


# ==========================================================================
# Per-step provider routing (multi-model)
# ==========================================================================

def test_provider_routing_uses_llm_client_when_configured(env, monkeypatch):
    import llm_client as lc

    seen = []

    class FakeClient:
        def __init__(self, provider):
            self.name = getattr(provider, "name", str(provider))
            seen.append(("init", self.name))

        def chat(self, prompt):
            seen.append(("chat", prompt))
            return "PROVIDER BRIEF"

    monkeypatch.setattr(lc, "LLMClient", FakeClient)
    monkeypatch.setattr(al, "_llm", lambda app, p: "DEFAULT BRAIN")
    monkeypatch.setitem(al.STEP_PROVIDERS, "research", "openai")
    monkeypatch.setitem(al.STEP_PROVIDERS, "summarize", "")

    research = al._do_research(None, "topic about mars")
    summarize = al._do_summarize(None, "some long text to condense. " * 20)

    assert research == "PROVIDER BRIEF"          # routed through the client
    assert any(ev[0] == "init" and ev[1] == "openai" for ev in seen)
    assert summarize == "DEFAULT BRAIN"          # other step stayed on _llm
    # only the research step produced a provider chat call
    assert sum(1 for ev in seen if ev[0] == "chat") == 1
    assert "Research this topic" in next(ev[1] for ev in seen if ev[0] == "chat")


def test_provider_routing_falls_back_to_llm_when_env_empty(env, monkeypatch):
    import llm_client as lc

    def forbidden(*a, **k):
        raise AssertionError("LLMClient must not be used when unset")

    monkeypatch.setattr(lc, "LLMClient", forbidden)
    monkeypatch.setattr(al, "_llm", lambda app, p: "BRAIN SAYS " + p[:6])
    assert al.STEP_PROVIDERS["research"] == ""
    assert al.STEP_PROVIDERS["summarize"] == ""

    assert "BRAIN SAYS" in al._do_research(None, "quantum foam")
    assert "BRAIN SAYS" in al._do_summarize(None, "long text. " * 30)


def test_provider_bad_name_falls_back_to_default(env, monkeypatch):
    import llm_client as lc

    def forbidden(*a, **k):
        raise AssertionError("no client should be constructed")

    monkeypatch.setattr(lc, "LLMClient", forbidden)
    monkeypatch.setattr(al, "_llm", lambda app, p: "SAFE DEFAULT")
    monkeypatch.setitem(al.STEP_PROVIDERS, "research", "does-not-exist")
    assert al._do_research(None, "anything") == "SAFE DEFAULT"


# ==========================================================================
# code_gen runner
# ==========================================================================

def _stub_delegate(monkeypatch, reply_box):
    import code_brain_pro as cbp

    calls = []

    def fake_delegate(app, cmd):
        calls.append(cmd)
        return reply_box[0]

    monkeypatch.setattr(cbp, "delegate_code_write", fake_delegate)
    return calls


def test_code_gen_happy_path_writes_file_and_baks_on_rerun(env, monkeypatch):
    box = ["Built locally, sir - verified syntax and compile.\n\n"
           "```python\nGREETING = 'v1'\n```\n"]
    calls = _stub_delegate(monkeypatch, box)

    out1 = al._do_code_gen(None, {"task": "make a greeter",
                                  "filename": "greeter.py"})
    target = os.path.join(env.tmp, "generated", "greeter.py")
    assert os.path.exists(target)
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "GREETING = 'v1'\n"
    assert target in out1 and "1 lines of code" in out1 and "sir." in out1

    box[0] = "```python\nGREETING = 'v2'\n```\n"
    out2 = al._do_code_gen(None, {"task": "make a greeter",
                                  "filename": "greeter.py"})
    with open(target + ".bak", encoding="utf-8") as fh:
        assert fh.read() == "GREETING = 'v1'\n"
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "GREETING = 'v2'\n"
    assert ".bak" in out2
    assert calls == ["write code for make a greeter"] * 2  # nothing else on disk


def test_code_gen_strips_non_fence_prose(env, monkeypatch):
    box = ["Generated and validated, sir (all checks passed).\n\n"
           "VALUE = 42\nSIDE = 'kept'\n"]
    _stub_delegate(monkeypatch, box)

    out = al._do_code_gen(None, {"task": "constant holder"})
    target = os.path.join(env.tmp, "generated", "constant_holder.py")
    with open(target, encoding="utf-8") as fh:
        assert fh.read() == "VALUE = 42\nSIDE = 'kept'\n"
    assert "Generated and validated" not in open(target).read()
    assert "2 lines of code" in out and target in out


def test_code_gen_honest_failure_paths(env, monkeypatch):
    _stub_delegate(monkeypatch, [None])
    out = al._do_code_gen(None, {"task": "impossible widget"})
    assert "could not generate code" in out and "sir." in out

    _stub_delegate(monkeypatch, ["Built locally, sir.\n\n```\n```"])
    out2 = al._do_code_gen(None, {"task": "empty thing"})
    assert "no usable code" in out2 and "sir." in out2

    out3 = al._do_code_gen(None, {})
    assert "No task given" in out3 and "sir." in out3


def test_code_gen_registered_in_step_runners():
    assert "code_gen" in al.STEP_RUNNERS
    wrapped = al.STEP_RUNNERS["code_gen"]
    assert wrapped.__name__ == "_do_code_gen"


# ==========================================================================
# Proactive notify
# ==========================================================================

def test_notify_fires_once_with_state(env, monkeypatch):
    fired = []
    al.set_notify(lambda job: fired.append((job["id"], job["state"])))
    registry = {
        "research": make_runner(env, "research", out="r"),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("notified task", app=None)
    al.run_job(job["id"], None)

    assert fired == [(job["id"], "done")]
    al.run_job(job["id"], None)          # re-finalizing must NOT refire
    assert len(fired) == 1


def test_notify_fires_for_failed_jobs_too(env, monkeypatch):
    fired = []
    al.set_notify(lambda job: fired.append((job["id"], job["state"])))
    registry = {
        "research": make_runner(env, "research", err=RuntimeError("x")),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)
    job = al.create_job("doomed task", app=None)
    al.run_job(job["id"], None)
    assert fired == [(job["id"], "failed")]


def test_notify_swallows_callback_exceptions(env, monkeypatch):
    def broken(job):
        raise RuntimeError("ui exploded")

    al.set_notify(broken)
    monkeypatch.setattr(al, "STEP_RUNNERS",
                        {"research": make_runner(env, "research", out="r"),
                         "summarize": make_runner(env, "summarize", out="s"),
                         "write_file": make_runner(env, "write_file", out="w"),
                         "list_files": make_runner(env, "list_files")})
    job = al.create_job("loud callback", app=None)
    rep = al.run_job(job["id"], None)     # must not raise
    assert job["state"] == "done" and rep.endswith("sir.")


def test_notify_via_app_say_queue_path(brain, env, monkeypatch):
    class FakeApp:
        def __init__(self):
            self.ui_q = Queue()

    release = threading.Event()
    registry = {
        "research": make_runner(env, "research", out="r", gate=release),
        "summarize": make_runner(env, "summarize", out="s"),
        "write_file": make_runner(env, "write_file", out="w"),
        "list_files": make_runner(env, "list_files"),
    }
    monkeypatch.setattr(al, "STEP_RUNNERS", registry)

    app = FakeApp()
    detect, execute = brain.skills["ag_start"]
    ctx = detect("jarvis agent: push me a notice")
    execute(app, ctx)                     # installs the default ui_q hook

    jids = [j["id"] for j in al.AGENT_JOBS.values()]
    jid = jids[-1]
    release.set()
    assert wait_until(lambda: al.AGENT_JOBS[jid]["state"] == "done")
    text = app.ui_q.get_nowait()
    assert text.startswith(f"Agent job {jid} finished: done")
    with pytest.raises(Exception):
        app.ui_q.get_nowait()             # exactly one notice


def test_ag_start_with_plain_app_installs_no_hook(brain, env, monkeypatch):
    monkeypatch.setattr(al, "STEP_RUNNERS",
                        {"research": make_runner(env, "research", out="r"),
                         "summarize": make_runner(env, "summarize", out="s"),
                         "write_file": make_runner(env, "write_file", out="w"),
                         "list_files": make_runner(env, "list_files")})
    detect, execute = brain.skills["ag_start"]
    execute(SimpleNamespace(), detect("jarvis agent: plain dummy"))  # no say/ui_q
    assert al.ON_JOB_DONE is None         # untouched for hook-less apps
