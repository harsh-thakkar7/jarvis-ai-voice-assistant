"""Tests for mail_skills.py — offline; osascript is mocked via _mail_script."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mail_skills as ms  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {
    "ml_unread", "ml_read_n", "ml_send_draft", "ml_send", "ml_search",
}


@pytest.fixture()
def brain():
    b = RecorderBrain()
    ms.register(b)
    return b


@pytest.fixture(autouse=True)
def clean_session(monkeypatch):
    """Every test starts with a fresh session draft state."""
    monkeypatch.setattr(ms, "LAST_DRAFT_ID", None)
    monkeypatch.setattr(ms, "LAST_DRAFT_TO", None)


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


class FakeOSA:
    """Records every script handed to _mail_script; replays results."""

    def __init__(self, results=None):
        self.calls = []
        self.results = list(results or [])

    def __call__(self, script, timeout=15.0):
        self.calls.append(script)
        if self.results:
            return self.results.pop(0)
        return 0, ""


@pytest.fixture()
def fake_mail(monkeypatch):
    def attach(results=None):
        fake = FakeOSA(results)
        monkeypatch.setattr(ms, "_mail_script", fake)
        return fake
    return attach


UNREAD_6 = "\n".join([
    f"m{i}\t2026-08-{27 - i}T10:00:00Z\tsender{i}@x.com\tSubject {i}"
    for i in range(1, 7)
])  # m1 is the newest; date-desc ordering keeps list positions stable

NOT_RUNNING = (1, "Mail got an error: Connection is invalid. (-600)")
PERMISSION_DENIED = (
    1, "execution error: Mail got an error: Not authorized to send Apple "
       "events. (-1743)")


# ==========================================================================
# Registration
# ==========================================================================

def test_registers_all_five_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


# ==========================================================================
# Escaping seam
# ==========================================================================

def test_js_escapes_quotes_and_backslashes():
    assert ms._js('say "hi"') == '"say \\"hi\\""'
    assert ms._js("C:\\path") == '"C:\\\\path"'
    assert ms._js("plain") == '"plain"'


def test_seam_refuses_on_non_darwin(monkeypatch):
    monkeypatch.setattr(ms.platform, "system", lambda: "Linux")
    code, out = ms._mail_script('tell application "Mail" to activate')
    assert code != 0 and "macos-only" in out.lower()


# ==========================================================================
# ml_unread
# ==========================================================================

def test_unread_lists_top5_with_total(brain, fake_mail):
    fake = fake_mail([(0, UNREAD_6)])
    reply = run(brain, "ml_unread", "check my email")
    assert 'tell application "Mail"' in fake.calls[0]
    assert "read status is false" in fake.calls[0]
    assert "6 unread message(s)" in reply
    assert "sender1@x.com - Subject 1" in reply
    assert "5." in reply and "6." not in reply      # capped at five rows
    assert reply.rstrip().endswith(", sir.")


def test_unread_empty_inbox_persona(brain, fake_mail):
    fake_mail([(0, "")])
    reply = run(brain, "ml_unread", "any new mail")
    assert "Inbox zero" in reply and reply.endswith(", sir.")


def test_unread_app_not_running_persona(brain, fake_mail):
    fake_mail([NOT_RUNNING])
    reply = run(brain, "ml_unread", "unread emails")
    assert "isn't running" in reply and reply.endswith(", sir.")


def test_unread_permission_denied_persona(brain, fake_mail):
    fake_mail([PERMISSION_DENIED])
    reply = run(brain, "ml_unread", "any new mail")
    assert "Automation" in reply and "-1743" in reply
    assert reply.endswith(", sir.")


# ==========================================================================
# ml_read_n
# ==========================================================================

LONG_BODY = "Dear Bruce, " + "filler text here. " * 60   # well past 400


def test_read_n_opens_second_email_truncated(brain, fake_mail):
    body_row = ("bruce@wayne.org\tGala invite\t" + LONG_BODY)
    fake = fake_mail([(0, UNREAD_6), (0, body_row)])
    reply = run(brain, "ml_read_n", "read email 2")
    assert len(fake.calls) == 2
    assert '"m2"' in fake.calls[1]                  # targets row 2 by id
    assert "Gala invite" in reply and "bruce@wayne.org" in reply
    snippet_start = LONG_BODY[:400][:20]
    assert snippet_start in reply
    assert LONG_BODY[400:] not in reply             # truncated at 400 chars
    assert reply.endswith(", sir.")


def test_read_n_first_ordinal(brain, fake_mail):
    fake = fake_mail([(0, UNREAD_6),
                      (0, "a@b.com\tHello\tshort body")])
    reply = run(brain, "ml_read_n", "open the first email")
    assert '"m1"' in fake.calls[1]
    assert "Email 1" in reply


def test_read_n_bounds_persona(brain, fake_mail):
    two_rows = "m1\t2026-08-23T10:00:00Z\ta@b.com\tOne\n" \
               "m2\t2026-08-23T09:00:00Z\tc@d.com\tTwo"
    fake = fake_mail([(0, two_rows)])
    reply = run(brain, "ml_read_n", "read email 9")
    assert len(fake.calls) == 1                     # never fetched a body
    assert "only 2 unread" in reply
    assert "between 1 and" in reply and reply.endswith(", sir.")


def test_read_n_zero_index_persona(brain, fake_mail):
    fake = fake_mail([(0, UNREAD_6)])
    reply = run(brain, "ml_read_n", "read email 0")
    assert "between 1 and" in reply


def test_read_n_no_unread_persona(brain, fake_mail):
    fake_mail([(0, "")])
    reply = run(brain, "ml_read_n", "read email 1")
    assert "spotless" in reply.lower() and reply.endswith(", sir.")


# ==========================================================================
# ml_send — drafts only, NEVER auto-sends
# ==========================================================================

def test_send_builds_draft_without_sending(brain, fake_mail):
    fake = fake_mail([(0, "draft:DRAFT-77")])
    reply = run(
        brain, "ml_send",
        'send an email to a@b.com about Q4 "wins" review saying '
        'Great job team! See C:\\notes')
    script = fake.calls[0]
    assert len(fake.calls) == 1                     # exactly one seam call
    assert "make new outgoing message" in script
    assert "send " not in script.lower()            # safety: no transmit verb
    assert 'address:"a@b.com"' in script
    assert 'Q4 \\"wins\\" review' in script         # escaped quotes survive
    assert "C:\\\\notes" in script                  # escaped backslash survives
    assert ms.LAST_DRAFT_ID == "DRAFT-77"
    assert ms.LAST_DRAFT_TO == "a@b.com"
    assert "staged" in reply.lower()
    assert "send last draft" in reply.lower()
    assert reply.endswith(", sir.")


def test_send_alias_expansion(brain, fake_mail):
    fake = fake_mail([(0, "draft:DRAFT-88")])
    reply = run(brain, "ml_send", "email dad saying dinner at eight?")
    script = fake.calls[0]
    assert f'address:"{ms.ALIASES["dad"]}"' in script
    assert ms.LAST_DRAFT_TO == ms.ALIASES["dad"]
    assert "dad" in reply and reply.endswith(", sir.")


def test_send_unknown_recipient_not_detected(brain):
    assert brain.skills["ml_send"][0]("email stranger saying hi") is None
    assert brain.skills["ml_send"][0]("send flowers to mom") is None


def test_send_failure_persona(brain, fake_mail):
    fake_mail([PERMISSION_DENIED])
    reply = run(brain, "ml_send",
                "send an email to a@b.com about Lunch saying Hungry")
    assert "Automation" in reply and reply.endswith(", sir.")


# ==========================================================================
# ml_send_draft — transmission only through this explicit skill
# ==========================================================================

def test_send_draft_fires_session_draft(brain, fake_mail, monkeypatch):
    monkeypatch.setattr(ms, "LAST_DRAFT_ID", "DRAFT-77")
    monkeypatch.setattr(ms, "LAST_DRAFT_TO", "a@b.com")
    fake = fake_mail([(0, "sent")])
    reply = run(brain, "ml_send_draft", "send the draft")
    script = fake.calls[0]
    assert '"DRAFT-77"' in script
    assert "\tsend msg\n" in script                 # explicit send verb here
    assert ms.LAST_DRAFT_ID is None                 # one-shot guard cleared
    assert "on its way" in reply and reply.endswith(", sir.")


def test_send_draft_without_session_draft_persona(brain, fake_mail):
    fake = fake_mail([])
    reply = run(brain, "ml_send_draft", "send my last email")
    assert fake.calls == []                         # nothing fired
    assert "no draft from this session" in reply.lower()
    assert reply.endswith(", sir.")


# ==========================================================================
# ml_search
# ==========================================================================

SEARCH_ROWS = "alfred@wayne.org\tGala catering\nlucius@wayne.org\tBudget"

def test_search_sender_and_subject_clauses(brain, fake_mail):
    fake = fake_mail([(0, SEARCH_ROWS)])
    reply = run(brain, "ml_search",
                "find email from bruce wayne about gala")
    script = fake.calls[0]
    assert 'sender contains "bruce wayne"' in script
    assert 'subject contains "gala"' in script
    assert "alfred@wayne.org - Gala catering" in reply
    assert "2 match(es)" in reply and reply.endswith(", sir.")


def test_search_about_only(brain, fake_mail):
    fake = fake_mail([(0, SEARCH_ROWS)])
    reply = run(brain, "ml_search", "emails about invoices")
    assert 'subject contains "invoices"' in fake.calls[0]
    assert "invoices" in fake.calls[0]
    assert "Budget" in reply


def test_search_no_hits_persona(brain, fake_mail):
    fake_mail([(0, "")])
    reply = run(brain, "ml_search", "find email from zodiac")
    assert "Nothing in the archive matches" in reply
    assert reply.endswith(", sir.")


def test_search_failure_persona(brain, fake_mail):
    fake_mail([NOT_RUNNING])
    reply = run(brain, "ml_search", "emails about gala")
    assert "isn't running" in reply and reply.endswith(", sir.")


# ==========================================================================
# Negative detection + guards
# ==========================================================================

@pytest.mark.parametrize("cmd", ["what time is it", "joke"])
def test_detectors_ignore_unrelated_commands(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_non_darwin_guard_disables_detectors(brain, monkeypatch):
    monkeypatch.setattr(ms, "IS_DARWIN", False)
    probes = ["check my email", "read email 2", "email dad saying hi",
              "send an email to a@b.com about X saying Y",
              "send the draft", "find email from bruce"]
    for name, (detect, _exec, _prio) in brain.skills.items():
        for cmd in probes:
            assert detect(cmd) is None, f"{name} fired while not Darwin"


def test_executor_wraps_crashes_in_persona(brain, monkeypatch):
    def boom(script, timeout=15.0):
        raise RuntimeError("cable pulled")

    monkeypatch.setattr(ms, "_mail_script", boom)
    reply = run(brain, "ml_unread", "check my email")
    assert reply.endswith(", sir.") and "misfired" in reply
