# -*- coding: utf-8 -*-
"""PUSH-TO-TALK ONBOARDING: deps/permission checks + guided macOS consent.

Smooth Clicky-style onboarding for the global hold-a-hotkey push-to-talk
engine (:mod:`hotkey_ptt`). This module answers three questions and acts
on them:

1. Is ``pynput`` importable?                      -> :func:`preflight`
2. Does macOS grant Accessibility trust?          -> :func:`preflight`
3. Can we deep-link the user to the exact pane?   ->
   :func:`open_accessibility_settings`

Consent (whether PTT should engage at all) persists as one JSON document
at ``PROJECT_DIR/jarvis_ptt_prefs.json``::

    {"ptt_enabled": true}

Loads/saves are atomic (tmp file + ``os.replace``); a missing or corrupt
file yields the default (enabled). Tests monkeypatch ``PREFS_FILE``.

Registers three skills into the main Brain via :func:`register`:
    pt_status, pt_enable_settings, pt_toggle

Honesty policy: flipping the preference only shapes the *next* launch.
The process-wide engine returned by ``hotkey_ptt.acquire`` pins its
callbacks at creation and exposes no live-swap, so the spoken replies say
"a restart is needed" rather than pretending otherwise. Every executor
reply ends with ", sir." and is exception-wrapped. Never imports main.
"""

from __future__ import annotations

import json
import os
import re
import subprocess

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)

import hotkey_ptt

log = get_logger("ptt_onboarding")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
PREFS_FILE = os.path.join(PROJECT_DIR, "jarvis_ptt_prefs.json")

#: Exact deep link into System Settings > Privacy & Security > Accessibility.
ACCESSIBILITY_URL = (
    "x-apple.systempreferences:com.apple.preference.security?"
    "Privacy_Accessibility"
)

DEFAULT_ENABLED = True


# ==========================================================================
# Seams (tests monkeypatch these)
# ==========================================================================

def _open_url(argv: list[str]) -> int:
    """Run *argv*, return exit code (nonzero on any failure). Test seam."""
    try:
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=5, check=False
        )
        return proc.returncode
    except Exception:
        return 1


# ==========================================================================
# Preflight: dependency + permission readiness
# ==========================================================================

def preflight() -> dict:
    """Probe PTT readiness without ever raising.

    Returns ``{"pynput": bool, "trusted": bool | None, "ready": bool}``
    where ``trusted`` is ``None`` whenever pynput itself is unavailable
    (there is nothing to grant permission *for* yet).
    """
    have_pynput = bool(getattr(hotkey_ptt, "HAVE_PYNPUT", False))
    trusted: bool | None = None
    if have_pynput:
        try:
            trusted = bool(hotkey_ptt.GlobalPTT.is_trusted())
        except Exception:
            log.warning("trust probe raised; treating as untrusted")
            trusted = False
    return {
        "pynput": have_pynput,
        "trusted": trusted,
        "ready": have_pynput and trusted is True,
    }


def open_accessibility_settings() -> bool:
    """Deep-link straight to the Accessibility permission pane."""
    return _open_url(["open", ACCESSIBILITY_URL]) == 0


# ==========================================================================
# Preference storage (atomic)
# ==========================================================================

def _load_prefs() -> dict:
    """Load prefs; missing/corrupt files yield the empty document."""
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_prefs(prefs: dict) -> None:
    """Atomically persist prefs (tmp file, then ``os.replace``)."""
    tmp = PREFS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(prefs, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, PREFS_FILE)


def set_enabled(flag: bool) -> bool:
    """Persist ``{"ptt_enabled": flag}``; True on successful save."""
    prefs = _load_prefs()
    prefs["ptt_enabled"] = bool(flag)
    try:
        _save_prefs(prefs)
    except OSError as exc:
        log.warning("could not persist PTT preference: %s", exc)
        return False
    return True


def is_enabled() -> bool:
    """Current consent; defaults to enabled until explicitly disabled."""
    return bool(_load_prefs().get("ptt_enabled", DEFAULT_ENABLED))


# ==========================================================================
# Shared helpers
# ==========================================================================

def _persona_safe(reply: str) -> str:
    """Guarantee the Jarvis persona: every reply ends with ', sir.'"""
    r = (reply or "").rstrip()
    if re.search(r"\bsir\b[\s.?!]*$", r, re.I):
        return r
    if r.endswith((".", "!", "?")):
        return r[:-1].rstrip() + ", sir" + r[-1:]
    return r + ", sir."


_GRANT_HOWTO = (
    "To grant it: say \"fix push to talk\" and I will open System "
    "Settings > Privacy & Security > Accessibility for you - just toggle "
    "this app on"
)


# ==========================================================================
# Executors
# ==========================================================================

