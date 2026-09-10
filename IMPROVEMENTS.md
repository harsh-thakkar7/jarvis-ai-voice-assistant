# IMPROVEMENTS

## Overview

CODING BRAIN upgrade: the assistant now behaves like a senior engineer instead of a code printer. Generated code is validated and retried with error feedback (`code_validator.py`), reviewed via AST-based scoring, written back to disk with automatic `.bak` backups (`file_power.py`), and extended by power file tools (git/docker/process), devops tools, intelligence tools (`power_skills.py`), and a `deepthink.py` reasoning layer that verifies its own multi-step answers before responding.

## What Changed

- `code_validator.py` (933 LOC): validation pipeline — AST syntax gate, runtime smoke check, review scoring; retry-with-error-feedback loop that feeds precise validator errors back to the model for regeneration.
- `code_brain_pro.py` (2834 LOC): upgraded coding skill pack built on the validator (validated generation with retry), superseding the older inline `cb_*` / generate-explain-debug skills.
- `file_power.py` (1067 LOC): power file operations — safe write-back with `.bak` (and `.bak.N`) rotation, plus file management tools.
- `power_skills.py` (1237 LOC): git status/commit, docker ps, process/system devops tools and intelligence tools exposed as registered skills.
- `deepthink.py` (781 LOC): reasoning layer — step decomposition with backward verification of intermediate results and transform-prefix handling for multi-step word problems.
- Integration: `brain.py` wires `code_brain_pro`, `file_power`, and `power_skills` into the skill registry via fail-soft `_load_pro_modules()` (brain.py:281-287) and prunes the superseded legacy coding skills so first-match ordering resolves to the PRO versions (brain.py:255-279); `main.py` inherits this through `Brain`. `deepthink.py` and `code_validator.py` remain importable standalone modules not yet directly wired.
- Tests: new suites `tests/test_code_validator.py`, `tests/test_file_power.py`, `tests/test_deepthink.py`, `tests/test_power_skills.py` covering all four modules. Note: `tests/test_code_brain_pro.py` does not exist in the repo at time of writing.

## Before / After Metrics

| Metric | Before | After |
|---|---|---|
| Consolidated pytest passing | none (no tests for these modules) | 1,113 passed in 5.5s across 30 suites |
| Legacy regression suites | 9 standalone scripts at repo root, untracked baseline | moved under `tests/legacy/` (9 scripts); one-command runner `run_tests.py` executes pytest + all legacy scripts (`--fast` = pytest only) |
| Registered skills at boot | ~1,200 | 2,084 (measured: `JARVIS_TEST=1` `Brain(None)`) |
| LLM backend | Groq-only | llm_client: Groq/OpenAI/Anthropic/Ollama via JARVIS_PROVIDER |
| Multi-model routing | single provider for every step | agent steps can use different providers via per-step `STEP_PROVIDERS` routing (agent_loop.py + llm_client) |
| Global voice | in-app only | hotkey_ptt: system-wide hold-to-talk (pynput + Accessibility), graceful degradation |
| Screen awareness | primary display | multi_monitor: per-display enumerate/capture/stitch + coordinate mapping |
| Cursor buddy | parked orb | follow-cursor mode with tweened motion (menu toggle) |
| Persistent memory | session-only (lost on restart) | memory_core: facts/prefs/turn-log, atomic JSON, survives restarts (verified end-to-end) |
| Multi-step agency | one command at a time | agent_loop: plan→execute→checkpoint→report background jobs with crash recovery |
| Skill supersession | implicit ordering, shadowing bugs | explicit `supersedes=` API + SUPERSEDED_SKILLS prune + think() result cache |
| Voice pipeline | block TTS | streaming_tts: sentence streaming, barge-in interrupt, wired into JarvisBot |
| Security | plaintext key, raw clipboard | keychain vault w/ legacy fallback, secret redaction (LUHN cards, API keys), exec policy engine |
| Clicky pointing UX | static red X | pulsing halo animation on point-at |
| CI | none | GitHub Actions: macOS pytest job + ruff lint, artifacts on failure |
| Per-suite counts | n/a | habits 91, net_diag 86, travel 83, focus 59, deepthink 56, home/games/briefing 50 each, journal 43, app_dev 39, ptt_onboarding 37, power_skills/code_validator 36, agent_loop 34, live_screen 33, security 31, llm_client/calendar_music 28, data_file/reply_bubble 27, mail 26, file_power 25, quick_bar/clicky 22, status_panel 20, web_dev/multi_monitor 19, memory_core 15, streaming_tts 11, hotkey_ptt 10 |
| Core-engine footprint | 0 | 18,135 LOC across the 26 skill/engine modules (measured `wc -l`; largest: code_brain_pro 3,107, power_skills 1,301, file_power 1,082) |

