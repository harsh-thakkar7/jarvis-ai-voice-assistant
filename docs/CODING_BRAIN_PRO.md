# CODING BRAIN PRO — Developer Guide

Developer documentation for the coding skill stack of this project:
`code_brain_pro.py`, `code_validator.py`, `file_power.py`, and
`power_skills.py`, and how they plug into `brain.Brain`.

---

## 1. Purpose and Design Principles

`code_brain_pro.py` turns JARVIS into a senior-engineer coding assistant. It
provides local code generation from a curated template library, static code
review, validated LLM rewrites with write-back to disk, AST explanations,
translation, and pytest scaffolding. It never imports `main`; it talks to the
language model only through `brain._llm(app, prompt)`, which returns `None`
whenever the model is unreachable, so every skill has an offline path.

Three principles govern the design:

1. **Local-first.** Before any network call, skills try local resources:
   keyword-scored template matching in `TEMPLATE_LIBRARY`, mechanical
   auto-fixes (`_local_auto_fixes`), AST-based analysis (`_analyze`), and
   pocket cheatsheets for translation. The LLM is a fallback, not a
   dependency.
2. **Validate-before-answer.** Raw model output is unreliable (markdown
   fences, polite prose, syntax errors, runtime failures). Nothing reaches
   the user or the disk until it passes `code_validator`. The module docstring
   of `code_validator.py` calls it "the gatekeeper between 'model said
   something' and 'JARVIS shows/executes code'".
3. **Honest degradation.** When the LLM, network, or a binary (`git`,
   `docker`, `node`) is unavailable, skills return an explicit persona message
   describing what was done locally and what still needs the missing piece,
   instead of raising or inventing output. Example: `pro_write_code` lists the
   offline library's capabilities when the model is down; `ps_docker_ps`
   offers to install Docker when the CLI is missing.

---

## 2. Skill Catalog

All modules expose a single `register(brain)` function that calls
`brain.register(name, detect, execute, priority=...)`. `priority=True` skills
are only consulted when `Brain.think(cmd, priority=True)` is called by the
main loop; they win over chit-chat detectors.

### 2.1 Coding skills — `pro_*` (code_brain_pro.py, 8 skills)

| Skill | Example commands | Priority | Returns |
|---|---|---|---|
| `pro_write_code` | "write a python fibonacci function", "create a quicksort script" (verb + code-noun pattern; poems/stories/tests intents rejected) | True | Local template hit: full code + validation one-liner + save hint. Otherwise LLM code via `generate_validated` + validation summary + suggested filename. Offline: honest capability list. |
| `pro_save_code` | "save it", "save the code as utils.py" | False | Writes `LAST_CODE` to disk under `PROJECT_DIR`, `.bak` backup if the target exists, validation status and line count; refuses paths escaping the project dir. |
| `pro_fix_code` | "fix the bug in utils.py", "debug this code:" + fenced snippet, "why does my program crash" | True | Local auto-fix pass + validated LLM rewrite; writes back to file with `.bak` backup plus changed-line diff summary, or stores as `fixed_code.py`; offline checklist when unreachable. |
| `pro_improve_code` | "improve the code in utils.py", "refactor this program", "polish it" | True | Validated senior-style rewrite seeded with top local review findings; write-back with `.bak` + key deltas; offline fallback prints the local review listing and score estimate. |
| `pro_review_code` | "review the code in utils.py", "audit this code" + snippet | False | Findings grouped CRITICAL/WARN/INFO with line numbers, score out of 10, top recommendation, optional blunt online second opinion (clipped to 900 chars). |
| `pro_explain_code` | "explain the code in utils.py", "walk me through this snippet" | False | AST-derived outline (functions with signatures, branch complexity, classes) + optional online narrative paragraph. |
| `pro_translate_code` | "convert this python to rust", "translate the javascript to python" | False | Translated code stored as `translated_<lang>.<ext>`; Python/JS targets fully re-validated, others bracket-balance checked; offline fallback is a Python<->JS pocket cheatsheet. |
| `pro_gen_tests` | "write unit tests for:" + snippet, "test this code" | False | Pytest scaffold covering each public function (happy path, edge argument, possible raises), compile-checked before display, plus extra online cases; run hint `pytest <fname>`. |

