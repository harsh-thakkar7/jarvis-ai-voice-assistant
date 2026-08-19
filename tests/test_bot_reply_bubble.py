"""Tests for bot_reply_bubble: pure text logic + say hook contract.

No tkinter instances are created anywhere; the fake bot carries root=None so
the add-on must survive without a display (fail-soft requirement).
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot_reply_bubble as brb


class FakeBot:
    """Recording stand-in for JarvisBot with just the attrs the add-on needs."""

    def __init__(self):
        self.calls = []
        self.speaks = []
        self.last_reply = ""
        self.root = None  # no tk: controller must fail-soft

    def say(self, text):
        self.calls.append(text)
        self.last_reply = text

    def _speak(self, text):
        self.speaks.append(text)


# ============================================================================
# wrap_at
# ============================================================================
class TestWrapAt:
    def test_short_text_single_line(self):
        assert brb.wrap_at("Hello sir.") == "Hello sir."

    def test_long_text_wraps_within_width(self):
        text = ("The reactor diagnostics are complete and every subsystem "
                "reports nominal output levels today.")
        out = brb.wrap_at(text)
        lines = out.split("\n")
        assert len(lines) <= brb.BUBBLE_MAX_LINES
        for ln in lines:
            assert len(ln) <= brb.BUBBLE_WRAP_CHARS
        assert out.replace("\n", " ").split() == text.split()

    def test_multiline_preserved(self):
        out = brb.wrap_at("line one\nline two\n\nline four")
        assert out.split("\n") == ["line one", "line two", "", "line four"]

    def test_exact_42_chars_untouched(self):
        line = "x" * 42
        assert brb.wrap_at(line) == line
        two_words = "a" * 20 + " " + "b" * 21  # exactly 42 incl space
        assert brb.wrap_at(two_words) == two_words

    def test_overlong_word_hard_split_no_loss(self):
        word = "w" * 100
        out = brb.wrap_at(word)
        lines = out.split("\n")
        assert all(len(ln) <= brb.BUBBLE_WRAP_CHARS for ln in lines)
        assert "".join(lines) == word

    def test_more_than_max_lines_gets_ellipsis(self):
        paras = "\n".join("row %d %s" % (i, "z" * 40) for i in range(9))
        out = brb.wrap_at(paras)
        lines = out.split("\n")
        assert len(lines) == brb.BUBBLE_MAX_LINES
        assert out.endswith("...")
        for ln in lines:
            assert len(ln) <= brb.BUBBLE_WRAP_CHARS

    def test_custom_width_and_max_lines(self):
        text = "aaaa bbbb cccc dddd"
        assert brb.wrap_at(text, width=10, max_lines=2) == \
            "aaaa bbbb\ncccc dddd"
        assert brb.wrap_at(text, width=10, max_lines=1) == "aaaa bb..."

    def test_none_and_blank(self):
        assert brb.wrap_at(None) == ""
        assert brb.wrap_at("") == ""


# ============================================================================
# format_reply
# ============================================================================
class TestFormatReply:
    def test_none_becomes_placeholder(self):
        assert brb.format_reply(None) == brb.NO_REPLY_TEXT

    def test_blank_becomes_placeholder(self):
        assert brb.format_reply("   ") == brb.NO_REPLY_TEXT

    def test_text_is_stripped_and_wrapped(self):
        out = brb.format_reply("  " + "hi " * 60 + " ")
        assert not out.startswith(" ")
        assert all(len(ln) <= brb.BUBBLE_WRAP_CHARS
                   for ln in out.split("\n"))


# ============================================================================
# autohide decision helpers
# ============================================================================
class TestAutohideDecisions:
    def test_hover_event_mapping(self):
        assert brb.hover_action("<Enter>") == "cancel"
        assert brb.hover_action("<Leave>") == "restart"
        assert brb.hover_action("<Motion>") is None
        assert brb.hover_action("") is None

    def test_should_autohide_matrix(self):
        assert brb.should_autohide(True, False) is True
        assert brb.should_autohide(True, True) is False
        assert brb.should_autohide(False, False) is False
        assert brb.should_autohide(False, True) is False

    def test_constants_sane(self):
        assert brb.AUTOHIDE_MS == 12000
        assert brb.FOLLOW_INTERVAL_MS == 400
        assert brb.BUBBLE_Y_OFFSET_PX == 120
        assert brb.BUBBLE_X_GAP_PX == 8


# ============================================================================
# say wrapper factory
# ============================================================================
class TestSayWrapperFactory:
    def _make(self):
        calls = []
        shows = []
        original = lambda text: calls.append(text)  # noqa: E731
        return calls, shows, original

    def test_original_called_once_then_show_formatted(self):
        calls, shows, original = self._make()
        wrapped = brb.make_say_wrapper(original, lambda t: shows.append(t))
        wrapped("Good morning sir, all systems are fully operational now.")
        assert calls == ["Good morning sir, all systems are fully operational now."]
        assert len(shows) == 1
        assert "\n" in shows[0]  # formatted => wrapped text
        assert shows[0] == brb.format_reply(
            "Good morning sir, all systems are fully operational now.")

    def test_exception_in_show_never_breaks_original_or_caller(self):
        calls, _, original = self._make()

        def boom(_text):
            raise RuntimeError("bubble exploded")

        wrapped = brb.make_say_wrapper(original, boom)
        wrapped("still speaking")  # must not raise
        assert calls == ["still speaking"]

    def test_original_return_value_passthrough(self):
        original = lambda t: "ret-" + t  # noqa: E731
        wrapped = brb.make_say_wrapper(original, lambda t: None)
        assert wrapped("x") == "ret-x"

    def test_wrapper_marks_chain(self):
        _, _, original = self._make()
        wrapped = brb.make_say_wrapper(original, lambda t: None)
        assert wrapped.__wrapped_say__ is original


# ============================================================================
# attach / detach lifecycle on a fake bot (root=None, fail-soft path)
# ============================================================================
class TestAttachLifecycle:
    def test_attach_hooks_and_fail_soft_without_root(self):
        bot = FakeBot()
        ctrl = brb.attach(bot)
        assert ctrl is not None
        assert callable(bot.say) and bot.say is not FakeBot.say.__get__(bot)
        bot.say("hello there")
        assert bot.calls == ["hello there"]  # original behaviour intact
        assert ctrl.last_formatted == "hello there"
        ctrl.detach()

    def test_detach_restores_original_say(self):
        bot = FakeBot()
        original = bot.say
        ctrl = brb.attach(bot)
        assert bot.say is not original
        ctrl.detach()
        assert bot.say == original
        bot.say("back to normal")
        assert bot.calls == ["back to normal"]

    def test_double_attach_idempotent(self):
        bot = FakeBot()
        c1 = brb.attach(bot)
        c2 = brb.attach(bot)
        assert c1 is c2
        bot.say("once only")
        assert bot.calls == ["once only"]
        c1.detach()
        assert getattr(bot, "_clicky_bubble", None) is None

    def test_double_detach_safe(self):
        bot = FakeBot()
        original = bot.say
        ctrl = brb.attach(bot)
        ctrl.detach()
        ctrl.detach()  # must not raise
        assert bot.say == original

    def test_unwrap_through_chained_wrapper(self):
        bot = FakeBot()
        original = bot.say
        ours = brb.attach(bot)
        # someone else wraps on top of ours before we detach
        top = lambda text, *a, **k: None  # noqa: E731
        top.__wrapped_say__ = bot.say
        bot.say = top
        ours.detach()
        assert bot.say is top          # foreign layer left in place...
        # ...relayed straight to the original say (bound methods compare ==)
        assert top.__wrapped_say__ == original

    def test_unwrap_direct_wrapper_returns_original(self):
        wrapper = brb.make_say_wrapper(lambda t: None, lambda t: None)
        original = lambda t: None  # noqa: E731
        assert brb.unwrap_say(wrapper, wrapper, original) is original

    def test_unwrap_leaves_unknown_chain_alone(self):
        current = lambda t: None  # noqa: E731
        inner = lambda t: None  # noqa: E731
        current.__wrapped_say__ = inner
        ours = brb.make_say_wrapper(inner, lambda t: None)
        assert brb.unwrap_say(current, ours, lambda t: None) is current

    def test_attach_requires_callable_say(self):
        class NoSay:
            root = None

        assert brb.attach(NoSay()) is None

    def test_controller_records_raw_reply_for_copy(self):
        bot = FakeBot()
        ctrl = brb.attach(bot)
        bot.say("Copy me please")
        assert ctrl.last_raw == "Copy me please"
        ctrl.detach()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