## Bug Fixes During Build

- `gen_skills2.py`: pre-existing tech/cs duplicate-append bug (skills appended twice on regeneration) — present before this work, documented here as inherited.
- `deepthink.py`: backward-verification bug (running-total check walked the wrong direction) and transform-prefix bug (multi-step transforms mis-parsed their prefix operand) — both fixed test-first via TDD; covered by the 56-test deepthink suite.
- `tests/test_power_skills.py`: git fixture applied path prefixes twice, corrupting repo-relative paths — double-prefix fixed in the `git_repo` fixture (tests/test_power_skills.py:115).

## New Features

Validated codegen
- AST-parse gate with `line N: msg` error reporting before any code is accepted (code_validator.py:353-384).
- Retry-with-error-feedback loop: validator errors are fed back to the generator for a corrected attempt.
- Review scoring over the parsed AST to rank candidate outputs.

File safety
- Automatic `.bak` write-back with numeric rotation (`.bak.1`, ...) when the target exists (file_power.py:109-112).
- File management skill set (read/write/edit/move/copy variants).

Power/devops/intelligence tools
- Git status and commit skills; docker ps; process/system inspection tools (`ps_git_status`, `ps_git_commit`, `ps_docker_ps`, ...).
- Intelligence tools pack registered alongside the file/power skills.

Deepthink reasoning layer
- Multi-step decomposition for word problems (running totals, shares, unit rates, each-multiply).
- Backward verification of every intermediate result; warnings logged on mismatch (deepthink.py:126-231, 352).
- Transform-prefix handling for chained transformations.

## Known Risks

- Linear skill scan cost grows with registry size; every request scans the full skill list.
- Legacy `print()` diagnostics remain in `brain_extra.py` / `main.py` paths instead of structured logging.
- Plaintext API-key warning pending: key material may still be handled in cleartext in config/loading code.
- First-match ordering sensitivity: skill resolution depends on registration order; pruning mitigates shadowing today but new same-prefix skills could regress it.

## Next Steps

See PROMPTS_BACKLOG.md.

---

# HARVEST: Skills & Harness Build (session 2026-09-12)

## Overview

Second major build pass: the assistant gained a harness-engineering layer and two full offline skill packs. `prompt_harness.py` now sits between the voice front-end and the Groq call (system-agent-editable prompts, intent routing, reply cleaning), while `skills_computer.py` gives JARVIS real computer control (open apps, click/type/press, screenshots, shell, volume/brightness, trash) and `skills_dev.py` adds a local, offline developer-tools pack (git messaging, code explain, test scaffolding, docstrings, todo scans, dependency checks, JSON tooling, regex, LOC). No LLM calls are involved in any of the 25 new skill executors — everything is deterministic macOS tooling.

## What Changed