Supporting state: `PROJECT_DIR` (line 28) pins all relative paths to the
module's directory; `LAST_CODE` (line 30) remembers the most recent generated
snippet (`{"code", "lang", "name"}`) so "save it" works without repeating the
code.

### 2.2 File tools — `fp_*` (file_power.py, 16 skills)

Caps: head/tail and range slices 60 shown lines, full read 200 lines, diff
80 lines, search 40 hits (400 matches scanned max), tree 120 entries, search
skips files over 2 MiB.

| Skill | Example commands | Priority | Returns |
|---|---|---|---|
| `fp_read_head` | "show first 20 lines of x.py", "head of x.py", "peek at x.py" | True | Line-numbered head of file + count of unshown lines. |
| `fp_read_tail` | "last 10 lines of x.py", "tail of x.py", "end of x.py" | False | Line-numbered tail with correct start number + trimmed note. |
| `fp_read_range` | "lines 5 to 10 of x.py" | False | Numbered slice; rejects inverted or out-of-bounds ranges politely. |
| `fp_read_full` | "contents of x.py", "cat x.py", "read x.py" | True | Numbered contents (capped at 200 lines); refuses binary files with their byte size. |
| `fp_write_file` | "write file notes.txt with: hello", "overwrite x.txt with: ..." | True | Bytes/line-count confirmation; creates parents, backs up existing file first; protected paths refused. |
| `fp_append_file` | "append text to x.log", "add a line foo to x.txt" | False | Append confirmation (adds newline separation when needed); creates the file if absent; backs up prior version. |
| `fp_replace_in_file` | "replace old_text with new_text in x.py" | True | Replacement count + backup path; reports "nothing matched" when 0 occurrences. Quote-aware argument parsing via `_parse_replace_args`. |
| `fp_insert_line` | "insert text at line 4 in x.py", "add text after line 2 in x.py" | False | Insert position confirmation; bounds-checks against line count + 1. |
| `fp_delete_lines` | "delete lines 3 to 5 in x.py", "delete line 7 in x.py" | False | Removed-line count and preview of deleted text + backup path; bounds-checked. |
| `fp_delete_file` | "delete file x.py", "trash x.py" | True | On macOS moves to `~/.Trash` (timestamped on name collision); falls back to `unlink`; refuses directories and protected paths. |
| `fp_copy_file` | "copy a.txt to b.txt" | False | Copy confirmation; refuses folder sources/destinations, backs up overwritten destination. |
| `fp_move_file` | "move a.txt to b.txt", "rename a.txt to b.txt" | False | Move/rename confirmation; same guards as copy. Shares `_e_copy_or_move`. |
| `fp_search_content` | "search for TODO in . for py", "grep 'def main' in src" (`/regex/` or quoted patterns) | False | `path:line:` hit list (max 40), total match/file counts; skips hidden files, binaries, SKIP_DIRS. |
| `fp_tree` | "folder tree of src", "tree of ." | False | ASCII tree (dirs first), file/dir counts, pruned at 120 entries. |
| `fp_diff_files` | "diff between a.py and b.py", "compare a with b" | False | Unified diff with added/removed counts, capped at 80 lines; "(identical, sir)" when equal. |
| `fp_mkdir` | "make a new folder called tests", "new directory at tmp/x" | False | Created-folder confirmation or "already there" note. |

### 2.3 Developer-relevant power skills — `ps_*` (power_skills.py, dev subset)

`power_skills.register()` installs 24 `ps_*` skills in total (clipboard x4,
system report, git x6, docker x3, wikipedia/define/synonyms/antonyms/news,
math solver x3, api test, sqlite). All are `priority=False`. The
developer-facing ones:

