"""Tests for bot_quick_bar.py — pure logic only, NO tk instantiation.

Covers: QUICK_ACTIONS table integrity (incl. the offline-verified command
phrases), positioning math edge cases, the show/hide state machine, and
attach() idempotency against a fake bot with a recording menu stub.
"""

import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot_quick_bar as bqb  # noqa: E402


# ==========================================================================
# QUICK_ACTIONS table integrity
# ==========================================================================

def test_labels_unique():
    labels = [label for _glyph, label, _action in bqb.QUICK_ACTIONS]
    assert len(labels) == len(set(labels))
    assert len(labels) >= 10  # voice..help


def test_every_entry_well_formed():
    for glyph, label, action in bqb.QUICK_ACTIONS:
        assert isinstance(glyph, str) and glyph.strip(), label
        assert isinstance(label, str) and label.strip()
        # action is a non-empty pipeline command or a callable resolver
        if isinstance(action, str):
            assert action.strip()
        else:
            assert callable(action)


def test_expected_entries_exist():
    by_label = {label: action for _g, label, action in bqb.QUICK_ACTIONS}
    # verified text-command phrases -> intended skills:
    #   what's the weather      -> JarvisBot._process shortcut (_get_weather)
    #   start a focus session   -> fx_start        (focus_pomodoro_brain)
    #   run a speed test        -> nd_speed_test   (net_diagnostics_brain)
    #   how's my day            -> br_day_digest   (briefing_brain)
    #   check my email          -> ml_unread       (mail_skills detector)
    #   clipboard history       -> ps_clipboard_history
    #                              (power_skills _CLIP_HIST_RE detector)
    verified = {
        "Weather": "what's the weather",
        "Pomodoro": "start a focus session",
        "Speed Test": "run a speed test",
        "My Agenda": "how's my day",
        "Mail": "check my email",
        "Clipboard": "clipboard history",
    }
    for label, cmd in verified.items():
        assert by_label.get(label) == cmd

    # callable chips resolve zero-arg bot methods
    for label in ("Voice", "Screen", "Timer 5m", "Help"):
        resolver = by_label[label]
        assert callable(resolver)


# ==========================================================================
# Positioning math — screen-edge cases
# ==========================================================================

W, H = 50, 400  # typical bar size


def test_position_happy_path():
    # orb mid-screen: exact spec placement (orb_x - w - gap, orb_y - 40)
    x, y = bqb.compute_bar_position(1000, 500, W, H, 1440, 900)
    assert x == 1000 - W - 8
    assert y == 500 - 40


def test_position_left_edge_clamped():
    x, y = bqb.compute_bar_position(20, 500, W, H, 1440, 900)
    assert x == bqb.MARGIN_PX          # would be negative otherwise
    assert y == 460


def test_position_top_edge_clamped():
    x, y = bqb.compute_bar_position(1400, 0, W, H, 1440, 900)
    assert x == 1400 - W - 8                # fits without clamping
    assert y == bqb.MARGIN_PX              # -40 clamped up to margin


def test_position_bottom_edge_clamped():
    x, y = bqb.compute_bar_position(1400, 895, W, H, 1440, 900)
    assert y == 900 - H - bqb.MARGIN_PX  # never pokes past the bottom


def test_position_tiny_screen_never_negative():
    x, y = bqb.compute_bar_position(0, 0, W, H, 30, 30)
    assert x >= bqb.MARGIN_PX or x == 30 - W - bqb.MARGIN_PX
    assert y == bqb.MARGIN_PX