- `prompt_harness.py` (531 LOC): harness layer — `build_messages()` (persona + optional context block + trimmed history + per-intent response contract), `classify_intent()` (anchored-regex intent routing → code/translate/summarize/rewrite/command/smalltalk/explain/question), `clean_reply()` (fence and butler-chatter stripping, blank-line collapse, "code" keep-only-body), and `wrap_code_prompt()` / `wrap_website_prompt()` (structured prompt builders for the code-gen and Google AI Studio single-file web / Kotlin app flows). Dependency-free stdlib; every public function is total and never raises; offline `selftest()` passes 8/8.
- `skills_computer.py` (1225 LOC): 15 `cp_*` computer-control skills — `cp_open_url`, `cp_open_app` (mdfind LaunchServices locate, difflib+token ranking), `cp_click`/`cp_double_click`/`cp_right_click` (pyautogui → osascript fallback), `cp_type`, `cp_press`, `cp_screenshot`, `cp_run` (whitelist-gated shell with `JARVIS_ALLOW_DESTRUCTIVE=1` override), `cp_volume`, `cp_brightness` (guarded Quartz), `cp_frontmost`, `cp_quit`, `cp_trash_file`, `cp_screen_size`. Every executor is fail-soft (`_wrap` returns a reply string, never raises); Accessibility/Automation denials map to a one-line permission hint.
- `skills_dev.py` (1573 LOC): 10 `dv_*` offline developer skills — `dv_git_msg`, `dv_git_summary`, `dv_code_explain`, `dv_test_scaffold`, `dv_docstring`, `dv_todo_scan`, `dv_deps_check`, `dv_json_tool`, `dv_regex`, `dv_loc`. Pure AST/regex/file-I/O, zero LLM calls; write-side actions use `.bak` first and `$HOME` rails.
- Integration (all fail-soft): `main.py:ask_ai` now builds the Groq payload through `prompt_harness.build_messages` and normalizes the reply through `clean_reply`, falling back to the legacy assembly on any failure; `brain.py` auto-discovers both new packs via the existing `skills_*.py` loader (brain.py:302-322) with `supersedes=` where they intentionally replace legacy detectors.

## Before / After Metrics

| Metric | Before | After |
|---|---|---|
| Registered skills at boot | 2,084 (measured `Brain(None)`) | 2,107 — +15 `cp_*`, +10 `dv_*`, +`pro_write_code`/`pro_gen_tests` lane corrections |
| Consolidated pytest | 1,113 passed across 30 suites | 1,113 passed (6.22s), unchanged and green with new packs loaded |
| `prompt_harness.selftest()` | module absent | 8/8 PASS (build_messages, intent, clean_reply, code/web prompt builders) |
| Computer control | brain_extra-only loose "screenshot" skill | 15 anchored `cp_*` skills incl. open-app (120s cache), click/type/press, screenshots, gated shell, volume/brightness, trash |
| Developer tools | LLM-hybrid `pro_explain`/`pro_gen_tests` only | 10 offline `dv_*` AST/file tools (git msg/summary, explain, scaffold, docstrings, todo scan, deps, JSON, regex, LOC) |
| Prompt engineering | hardcoded in main / scattered per-skill | centralized `prompt_harness` persona + context + contracts, fail-open |
| Reply hygiene | raw model output surfaced | fences/chatter stripped, code bodies kept clean; fail-open to raw |

## Bug Fixes During Build (this session, applied & live-verified)

- 13 confirmed bugs in the live voice/GUI flow fixed during the session's earlier passes and live-verified: mic-spam debouncing, the code-save path, the Google AI Studio workflow, a chat deadlock, animation edge cases, plus round-2/round-3 driver findings (verified by background test drivers; exit code 0 each).
- Collision work in `skills_dev.py`: documented and routed around `brain_extra.git_help` (keeps "git commit message in <dir>"; `dv_git_msg` owns the git-less "commit message for <dir>") and `brain_extra.line_count` / `data_file_tools` JSON lanes, so the new packs never shadow legacy skill ground.

## New Features

