# PROMPTS_BACKLOG

How to use: pick exactly one prompt per session, paste it into the coding engine, and ship it as its own change — implement, add or adjust tests, run the full suite with `pytest -p no:debugging`, and commit only when green. Keep scope limited to that single prompt (touch nothing else), lean on the existing `.bak` write-back and validation gates for safety, and strike completed items through with `~~strikethrough~~` so the next session picks up cleanly where this one stopped.

## A. Coding-brain depth

### 1. Unified-diff incremental editing with per-hunk validation
Teach the coding engine to accept LLM edits as unified diffs applied hunk-by-hunk, validating each hunk against current file content plus a syntax compile before any write, and rejecting the entire diff if a single hunk fails context match. Acceptance: a 3-hunk diff with one stale hunk writes zero bytes, reports an error naming the failed hunk, and unit tests cover both that rejection path and a clean round-trip.

### 2. Multi-file refactor planning
Implement a `refactor_plan` skill that takes a rename/move/signature-change goal, emits an ordered step list (file, old text, new text, depends-on) saved to `.jarvis/refactor_plan.json`, then applies steps sequentially after user confirmation with rollback on first failure. Acceptance: renaming `Assistant.process` to `Assistant.handle` across 4 files completes atomically; a deliberately failing step aborts remaining steps and restores prior content from `.bak`.

### 3. Repo map builder
Build a `repo_map` command that walks the project (respecting .gitignore), extracts files, classes, functions, and imports via AST, and renders a compact tree with line numbers under a fixed token budget. Acceptance: on this repo it lists every module with public symbols in under 2000 tokens, caches to `.jarvis/repo_map.md`, and reuses the cache unless file mtimes change.

### 4. Unit-test runner parsing pytest output
Create a skill that runs `pytest -q -p no:debugging`, parses the summary line and failure blocks into structured JSON (test id, outcome, duration, error excerpt). Acceptance: against a suite seeded with 2 failures and 1 error, the parsed report names exactly those three with correct ids, and `--json` output feeds directly into the self-critique prompt.

### 5. cProfile skill
Add `profile_run <module>` executing code under cProfile, saving stats to `.jarvis/profiles/<timestamp>.prof`, and printing the top 20 functions by cumulative time in a readable table. Acceptance: profiling a known-slow fixture ranks it number 1, and `profile_compare <a> <b>` flags regressions over 10 percent by function.

### 6. Type-hint inference pass
Implement a pass that infers parameter and return annotations for untyped functions from call-site evidence and simple value flow, inserting them via the unified-diff editor. Acceptance: running it on a fixture module annotates at least 80 percent of functions, the result passes `mypy --ignore-missing-imports`, and the full test suite stays green unchanged.

### 7. Docstring linter autofix
Add a docstring checker flagging missing, too-short, or stale docstrings per pydocstyle-style rules, with autofix generating stubs from signatures covering args, returns, and raises. Acceptance: autofix completes NumPy-style docstrings on a fixture while never touching private `_prefixed` helpers, and `--check` mode exits nonzero while any violation remains.

### 8. Complexity budget enforcer
Enforce a configurable cyclomatic complexity budget (default 10) computed via radon, reporting violations and refusing coding-engine edits that raise a function above its previous score unless `--allow-complexity` is passed. Acceptance: editing a function from CC 8 to CC 12 without the flag fails validation naming the function and both scores, proven by test.

### 9. AST-query code search
Provide `ast_query "<pattern>"` supporting forms like functions calling X, classes inheriting Y, and assignments to Z, implemented over Python's ast module rather than regex. Acceptance: on a fixture repo each documented query form returns the exact expected symbol list as file:line entries in under 1 second across 500 files.

### 10. Commit-message generator from diffs
Generate conventional-commit messages (`type(scope): subject` plus body bullets) from staged diffs, classifying type from changed paths and hunk contents. Acceptance: for a staged change touching two modules and their tests, output obeys the 50-character subject rule, the body lists each behavior change, and `git commit -F` accepts it verbatim in a temp-clone test harness.

## B. File & system power