| Skill | Example commands | Priority | Returns |
|---|---|---|---|
| `ps_git_status` | "git status", "git status in ~/proj" | False | Branch name + change count + first 10 porcelain entries; "not a git repository" guard. |
| `ps_git_add` | "git add .", "git add src in ~/proj" | False | Staged-target confirmation; non-zero exits surface git's first error line. |
| `ps_git_commit` | 'git commit with message "second"' | False | Committed summary line with changed-file counts; rejects messages under 3 chars; detects clean tree. |
| `ps_git_log` | "git log", "git show log" | False | Last 7 commits, newest first (`log --oneline -7`). |
| `ps_git_branches` | "git branches", "current branch" | False | Current branch + up to 8 other branch names. |
| `ps_git_diff` | "git diff" | False | Tail of `git diff --stat` (last 6 lines) or "no unstaged changes". |
| `ps_docker_ps` | "docker ps", "docker running containers" | False | Up to 10 rows of name/image/status; install offer when the CLI is missing; daemon-down probe message. |
| `ps_docker_images` | "docker images" | False | Up to 10 cached repository:tag entries with sizes. |
| `ps_docker_version` | "docker version", "is docker running" | False | Daemon version string or unreachable-daemon notice. |
| `ps_api_test` | "test the api https://example.com/health", "ping the api ..." | False | Status verdict ("healthy"/status code), latency in ms, content type, body size, JSON parse check. |
| `ps_sqlite_query` | "sqlite query data.db select id from users" | False | Read-only SELECT/WITH results as an ASCII table (20 rows max, cells clipped to 28 chars); mutations refused by voice; opens the DB with `mode=ro` URI. |
| `ps_system_report` | "system report", "how is my system" | False | CPU %, RAM used/total, disk free, uptime days, battery state, top CPU process; telemetry-failure honesty line when everything fails. |

Non-dev `ps_*` skills not tabulated above follow the same contract: clipboard
history/paste/clear/copy (macOS `pbpaste`/`pbcopy` with a persisted 50-item
history in `jarvis_clipboard.json`), wikipedia/define/synonyms/antonyms/news
(network-guarded REST calls), and solve_equation/derivative/integral (local
exact-arithmetic math with step-by-step replies).

---

## 3. Validation Pipeline

`code_validator.py` sits between generation and delivery. Public API:
`strip_fences`, `extract_code_blocks`, `detect_language`, `validate_python`,
`validate_javascript`, `validate`, `generate_validated`,
`summarize_validation`, and the `ValidationResult` dataclass
(`ok`, `lang`, `code`, `errors`, `warnings`, `stage`). Every public function
is deterministic and never raises on malformed input.

```
            raw LLM reply / pasted snippet
                        |
          +-------------v--------------+
          | fence-strip                |   extract_code_blocks() joins ALL
          | ```lang ... ``` blocks     |   fenced blocks with blank lines;
          | else leading/trailing      |   without fences, prose openers
          | prose trimming             |   ("Here's...", "Sure...") and tails
          +-------------+--------------+   ("Let me know...") are trimmed
                        |
          +-------------v--------------+
          | language detection         |   detect_language(): normalized hint
          | (hint aliases -> sniffing) |   (py/js/node/c++...) short-circuits;
          +------+------+-------------+   else sniffs shebangs, DOCTYPE, SQL,
                 |                       | fn main, #include, def/import/class,
                 v                       | function/const/=>
   +-----------------------------------v-----------------------------------+
   |                          validate() dispatch                         |
   +-----------------------+-------------------------+---------------------+
   | python                | javascript              | everything else     |
   |  1. ast.parse         |  node --check on a      | typescript: JS      |
   |     ("line N: msg")   |  temp .js file (10 s    |  check + warning    |
   |  2. compile()         |  budget); node lookup   | html: tag presence  |
   |  3. optional exec:    |  cached via which();    | sql/bash/go/rust/   |
   |     sys.executable -I |  missing node => ok +   | cpp/java/c: bracket |
   |     - fed via stdin,  |  explanatory warning    | balance only        |
   |     fresh tempdir cwd,|                         | (strings/comments   |
   |     timeout 6 s,      |                         | aware; warnings,    |
   |     stderr distilled  |                         | never hard fail)    |
   |     to last meaningful|                         | unknown: accept +   |
   |     exception line    |                         | warning             |
   +-----------------------+-------------------------+---------------------+

Exec-stage guards (skip execution with a warning):
  * input( ... ) present            -> "skipped execution: waits for stdin"
  * while True without any break    -> "skipped execution: potential infinite loop"
```