- Full-computer-control lane: "open figma", "open example.com", "click at 500 400", "type hello world", "press cmd+s", "take a screenshot", "trash /path", "what window is focused" — with hard refusals/safety rails on destructive shell (rm -rf on root/home/system, diskutil erase, mkfs, killall system procs, kill -9), override-gated by `JARVIS_ALLOW_DESTRUCTIVE=1`.
- Offline dev toolkit: commit-message drafting from porcelain+diff, test scaffolder, docstring proposer, TODO scanner, dependency checker, JSON validate/format with `.bak`, anchored regex match/explain, per-extension LOC.
- Harness message assembly: system persona + context block (frontmost app / recent commands / ai mode / time) + 8-turn / 3000-char history trim + intent contract appended per request; `clean_reply` normalizes both prose and code outputs.
- Structured Google AI Studio prompts (single-file HTML or Kotlin app) via `wrap_website_prompt` for the existing `app_dev_brain` flow.

## Known Risks

- `cp_run` executes shell through `shell=True`; destructive commands are refused by pattern, but the deny-list is not exhaustive — the `JARVIS_ALLOW_DESTRUCTIVE=1` override exists for deliberate power use.
- Brightness absolute control is AppleScript-less on modern macOS; `cp_brightness` falls back to up/down key codes when absolute control is locked.
- First-match skill ordering still governs overlapping lanes; the new packs use `supersedes=` where intentional and `priority=False` elsewhere, so future same-prefix packs could re-shadow them.

## Next Steps

See PROMPTS_BACKLOG.md.

# HARVEST: Website & App Workflow Audit + Fixes (session 2026-09-12, part 2)

## Overview

End-to-end audit of the website/app generation workflow ("make a website / build an app"), the flow that routes through Google AI Studio with a Groq-crafted prompt in two modes (online handoff vs offline local template). The audit tested routing, the online handoff, and the offline scaffolds; three defects were found and fixed. All verification offline (no live LLM — Groq quota was exhausted).

## What Changed

- `jarvis/app_dev_brain.py` — online mode no longer discards the Groq reply. Previously it fired a full app-generation call as a reachability probe, threw away the reply, copied a static brief, and opened the bare AI Studio homepage. Now it asks Groq to *draft the AI Studio prompt* (`_AISTUDIO_META`), prefers that drafted prompt (static `_groq_prompt` brief kept as thin-reply fallback), and opens the **pre-filled** build link `https://aistudio.google.com/apps?prompt=<quote(...)>` via new `_aistudio_build_url()` (mirrors `main.aistudio_build_url`, no main import). Local template path is the fallback when Groq is unavailable (preserves the two-mode design).
- `jarvis/web_dev_brain.py` — `_try_handoff` already used the LLM-crafted prompt but opened the bare homepage. Added `_aistudio_build_url()` / upgraded `_open_ai_studio(prompt)` so the drafted prompt is dropped into the pre-filled build screen (URL-encoded), not just the clipboard. Reply message updated accordingly.
- `jarvis/brain_extra.py` — `build_webpage` (priority=True) hijacked "build a landing page / portfolio / blog / dashboard / pwa / ..." phrases before the richer `wd_*` scaffolder could run, emitting its plain generic template instead. Detector now excludes all `_RICH_WEB_PHRASES` (the exact wd_* trigger set) so the rich skills win; `build_webpage` remains only for generic "website/webpage" requests.

## Verification (offline)

- `tests/test_web_dev_brain.py` + `tests/test_app_dev_brain.py`: 60 passed (was 58 — added `test_aistudio_build_url_encodes_prompt`, `test_handoff_deep_link_prefills_the_drafted_prompt`; updated handoff assertions to the pre-filled deep link).
- Full suite: `pytest tests/ -q --ignore=tests/legacy` → **1115 passed** (was 1113).
- Routing probes (bad ones fixed): `create a landing page` → wd_landing_page (was build_webpage), `portfolio site` → wd_portfolio, `build a website about X` → build_webpage (intentional, generic lane), `flask api` → ad_flask_api, `pwa scaffold` → wd_pwa_scaffold.
- Online handoff (monkeypatched `_llm`/clipboard/browser): prompt appears URL-encoded in `apps?prompt=...` for both brains; the LLM-drafted prompt is what gets handed off (138-char draft verified in the deep link).
- Offline end-to-end: landing page + PWA written; Flask + CLI scaffolds written; generated CLI tool's own pytest runs 3 passed.

