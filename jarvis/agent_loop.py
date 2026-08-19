"""JARVIS BACKGROUND AGENT: Clicky-style plan -> execute -> verify -> report.

"jarvis agent: TASK" spawns a daemon thread that plans the work, runs the
steps one at a time, verifies the outcome and reports back, all checkpointed
to disk after EVERY step so a crash never loses progress.

Skills added here (all replies persona-tagged ", sir."):

* ag_start   - "jarvis agent: TASK" | "background agent TASK" |
               "agent task: X"      -> creates the job, spawns the worker,
               replies immediately with the job id + planned steps
               (never blocks on execution).
* ag_status  - "agent status" / "job status [id]" -> one line per job.
* ag_result  - "agent result" / "what did the agent find" ->
               final report of the last finished job, incl. written files.
* ag_cancel  - "cancel agent job [id]" -> stop a running/queued job.

Design:
* AGENT_JOBS: dict job_id -> {"task", "steps":[{name,args,status,note}],
              "state": "running|done|failed", "created", "updated"}
* Checkpoint JSON PROJECT_DIR/jarvis_agent_jobs.json, saved atomically
  (tmp file + os.replace) after every step transition.
* plan_task(task): asks the LLM for a JSON array of {"tool","args"} steps
  constrained to STEP_RUNNERS, parsed defensively; falls back to a
  heuristic research -> summarize -> write_file plan offline.
* STEP_RUNNERS registry: {"research", "write_file", "summarize",
  "list_files", "code_gen"} - each builtin wrapped persona-safe (honest
  errors, never raise). Tests may monkeypatch the registry wholesale.
* Multi-model: STEP_PROVIDERS maps a step name to an optional alternate
  LLM provider (see llm_client.PROVIDERS); empty means the default
  brain._llm seam. Research/summarize/code_gen consult it per step.
* Proactive notify: ON_JOB_DONE (set via set_notify) fires once when a
  job lands in done/failed; ag_start wires a default hook that pushes
  "Agent job <id> finished: <state>" into app.say / app.ui_q when the
  app exposes either.
* Failure policy: a failed step does NOT abort the job - execution
  continues, EXCEPT downstream write_file steps whose source step failed
  are skipped (dependency-aware).
* Never imports main. LLM seam: brain._llm(app, prompt) -> str | None.
* Max 2 concurrent jobs; extras queue until a slot frees.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("agent_loop")

try:
    from brain import _llm
except Exception:  # pragma: no cover - standalone use
    _llm = None

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
JOBS_FILE = os.path.join(PROJECT_DIR, "jarvis_agent_jobs.json")
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated_agent")

MAX_CONCURRENT_JOBS = 2
MAX_PLAN_STEPS = 6
NOTE_LIMIT = 500
_STEP_GLYPHS = {"done": "[ok]", "failed": "[FAIL]", "skipped": "[skip]",
                "pending": "[....]"}

# Per-step provider routing: a non-empty name routes that step through
# llm_client.LLMClient(PROVIDERS[name]) instead of the default brain._llm
# seam. Empty string -> default path.
STEP_PROVIDERS = {
    "research": os.environ.get("JARVIS_AGENT_RESEARCH_PROVIDER", ""),
    "summarize": os.environ.get("JARVIS_AGENT_SUMMARIZE_PROVIDER", ""),
    "code_gen": "",
}

# Proactive notification: fired (guarded, once per job) when a job lands
# in done/failed. Register via set_notify(fn).
ON_JOB_DONE = None
_notified_jobs: set = set()


def set_notify(fn) -> None:
    """Set the job-completion callback; fn(job) fires once per finished job."""
    global ON_JOB_DONE
    ON_JOB_DONE = fn


def _provider_reply(step_name, prompt):
    """Chat via the step's configured alternate provider, else None.

    Any failure here (missing llm_client, unknown provider name, env
    problems) collapses to None so callers fall back to the default seam.
    """
    name = str(STEP_PROVIDERS.get(step_name) or "").strip()
    if not name:
        return None
    try:
        from llm_client import LLMClient, PROVIDERS
        return LLMClient(PROVIDERS[name]).chat(prompt)
    except Exception as exc:  # ImportError / KeyError / bad env -> default
        log.warning("alt provider %r for %s unusable (%s); using default "
                    "brain", name, step_name, exc)
        return None


def _app_notify(app):
    """Default completion hook routing notices into *app*'s UI.

    Returns None when the app exposes neither ``say`` nor ``ui_q`` so
    plain dummies leave the notify hook untouched.
    """
    say = getattr(app, "say", None)
    ui_q = getattr(app, "ui_q", None)
    if not callable(say) and ui_q is None:
        return None

    def _notify(job):
        text = f"Agent job {job['id']} finished: {job['state']}"
        try:
            if callable(say):
                say(text)
            elif ui_q is not None:
                ui_q.put(text)
        except Exception:  # never let UI delivery kill the worker
            log.exception("could not deliver agent completion notice")

    return _notify


def _fire_job_done(job) -> None:
    """Fire ON_JOB_DONE exactly once when *job* reaches done/failed."""
    jid = job.get("id")
    if job.get("state") not in {"done", "failed"}:
        return
    with _lock:
        if jid in _notified_jobs:
            return
        _notified_jobs.add(jid)
    fn = ON_JOB_DONE
    if fn is None:
        return
    try:
        fn(job)
    except Exception:  # defensive: callbacks are untrusted
        log.exception("agent job-done notify failed")


# ==========================================================================
# Shared state
# ==========================================================================

AGENT_JOBS: dict = {}

_lock = threading.RLock()
_run_cond = threading.Condition()
_active = 0
_loaded = False


def _now() -> float:
    return time.time()


# ==========================================================================
# Checkpointing (atomic, after every step)
# ==========================================================================

def _save_jobs() -> None:
    """Atomically persist every job (tmp file, then os.replace)."""
    with _lock:
        data = {"version": 1, "saved": _now(), "jobs": AGENT_JOBS}
        tmp = JOBS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1)
            os.replace(tmp, JOBS_FILE)
        except OSError as exc:  # defensive: never kill the agent over IO
            log.warning("agent checkpoint failed: %s", exc)


def load_jobs() -> None:
    """Restore checkpointed jobs once; recover jobs orphaned by a crash."""
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            with open(JOBS_FILE, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for jid, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict) or jid in AGENT_JOBS:
                continue
            if job.get("state") == "running":  # crashed mid-flight
                job["state"] = "failed"
                note = str(job.get("note") or "").strip()
                job["note"] = (note + "; " if note else "") \
                    + "interrupted by restart; completed steps preserved"
                for step in job.get("steps") or []:
                    if isinstance(step, dict) and step.get("status") == "pending":
                        step["status"] = "skipped"
                        step["note"] = "interrupted by restart"
            AGENT_JOBS[jid] = job


# ==========================================================================
# Built-in step runners (each persona-safe wrapped below)
# ==========================================================================

def _do_research(app, topic):
    """Research a topic via the LLM, or an honest offline brief."""
    prompt = ("Research this topic and reply with a concise factual "
              "brief (max 8 sentences):\n" + str(topic))
    reply = _provider_reply("research", prompt)
    if not reply and _llm is not None:
        reply = _llm(app, prompt)
    if reply:
        return str(reply).strip()
    return ("Offline research brief on '%s' (no AI link right now):\n"
            "- Key question: %s\n"
            "- Known context gathered locally; specifics unavailable offline.\n"
            "- Recommendation: retry when connectivity to the AI is restored."
            % (topic, topic))


def _do_summarize(app, text):
    """Summarize text via the LLM, else an honest local condensation."""
    body = str(text or "").strip()
    if not body:
        return "Nothing to summarize - the source step produced no text."
    prompt = "Summarize in at most 4 sentences:\n" + body[:4000]
    reply = _provider_reply("summarize", prompt)
    if not reply and _llm is not None:
        reply = _llm(app, prompt)
    if reply:
        return str(reply).strip()
    cut = body[:280]
    dot = cut.rfind(". ")
    if dot > 60:
        cut = cut[:dot + 1]
    return cut.strip() + ("..." if len(body) > len(cut) else "")


def _do_list_files(app, directory):
    """List a directory with sizes; honest message when unavailable."""
    d = str(directory or PROJECT_DIR)
    try:
        entries = sorted(os.listdir(d))
    except OSError as exc:
        return f"Could not list '{d}': {exc}"
    if not entries:
        return f"'{d}' is empty."
    lines = []
    for name in entries[:50]:
        full = os.path.join(d, name)
        try:
            size = os.path.getsize(full) if os.path.isfile(full) else -1
        except OSError:
            size = -1
        lines.append(f"- {name}" + (f" ({size} bytes)" if size >= 0 else "/"))
    if len(entries) > 50:
        lines.append(f"... and {len(entries) - 50} more")
    return f"{d}:\n" + "\n".join(lines)


def _do_write_file(app, args):
    """Write content under GENERATED_DIR only; .bak any previous version."""
    args = args if isinstance(args, dict) else {}
    raw = str(args.get("path") or args.get("filename") or "agent_output.txt")
    name = os.path.basename(raw.replace("\\", "/")).strip() or "agent_output.txt"
    if "." not in name:
        name += ".txt"
    target = os.path.join(GENERATED_DIR, name)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    bak = None
    if os.path.exists(target):
        bak = target + ".bak"
        try:
            shutil.copy2(target, bak)
        except OSError:
            bak = None
    content = str(args.get("content") or "")
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    msg = f"Wrote {len(content)} chars to {target}"
    if bak:
        msg += f" (previous copy saved as {bak})"
    return msg


_FENCE_MARK = "```"


def _extract_code_block(text):
    """Return *text* minus surrounding prose.

    When ``` fences are present only the lines inside them survive;
    otherwise a leading 'Built ...'/'Generated ...' prose line is dropped.
    """
    lines = str(text or "").splitlines()
    if any(ln.lstrip().startswith(_FENCE_MARK) for ln in lines):
        kept, inside = [], False
        for ln in lines:
            if ln.lstrip().startswith(_FENCE_MARK):
                inside = not inside
                continue
            if inside:
                kept.append(ln)
        return "\n".join(kept)
    if lines and re.match(r"\s*(Built|Generated)\b", lines[0]):
        lines = lines[1:]
    return "\n".join(lines)


def _do_code_gen(app, args):
    """Generate code via code_brain_pro; save under GENERATED_DIR only."""
    args = args if isinstance(args, dict) else {}
    task = str(args.get("task") or "").strip()
    if not task:
        return "No task given for code generation - nothing to build, sir."
    try:
        import code_brain_pro
    except ImportError as exc:  # optional dependency
        return f"code_brain_pro is unavailable ({exc}); standing by, sir."
    try:
        raw = code_brain_pro.delegate_code_write(app, "write code for " + task)
    except Exception as exc:  # defensive: delegate is untrusted here
        log.warning("delegate_code_write failed: %s", exc)
        raw = None
    if not raw or not isinstance(raw, str):
        return f"I could not generate code for '{task}' right now, sir."
    code = _extract_code_block(raw).strip("\n")
    if not code.strip():
        return f"The generator returned no usable code for '{task}', sir."
    raw_name = str(args.get("filename") or "").strip()
    name = os.path.basename(raw_name.replace("\\", "/")).strip() \
        if raw_name else ""
    if not name:
        name = _slug(task) + ".py"
    elif "." not in name:
        name += ".py"
    target = os.path.join(GENERATED_DIR, name)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    bak = None
    if os.path.exists(target):
        bak = target + ".bak"
        try:
            shutil.copy2(target, bak)
        except OSError:
            bak = None
    content = code + "\n"
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    n_lines = content.count("\n")
    msg = f"Wrote {name} ({n_lines} lines of code) to {target}"
    if bak:
        msg += f" (previous copy saved as {bak})"
    return msg + ", sir."


def _persona_safe(fn):
    """Wrap a runner so it never raises and always speaks persona."""
    def wrapped(app, payload):
        try:
            out = fn(app, payload)
        except Exception as exc:  # defensive containment
            log.exception("step runner %s failed", getattr(fn, "__name__", fn))
            return f"That step hit a snag ({exc}); carrying on regardless, sir."
        return "" if out is None else str(out)
    wrapped.__name__ = getattr(fn, "__name__", "runner")
    return wrapped


STEP_RUNNERS = {
    "research": _persona_safe(_do_research),
    "write_file": _persona_safe(_do_write_file),
    "summarize": _persona_safe(_do_summarize),
    "list_files": _persona_safe(_do_list_files),
    "code_gen": _persona_safe(_do_code_gen),
}


# ==========================================================================
# Planning
# ==========================================================================

def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")
    return s[:40] or "task"


def _norm_args(tool: str, args):
    """Coerce LLM-supplied args into a safe JSON-able dict/str per tool."""
    if isinstance(args, dict):
        return {str(k): (v if isinstance(v, (int, float, bool)) else str(v))
                for k, v in args.items()}
    if isinstance(args, str):
        val = args.strip()
        if tool == "write_file":
            return {"path": _slug(val) + ".md"}
        if tool == "list_files":
            return {"dir": val}
        if tool == "code_gen":
            return {"task": val}
        return {"topic" if tool == "research" else "text": val}
    return {}


def _plan_with_llm(task, app):
    """Ask the LLM for a JSON step plan; parse defensively."""
    if _llm is None:
        return []
    tools = ", ".join(sorted(STEP_RUNNERS))
    prompt = (
        "You are a planning module. Decompose the task into at most "
        f"{MAX_PLAN_STEPS} steps using ONLY these tools: {tools}.\n"
        'Reply with ONLY a JSON array, e.g. '
        '[{"tool": "research", "args": {"topic": "..."}}, '
        '{"tool": "summarize", "args": {"source": "research"}}]. '
        "A write_file step may set \"source\": \"<earlier tool>\" to use its "
        "output as content. Task: " + str(task))
    try:
        raw = _llm(app, prompt)
    except Exception:
        raw = None
    if not raw or not isinstance(raw, str):
        return []
    seg = raw[raw.find("["):raw.rfind("]") + 1]
    if not seg:
        return []
    try:
        arr = json.loads(seg)
    except ValueError:
        return []
    if not isinstance(arr, list):
        return []
    steps = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or item.get("name") or "").strip().lower()
        if tool not in STEP_RUNNERS:
            continue  # constrain to the registry, drop anything else
        steps.append({"name": tool,
                      "args": _norm_args(tool, item.get("args")),
                      "status": "pending", "note": ""})
        if len(steps) >= MAX_PLAN_STEPS:
            break
    return steps


def plan_task(task, app=None):
    """Return a step list for the task: LLM plan or heuristic fallback."""
    steps = _plan_with_llm(task, app)
    if not steps:
        steps = [
            {"name": "research", "args": {"topic": str(task)},
             "status": "pending", "note": ""},
            {"name": "summarize", "args": {"source": "research"},
             "status": "pending", "note": ""},
            {"name": "write_file",
             "args": {"path": _slug(task) + ".md", "content_from": "summarize"},
             "status": "pending", "note": ""},
        ]
    return steps


# ==========================================================================
# Job lifecycle
# ==========================================================================

def create_job(task, app=None):
    """Plan the task, register a new job, persist it. Returns the job."""
    task = str(task).strip()
    with _lock:
        load_jobs()
        jid = "job-" + uuid.uuid4().hex[:6]
        job = {"id": jid, "task": task, "steps": plan_task(task, app),
               "state": "running", "created": _now(), "updated": _now(),
               "note": "", "cancel": False}
        AGENT_JOBS[jid] = job
        _save_jobs()
        return job


def active_job_count() -> int:
    with _run_cond:
        return _active


def launch_job(job_id, app=None):
    """Spawn the daemon worker thread for a job; returns the Thread."""
    th = threading.Thread(target=_worker, args=(job_id, app),
                          name=f"jarvis-agent-{job_id}", daemon=True)
    th.start()
    return th


def _worker(job_id, app):
    global _active
    with _lock:
        job = AGENT_JOBS.get(job_id)
    if job is None:
        return
    with _run_cond:
        while _active >= MAX_CONCURRENT_JOBS and not job.get("cancel"):
            _run_cond.wait(timeout=0.2)
        _active += 1
    try:
        run_job(job_id, app)
    finally:
        with _run_cond:
            _active -= 1
            _run_cond.notify_all()


def _find_step(job, name):
    for s in job.get("steps") or []:
        if s.get("name") == name:
            return s
    return None


_MISSING = object()


def _build_arg(step, job, outputs):
    """Compute the runner argument; _MISSING means unmet dependency."""
    name, args = step["name"], dict(step.get("args") or {})
    if name == "write_file":
        dep = args.get("content_from") or args.get("source")
        if dep:
            if dep in outputs:
                args.setdefault("content", outputs[dep])
            elif "content" not in args:
                return _MISSING
        return args
    if name == "summarize":
        if str(args.get("text") or "").strip():
            return args["text"]
        dep = args.get("source")
        return outputs.get(dep, "") if dep else ""
    if name == "list_files":
        return args.get("dir") or PROJECT_DIR
    if name == "research":
        return args.get("topic") or job["task"]
    return args


def run_job(job_id, app=None):
    """Execute pending steps sequentially in the CALLER thread.

    Each step is try/except-isolated: a failure marks the step failed but
    execution continues, except write_file steps whose source step failed
    (or produced nothing) are skipped. Checkpoint saved after every step.
    """
    with _lock:
        job = AGENT_JOBS.get(job_id)
    if job is None:
        return f"No such agent job '{job_id}', sir."
    with _lock:
        job["started"] = True
        _save_jobs()
    outputs = {}
    for step in job["steps"]:
        if job.get("cancel"):
            if step.get("status") == "pending":
                step["status"] = "skipped"
                step["note"] = "cancelled before running"
                with _lock:
                    _save_jobs()
            continue
        if step.get("status") != "pending":
            continue  # already completed/resumed from checkpoint
        dep = step.get("args", {}).get("source") \
            or step.get("args", {}).get("content_from")
        if dep and step["name"] == "write_file":
            # Dependency-aware: only write_file is gated on its source.
            dep_step = _find_step(job, dep)
            if dep_step and dep_step.get("status") in {"failed", "skipped"}:
                step["status"] = "skipped"
                step["note"] = f"skipped: upstream step '{dep}' did not complete"
                with _lock:
                    job["updated"] = _now()
                    _save_jobs()
                continue
            if "content" not in step.get("args", {}) and dep not in outputs:
                step["status"] = "skipped"
                step["note"] = f"skipped: dependency '{dep}' produced no output"
        arg = _build_arg(step, job, outputs)
        if arg is _MISSING:
            step["status"] = "skipped"
            step["note"] = f"skipped: dependency '{dep}' produced no output"
            with _lock:
                job["updated"] = _now()
                _save_jobs()
            continue
        runner = STEP_RUNNERS.get(step["name"])
        if runner is None:
            step["status"] = "failed"
            step["note"] = f"unknown tool '{step['name']}'"
        else:
            try:
                result = runner(app, arg)
            except Exception as exc:  # defensive: raw runners may raise
                log.exception("step %s/%s raised", job_id, step["name"])
                step["status"] = "failed"
                step["note"] = str(exc)[:NOTE_LIMIT]
            else:
                step["status"] = "done"
                step["note"] = ("" if result is None
                                else str(result).strip()[:NOTE_LIMIT])
                if result is not None:
                    outputs[step["name"]] = str(result)
        with _lock:
            job["updated"] = _now()
            _save_jobs()  # checkpoint after EVERY step
    return _finalize(job)


def _finalize(job):
    with _lock:
        done = [s for s in job["steps"] if s.get("status") == "done"]
        bad = [s for s in job["steps"] if s.get("status") == "failed"]
        if job.get("cancel"):
            job["state"] = "failed"
            prev = str(job.get("note") or "").strip()
            job["note"] = (prev + "; " if prev else "") + "cancelled by user"
        elif bad:
            job["state"] = "failed"
        elif done:
            job["state"] = "done"
        else:
            job["state"] = "failed"
            job["note"] = "no steps produced output"
        job["updated"] = _now()
        _save_jobs()
    _fire_job_done(job)
    return format_report(job)


def cancel_job(job_id=None):
    """Request cancellation of a job (default: newest running/queued one)."""
    with _lock:
        load_jobs()
        job = AGENT_JOBS.get(job_id) if job_id else None
        if job is None:
            running = [j for j in AGENT_JOBS.values()
                       if j.get("state") == "running" and not j.get("cancel")]
            if not running:
                return "No cancellable agent jobs right now, sir."
            job = max(running, key=lambda j: j.get("created", 0))
        job["cancel"] = True
        job["updated"] = _now()
        _save_jobs()
        with _run_cond:
            _run_cond.notify_all()
        return f"Cancelling agent job {job['id']} right away, sir."


# ==========================================================================
# Reporting
# ==========================================================================

def format_report(job):
    lines = [f"Agent job {job['id']} - \"{job['task']}\" "
             f"finished {job['state']}:"]
    for s in job["steps"]:
        glyph = _STEP_GLYPHS.get(s.get("status"), "[....]")
        note = (s.get("note") or "").splitlines()[0][:160] if s.get("note") \
            else "-"
        lines.append(f"  {glyph} {s['name']}: {note}")
    paths = []
    for s in job["steps"]:
        if s.get("name") != "write_file" or s.get("status") != "done":
            continue
        m = re.search(r"to (\S+)", s.get("note") or "")
        if m:
            paths.append(m.group(1))
    if paths:
        lines.append("Files written: " + ", ".join(paths))
    verdict = {"done": "All steps verified",
               "failed": "Some steps misfired along the way"}.get(
                   job.get("state"), job.get("state", ""))
    lines.append(f"{verdict} - debrief complete, sir.")
    return "\n".join(lines)


def _fmt_job_line(job):
    total = len(job.get("steps") or [])
    done = sum(1 for s in job.get("steps") or [] if s.get("status") == "done")
    extra = ""
    if job.get("state") == "running" and not job.get("started"):
        extra = " [queued]"
    if job.get("state") == "failed" and job.get("note"):
        extra = f" ({job['note'].split(';')[-1].strip()[:60]})"
    return (f"{job['id']}: {job['task'][:40]} - {job['state']}, "
            f"{done}/{total} steps{extra}")


# ==========================================================================
# Skills
# ==========================================================================

_RE_START = re.compile(
    r"^(?:jarvis\s+agent|background\s+agent|agent\s+task)\s*(?::|-)?\s+(.+)$",
    re.I)
_RE_STATUS = re.compile(
    r"\b(?:agent|job)\s+status\b(?:\s+(job-[0-9a-f]+|\b[0-9a-f]{6}\b))?", re.I)
_RE_RESULT = re.compile(
    r"\bagent\s+results?\b|\bwhat\s+did\s+the\s+agent\s+find\b", re.I)
_RE_CANCEL = re.compile(
    r"\bcancel\s+(?:the\s+)?agent\s+job(?:\s+(job-[0-9a-f]+|\b[0-9a-f]{6}\b))?",
    re.I)


def _d_start(cmd):
    m = _RE_START.match((cmd or "").strip())
    if not m:
        return None
    task = m.group(1).strip().strip('"')
    return {"task": task} if task else None


def _e_start(app, ctx):
    task = ctx["task"]
    job = create_job(task, app)
    queued = active_job_count() >= MAX_CONCURRENT_JOBS
    hook = _app_notify(app)  # proactive "job finished" push when possible
    if hook is not None:
        set_notify(hook)
    launch_job(job["id"], app)
    names = " -> ".join(s["name"] for s in job["steps"])
    queue_note = " You're queued behind my other jobs;" if queued else ""
    return (f"On it, sir. Agent job {job['id']} is planned with "
            f"{len(job['steps'])} steps: {names}.{queue_note} "
            f"I'll report back when it's finished, sir.")


def _d_status(cmd):
    m = _RE_STATUS.search(cmd or "")
    return {"job_id": m.group(1)} if m else None


def _e_status(app, ctx):
    with _lock:
        load_jobs()
        jobs = list(AGENT_JOBS.values())
    if ctx.get("job_id"):
        jobs = [j for j in jobs if j["id"] == ctx["job_id"]
                or j["id"].startswith(ctx["job_id"])]
    if not jobs:
        return "No agent jobs on the books, sir."
    jobs.sort(key=lambda j: j.get("created", 0))
    return ("Agent jobs:\n"
            + "\n".join(_fmt_job_line(j) for j in jobs)
            + "\nAll accounted for, sir.")


def _d_result(cmd):
    return {"_": True} if _RE_RESULT.search(cmd or "") else None


def _e_result(app, ctx):
    with _lock:
        load_jobs()
        finished = [j for j in AGENT_JOBS.values()
                    if j.get("state") in {"done", "failed"}]
    if not finished:
        return "No finished agent jobs to report on yet - still working, sir."
    job = max(finished, key=lambda j: j.get("updated", 0))
    return format_report(job)


def _d_cancel(cmd):
    m = _RE_CANCEL.search(cmd or "")
    if m:
        return {"job_id": m.group(1)}
    return None


def _e_cancel(app, ctx):
    return cancel_job(ctx.get("job_id"))


_SKILLS = (
    ("ag_start", _d_start, _e_start),
    ("ag_status", _d_status, _e_status),
    ("ag_result", _d_result, _e_result),
    ("ag_cancel", _d_cancel, _e_cancel),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register the background-agent skills with the given Brain."""
    for name, detect, execute in _SKILLS:
        def safe(app, ctx, _fn=execute, _n=name):
            try:
                out = _fn(app, ctx)
            except Exception as exc:  # defensive containment
                log.exception("skill %s failed", _n)
                return f"My {_n} module misfired ({exc}); standing by, sir."
            if isinstance(out, tuple):  # guard against stray commas
                out = out[0]
            return out
        safe.__name__ = f"safe_{name}"
        # ag_start is priority=True: "jarvis agent: research X" must win
        # over legacy research/note detectors in main's priority pass.
        brain.register(name, detect, safe,
                       priority=(name == "ag_start"))
    log.info("agent loop skills registered (%d)", len(_SKILLS))


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
