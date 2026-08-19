"""JARVIS SECURITY HARDENING: keychain vault, redaction, exec policy.

Three pillars that turn Jarvis's thin security posture into a defensible
one, without breaking the existing plaintext workflow:

A. KEY VAULT      - macOS Keychain first (`security` CLI), legacy 0600
                    file fallback; keys are NEVER echoed back (masked).
B. REDACTION      - regex heuristics for API keys, tokens, cards (LUHN),
                    private keys; exported for clipboard/files/logs.
C. EXEC POLICY    - evaluate_command() denylist + scope checks used to
                    gate any shell/python execution skill.

Skills: sc_clipboard_guard / sc_policy_check.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Optional

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    logging.basicConfig(level=logging.WARNING)

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("security_hardening")

_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_HERE) if os.path.isfile(
    os.path.join(os.path.dirname(_HERE), "main.py")) else _HERE
LEGACY_KEY_FILE = os.path.join(PROJECT_DIR, ".jarvis_api_key")
KEYCHAIN_SERVICE = "jarvis-groq"
KEYCHAIN_ACCOUNT = "groq"

MASK_RE = re.compile(r"(gsk_|sk-|AKIA)?([A-Za-z0-9_-]{4})[A-Za-z0-9_-]+"
                     r"([A-Za-z0-9_-]{4})")


def mask_secret(text: str) -> str:
    """gsk_abc...wxyz -> gsk_***last4 — never leak a full key."""
    return MASK_RE.sub(
        lambda m: f"{m.group(1) or ''}***{m.group(3)}", text)


# ==========================================================================
# A. Key vault
# ==========================================================================

def _run(cmd: list[str], input_text: str | None = None,
         timeout: float = 6.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              input=input_text, timeout=timeout)
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, "security CLI not found"
    except Exception as exc:
        return 1, str(exc)[:160]


def keychain_available() -> bool:
    rc, _ = _run(["which", "security"])
    return rc == 0


def keychain_store(key: str) -> bool:
    rc, _ = _run(["security", "add-generic-password", "-U",
                  "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT,
                  "-w", key])
    if rc != 0:
        log.warning("keychain store failed rc=%s", rc)
    return rc == 0


def keychain_load() -> Optional[str]:
    rc, out = _run(["security", "find-generic-password",
                    "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"])
    key = out.strip() if rc == 0 else ""
    return key or None


def store_api_key(key: str) -> str:
    """Store key preferring Keychain; returns a human status (masked)."""
    key = (key or "").strip()
    if len(key) < 10:
        return "That key is too short to be real, sir."
    if keychain_store(key):
        # Best-effort removal of any legacy plaintext copy.
        try:
            if os.path.exists(LEGACY_KEY_FILE):
                os.remove(LEGACY_KEY_FILE)
        except OSError:
            pass
        return ("Key sealed in your macOS Keychain, sir "
                f"({mask_secret(key)}).")
    try:
        with open(LEGACY_KEY_FILE, "w", encoding="utf-8") as fh:
            fh.write(key)
        os.chmod(LEGACY_KEY_FILE, 0o600)
    except OSError as exc:
        return f"Keychain refused and file write failed, sir: {exc}"
    return ("Keychain unavailable; stored in %s with 0600 permissions "
            "(%s). Prefer the Keychain next time, sir."
            % (os.path.basename(LEGACY_KEY_FILE), mask_secret(key)))


def load_api_key() -> str:
    env = os.environ.get("GROQ_API_KEY", "").strip()
    if env:
        return env
    kc = keychain_load()
    if kc:
        return kc
    try:
        with open(LEGACY_KEY_FILE, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
    except Exception:
        return ""
    m = re.search(r"gsk_[A-Za-z0-9_-]+", content)
    if m:
        return m.group(0)
    return content if len(content) > 10 else ""


def migrate_to_keychain() -> str:
    key = load_api_key()
    if not key:
        return "No stored key found to migrate, sir."
    if keychain_store(key):
        try:
            os.remove(LEGACY_KEY_FILE)
        except OSError:
            pass
        return ("Migrated your API key into the Keychain and removed the "
                f"plaintext copy, sir ({mask_secret(key)}).")
    return ("The Keychain refused the migration, sir - the plaintext "
            "file stays until that is resolved.")


# ==========================================================================
# B. Redaction heuristics
# ==========================================================================

_REDACT_RULES = [
    ("api-key", re.compile(r"\b(?:gsk|sk)_[A-Za-z0-9_-]{16,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("assign-secret",
     re.compile(r"(?i)\b(pass(word)?|token|secret|api[_-]?key)\b\s*[:=]\s*\S{6,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("long-hex", re.compile(r"\b[a-f0-9]{32,}\b", re.I)),
]


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def redact(text: str) -> tuple[str, int]:
    """Mask secrets in *text*; returns (safe_text, redaction_count)."""
    count = 0
    safe = text or ""

    def sub_n(pattern, replacement):
        nonlocal safe, count
        safe, n = pattern.subn(replacement, safe)
        count += n

    for name, pattern in _REDACT_RULES:
        if name == "assign-secret":
            sub_n(pattern,
                  lambda m: re.sub(r"(:\s*)\S{6,}$", r"\1***", m.group(0))
                  if ":" in m.group(0) else
                  re.sub(r"(=\s*)\S+$", r"\1***", m.group(0)))
        else:
            sub_n(pattern, "***REDACTED***")

    def card_sub(m: "re.Match") -> str:
        digits = re.sub(r"[ -]", "", m.group(0))
        if digits.isdigit() and 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return "***CARD***"
        return m.group(0)

    safe, n = _CARD_RE.subn(card_sub, safe)
    count += n
    return safe, count


# ==========================================================================
# C. Execution policy
# ==========================================================================

_BLOCK_PATTERNS = [
    ("disk-wipe", re.compile(r"\brm\s+(-[a-z]*\s+)*-?[rf]{2,}\b.*\s/(\s|$)",
                             re.I)),
    ("sudo", re.compile(r"\bsudo\b")),
    ("mkfs", re.compile(r"\bmkfs\b|\bdiskutil\s+eraseDisk\b", re.I)),
    ("raw-disk", re.compile(r"\bdd\b[^|]*of=/dev/", re.I)),
    ("pipe-sh", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(ba)?sh\b", re.I)),
    ("chmod-root", re.compile(r"\bchmod\s+777\s+/(?:\s|$)", re.I)),
    ("fork-bomb", re.compile(r":\(\)\s*\{\s*:\|\:&\s*\};:")),
    ("shutdown", re.compile(r"\b(shutdown|halt|reboot)\b", re.I)),
]

_WRITE_OUTSIDE_HOME = re.compile(
    r"(?:>|>>)\s*(/(?:etc|usr|bin|sbin|System|Library)(?:/|\b))", re.I)


def evaluate_command(cmdline: str) -> tuple[bool, str]:
    cmd = cmdline or ""
    for label, pattern in _BLOCK_PATTERNS:
        if pattern.search(cmd):
            return False, f"blocked: {label}"
    if _WRITE_OUTSIDE_HOME.search(cmd):
        return False, "blocked: writes outside home directory"
    return True, "allowed"


# ==========================================================================
# Skills
# ==========================================================================

_CLIP_GUARD_RE = re.compile(
    r"\b(was\s+my\s+clipboard\s+sensitive|redact\w*\s+clipboard|"
    r"clipboard\s+(privacy|secrets?))\b", re.I)


def _e_clipboard_guard(app, ctx) -> str:
    try:
        proc = subprocess.run(["pbpaste"], capture_output=True, text=True,
                              timeout=5)
        text = (proc.stdout or "")[:4000]
    except Exception as exc:
        return f"I could not read the clipboard, sir: {exc}"
    if not text.strip():
        return "The clipboard is empty, sir - nothing to guard."
    safe, n = redact(text)
    preview = safe.replace("\n", " ")[:140]
    if n == 0:
        return (f"Clipboard looks clean, sir (no secrets matched): "
                f"\"{preview}\"")
    return (f"Sensitive content detected and masked, sir - "
            f"{n} item(s). Preview: \"{preview}\"")


def _d_clipboard_guard(cmd):
    return {"cmd": cmd} if _CLIP_GUARD_RE.search(cmd) else None


_POLICY_RE = re.compile(r"\bis\s+(?:this\s+)?command\s+safe\s*[:,-]?\s*(.+)$"
                        r"|\bpolicy\s+check\s*[:,-]?\s*(.+)$", re.I)


def _e_policy_check(app, ctx) -> str:
    allowed, reason = evaluate_command(ctx["cmdline"])
    verdict = "Safe to run" if allowed else "I would refuse that"
    return f"{verdict}, sir ({reason}): {ctx['cmdline'][:120]}"


def _d_policy_check(cmd):
    m = _POLICY_RE.search(cmd)
    if m:
        return {"cmd": cmd, "cmdline": (m.group(1) or m.group(2)).strip()}
    return None


_SKILLS = (
    ("sc_clipboard_guard", _d_clipboard_guard, _e_clipboard_guard),
    ("sc_policy_check", _d_policy_check, _e_policy_check),
)


def register(brain) -> None:  # noqa: ANN001
    for name, detect, execute in _SKILLS:
        def wrapped(app, ctx, _fn=execute):
            try:
                return _fn(app, ctx)
            except Exception as exc:
                log.exception("security skill failed")
                return f"My security module misfired, sir: {exc}"
        brain.register(name, detect, wrapped, priority=False)
    log.info("security hardening registered (%d skills)", len(_SKILLS))


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, d, e, priority=False):
            print("would register", name)

    register(_B())
