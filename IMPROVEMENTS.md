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
