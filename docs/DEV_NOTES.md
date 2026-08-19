# Dev Notes

One-page map of every module: role + how/where it registers. Measured 2026-08-24.
Skill count at boot: 2,084. Consolidated pytest: 1,113 passed / 30 suites.

## Skill module registration

- Skill packs live in two places:
  1. Modules explicitly listed in `Brain._load_pro_modules` (brain.py) — fail-soft import + `register(brain)`.
  2. Any `skills_<domain>.py` in the project root exposing `register(brain)` is auto-discovered by `_load_skill_packs()`.
- To add a new skill pack: create `skills_<domain>.py` (auto-loaded) or append the module name to the `_load_pro_modules` tuple.
- `deepthink.py` and `code_validator.py` are standalone modules, imported lazily (brain.py / tests), not registered via `register()`.

## Module map

### Registered via Brain._load_pro_modules, in order (brain.py:286-300)

| # | Module | LOC | Role |
|---|---|---|---|
| 1 | code_brain_pro | 3,107 | Validated coding skills: write/fix/improve/review/explain/translate/generate-tests, built on code_validator retry loop |
| 2 | file_power | 1,082 | Safe file write-back with .bak rotation; read/write/edit/move/copy/search/tree/diff skills |
| 3 | power_skills | 1,301 | Git status/commit, docker ps, process/system devops tools, intelligence tools |
| 4 | web_dev_brain | 643 | Website generation skills (output under generated_websites/) |
| 5 | app_dev_brain | 732 | App-scaffolding skills (output under generated_agent/) |
| 6 | calendar_music_skills | 495 | Calendar events/reminders + Spotify/music voice control |
| 7 | mail_skills | 495 | Mail reading/composing voice skills |
| 8 | live_screen_brain | 479 | Screen Q&A / read-aloud on all monitors (uses multi_monitor capture) |
| 9 | journal_brain | 421 | Knowledge journal notes + spaced-repetition review sessions |
| 10 | data_file_tools | 633 | Data-file skills: CSV/JSON/SQLite querying ("sqlite query ...") |
| 11 | agent_loop | 833 | Background agent jobs: plan -> execute -> checkpoint -> report, crash recovery, per-step provider routing (STEP_PROVIDERS); proactive toast from JarvisBot |
| 12 | memory_core | 311 | Persistent facts/preferences/turn-log in atomic JSON (jarvis_memory_core.json); survives restarts |
| 13 | security_hardening | 307 | Keychain vault for API keys, secret redaction (LUHN cards/API keys), exec policy engine |
| 14 | briefing_brain | 338 | Daily briefing generation ("brief me") |
| 15 | focus_pomodoro_brain | 480 | Focus sessions and pomodoro timers |
| 16 | net_diagnostics_brain | 561 | Network diagnostics skills (ping/DNS/speed checks) |
| 17 | ptt_onboarding | 338 | PTT permission onboarding flow; "open accessibility settings" handler |

Ordering matters: modules after agent_loop should register skills with
`priority=True`, or ensure their detectors can't be shadowed by the agent's
first-match detectors (see section below).

### Auto-discovered skill packs (_load_skill_packs, sorted glob of skills_*.py)

| Module | LOC | Role |
|---|---|---|
| skills_games | 721 | Game skills (state in .jarvis_games.json) |
| skills_habits | 861 | Habit tracking skills |
| skills_home | 1,012 | Home inventory & maintenance skills (11) |
| skills_travel | 951 | Trip-planning skills (10) |

### Separate registration path

- brain_extra.py (8,843 LOC): bulk legacy skill pack, registered via `Brain.load_extra()`, not part of _load_pro_modules.

### Standalone libraries, imported lazily, never registered

- code_validator.py (940): safety gate — fence-strip, ast.parse, compile, sandboxed exec with timeout, node --check for JS; feeds errors back to generator.
- deepthink.py (791): offline reasoning cascade — step decomposition, backward verification, transform prefixes.
- llm_client.py (228): provider-agnostic client; Groq/OpenAI-compatible/Anthropic/Ollama selected by JARVIS_PROVIDER (default Groq).

### Libraries wired into main.py / JarvisBot (no skill registration)

- hotkey_ptt.py (293): global hold-to-talk PTT engine (pynput + Accessibility grant).
- multi_monitor.py (332): per-display enumerate/capture/stitch + coordinate mapping.
- streaming_tts.py (171): sentence-streaming TTS with instant barge-in interrupt.
- bot_clicky.py (61): orb add-on integration point (`attach(bot)`), loads bot_quick_bar, bot_reply_bubble, bot_status_panel fail-soft; auto-discovers extra bot_*.py add-ons.
- jarvis_logging.py (291): logging setup.

### Core

- main.py (5,990): JarvisApp HUD chat UI + JarvisBot orb (follow-cursor, auto-park, pulsing point-at halo, toasts), launch point.
- brain.py (1,416): rule-based core: intent detection, classic skills, think() cache, SUPERSEDED_SKILLS prune, LLM fallback hooks, registration orchestration.
- tests/ (30 pytest suites, 1,113 tests), tests/legacy/ (9 standalone E2E scripts run by run_tests.py).
- screenshots/: captures used by live-screen features.

## Historical build scripts

- `tools/generators/` contains the one-shot scripts (`gen_*.py`) that originally generated `brain_extra.py`. They are NOT imported at runtime; kept for archaeology only.

## Priority skills vs background-agent matching

- Skills registered AFTER `agent_loop` in `_load_pro_modules` must use `priority=True`, otherwise first-match agent detectors can shadow them. (Historical note: a `_d_cancel` bug in `agent_loop.py` used to make every command match "cancel"; it now returns `None` on no-match, so non-priority registration is safe again — revisit `nd_*` etc.)

## Backups

- `.master_backup/` holds pre-edit snapshots of critical files (e.g. `main.py.bak_*`). Not runtime data; safe to prune periodically.

## Runtime files (gitignored)

- `.jarvis_api_key`, `.jarvis_bot_state.json`, `.jarvis_games.json`,
  `jarvis_agent_jobs.json`, `jarvis_clipboard.json`,
  `jarvis_memory.json`, `jarvis_memory_core.json`, `jarvis_notes.txt`
- Logs: `jarvis.log*`, `jarvis_transcript.log`