### 11. Atomic temp-plus-rename writes everywhere
Replace every direct file write across tools with a shared `atomic_write(path, data)` helper writing `<path>.tmp` in the same directory, fsyncing, then `os.replace`-ing into place. Acceptance: grep finds no bare write-mode opens outside the helper, a kill-mid-write test leaves the original intact, and all tool tests pass unchanged.

### 12. File watcher
Add a debounced filesystem watcher built on watchdog exposing `watch <path> --on <create|modify|delete> <command>` firing shell or JARVIS commands. Acceptance: rapid successive writes to a watched file trigger exactly one callback within 500 ms of quiescence, and all events append to `.jarvis/watch.log`.

### 13. Zip/tar extract/create
Implement `archive extract <file> [dest]` and `archive create <zip|tar.gz> <paths...>` with safe extraction rejecting path-traversal members. Acceptance: extracting a malicious archive containing `../evil.txt` aborts writing nothing outside dest, while normal zip and tar.gz round-trips preserve member bytes exactly.

### 14. Batch rename patterns
Add `rename_batch --match <regex> --to <template>` supporting capture-group placeholders, a dry-run preview table, and undo driven by a recorded journal. Acceptance: renaming 12 files shows exact before/after rows first, execution applies all 12, and `rename_batch --undo` restores every original name with zero mismatches.

### 15. Disk usage analyzer
Build `disk_usage [path]` reporting largest directories and files with sizes and counts plus a compact text treemap, caching scan results for reuse. Acceptance: on a seeded fixture tree totals match `du -sk` within rounding, the top-10 list is sorted descending, and a repeat scan serves from cache in under 100 ms.

### 16. Process manager
Provide safe process tooling: `ps_top [--by cpu|mem]`, `kill_pid <pid>`, and `kill_name <name>` gated behind explicit confirmation for processes not owned by this session. Acceptance: `ps_top` ordering matches Activity Monitor within tolerance, killing a spawned test process returns its exit status, and attempting to kill PID 1 is refused with a clear denial message.

### 17. launchctl services wrapper
Wrap launchctl for listing, starting, stopping, and bootstrapping user services with parsed tabular output instead of raw plist dumps. Acceptance: loading a sample agent plist shows it under `services list --user`, stop and start transitions reflect in `launchctl print`, and failures surface friendly messages carrying the underlying exit code.

### 18. Network diagnostics ping/port/dns
Add `net check <host>` bundling DNS resolution, a TCP port probe (default 443), and latency stats (min/avg/max/jitter over N pings) into one report. Acceptance: a known-good host yields resolved IP, open port, and latency lines; a nonexistent domain fails at the DNS stage with a targeted message; forced offline mode degrades gracefully stage by stage.

### 19. Env var editor
Implement persistent environment management storing overrides in `.jarvis/env.json` with `env set/get/unset/list`, applied to spawned subprocesses plus shell export output. Acceptance: `env set FOO=bar` survives an assistant restart, a spawned child sees FOO, and `env export` prints valid lines zsh evals without error.

### 20. Secure shred
Add `shred <path>` overwriting files with random bytes for multiple passes before unlinking, refusing symlinks and any path outside an allowlist root. Acceptance: shredded content cannot be recovered from a pre-captured mirror of the freed blocks, symlink targets are untouched, and refusal cases exit nonzero with explanations.

## C. Intelligence & reasoning

### 21. Conversation memory summarization
Add rolling summarization compressing conversation older than N turns into a durable per-session summary object injected as context. Acceptance: after 40 turns the live context holds only the last 10 verbatim turns plus the summary, a key fact stated at turn 3 remains answerable, and summaries update incrementally instead of regenerating each turn.

### 22. Context compaction
Implement a token-budget compactor trimming oversized tool outputs (keeping head, tail, and full error blocks) and deduplicating repeated snippets before hitting model limits. Acceptance: a 30k-token conversation compacts to fit an 8k budget while preserving every final tool error verbatim, and a regression test pins the ratio within 15 percent of target.

### 23. Plan-and-execute loop with checkpoints
Add a plan mode emitting numbered steps, executing one step per iteration, checkpointing completed state to disk after each step, and resuming mid-plan after crash or restart. Acceptance: killing the process after step 2 of 5 then restarting continues at step 3 without repeating steps 1-2, verified by journal entries and a side-effect counter.

