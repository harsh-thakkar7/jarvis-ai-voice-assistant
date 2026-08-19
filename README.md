# JARVIS — Voice AI Assistant (macOS)

JARVIS is a voice- and text-driven desktop assistant for macOS with an Iron-Man persona ("sir" included). It ships two user interfaces built on Tkinter: **Chat Mode**, a fullscreen HUD-style console for typed conversations, and **Bot Mode**, a floating animated orb that reacts to sleep, standby, listen, think, and speak states. Requests are handled first by a local rule-based skill engine (2,000+ registered offline skills at boot, covering coding, files, system control, math, and knowledge lookups), and anything open-ended falls back to the Groq cloud API using the `openai/gpt-oss-20b` model, so the assistant degrades gracefully when offline.

## Quick Start

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Provide your Groq API key either way:

- Export the `GROQ_API_KEY` environment variable before launching, or
- Say **"set api key ..."** inside the app; the key is stored in `.jarvis_api_key` with `chmod 600` permissions (if the restricted write fails, a plaintext-file fallback is used and a warning is logged).

Launch:

```bash
.venv/bin/python main.py
```

## Commands

| Group | Example commands |
| --- | --- |
| Coding | "write code for X", "fix this code in file.py", "improve the code in main.py", "review this code", "save it as app.py", "write tests for this code", "convert this python to javascript" |
| Files | "read file X", "replace 'a' with 'b' in X", "show folder tree of X", "diff A and B", "search for 'pattern'" |
| System & DevOps | "system report", "git status", "git log", "git commit with message 'x'", "docker ps", "docker images", "clipboard history", "copy X to clipboard", "sqlite query data.db select ..." |
| Intelligence | "wikipedia X", "define X", "synonyms of X", "news headlines", "solve x^2 - 5x + 6 = 0", "derivative of 3x^3 + 2x", "plan my week", "python vs javascript", "how does dns resolution work" |
| Classic | timers, "weather in X", "battery", "volume up" / "volume down" / "mute", "open youtube", "play \<song\>" |

## Architecture

```text
main.py (JarvisApp HUD / JarvisBot orb)
        |
        v
   Brain.think  -- priority pass -->
        |
        +--> [ code_brain_pro | file_power | power_skills | brain_extra ]
        |
        v
   deepthink / local_chat  -- offline cascade -->
        |
        v
     ask_ai  -->  Groq API (openai/gpt-oss-20b) fallback
```

Generated code never runs unvetted: `code_validator` gates it through fence-strip, `ast.parse`, `compile`, restricted execution with a timeout, and (for JavaScript) `node --check`, retrying with error feedback on failure. File write-backs performed by skills keep `.bak` backups of the previous contents.

## Testing

One command runs everything:

```bash
.venv/bin/python run_tests.py
```

This first executes the consolidated pytest suite (`tests/test_*.py`, currently 1,113 tests across 30 suites), then every legacy standalone regression script in `tests/legacy/`. Use `--fast` to run only the pytest portion:

```bash
.venv/bin/python run_tests.py --fast
```

The legacy suites (9 scripts such as `tests/legacy/test_all.py`) are end-to-end checks kept for regression coverage; they run as plain scripts and the runner exits non-zero if any suite fails.

## Clicky parity

Feature parity with the Clicky desktop-AI orb, implemented natively:

- Orb buddy with follow-cursor mode (tweened motion) plus auto-park when idle; touching the orb wakes a parked follower.
- Global push-to-talk: hold a hotkey combo anywhere in macOS (Accessibility permission grant via "open accessibility settings").
- Screen question-and-answer with read-aloud on ALL connected monitors (per-display capture, stitched analysis, coordinate mapping).
- Pulsing point-at halo animation when the orb indicates something on screen.
- Background agent jobs: multi-step plans executed in the background with proactive toast notifications on completion.
- Knowledge journal with spaced-repetition review sessions.
- Calendar, Mail, and Spotify voice control.
- Any-LLM backend selection via `JARVIS_PROVIDER` (Groq / OpenAI-compatible / Anthropic / Ollama).
- Streaming text-to-speech with instant barge-in interruption.

## Project Layout

```text
main.py               JarvisApp (HUD chat UI), JarvisBot (orb + follow-cursor + toasts), launch point
brain.py              Rule-based Brain core: intent detection, classic skills, LLM fallback hooks,
                      _load_pro_modules() registration order, skill-pack auto-discovery
llm_client.py         Provider-agnostic LLM client: Groq / OpenAI-compatible / Anthropic / Ollama
code_brain_pro.py     Coding skills: validated write, fix, improve, review, explain, translate
code_validator.py     Safety gate for generated code (parse, compile, sandboxed exec, node check)
file_power.py         File skills: safe write-back with .bak rotation, read/write, search, tree, diff
power_skills.py       System/devops/knowledge skills: git, docker, clipboard, sqlite, wiki, math
deepthink.py          Offline reasoning cascade: equations, planning, comparisons, explanations
agent_loop.py         Background agent jobs: plan -> execute -> checkpoint -> report, crash recovery
memory_core.py        Persistent memory: facts/preferences/turn-log in atomic JSON
security_hardening.py Keychain vault, secret redaction, exec policy engine
streaming_tts.py      Sentence-streaming TTS with instant barge-in interrupt
hotkey_ptt.py         Global hold-to-talk push-to-talk engine (pynput + Accessibility)
multi_monitor.py      Per-display enumerate/capture/stitch and coordinate mapping
live_screen_brain.py  Screen Q&A / read-aloud skills on all monitors
journal_brain.py      Knowledge journal + spaced-repetition review sessions
data_file_tools.py    Data-file skills (CSV/JSON/SQLite querying)
calendar_music_skills.py  Calendar and Spotify/music voice control
mail_skills.py        Mail reading/composing voice skills
briefing_brain.py     Daily briefing generation
focus_pomodoro_brain.py   Focus sessions and pomodoro timers
net_diagnostics_brain.py  Network diagnostics skills
ptt_onboarding.py     PTT permission onboarding ("open accessibility settings" flow)
web_dev_brain.py      Website generation skills
app_dev_brain.py      App-scaffolding skills
skills_*.py           Auto-discovered skill packs (games, habits, home, travel)
brain_extra.py        Bulk-registered legacy skill pack layered onto the Brain
jarvis_logging.py     Logging setup
bot_clicky.py         Orb add-on integration point; loads bot_quick_bar/bot_reply_bubble/bot_status_panel
tests/                Consolidated pytest suite (30 suites)
tests/legacy/         Legacy standalone end-to-end regression scripts (9)
tools/generators/     One-off authoring scripts used to generate bulk skill tables (not imported at runtime)
screenshots/          Captured screen images used by live-screen features
docs/                 Developer notes and module deep-dives
generated_websites/, generated_agent/   Output dirs for web/app generators
```

## Limitations

- macOS-first: app control, clipboard, volume, and several system skills rely on macOS integrations (`osascript`) and are inert elsewhere.
- Currency conversions use static rates bundled in the source; they are approximations, not live quotes.
- JavaScript validation via `node --check` requires Node.js to be installed; without it, JS output skips that check.