## Known Risks

- Even with the fix, the online path still requires one live Groq call to draft the prompt — that is by design (the user's workflow) and it now *uses* the reply instead of discarding a full generation.
- `build_webpage`'s exclusion list must stay in sync with new `wd_*` trigger phrases added to `web_dev_brain._KINDS` in the future.
- The pre-filled AI Studio link relies on the `?prompt=` parameter staying supported by aistudio.google.com; `main.aistudio_build_url` semantics are unchanged.

# HARVEST: Full-Code Bug Hunt + Hardening (session 2026-09-12, part 3)

## Overview

Full-code audit pass across the whole repo (~97k LOC, 30 test suites). Ran the suite, `pyflakes` static pass, runtime registration scan of all 2,107 registered skills, and three scoped sub-agent audits (threading/lifecycle, file-write safety, LLM/pipeline modules) with live edge-case execution (offline — no live LLM calls). Confirmed bugs were fixed; future-risk findings documented.

## Fixed

- **`jarvis/brain_extra.py` — 124 duplicate skill registrations removed.** The entire "what is X" knowledge `reg(...)` block was pasted twice (two byte-identical 121-line copies). Both copies registered the same skill names, doubling `think()` scan cost and bloating the skill list 2,107 → **1,986** (removed the *later* copy so runtime behavior is bit-for-bit unchanged). Also removed the earlier-of-two `aluminium`/`arsenic` element entries, `photosynthesis`/`machine learning`/`blockchain` concept entries, and `indian independence`/`fall of berlin wall` history entries (the earlier duplicate dict key was silently discarded by Python — later value wins — so deleting it is behavior-preserving). Removed the dead first `_score_pct_detect`.
- **`jarvis/brain_extra.py` — Morse decode bug.** The decode map mapped `.--` to BOTH `J` and `W` (later wins → W, correct) but `.---` (J) was completely missing. Now `.--`→W and `.---`→J; verified `decode morse .--- .-- ...` → `JWS`.
- **`jarvis/todo_list.py` — non-atomic state write.** `_save` wrote the todo list via plain `open('w')`; a crash mid-write truncated the file and the next mutation rewrote the recoverable file as `[]` (whole list lost). Now writes `jarvis_todo.json.tmp` then `os.replace` (same pattern as `memory_core`/`journal_brain`).
- **`jarvis/llm_client.py` — three robustness fixes.** (1) HTTP 429 (rate limit) is now retried like 5xx instead of failing the turn immediately (the most common transient LLM failure previously got zero retries); (2) `_extract_text` no longer indexes `choices[0]` when upstream returns `"choices": {}` (would have raised `KeyError` and burned the retry); (3) `chat()` now returns `None` (not `""`) on empty/unparseable bodies, honoring its documented `str | None` contract — fixes `is None` fallbacks like `agent_loop._provider_reply` and prevents `"".splitlines()[0]` IndexError.
- **`jarvis/deepthink.py` — transform solver shipped confidently-wrong answers.** `double the price, then add 5` returned `10`, silently dropping the trailing `+5` (under-specified expression). Unconsumed pending operators now make the solver decline (`None`) instead of fabricating a result; verified `6, then double it, and add 3` still returns 15.
- **`main.py` — `_handle_smart_fix` discarded its vision analysis.** It computed `analysis = self._ask_vision(...)` then `return`ed without speaking or acting (silent no-op; latent, uncalled). Now uses the context-aware analysis for an actual reply; delegates to `_handle_fix_screen` when no context.
- **`main.py` — voice engine could die silently.** `_sleep_loop`/`_awake_loop` outer bodies are now exception-guarded (a transient audio/tool error logs and continues instead of killing the always-on wake/listen engine); the unguarded `process(rest)` in `_sleep_loop` is covered too.
- **`main.py` — cosmetic.** Removed a placeholder-less `f"..."` string in the weather fallback.

## Verified

- Full suite `pytest tests/ -q --ignore=tests/legacy` → **1,117 passed** (was 1,115; +2 new LLM tests for 429-retry and dict-choices, updated empty-body contract test).
- Registration scan: 2,107 → 1,986 skills; remaining same-name collisions (`fibonacci`, `regex_test`, `json_validate`) confirmed *intentional* complementary detectors serving different phrasings — not deduplicated.
- `pyflakes` on `brain_extra.py` now reports zero duplicate-dictionary-key violations; morse round-trip, `what is X` concept answers, `7 out of 5 is what percent` → 140%, all verified.

## Known Risks (documented from audit — not landed)

- **`code_brain_pro.py` HIGH:** `_e_fix`/`_e_improve`/`_e_fix_and_run` read *any* file the chat names (absolute paths and `~` allowed) and overwrite it with model output; `_local_auto_fixes` regex edits can rewrite text inside comments/string literals (confirmed: `# a == None` → `# a is None`). `_run_python_file` executes any user-named path via `[sys.executable, path]`. Recommend a path rail + comment/string-aware edit guard before enabling these flows.
- **Concurrency (main.py):** `history`/`last_reply` mutated by up to 4 concurrent `_process` entry points (voice, wake-word, command-palette, PTT) with no lock → interleaved turns under simultaneous commands; lazy `_get_brain()` has a benign create-once race; shared `speech_done` Event and a `_watch_for_interrupt` thread per utterance grab the mic mid-reply. Low likelihood day-to-day (single user), but worth a lock pass if multi-entry is exercised.
- **File-write safety:** `file_power._e_write`/`_e_replace`/`_e_insert`/`_e_delete_lines` rewrite in place (only `.bak` survives a mid-write crash); `data_file_tools` has no protected-path rail (in-place image resize can write any absolute path); `memory_core`/`journal_brain` treat a *transient* read error as "empty" and can clobber stored data on the next save. All documented; not changed to avoid behavior drift.
- **`llm_client`:** 400-series failures (other than 429) are still fatal, and `_post` has no exponential backoff — fine now, amplification risk if concurrent workers hammer a flaky provider.

## Part 4 — Gemini provider, quota-fallback, and planning layer (offline-verified)

## What Changed

- **`jarvis/llm_client.py` — new `google` provider.** Backed by Geminis OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`, `GEMINI_API_KEY`, default model `gemini-2.5-flash`, `JARVIS_GEMINI_MODEL` override). Reuses the entire existing `openai` request/parse path — no key or body special-casing.
- **`jarvis/llm_client.py` — `chat_anywhere(prompt, history, system, chain)`.** Try providers in order; first non-empty reply wins; backends without a configured key are skipped; never raises. Default chain `("groq", "google")` makes Gemini the escape hatch for the daily Groq quota / outages.
- **`jarvis/llm_client.py` — `planner_reply(text)`.** Gemini-backed planning layer that fires ONLY when `GEMINI_API_KEY` is set AND the text matches a hard-problem gate (`compare|plan|pros and cons|trade-off|analy|evaluate|choose between|architecture|roadmap|…`). Returns a short structured spoken plan or `None`. Everything else falls through untouched so the fast path is never slowed.
- **`jarvis/brain.py` — `chat()` now runs `deepthink` → Gemini planner → local brain.** Hard multi-step questions go to Gemini before the generic local/code path.
- **`main.py` — Groq failure fallback in `_ask_ai_safely` (both JarvisApp and JarvisBot).** When Groq returns `None` / `__UNAUTHORIZED__` / `__RATE_LIMITED__`, a configured Gemini answers instead of dropping to the offline brain. Also wired into the `JARVIS_PROVIDER` branch of `ask_ai`.
- Explicitly NOT building a standalone "Gemini planner" subsystem — Gemini is a provider + a planning gate, not a parallel architecture (matches the approved plan).

## Verified

- Full suite `pytest tests/ -q --ignore=tests/legacy` → **1,129 passed** (was 1,117; +12: google provider matrix coverage, `chat_anywhere` fallback/primary/missing-key/blank-prompt, `planner_reply` require-key/quick-question/hard-problem/network-failure).
- Both `main.py` and `jarvis/brain.py` parse clean; Gemini paths degrade to `None` (no calls) when `GEMINI_API_KEY` is unset.
- GitHub research (hey-jarvis, Jarvis-AI-assistant, AFIN7/jarvis, Jupiter voice): wake word, interrupt detection, date-in-system-prompt, retry, and smart routing all already exist in Jarvis — the Gemini planner/fallback adds the one missing piece (two-tier cost/quality routing: fast Groq for routine chat, Gemini for planning and for Groq outage/quota survival). No further cherry-picks needed.

## Next

- Set `GEMINI_API_KEY` to activate fallback + planner; live smoke test: a hard problem (e.g. `best approach to plan a software migration`) should return a Gemini plan, and every other command stays on the Groq/local fast path.

## Part 5 — Gemini key persistence + harness hardening (live-verified)

## What Changed

- **Gemini key persistence (`jarvis/llm_client.py`).** The real `GEMINI_API_KEY` is stored at project root `.jarvis_gemini_key` (mode 0600, mirroring the Groq `.jarvis_api_key` convention) via `configure_gemini_key()` — never hardcoded in source. `provider_api_key()` resolves env-first then file so the GUI app keeps working across relaunches; `gemini_configured()` gates the planner/fallback. Tests monkeypatch the file path so a real on-disk key never leaks into the suite.
- **Model upgraded to `gemini-3.6-flash`** (configurable via `JARVIS_GEMINI_MODEL`). Live diagnosis: Google's catalog no longer serves `gemini-2.5-flash` to new keys — both the native and OpenAI-compat endpoints 404'd; the model list confirmed `gemini-3.6-flash` works on the existing OpenAI-compat path with zero code changes.
- **`jarvis/prompt_harness.py` — three upgrades.** (1) `build_messages()` now bakes in today's date (unifying the harness persona with `main._system_prompt`) and accepts `persona_extra`; (2) `intent="code"` (auto-classified) now pulls in the full `wrap_code_prompt` harness contract (only-code / first-line-is-code / never-truncate) instead of the terse code contract; (3) `clean_reply` is now applied to the Gemini planner/fallback replies, so Gemini chatter is stripped exactly like Groq's.
- **`main.py` — wiring.** `ask_ai` passes `classify_intent(prompt)` into `build_messages` (code requests get the code harness automatically); `_harness_clean()` normalizes Gemini fallback replies in `_ask_ai_safely` (both JarvisApp and JarvisBot) and the `JARVIS_PROVIDER` fallback branch.

## Verified

- Full suite `pytest tests/ -q --ignore=tests/legacy` → **1,147 passed** (was 1,129; +18: harness suite + key-resolution/planner-normalization tests). New `tests/test_prompt_harness.py` mirrors/supersedes the module's offline `selftest`.
- Live with the real key: `planner_reply('What is the best approach to plan a home renovation budget?')` returns a structured 4-step Gemini plan; quick commands (`turn on the lights`) return `None` with zero network calls; `.jarvis_gemini_key` is mode 0600 and the key never appears in source.
- Harness contract confirmed live: Gemini's reply is post-processed by `clean_reply` (fences/chatter stripped) before it reaches the spoken UI.

## Security note

- The key lives only in `.jarvis_gemini_key` (0600) next to the existing `.jarvis_api_key`; the project is not a git repo, so nothing is tracked. Logging and tests only ever see `mask_key()` output.