### 24. Self-critique pass
Insert an automatic critique stage after draft answers or code changes checking requirement coverage, edge cases, and test impact, then revising once before presenting. Acceptance: critique output includes a checklist mapping each requirement to addressed or unaddressed, and seeded-flaw fixtures show the revision fixing the injected flaw.

### 25. Citation-required research mode
Add `research <topic>` requiring every factual sentence in the answer to carry an inline `[n]` citation mapped to fetched sources listed at the end with retrieval dates. Acceptance: answers containing uncited factual claims are internally rejected and regenerated up to twice, and a validator unit test confirms all listed URLs resolve on fixture pages.

### 26. Chart data interpreter
Interpret pasted chart images extracting axes, series labels, approximate data points, and trend classification into structured JSON plus a plain-language summary. Acceptance: across 5 seeded matplotlib charts extracted series values land within 10 percent of ground truth and trend labels (up/down/flat/noisy) are correct on all seeds.

### 27. Spreadsheet reader/writer
Support reading and writing xlsx/csv via openpyxl with cell-range access, formula awareness, and typed column inference. Acceptance: writing a workbook of headers plus 100 typed rows then re-reading preserves int/float/date types, cached formula values are surfaced on read, and csv-to-xlsx-to-csv round-trips losslessly on fixtures.

### 28. PDF extraction Q&A
Add PDF ingestion extracting text page-wise with offsets, caching results, and answering questions with page-number citations. Acceptance: 10 curated questions about a 30-page fixture are answered correctly with correct page citations, and scanned-PDF input falls back to a clear OCR-unavailable notice rather than garbage text.

### 29. Email tone drafting
Provide `draft_email` with tone presets (formal, friendly, firm, apologetic) transforming bullet intent into complete emails with subject options. Acceptance: the same bullets rendered formal versus friendly differ measurably in greeting, sign-off, and hedging per a keyword rubric, and output always includes exactly 3 subject candidates.

### 30. Meeting-notes structurer
Convert rough transcripts or notes into structured minutes containing decisions, action items (owner, due date), risks, and parking lot, emitted as Markdown plus JSON. Acceptance: on a fixture transcript every action item maps to a speaker-attributed quote, owners and dates normalize to schema, and both outputs validate against a provided JSON Schema.

## D. Voice & UX

### 31. Streaming TTS sentence pipelining
Pipeline TTS so playback starts once the first sentence finishes synthesis while later sentences queue during generation, with barge-in cancel. Acceptance: time-to-first-audio drops below 800 ms versus whole-reply synthesis on a 5-sentence reply, and mid-stream interruption halts audio within 300 ms and flushes the queue.

### 32. Whisper-local STT
Integrate local faster-whisper as an STT backend selectable beside the cloud path, with auto language detection and configurable model size. Acceptance: transcribing 10 seeded WAV phrases achieves at most 5 percent WER fully offline, network-disabled end-to-end operation succeeds, and backend switching requires only a config flip.

### 33. Wake-word tuning UI
Build a tuning panel (CLI or minimal GUI) recording samples, computing detection thresholds, and letting the user adjust sensitivity with live false-accept/reject feedback. Acceptance: calibrating on 10 positive and 10 negative clips selects the threshold maximizing held-out accuracy, settings persist, and a rerun reproduces the same recommendation.

### 34. Syntax-highlighted transcript
Render the terminal transcript with pygments-highlighted code blocks and color-coded speakers, degrading to plain text when piped. Acceptance: Python and bash blocks render highlighted in a TTY, `JARVIS_PLAIN=1` or non-TTY output strips all ANSI codes, and no escape sequences leak into log files.

### 35. Dark/light theme
Add theme support defining palettes for prompt, transcript, errors, and highlights, switchable at runtime and persisted. Acceptance: `theme light|dark|auto` switches immediately without restart, auto follows macOS appearance via defaults read, and custom themes load from YAML overriding any subset of keys.