The exec stage runs in a subprocess (`sys.executable -I -`) inside a fresh
`tempfile.TemporaryDirectory`, so imports/site state are isolated and the
wall-clock budget (default 6.0 s) turns hangs into errors. A non-zero exit
surfaces only the most diagnostic stderr line, found by scanning the traceback
backwards for known exception names.

### Retry-with-error-feedback and best-candidate fallback

`generate_validated(llm_call, prompt, lang_hint=..., max_attempts=2,
exec_simple=False)` closes the loop:

```
for attempt in 1..max_attempts:
    reply = llm_call(current_prompt)
    if reply is None:            # transport/API failure
        return "", result(stage="no-code",
                          errors=["language model unavailable"])   # stop now
    candidate = strip_fences(reply)
    result    = validate(candidate, hint=lang_hint, ...)
    if result.ok:
        return candidate, result                                   # done
    track best candidate (fewest errors so far; earliest wins ties)
    if attempts remain:
        current_prompt = prompt +
            "\n\nYour previous output FAILED validation with these errors:\n" +
            "- <error 1>\n- <error 2>\n" +
            "Fix EVERY issue and return ONLY the corrected complete code..."
return best_code, best_result        # best-candidate fallback
```

Callers render the verdict with `summarize_validation(vr)` (one line such as
`validated Python (syntax + compile)` or `syntax errors found: line 3: invalid
syntax`); `code_brain_pro._summarize_vr` wraps it with a persona-safe fallback
when the validator module is absent.

`code_validator` itself is optional from `code_brain_pro`'s point of view: if
the import fails, `_cv()` retries once via `importlib` and skills degrade to
`_strip_fences_basic` plus no validation summary.

---

## 4. Local Template Library

`TEMPLATE_LIBRARY = TEMPLATE_A + TEMPLATE_B + TEMPLATE_C` (35 templates:
13 algorithms, 7 data/services, 15 tooling).
Each entry is `(keywords, filename, code)`. Matching (`_local_template`)
lowercases the task, scores whole-word keyword hits, and picks the highest
scorer; the chosen template then gets the user's task embedded into its module
docstring (`_embed_task`) before being validated like any other code. Entries
whose first keyword starts with `# jarvis:no-exec` declare side-effecting code
that must skip the exec stage (enforced separately by `_safe_to_exec`).

Categories:

- **TEMPLATE_A — classic algorithms and data structures:** fibonacci
  (iterative/recursive/series), factorial family, primes below a limit with
  sieve, palindrome checks and longest substring, anagram checking/grouping,
  binary search with insertion point, quicksort (in-place and functional),
  bubble sort, singly linked list, stack (with balanced-brackets use case),
  queue, binary search tree, BFS/DFS graph traversal with shortest path.
- **TEMPLATE_B — I/O, data, and services:** word frequency counting, CSV
  reader/writer, JSON load/save/merge, HTTP GET wrapper (requests), Flask demo
  API, FastAPI + pydantic task store, sqlite CRUD helpers.
- **TEMPLATE_C — tooling and utilities:** dataclass record model, custom
  exception hierarchy, timing decorator, retry decorator, context-manager
  timer block, generator utilities (infinite Fibonacci stream), argparse CLI
  skeleton, tkinter GUI window, password generator, countdown timer, email
  validator/harvester, gcd/lcm, matrix multiply, temperature converter, pytest
  test template.

A template hit is still passed through `cv.validate(...,
exec_simple=_safe_to_exec(code))`; if validation flags it, the answer carries
a "Heads-up, sir" warning rather than silently shipping broken code.

---

## 5. Review Engine

`_analyze(code)` produces findings as `(severity, line, title, detail)`
tuples, sorted by severity rank (CRITICAL 0, WARN 1, INFO 2), then line
number, then title. A `SyntaxError` short-circuits to a single WARN "does not
parse".

Severity weights (`_SEVERITY_WEIGHT`, line 384):

| Severity | Weight |
|---|---|
| CRITICAL | 2.0 |
| WARN | 0.5 |
| INFO | 0.1 |

Score formula (`_score_findings`):