def _execute_status(app, ctx) -> str:  # noqa: ANN001 - duck-typed Brain/app
    st = preflight()
    enabled = is_enabled()
    if st["ready"]:
        mood = "" if enabled else (
            " The engine is healthy, though you have asked me to keep it "
            "disabled - say \"enable push to talk\" whenever you want it back."
        )
        return (
            "Push-to-talk is fully operational: pynput is installed and "
            "macOS Accessibility trust is granted. Hold Ctrl and Alt "
            "anywhere in the OS and speak." + mood
        )
    if not st["pynput"]:
        return (
            "Push-to-talk cannot run yet: the pynput package is missing. "
            "Install it into this environment (pip install pynput), then "
            "ask me for your push to talk status again."
        )
    return (
        "Push-to-talk is blocked by permissions: pynput is installed but "
        "macOS has not granted Accessibility trust, so global keystrokes "
        "stay invisible to me. " + _GRANT_HOWTO
    )


def _execute_settings(app, ctx) -> str:  # noqa: ANN001
    opened = open_accessibility_settings()
    steps = [
        "find this app (JARVIS, or the terminal/IDE running me) in the list",
        "flip its switch to ON - macOS may ask for a logout first",
        "restart me, then say \"push to talk status\" to confirm",
    ]
    body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
    if opened:
        head = (
            "I have opened System Settings at Privacy & Security > "
            "Accessibility. Here is the short path to full trust:"
        )
    else:
        head = (
            "I could not pop the Settings pane open automatically - please "
            "navigate to System Settings > Privacy & Security > "
            "Accessibility yourself. Then:"
        )
    return f"{head}\n{body}"


def _execute_toggle(app, ctx) -> str:  # noqa: ANN001
    want = bool(ctx.get("enable"))
    verb = "enabled" if want else "disabled"
    current = is_enabled()
    changed = set_enabled(want)
    if current == want:
        lead = (
            f"Push-to-talk was already {verb}; the preference stays "
            "as-is and remains safely saved"
        )
    elif not changed:
        lead = (
            f"I tried to record that push-to-talk should be {verb}, but "
            "writing the preference file failed, so nothing has changed"
        )
    else:
        lead = f"Done - push-to-talk is now {verb} and the setting is saved"
    return (
        f"{lead}. Honest caveat: this applies on my next launch - the "
        "engine acquired by hotkey_ptt.acquire pins its wiring at startup "
        "and cannot be swapped live, so a restart makes it stick."
    )


# ==========================================================================
# Detectors (tight; noise passes through untouched)
# ==========================================================================

_RE_STATUS = re.compile(
    r"\b(?:push[\s-]?to[\s-]?talk|global\s+hotkey)\s+status\b"
)
_RE_ENABLE = re.compile(
    r"\b(?:(?:re-)?enable|turn\s+on)\s+(?:the\s+)?push[\s-]?to[\s-]?talk\b"
)
_RE_DISABLE = re.compile(
    r"\b(?:disable|turn\s+off)\s+(?:the\s+)?push[\s-]?to[\s-]?talk\b"
)
_RE_SETTINGS = re.compile(
    r"\b(?:open\s+accessibility\s+settings|accessibility\s+(?:permission|pane)"
    r"|fix\s+(?:my\s+)?push[\s-]?to[\s-]?talk)\b"
)

_CLAIMS_ELSEWHERE = (_RE_STATUS, _RE_ENABLE, _RE_DISABLE, _RE_SETTINGS)


def _detect_status(cmd: str):
    m = _RE_STATUS.search(cmd or "")
    if not m:
        return None
    if any(rx.search(cmd) for rx in _CLAIMS_ELSEWHERE if rx is not _RE_STATUS):
        return None
    return {"kind": "status"}


def _detect_settings(cmd: str):
    m = _RE_SETTINGS.search(cmd or "")
    if not m:
        return None
    if any(rx.search(cmd) for rx in _CLAIMS_ELSEWHERE if rx is not _RE_SETTINGS):
        return None
    return {"kind": "settings"}


def _detect_toggle(cmd: str):
    text = cmd or ""
    if _RE_DISABLE.search(text):
        if _RE_STATUS.search(text) or _RE_SETTINGS.search(text):
            return None
        return {"kind": "toggle", "enable": False}
    if _RE_ENABLE.search(text):
        if _RE_STATUS.search(text) or _RE_SETTINGS.search(text):
            return None
        return {"kind": "toggle", "enable": True}
    return None


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("pt_status", _detect_status, _execute_status, False),
    ("pt_enable_settings", _detect_settings, _execute_settings, False),
    ("pt_toggle", _detect_toggle, _execute_toggle, False),
)


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):  # noqa: ANN001
        try:
            return _persona_safe(str(execute(app, ctx)))
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (
                f"Something misfired in my push-to-talk onboarding module "
                f"({str(exc)[:120]}), sir."
            )
    safe.__name__ = f"safe_{name}"
    return safe


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register the three PTT onboarding skills with the given Brain."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("PTT onboarding skills registered (%d)", len(_SKILLS))


register_extra = register


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
    print(preflight())
    print("prefs:", PREFS_FILE, "enabled:", is_enabled())