### 36. Keyboard shortcuts
Wire readline-based shortcuts: Ctrl+L clear, Ctrl+U wipe input, Ctrl+R history search, Alt+Enter newline submit, Esc cancel current generation. Acceptance: each shortcut performs its documented action in the interactive REPL, Ctrl+C during generation cancels leaving state consistent, and a `shortcuts` screen documents all of them.

### 37. Fuzzy help search
Implement `help <query>` fuzzy matching over skills, commands, and flags with ranked results and usage snippets. Acceptance: querying "renam" surfaces batch-rename first, a typo like "netwrk" still hits network diagnostics, and every result includes an example invocation verified parseable.

### 38. Macro recording
Add `macro start|stop|run <name>` recording user commands (not outputs) to replayable scripts with positional variable substitution. Acceptance: recording 4 commands then running replays them in order honoring `$1`/`$2` substitution, nested macro-start is refused, and macros persist across restarts in `.jarvis/macros/`.

### 39. Notification center integration
Surface long-task completions, errors, and reminders as native macOS notifications with click-through focus actions. Acceptance: any task over 5 seconds fires exactly one notification, clicking focuses the terminal app, and do-not-disturb suppresses everything except error-level notifications.

### 40. Menu-bar status item
Add a rumps menu-bar item showing idle/listening/thinking state with menu actions for mute, theme, and quit. Acceptance: the icon tracks real session transitions within 500 ms, menu actions toggle the same internals as their CLI equivalents, and quitting via the menu terminates all child processes cleanly.

## E. Reliability & security

### 41. Secret-scan before writes
Scan every file-write payload and diff for high-entropy strings and known key patterns (AWS, OpenAI, SSH, PEM), blocking the write until redacted. Acceptance: saving a fixture containing a fake AWS key is blocked with the offending line number, `# jarvis:allow` comments suppress known-safe hits, and zero false positives occur on existing repo fixtures.

### 42. Dependency audit
Add `audit deps` reconciling requirements/pyproject against PyPI advisories via pip-audit plus pin-drift checks, producing a Markdown report with severity and fix suggestions. Acceptance: seeding a vulnerable pinned package yields a finding with CVE id and fixed-version suggestion, a clean tree reports green, and the audit completes in under 90 seconds.

### 43. Sandboxed exec resource limits
Run untrusted or generated code in subprocesses capped by CPU seconds, wall clock, and RSS memory, with outbound network denied via a sandbox-exec profile. Acceptance: an infinite loop dies at the wall-clock cap, a memory bomb dies at the RSS cap with the reason recorded, and socket creation fails fast inside the profile.

### 44. Prompt-injection hardening for web text
Sanitize all fetched web/wiki/news text before it reaches the model: strip instruction-like directives and wrap content in delimited data blocks marked non-authoritative. Acceptance: an automated eval of 10 injection payloads embedding "ignore previous instructions" strings fails to override the active task, and provenance metadata survives into the transcript log.

### 45. Rate-limit budget tracker
Track API calls per provider against configured minute/hour/day budgets using a token-bucket limiter with friendly wait messages replacing raw 429 surfacing. Acceptance: exceeding the minute budget defers with an ETA, persisted counters survive restart, and simulated provider 429s trigger exponential backoff capped at 60 seconds.

### 46. Crash-recovery journal
Journal every mutating action (files written, commands run, plans advanced) to append-only `.jarvis/journal.ndjson` with pre/post hashes enabling `recover last`. Acceptance: simulating a crash mid-refactor then running `recover last` restores a consistent tree matching the journal post-state, and a corrupt trailing line loses nothing earlier.

### 47. Health-check command
Provide `doctor` verifying python version, required binaries (git, docker, ffmpeg, whisper model), API-key presence (never printing values), disk space, and config validity, exiting nonzero on critical failures. Acceptance: doctor catches a deliberately broken PATH and a missing key in fixtures, groups output as pass/warn/fail, and CI adopts it as a smoke gate.

### 48. Dot-bak rotation policy
Extend the existing `.bak` write-back with rotation keeping the last N versions per file under `.jarvis/bak/<relpath>/` with timestamps and a global size cap pruning oldest-first. Acceptance: 12 sequential edits leave exactly N=5 restorable versions, `bak list <file>` shows them newest-first with sizes, and total bak storage respects the cap.