```
score = round(max(0.0, min(10.0, 10.0 - sum(weight(f.severity) for f in findings))), 1)
```

Checks by severity:

| Severity | Check | Trigger |
|---|---|---|
| CRITICAL | eval()/exec() usage | any `ast.Call` naming `eval` or `exec` |
| CRITICAL | hardcoded credentials | regexes for Groq keys (`gsk_...`), AWS keys (`AKIA...`), and `api_key=`/`password=`/`secret=` string literals |
| WARN | SQL built with an f-string | f-string literal text containing SELECT/INSERT/UPDATE/DELETE plus FROM/WHERE/LIKE placeholders |
| WARN | global statement | any `ast.Global` |
| WARN | == comparison to None/True/False | `Compare` with Eq/NotEq against those constants |
| WARN | mutable default argument | default is a list/dict/set literal or `list()/dict()/set()` call |
| WARN | long function | function spans more than 60 lines |
| WARN | bare except (incl. except: pass variant) | `ExceptHandler` with no type |
| WARN | open() without with | `open()` call whose lineno is not inside a `With`/`AsyncWith` body |
| WARN | deep nesting | conditional/loop/try/with/match nesting deeper than 4 levels |
| INFO | missing docstring | public function or class (name not starting with `_`) without one |
| INFO | except: pass | typed handler whose body is only `pass` |
| INFO | debug prints | aggregated count of all `print()` calls (reported once at the first site) |
| INFO | TODO/FIXME/HACK markers | aggregated marker count |
| INFO | long lines | lines beyond 120 characters (aggregated) |
| INFO | unused import | imported name appears at most once in the source |

`pro_review_code` renders these grouped by severity (12 per group maximum),
appends `_top_recommendation(findings)` (the first finding turned into an
action), and adds a clipped online second opinion when reachable.

Related mechanical repairs used by `pro_fix_code` (`_local_auto_fixes`):
bare `except:` -> `except Exception as e:`, `== None/True/False` -> identity
checks, tabs -> 4-space indentation, trailing whitespace removal, EOF newline,
and DEBUG-print flagging (left in place).

---

## 6. File Safety

Backups:

- `file_power._backup(path)` copies with `shutil.copy2` to `path.bak`,
  falling through to `path.bak.2`, `path.bak.3`, ... until a free name is
  found. Used by every mutating `fp_*` skill before writing.
- `code_brain_pro` uses simpler overwrite backups: `_e_save` and
  `_write_back` make `path.bak` when the target exists (single slot).

Protected prefixes (`file_power.PROTECTED_PREFIXES`, lines 15-23):
`/System`, `/bin`, `/sbin`, `/usr`, `/etc`, `/private/var`,
`/Library/System`. `_protected(path)` resolves symlinks with
`os.path.realpath` and compares against these prefixes; anything inside the
project directory is always allowed. Mutating `fp_*` skills return a refusal
message instead of touching protected paths.

Traversal rules:

- Relative paths resolve against the module's `PROJECT_DIR` after
  `os.path.expanduser` and `normpath`.
- `pro_save_code._resolve_save_path` rejects any target whose realpath is not
  strictly inside `PROJECT_DIR` (the project directory itself is also
  refused), so `..` tricks and absolute escapes cannot write outside the
  workspace.
- Deletion is two-step safe: directories are refused outright, macOS deletes
  go to `~/.Trash` with timestamped collision handling, and only a failed
  Trash move falls back to `os.unlink`.

Read-side limits (see section 2.2 caps list): binary sniffing (NUL byte in the
first 8192 bytes), hidden-file and `SKIP_DIRS` skipping (`.venv`, `venv`,
`__pycache__`, `.git`, `node_modules`, `.idea`, `.Trash`), and per-skill line/
hit/entry caps keep outputs bounded.

---

## 7. Extending Guide

### 7.1 The registration contract

`Brain.register(name, detect, execute, priority=False)` (brain.py:302) appends
a `Skill`. The contract every module follows:

```python
def detect(cmd_lower: str) -> dict | None:
    """Return a ctx dict when this skill owns the command, else None."""

def execute(app, ctx) -> str:
    """Return the persona reply string ('..., sir.')."""
```