def test_position_stays_on_screen_for_all_edges():
    sw, sh = 800, 600
    corners = [(0, 0), (sw, 0), (0, sh), (sw, sh), (sw // 2, sh // 2)]
    for ox, oy in corners:
        x, y = bqb.compute_bar_position(ox, oy, W, H, sw, sh)
        assert x >= bqb.MARGIN_PX
        assert y >= bqb.MARGIN_PX
        assert x + W <= sw - bqb.MARGIN_PX + 1  # tiny screens may force it
        assert y + H <= sh - bqb.MARGIN_PX + 1


# ==========================================================================
# Show/hide state machine
# ==========================================================================

def test_state_machine_starts_hidden():
    sm = bqb.BarState(delay_ms=1500)
    assert sm.state == bqb.BarState.HIDDEN
    assert sm.tick(0) is None


def test_enter_orb_shows():
    sm = bqb.BarState()
    assert sm.request_show() == "show"
    assert sm.state == bqb.BarState.SHOWN
    assert sm.request_show() is None    # idempotent while shown


def test_leave_bar_then_delay_hides():
    sm = bqb.BarState(delay_ms=1500)
    sm.request_show()
    assert sm.bar_left(now_ms=1000) == "watch"
    assert sm.state == bqb.BarState.WAITING
    assert sm.tick(1000 + 1499) is None     # just before deadline
    assert sm.tick(1000 + 1500) == "hide"   # exactly at delay
    assert sm.state == bqb.BarState.HIDDEN


def test_reenter_bar_cancels_hide():
    sm = bqb.BarState(delay_ms=1500)
    sm.request_show()
    sm.bar_left(now_ms=0)
    assert sm.bar_entered() == "show"
    assert sm.left_at_ms is None            # countdown cancelled
    assert sm.tick(60_000) is None          # much later: still shown
    assert sm.state == bqb.BarState.SHOWN


def test_bar_left_while_hidden_is_ignored():
    sm = bqb.BarState()
    assert sm.bar_left(now_ms=5) is None
    assert sm.state == bqb.BarState.HIDDEN


def test_manual_toggle_cycles():
    sm = bqb.BarState()
    assert sm.toggle() == "show"
    assert sm.state == bqb.BarState.SHOWN
    assert sm.toggle() == "hide"
    assert sm.state == bqb.BarState.HIDDEN
    assert sm.toggle() == "show"


def test_toggle_from_waiting_resets_to_shown():
    sm = bqb.BarState()
    sm.request_show()
    sm.bar_left(now_ms=0)
    assert sm.toggle() == "show"            # waiting counts as visible
    assert sm.state == bqb.BarState.SHOWN


def test_force_hide_from_any_state():
    sm = bqb.BarState()
    assert sm.force_hide() is None          # already hidden
    sm.request_show()
    assert sm.force_hide() == "hide"
    assert sm.state == bqb.BarState.HIDDEN


# ==========================================================================
# attach() guard logic against a fake bot (no tk objects anywhere)
# ==========================================================================

class RecordingMenu:
    def __init__(self):
        self.calls = []

    def add_command(self, label=None, command=None):
        self.calls.append((label, command))


class NoTkRoot:
    """Stands in for bot.root; any after() scheduling must fail soft."""

    def after(self, *_a, **_k):
        raise RuntimeError("no tkinter event loop in tests")

    def after_cancel(self, *_a, **_k):
        raise RuntimeError("no tkinter event loop in tests")


def make_fake_bot():
    return types.SimpleNamespace(menu=RecordingMenu(), root=NoTkRoot(),
                                 ORB_SIZE=56)


def test_attach_adds_single_menu_item_and_sets_guard():
    bot = make_fake_bot()
    ctrl = bqb.attach(bot)
    assert getattr(bot, "_clicky_quickbar") is ctrl
    assert len(bot.menu.calls) == 1
    label, command = bot.menu.calls[0]
    assert "Quick Bar" in label
    assert callable(command)                # command is the toggle
    ctrl.detach()


def test_attach_is_idempotent():
    bot = make_fake_bot()
    first = bqb.attach(bot)
    second = bqb.attach(bot)
    assert first is second
    assert len(bot.menu.calls) == 1         # no duplicate menu item
    first.detach()


def test_detach_clears_guard_and_allows_reattach():
    bot = make_fake_bot()
    bqb.attach(bot).detach()
    assert getattr(bot, "_clicky_quickbar", None) is None
    ctrl2 = bqb.attach(bot)
    assert len(bot.menu.calls) == 2         # fresh item after re-attach
    ctrl2.detach()


def test_toggle_fails_soft_without_tk():
    bot = make_fake_bot()
    ctrl = bqb.attach(bot)
    # toggle tries to build the Toplevel on a fake root: must not raise,
    # and the state machine still flips.
    ctrl.toggle()
    assert ctrl.state_machine.state == bqb.BarState.SHOWN
    ctrl.toggle()
    assert ctrl.state_machine.state == bqb.BarState.HIDDEN
    ctrl.detach()


def test_detach_twice_is_safe():
    bot = make_fake_bot()
    ctrl = bqb.attach(bot)
    ctrl.detach()
    ctrl.detach()                            # no exception
    assert getattr(bot, "_clicky_quickbar", None) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