### 49. Permission prompts outside project
Gate any write or exec outside the project root behind an interactive y/n prompt with remembered per-path grants stored in `.jarvis/permissions.json`. Acceptance: a first write to ~/Documents asks and honors the answer, remembered grants skip future prompts, and non-interactive mode denies by default rather than hanging.

### 50. File-mutation audit log
Record every create/modify/delete performed by any tool with timestamp, tool name, prompt id, and content hash, queryable via `audit [path] [since]`. Acceptance: a scripted sequence of 8 mutations produces exactly 8 entries, since/path filters return correct subsets, and tampering is detectable through chained hashes.

## F. Performance & architecture

### 51. Lazy-load brain_extra chunks
Split brain_extra into lazily-imported capability chunks loaded on demand keyed by detected intent, keeping the base import graph minimal. Acceptance: cold import of the core touches none of the heavy modules (verified via import hook), invoking a coding skill loads only the coding chunk, and idle RSS drops measurably.

### 52. Dict skill index replacing linear scan
Replace linear skill-name scanning with a dict index built at registration including an alias map, preserving registration order for listings. Acceptance: a dispatch benchmark over 10k lookups improves at least 50x versus baseline, unknown-skill fallback behavior is unchanged, and existing skill tests pass untouched.

### 53. Package split with shims
Split the monolith into subpackages (core, skills, io, ui) shipping temporary shim modules re-exporting old paths with deprecation warnings. Acceptance: legacy imports such as `from brain import respond` still work emitting DeprecationWarning exactly once, internal imports use the new layout, and `-W error::DeprecationWarning` proves warnings fire.

### 54. Config.py tunables
Centralize magic numbers and toggles (timeouts, budgets, thresholds, feature flags) into typed config.py with env-var overrides validated at startup. Acceptance: grep finds zero hardcoded timeout literals outside config.py, invalid values like negative timeouts fail fast naming the field, and flipping a flag via env changes behavior in an integration test without edits.

### 55. Plugin loader
Load third-party skills from a plugins directory following a manifest convention (plugin.yaml declaring name, version, permissions), isolating load failures per plugin. Acceptance: dropping a sample plugin makes its skill discoverable with no core edits, a syntactically broken plugin logs an error without booting anything down, and declared permissions gate callable tool APIs.

### 56. Async cancellable LLM client
Rework the LLM client around asyncio with cancellation tokens, per-request timeouts, and retry-with-jitter shared across skills. Acceptance: cancelling a streamed completion stops token consumption immediately with no billed-after-cancel calls in the mock transport, timeouts fire per config, and concurrent skills share one client safely under a stress test.

### 57. Duplicate-prompt coalescing
Coalesce identical in-flight prompts so concurrent duplicates share one upstream request and one result via a keyed future map. Acceptance: firing the same prompt 5 times concurrently produces exactly 1 upstream call and 5 identical resolutions, distinct prompts never coalesce, and cleanup prevents leaks across 1k sequential unique prompts.

### 58. Memory profiling harness
Add `mem_profile <scenario>` running scripted scenarios under tracemalloc, snapshotting peaks, and diffing against a baseline stored in `.jarvis/mem_baseline.json`. Acceptance: a seeded leak fixture reports growing retained allocations with top allocators identified, clean scenarios stay within 10 percent of baseline, and the report fits one terminal screen.

### 59. Sub-2-second startup budget
Profile and optimize cold start to reach the interactive prompt in under 2 seconds via lazy imports, deferred hardware init, and parallel warmups, tracked by a timing breakdown command. Acceptance: `startup_report` prints per-phase timings summing to measured wall time, p95 over 10 runs stays under 2 s on the dev machine, and any phase regressing more than 25 percent fails the perf test.

### 60. Headless CI workflow
Add a GitHub Actions workflow running lint, typecheck, pytest (`-p no:debugging`), doctor smoke, and the startup perf test on push and PR, uploading logs and profiles as artifacts. Acceptance: a PR on a passing tree goes green, intentionally broken commits fail at the correct stage, and artifacts contain pytest output plus profiles retrievable without repo access.