- `detect` receives the lowercased command. Exceptions raised inside `detect`
  are swallowed by `Brain.think` (treated as None); `file_power` additionally
  wraps detectors in `_detector(...)` for logging.
- Registration order is match order: `Brain.think(cmd, priority=None)` walks
  `self.skills` linearly and the first truthy ctx wins. `priority=True` skills
  are consulted only on the main loop's priority pass.
- Loading order in `Brain.__init__`: core `_register()` skills ->
  `brain_extra.register_extra` -> prune `SUPERSEDED_SKILLS` (old coding skills
  that would shadow PRO versions) -> `_load_pro_modules()` importing
  `code_brain_pro`, `file_power`, `power_skills`, each fail-soft with a
  WARNING print.
- Wrap your executor defensively like the built-ins do (`@_guard` in
  `code_brain_pro`, `_executor(...)` in `file_power`, `_wrap(...)` in
  `power_skills`) so a crash becomes a persona apology, never an exception
  escaping into the assistant loop.
- Persona convention: replies address the user as "sir" (e.g. "Saved to
  ..., sir"). Keep new replies consistent.

To add a pack, define a `register(brain)` that loops your
`(name, detect, execute, priority)` tuples into `brain.register(...)`, then
append your module name to the tuple in `Brain._load_pro_modules`
(brain.py:283).

### 7.2 Testing pattern (RecorderBrain)

Follow `tests/test_power_skills.py`: a minimal fake brain captures
registrations, and a `run` helper asserts detection before executing.

```python
class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute)


@pytest.fixture()
def brain():
    b = RecorderBrain()
    ps.register(b)
    return b


def run(brain, name, cmd):
    detect, execute = brain.skills[name]
    ctx = detect(cmd)                      # assert ctx is not None
    return execute(DummyApp(), ctx)
```

Conventions used across `tests/`: insert the repo root into `sys.path`, mock
network (`_net_get`) and subprocesses (`_run`, `shutil.which`) with
`monkeypatch`, set `JARVIS_TEST=1` to disable `power_skills`' clipboard poller
thread, use `tmp_path` plus `monkeypatch.setattr(module, "PROJECT_DIR", ...)`
to sandbox file operations, and end with a detector-hygiene test asserting
chit-chat ("tell me a joke", "flip a coin") matches nothing.

### 7.3 Running pytest

Run the suite as:

```
pytest -p no:debugging
```

While the legacy `code.py` exists in the project root, it shadows the standard
library `code` module, which breaks pytest's debugging plugin; disabling that
plugin with `-p no:debugging` keeps collection working. Remove the flag once
the legacy stub is gone.

---

## 8. Known Limitations

- Full static validation (ast.parse -> compile -> optional restricted exec)
  exists for Python only. JavaScript gets `node --check` syntax checking;
  TypeScript is checked at the JavaScript level with an explicit "no full type
  check" warning; SQL/Bash/Go/Rust/C++/Java/C get bracket-balance warnings
  only; anything else is accepted with an "unknown language" warning.
- The exec stage is isolation, not a security sandbox: `sys.executable -I -`
  in a temp directory with a timeout blocks stdin-driven hangs and infinite
  loops, but does not firewall network access, the filesystem outside the cwd,
  or resource exhaustion.
- Template matching is keyword-scored; paraphrases that miss the keywords fall
  through to the LLM, and offline they produce the honest capability list.
- `LAST_CODE` holds exactly one snippet; generating new code silently replaces
  it, and `pro_save_code` overwrites an existing target (with `.bak`).
- Generated files can only be saved inside `PROJECT_DIR`.
- Detectors are English-language regexes; unusual phrasings may miss, and
  heavily nested natural-language requests may misroute to the first matching
  detector in registration order.
- The review engine is AST/regex based: no type inference, no dataflow or
  cross-module analysis; unused-import detection is a word-count heuristic.
- Platform coupling: clipboard skills need `pbpaste`/`pbcopy`, deletion uses
  `~/.Trash`, and uptime falls back to `sysctl kern.boottime` — i.e. the
  stack assumes macOS for those paths while remaining importable elsewhere
  with graceful failures.
