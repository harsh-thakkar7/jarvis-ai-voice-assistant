"""JARVIS MAIL SKILLS: Apple Mail (Mail.app) control via pure AppleScript.

Five skills, all macOS-only (Darwin) and driven through the single
``_mail_script`` seam that tests monkeypatch:

    - ml_unread     : "check my email" -> top 5 unread (sender + subject),
                      plus the total unread count
    - ml_read_n     : "read email 2" / "open the first email" -> sender,
                      subject and first 400 characters of the body
    - ml_send       : "send an email to a@b.com about X saying Y" /
                      "email dad saying ..." -> builds a DRAFT only;
                      it never transmits without the explicit follow-up
    - ml_send_draft : "send the draft" -> fires the draft created this
                      session (guarded by the module-level LAST_DRAFT_ID)
    - ml_search     : "find email from bruce" / "emails about gala" ->
                      sender/subject contains query, top 5

Aliases: ``ALIASES`` below is a USER-EDITABLE dict mapping spoken names
("dad", "mom", "boss") to addresses. Add your own contacts there.

Every executor maps app-not-running / permission-denied failures to a
friendly persona reply. This module never imports main.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("mail_skills")

IS_DARWIN = platform.system() == "Darwin"

OSA_TIMEOUT = 15.0
TOP_N = 5                 # how many messages we ever list
SNIPPET_CHARS = 400       # body preview length for ml_read_n

# ==========================================================================
# USER-EDITABLE: spoken alias -> real address. Speak "email dad saying hi"
# and JARVIS resolves "dad" through this table.
# ==========================================================================
ALIASES: dict[str, str] = {
    "dad": "placeholder@example.com",
    "mom": "placeholder@example.com",
    "boss": "placeholder@example.com",
}

# Session-scoped draft bookkeeping. Only ml_send populates it and only
# ml_send_draft consumes it - the send path is never automatic.
LAST_DRAFT_ID: str | None = None
LAST_DRAFT_TO: str | None = None


# ==========================================================================
# Seam (tests monkeypatch this)
# ==========================================================================

def _mail_script(script: str, timeout: float = OSA_TIMEOUT) -> tuple[int, str]:
    """Run an AppleScript against Mail.app; return ``(code, output)``.

    Guarded by Darwin: on anything other than macOS it refuses honestly
    instead of shelling out. Never raises - failures come back as a
    non-zero code with the diagnostics attached.
    """
    if platform.system() != "Darwin":
        return 126, "osascript is macOS-only; Mail skills need a Mac"
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout)
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return proc.returncode, out
    except FileNotFoundError:
        return 127, "osascript not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except Exception as exc:  # defensive containment
        return 1, str(exc)[:200]


def _js(value: str) -> str:
    """Escape a value into an AppleScript string literal.

    Uses the json.dumps trick: JSON's quoting rules produce exactly the
    \\" and \\\\ escapes AppleScript string literals expect.
    """
    return json.dumps(str(value), ensure_ascii=False)


_APP_NOT_RUNNING_MARKERS = (
    "not running",
    "can't be seen",
    "cant be seen",
    "connection is invalid",
    "-600",
    "-1728",
)

_PERMISSION_MARKERS = (
    "not authorized",
    "not allowed",
    "permission",
    "access denied",
    "-1743",
    "automation",
)


def _friendly_fail(action: str, code: int, out: str) -> str:
    """Map an osascript failure to an honest, friendly persona reply."""
    first = (out.splitlines() or ["unspecific error"])[0][:120]
    low = (out or "").lower()
    if code != 0 and any(m in low for m in _APP_NOT_RUNNING_MARKERS):
        return (f"Mail.app isn't running at the moment - launch it and "
                f"I'll {action} straight away, sir.")
    if code != 0 and any(m in low for m in _PERMISSION_MARKERS):
        return (f"I'm not cleared to control Mail - System Settings > "
                f"Privacy & Security > Automation will clear that up "
                f"({first}), sir.")
    return (f"My attempt to {action} hit a snag, sir: {first}. "
            f"Worth another go presently, sir.")


# ==========================================================================
# Shared AppleScript builders
# ==========================================================================

_UNREAD_SCRIPT = '''
set out to ""
tell application "Mail"
\tset unreadMsgs to (every message of inbox whose read status is false)
\trepeat with m in unreadMsgs
\t\tset out to out & (id of m) & tab & ((date sent of m) as «class isot» as string) & tab & (sender of m) & tab & (subject of m) & linefeed
\tend repeat
end tell
return out
'''.strip()


def _body_script(msg_id: str) -> str:
    return f'''
tell application "Mail"
\tset m to first message of inbox whose id is {_js(msg_id)}
\treturn (sender of m) & tab & (subject of m) & tab & (content of m)
end tell
'''.strip()


def _draft_script(rcpt: str, subject: str, body: str) -> str:
    """Build a Mail.app DRAFT. Deliberately contains no send verb."""
    return f'''
tell application "Mail"
\tset outMsg to make new outgoing message with properties {{subject:{_js(subject)}, content:{_js(body)}, visible:true}}
\tmake new to recipient at end of to recipients of outMsg with properties {{address:{_js(rcpt)}}}
\treturn "draft:" & (id of outMsg)
end tell
'''.strip()


def _send_draft_script(draft_id: str) -> str:
    return f'''
tell application "Mail"
\tset msg to first outgoing message whose id is {_js(draft_id)}
\tsend msg
\treturn "sent"
end tell
'''.strip()


def _search_script(frm: str | None, subj: str | None) -> str:
    clauses = []
    if frm:
        clauses.append(f"sender contains {_js(frm)}")
    if subj:
        clauses.append(f"subject contains {_js(subj)}")
    where = " and ".join(clauses) if clauses else "true"
    return f'''
set out to ""
tell application "Mail"
\tset hits to (every message of inbox whose {where})
\trepeat with m in hits
\t\tset out to out & (sender of m) & tab & (subject of m) & tab & ((date sent of m) as «class isot» as string) & linefeed
\tend repeat
end tell
return out
'''.strip()


def _parse_rows(out: str, min_cols: int) -> list[list[str]]:
    rows = []
    for line in (out or "").splitlines():
        line = line.rstrip("\r")
        if not line.strip():
            continue
        cols = line.split("\t")
        if len(cols) >= min_cols:
            rows.append(cols)
    return rows


def _unread_rows(out: str) -> list[dict[str, str]]:
    """id<TAB>dateISO<TAB>sender<TAB>subject lines -> dicts."""
    rows = []
    for cols in _parse_rows(out, 4):
        rows.append({"id": cols[0], "date": cols[1], "sender": cols[2],
                     "subject": "\t".join(cols[3:])})
    return rows


# ==========================================================================
# Skill 1 - ml_unread
# ==========================================================================

_UNREAD_RE = re.compile(
    r"\b(?:check|see)\s+(?:my\s+)?(?:e-?mails?|mail)\b"
    r"|\bunread\b"
    r"|\bany\s+new\s+(?:e-?mails?|mail)\b", re.I)


def _d_unread(cmd: str):
    if not IS_DARWIN:
        return None
    if _UNREAD_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_unread(app, ctx) -> str:
    code, out = _mail_script(_UNREAD_SCRIPT)
    if code != 0:
        return _friendly_fail("check your mail", code, out)
    rows = sorted(_unread_rows(out), key=lambda r: r["date"], reverse=True)
    if not rows:
        return "Inbox zero - not a single unread message awaits you, sir."
    listing = "\n".join(
        f"{i}. {r['sender']} - {r['subject']}"
        for i, r in enumerate(rows[:TOP_N], 1))
    return (f"You have {len(rows)} unread message(s), sir. Top of the pile:"
            f"\n{listing}\nSay 'read email 1' and I'll open it, sir.")


# ==========================================================================
# Skill 2 - ml_read_n
# ==========================================================================

_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}

_READ_N_RE = re.compile(
    r"\b(?:read|open)\s+(?:the\s+)?(?:e-?mail\s+)?"
    r"(?P<num>\d{1,2}(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\b"
    r"(?:\s*e-?mails?\b|\s*$)", re.I)


def _d_read_n(cmd: str):
    if not IS_DARWIN:
        return None
    m = _READ_N_RE.search(cmd)
    if not m:
        return None
    raw = m.group("num").lower()
    if raw.isdigit():
        idx = int(re.sub(r"(st|nd|rd|th)$", "", raw))
    else:
        idx = _ORDINALS.get(raw)
    if idx is None:
        return None
    return {"cmd": cmd, "idx": idx}


def _e_read_n(app, ctx) -> str:
    idx: int = ctx["idx"]
    code, out = _mail_script(_UNREAD_SCRIPT)
    if code != 0:
        return _friendly_fail("fetch that email", code, out)
    rows = sorted(_unread_rows(out), key=lambda r: r["date"], reverse=True)
    if not rows:
        return ("The inbox is spotless, sir - there's nothing unread "
                "to open, sir.")
    if idx < 1 or idx > len(rows):
        return (f"There {'are' if len(rows) != 1 else 'is'} only "
                f"{len(rows)} unread in the stack - pick a number between "
                f"1 and {min(len(rows), TOP_N)}, sir.")
    row = rows[idx - 1]

    code2, out2 = _mail_script(_body_script(row["id"]))
    if code2 != 0:
        return _friendly_fail("open that email", code2, out2)
    cols = out2.split("\t", 2)
    sender = cols[0].strip() if cols else row["sender"]
    subject = cols[1].strip() if len(cols) > 1 else row["subject"]
    body = cols[2] if len(cols) > 2 else ""
    snippet = body.strip()[:SNIPPET_CHARS]
    return (f"Email {idx} - \"{subject}\" from {sender}:\n\n{snippet}\n"
            f"That's email {idx} of {len(rows)}, sir.")


# ==========================================================================
# Skill 3 - ml_send (creates drafts only; transmission is explicit)
# ==========================================================================

_SEND_INTENT_RE = re.compile(
    r"\b(?:send|compose|write|dash\s*off)\s+(?:an?\s+|a\s+)?(?:e-?mail|mail)\b"
    r"|\be-?mail\b[^.?!]*\bsaying\b", re.I)

_TO_RE = re.compile(r"\bto\s+(?P<rcpt>[^\s,!?]+)", re.I)
_VERB_RCPT_RE = re.compile(
    r"\be-?mails?\s+(?P<rcpt>[^\s,!?]+)\s+(?:about|saying)\b", re.I)
_ABOUT_RE = re.compile(
    r"\sabout\s+(?P<subj>.+?)(?=\s+saying\b|\s*$)", re.I | re.S)
_SAYING_RE = re.compile(r"\bsaying\s+(?P<body>.+)$", re.I | re.S)
_ADDR_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.\-]+$")


def _resolve_rcpt(token: str) -> tuple[str, str] | None:
    """'bruce@wayne.org' -> address; 'dad' -> ALIASES lookup."""
    tok = token.strip().strip("\"'")
    if _ADDR_RE.match(tok):
        return tok, tok
    alias = ALIASES.get(tok.lower())
    if alias:
        return alias, tok.lower()
    return None


def _d_send(cmd: str):
    if not IS_DARWIN:
        return None
    if not _SEND_INTENT_RE.search(cmd):
        return None
    rcpt_tok = None
    m = _TO_RE.search(cmd)
    if m:
        rcpt_tok = m.group("rcpt")
    else:
        m = _VERB_RCPT_RE.search(cmd)
        if m:
            rcpt_tok = m.group("rcpt")
    if not rcpt_tok:
        return None
    resolved = _resolve_rcpt(rcpt_tok)
    if not resolved:
        return None          # unknown name and no address: refuse silently
    to_addr, display = resolved
    sm = _SAYING_RE.search(cmd)
    body = sm.group("body").strip() if sm else ""
    am = _ABOUT_RE.search(cmd)
    subject = am.group("subj").strip().strip("\"'") if am else "(no subject)"
    return {"cmd": cmd, "to": to_addr, "display": display,
            "subject": subject, "body": body}


def _e_send(app, ctx) -> str:
    global LAST_DRAFT_ID, LAST_DRAFT_TO
    to_addr = ctx["to"]
    subject = ctx["subject"]
    body = ctx["body"]
    code, out = _mail_script(_draft_script(to_addr, subject, body))
    if code != 0:
        return _friendly_fail("stage that draft", code, out)
    draft_id = out.strip()
    if draft_id.lower().startswith("draft:"):
        draft_id = draft_id.split(":", 1)[1].strip()
    LAST_DRAFT_ID = draft_id or None
    LAST_DRAFT_TO = to_addr
    log.info("draft %s staged for %s (not sent)", LAST_DRAFT_ID, to_addr)
    return (f'A draft to {ctx["display"]} (subject "{subject}") is staged '
            f"and waiting - I don't transmit without your word, sir. "
            f"Say 'send last draft' when you want it fired, sir.")


# ==========================================================================
# Skill 4 - ml_send_draft (the ONLY skill that transmits)
# ==========================================================================

_SEND_DRAFT_RE = re.compile(
    r"\bsend\s+(?:the\s+|my\s+|that\s+)?(?:last\s+)?draft\b"
    r"|\bsend\s+(?:my\s+|the\s+)?last\s+(?:e-?mail|email)\b"
    r"|\bfire\s+(?:off\s+)?the\s+draft\b", re.I)


def _d_send_draft(cmd: str):
    if not IS_DARWIN:
        return None
    if _SEND_DRAFT_RE.search(cmd):
        return {"cmd": cmd}
    return None


def _e_send_draft(app, ctx) -> str:
    global LAST_DRAFT_ID
    if not LAST_DRAFT_ID:
        return ("There's no draft from this session waiting for me, sir - "
                "compose one via 'email someone saying ...' first, sir.")
    code, out = _mail_script(_send_draft_script(LAST_DRAFT_ID))
    if code != 0:
        return _friendly_fail("fire that draft", code, out)
    fired_to = LAST_DRAFT_TO or "the recipient"
    LAST_DRAFT_ID = None          # one shot per draft; no accidental re-fire
    log.info("draft sent to %s", fired_to)
    return f"Fired. Your draft to {fired_to} is on its way, sir."


# ==========================================================================
# Skill 5 - ml_search
# ==========================================================================

_SEARCH_FROM_RE = re.compile(
    r"\b(?:find|search)\s+(?:all\s+|my\s+)?(?:e-?mails?|mail)\s+"
    r"(?:from|by)\s+(?P<frm>.+?)(?:\s+about\s+(?P<subj>.+?))?\s*$",
    re.I | re.S)
_SEARCH_ABOUT_RE = re.compile(
    r"\b(?:find\s+|search\s+)?(?:e-?mails?|mail)\s+about\s+(?P<subj>.+?)\s*$",
    re.I | re.S)


def _d_search(cmd: str):
    if not IS_DARWIN:
        return None
    m = _SEARCH_FROM_RE.search(cmd)
    if m:
        frm = (m.group("frm") or "").strip().strip("\"'")
        subj = (m.group("subj") or "").strip().strip("\"'") or None
        return {"cmd": cmd, "frm": frm or None, "subj": subj}
    m = _SEARCH_ABOUT_RE.search(cmd)
    if m:
        subj = (m.group("subj") or "").strip().strip("\"'")
        if subj:
            return {"cmd": cmd, "frm": None, "subj": subj}
    return None


def _e_search(app, ctx) -> str:
    frm, subj = ctx.get("frm"), ctx.get("subj")
    code, out = _mail_script(_search_script(frm, subj))
    if code != 0:
        return _friendly_fail("search your mail", code, out)
    rows = _parse_rows(out, 2)
    if not rows:
        term = subj or frm or ""
        return f"Nothing in the archive matches \"{term}\", sir."
    listing = "\n".join(
        f"{i}. {cols[0]} - {cols[1]}"
        for i, cols in enumerate(rows[:TOP_N], 1))
    return (f"I found {len(rows)} match(es), sir. Best bets:"
            f"\n{listing}\nPoint me at a number if any deserve opening, sir.")


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("ml_unread", _d_unread, _e_unread, False),
    ("ml_read_n", _d_read_n, _e_read_n, False),
    ("ml_send_draft", _d_send_draft, _e_send_draft, True),
    ("ml_send", _d_send, _e_send, False),
    ("ml_search", _d_search, _e_search, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register all mail skills with the given Brain instance."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("mail skills registered (%d)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return f"Something misfired in my mail module ({str(exc)[:120]}), sir."
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
