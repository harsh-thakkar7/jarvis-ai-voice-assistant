#!/usr/bin/env python3
"""ONE-TIME merger v3: folds every jarvis module into a single main.py.

Collision rule: top-level names defined by MULTIPLE chunks get renamed
(with the owning chunk's slug) inside every chunk that defines them.
Single-definition names stay global. Base main.py gets import/demo
cleanup but no renames.
"""

import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SOURCES_DIR = ROOT / ".master_backup" / "premerge"

ORDER = [
    "jarvis_logging", "brain", "brain_extra", "deepthink",
    "code_validator", "code_brain_pro", "file_power", "power_skills",
    "web_dev_brain", "app_dev_brain", "calendar_music_skills",
    "mail_skills", "live_screen_brain", "journal_brain",
    "data_file_tools", "agent_loop", "memory_core",
    "security_hardening", "streaming_tts", "hotkey_ptt",
    "multi_monitor", "llm_client", "ptt_onboarding", "briefing_brain",
    "focus_pomodoro_brain", "net_diagnostics_brain", "skills_habits",
    "skills_home", "skills_travel", "bot_clicky", "bot_quick_bar",
    "bot_reply_bubble", "bot_status_panel",
]

SIBLING_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(?:brain|brain_extra|jarvis_logging|"
    + "|".join(ORDER) +
    r")\b")
FUTURE_RE = re.compile(r"^\s*from __future__ import .*$")
MAIN_GUARD_RE = re.compile(r"^(\s*)if __name__ == ['\"]__main__['\"]\s*:")
TOPLEVEL_DEF = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)")
TOPLEVEL_ASSIGN = re.compile(r"^([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*([^#\n].*)$")

IDENTICAL_CONST = {"PROJECT_DIR"}

sources: dict[str, str] = {}
for slug in ORDER:
    p = SOURCES_DIR / f"{slug}.py"
    if p.exists():
        sources[slug] = p.read_text(encoding="utf-8")


def strip_imports_and_futures(src: str) -> str:
    out: list[str] = []
    skip_backslash, skip_paren = False, 0
    for line in src.splitlines():
        if FUTURE_RE.match(line):
            continue
        if skip_backslash:
            skip_backslash = line.rstrip().endswith("\\")
            continue
        if skip_paren:
            skip_paren += line.count("(") - line.count(")")
            if skip_paren > 0:
                continue
            skip_paren = 0
            continue
        if SIBLING_IMPORT_RE.match(line):
            delta = line.count("(") - line.count(")")
            if delta > 0:
                skip_paren = delta
            elif line.rstrip().endswith("\\"):
                skip_backslash = True
            prev = next((l for l in reversed(out) if l.strip()), "")
            if prev.rstrip().endswith(":"):
                ind = len(line) - len(line.lstrip())
                out.append(" " * ind + "pass  # merged")
            continue
        out.append(line)
    return "\n".join(out)


def strip_demo_blocks(src: str) -> str:
    out: list[str] = []
    skipping, indent = False, ""
    for line in src.splitlines():
        m = MAIN_GUARD_RE.match(line)
        if m:
            skipping, indent = True, m.group(1)
            continue
        if skipping:
            if line.strip() and \
                    (len(line) - len(line.lstrip())) <= len(indent):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def clean(src: str) -> str:
    return strip_demo_blocks(strip_imports_and_futures(src))


# ---- Pass 1: clean + collect top-level definitions per chunk ----
cleaned: dict[str, list[str]] = {}
defs: dict[str, set[str]] = {}
for slug in ORDER:
    if slug not in sources:
        print(f"!! missing {slug}.py — skipped")
        continue
    lines = clean(sources[slug]).splitlines()
    cleaned[slug] = lines
    owned: set[str] = set()
    for line in lines:
        dm = TOPLEVEL_DEF.match(line)
        am = TOPLEVEL_ASSIGN.match(line)
        if dm:
            owned.add(dm.group(1))
        elif am:
            n = am.group(1)
            if not (n.startswith("__") and n.endswith("__")):
                owned.add(n)
    defs[slug] = owned

name_owners: dict[str, set[str]] = defaultdict(set)
for slug, owned in defs.items():
    for n in owned:
        name_owners[n].add(slug)

colliding = {
    n: owners for n, owners in name_owners.items()
    if len(owners) > 1 and n not in IDENTICAL_CONST
}


def render(lines: list[str], rename: set[str]) -> str:
    if rename:
        # (?<!\.) — never rename attribute access (brain.register stays).
        pat = re.compile(
            r"(?<!\.)\b(" + "|".join(map(re.escape, sorted(rename))) +
            r")\b")
        text = pat.sub(lambda m: f"{m.group(0)}__{slug_of(rename)}",
                       "\n".join(lines))
        return text
    return "\n".join(lines)


_slug_ctx = {"slug": ""}


def slug_of(_rename) -> str:
    return _slug_ctx["slug"]


def transform(slug: str) -> str:
    _slug_ctx["slug"] = slug
    mine = {n for n in colliding if slug in colliding[n]}
    return render(cleaned[slug], mine)


merged: list[str] = []
merged.append("# " + "=" * 74)
merged.append("# JARVIS — SINGLE-FILE BUILD (all subsystems embedded)")
merged.append("# Generated by tools/merge_into_main.py.")
merged.append("# " + "=" * 74)

base_src = SOURCES_DIR / "main.py"
_slug_ctx["slug"] = "main"
merged.append(render(clean(base_src.read_text(encoding="utf-8")).splitlines(),
                     set()))

for slug in ORDER:
    if slug not in sources:
        print(f"!! missing {slug}.py — skipped")
        continue
    _slug_ctx["slug"] = slug
    body = render(cleaned[slug], {n for n in colliding
                                  if slug in colliding[n]})
    merged.append(f"\n\n# {'─' * 70}\n# ── EMBEDDED: {slug}.py\n"
                  f"# {'─' * 70}\n" + body)

aliases = ", ".join(f'"{n}"' for n in ORDER)
merged.append(
    "\n\n# " + "=" * 70 +
    "\n# COMPATIBILITY ALIASES — merged modules importable by name.\n# " +
    "=" * 70 +
    f"\nimport sys as _sys\nfor _alias in ({aliases}):\n"
    "    _sys.modules.setdefault(_alias, _sys.modules[__name__])\n")

result = "\n".join(merged)
out_path = ROOT / "main_merged.py"
out_path.write_text(result, encoding="utf-8")
print("wrote", out_path, f"{len(result.splitlines())} lines | "
      f"renamed collisions: {len(colliding)}")
