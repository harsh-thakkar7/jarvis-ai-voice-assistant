"""Headless JarvisBot tests for the Clicky-excellence pack.

Pattern: JARVIS_TEST=1, real JarvisBot with a withdrawn Tk root, every
external seam (screenshots, vision, mouse position, clock, PTT probes)
monkeypatched. Fully offline; no audio leaves the room.

Covers:
  1. "📖 Read Screen Aloud" right-click menu item — placement, invocation,
     live_screen_brain seam preference, bot-seam fallback, total failure.
  2. Follow-cursor auto-park: 12 s idle -> glide home + pause; mouse
     movement or menu/drag interaction resumes trailing.
  3. Startup PTT toast honesty across the availability matrix.
  4. Pointer-halo clamping math via the extracted helper.
"""

import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JARVIS_TEST", "1")

import main  # noqa: E402
import hotkey_ptt  # noqa: E402
import ptt_onboarding  # noqa: E402


# ==========================================================================
# Headless JarvisBot fixture
# ==========================================================================

@pytest.fixture
def bot(monkeypatch):
    """A real JarvisBot with a withdrawn root and a silent voice."""
    monkeypatch.setenv("JARVIS_TEST", "1")
    monkeypatch.setattr(main.JarvisBot, "_init_tts",
                        lambda self: setattr(self, "_tts_engine", None))
    b = main.JarvisBot()
    b.root.withdraw()
    yield b
    try:
        b.root.destroy()
    except Exception:
        pass


def _menu_items(menu):
    """(menu_index, label) pairs, skipping separators."""
    out = []
    for i in range(menu.index("end") + 1):
        if str(menu.type(i)) == "separator":
            continue
        try:
            out.append((i, str(menu.entrycget(i, "label"))))
        except Exception:
            continue
    return out


# ==========================================================================
# 1. 📖 Read Screen Aloud menu item
# ==========================================================================

def test_read_screen_aloud_sits_right_after_read_my_screen(bot):
    items = _menu_items(bot.menu)
    labels = [lbl for _i, lbl in items]
    assert "📖  Read Screen Aloud" in labels
    i = labels.index("📸  Read My Screen")
    assert labels[i + 1] == "📖  Read Screen Aloud"
    menu_idx = items[i + 1][0]
    assert str(bot.menu.type(menu_idx)) == "command"
    assert str(bot.menu.entrycget(menu_idx, "command")).strip()


def test_invoke_reads_screen_via_live_screen_seams(bot, monkeypatch):
    asked = threading.Event()

    fake = types.ModuleType("live_screen_brain")

    def take_screenshot():
        return "c2NyZWVuc2hvdA=="  # "screenshot"

    def ask_vision(app, b64, question):
        assert isinstance(b64, str) and b64
        asked.set()
        return ("Terminal window titled jarvis. The prompt shows a pytest "
                "run. Ten tests passed in two seconds. A caret blinks.")

    fake.take_screenshot = take_screenshot
    fake.ask_vision = ask_vision
    monkeypatch.setitem(sys.modules, "live_screen_brain", fake)

    spoken, toasts = [], []
    monkeypatch.setattr(bot, "_speak", spoken.append)
    monkeypatch.setattr(bot, "_show_toast",
                        lambda text, duration=4000: toasts.append(text))

    idx = dict((lbl, i) for i, lbl in _menu_items(bot.menu))[
        "📖  Read Screen Aloud"]
    bot.menu.invoke(idx)                       # fires the real command

    assert asked.wait(5), "vision seam was never consulted"
    deadline = time.monotonic() + 5
    while not spoken and time.monotonic() < deadline:
        time.sleep(0.01)                       # worker thread lands its lines
    assert spoken, "orb stayed silent, sir"
    assert len(spoken[0]) <= 260               # concise, speakable summary
    assert "pytest" in spoken[0]               # drawn from the transcription
    assert toasts and toasts[0].startswith("📖")   # info window shown


def test_falls_back_to_bot_screenshot_and_vision(bot, monkeypatch):
    fake = types.ModuleType("live_screen_brain")
    fake.take_screenshot = lambda: None        # upstream optics dark; the
    monkeypatch.setitem(sys.modules, "live_screen_brain", fake)  # module has
    # no ask_vision at all -> bot's own _take_screenshot/_ask_vision serve.

    monkeypatch.setattr(bot, "_take_screenshot",
                        lambda: (object(), "Ym90c2hvdA=="))
    monkeypatch.setattr(bot, "_ask_vision",
                        lambda b64, q: "Fallback transcription, sir.")
    spoken, toasts = [], []
    monkeypatch.setattr(bot, "_speak", spoken.append)
    monkeypatch.setattr(bot, "_show_toast",
                        lambda text, duration=4000: toasts.append(text))

    bot._read_screen_aloud_work()              # synchronous on purpose

    assert spoken and "Fallback transcription" in spoken[0]
    assert toasts and "Fallback transcription" in toasts[0]


def test_total_failure_stays_polite_and_soft(bot, monkeypatch):
    monkeypatch.setitem(sys.modules, "live_screen_brain", None)  # import dies
    monkeypatch.setattr(bot, "_take_screenshot", lambda: (None, None))
    said = []
    monkeypatch.setattr(bot, "say", said.append)
    monkeypatch.setattr(bot, "_speak", said.append)

    bot._read_screen_aloud_work()              # must not raise

    assert said and "sir" in said[0].lower()


def test_speech_summary_condenses_long_transcriptions():
    short = "All systems nominal."
    assert main.JarvisBot._speech_summary(short) == short
    long_text = ("First sentence lands here. " * 30).strip()
    out = main.JarvisBot._speech_summary(long_text, limit=240)
    assert len(out) <= 240
    assert out.endswith(".")                   # sentence-boundary cut


# ==========================================================================
# 2. Follow-cursor auto-park
# ==========================================================================

def _arm_follow_loop(bot, monkeypatch, clock, pos, steps):
    """Fake clock + fake mouse + recording stepping; loop won't reschedule."""
    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])

    fake_pg = types.ModuleType("pyautogui")
    fake_pg.position = lambda: pos["p"]
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pg)

    monkeypatch.setattr(bot, "_step_orb_toward",
                        lambda tx, ty: steps.append((tx, ty)))
    monkeypatch.setattr(bot.root, "after", lambda ms, fn=None: None)


def test_follow_loop_trails_then_auto_parks_after_12s(bot, monkeypatch):
    clock = {"t": 1000.0}
    pos = {"p": (500, 400)}
    steps = []
    _arm_follow_loop(bot, monkeypatch, clock, pos, steps)

    bot._follow_cursor = True
    bot._follow_home = (100, 100)
    bot._follow_parked = False
    bot._follow_idle_since = clock["t"]
    bot._follow_last_mouse = (500, 400)

    # 5 s idle: still trailing at the cursor offset (+34, -18).
    clock["t"] += 5.0
    bot._follow_cursor_loop()
    assert bot._follow_parked is False
    assert steps[-1] == (534, 382)

    # 12.5 s idle total: parked; eases gently back to the pre-follow home.
    clock["t"] += 7.5
    steps.clear()
    bot._follow_cursor_loop()
    assert bot._follow_parked is True
    assert steps == [(100, 100)]

    # While parked the orb ignores the cursor and keeps drifting home only.
    clock["t"] += 3.0
    steps.clear()
    bot._follow_cursor_loop()
    assert bot._follow_parked is True
    assert steps == [(100, 100)]


def test_follow_resumes_when_mouse_moves_again(bot, monkeypatch):
    clock = {"t": 0.0}
    pos = {"p": (500, 400)}
    steps = []
    _arm_follow_loop(bot, monkeypatch, clock, pos, steps)

    bot._follow_cursor = True
    bot._follow_home = (10, 10)
    bot._follow_last_mouse = (500, 400)
    bot._follow_idle_since = clock["t"]

    clock["t"] += 13.0                         # long enough to auto-park
    bot._follow_cursor_loop()
    assert bot._follow_parked is True

    clock["t"] += 1.0
    pos["p"] = (600, 420)                      # the hand comes back
    steps.clear()
    bot._follow_cursor_loop()
    assert bot._follow_parked is False
    assert steps[-1] == (634, 402)             # trailing again


def test_menu_or_drag_interaction_resumes_following(bot, monkeypatch):
    clock = {"t": 50.0}
    pos = {"p": (500, 400)}
    steps = []
    _arm_follow_loop(bot, monkeypatch, clock, pos, steps)

    bot._follow_cursor = True
    bot._follow_home = (10, 10)
    bot._follow_last_mouse = (500, 400)
    bot._follow_idle_since = clock["t"]
    clock["t"] += 12.5
    bot._follow_cursor_loop()
    assert bot._follow_parked is True

    bot._follow_resume()                       # what right-click/drag call
    assert bot._follow_parked is False
    steps.clear()
    bot._follow_cursor_loop()
    assert steps[-1] == (534, 382)             # trailing again


def test_resume_is_harmless_before_follow_enabled(bot):
    bot._follow_resume()                       # no attrs yet, no crash
    assert getattr(bot, "_follow_parked", False) is False


def test_step_orb_toward_clamps_target_within_screen(bot):
    geom = {}
    shim = types.SimpleNamespace(
        winfo_width=lambda: 56,
        winfo_height=lambda: 56,
        winfo_screenwidth=lambda: 800,
        winfo_screenheight=lambda: 600,
        winfo_x=lambda: 100,
        winfo_y=lambda: 100,
        geometry=lambda g: geom.update(g=g),
    )
    orig_root, bot.root = bot.root, shim
    try:
        main.JarvisBot._step_orb_toward(bot, 2000, 1500)
    finally:
        bot.root = orig_root
    nx, ny = (int(v) for v in geom["g"].split("+")[1:])
    assert nx == 100 + (744 - 100) // 2        # halfway toward clamped x
    assert ny == 100 + (544 - 100) // 2        # halfway toward clamped y
    assert 0 <= nx <= 800 - 56 and 0 <= ny <= 600 - 56


# ==========================================================================
# 3. Startup PTT toast honesty
# ==========================================================================

def _startup_toast(bot, monkeypatch):
    shown = []
    monkeypatch.setattr(bot, "_show_toast",
                        lambda text, duration=4000: shown.append(text))
    monkeypatch.setattr(bot, "_start_global_ptt", lambda: None)
    monkeypatch.setattr(bot.root, "mainloop", lambda: None)
    bot.run()
    assert shown, "startup cheatsheet toast vanished"
    return shown[0]


def _patch_ptt(monkeypatch, *, have, trusted, enabled):
    monkeypatch.setattr(hotkey_ptt, "HAVE_PYNPUT", have)
    monkeypatch.setattr(hotkey_ptt.GlobalPTT, "is_trusted",
                        staticmethod(lambda: trusted))
    monkeypatch.setattr(ptt_onboarding, "is_enabled", lambda: enabled)


def test_toast_ready_when_everything_available(bot, monkeypatch):
    _patch_ptt(monkeypatch, have=True, trusted=True, enabled=True)
    toast = _startup_toast(bot, monkeypatch)
    assert "Ctrl+Alt global PTT: ready" in toast


def test_toast_unavailable_without_accessibility_trust(bot, monkeypatch):
    _patch_ptt(monkeypatch, have=True, trusted=False, enabled=True)
    toast = _startup_toast(bot, monkeypatch)
    assert ("Ctrl+Alt global PTT: unavailable — double-click voice" in toast)
    assert "PTT: ready" not in toast


def test_toast_off_when_user_disabled_ptt(bot, monkeypatch):
    _patch_ptt(monkeypatch, have=True, trusted=True, enabled=False)
    toast = _startup_toast(bot, monkeypatch)
    assert "Ctrl+Alt global PTT: off — double-click voice" in toast


def test_toast_unavailable_without_pynput(bot, monkeypatch):
    _patch_ptt(monkeypatch, have=False, trusted=False, enabled=True)
    toast = _startup_toast(bot, monkeypatch)
    assert ("Ctrl+Alt global PTT: unavailable — double-click voice" in toast)


def test_toast_unavailable_when_probe_blows_up(bot, monkeypatch):
    monkeypatch.setitem(sys.modules, "hotkey_ptt", None)       # import fails
    toast = _startup_toast(bot, monkeypatch)
    assert ("Ctrl+Alt global PTT: unavailable — double-click voice" in toast)


def test_cheatsheet_keeps_core_lines(bot, monkeypatch):
    _patch_ptt(monkeypatch, have=True, trusted=True, enabled=True)
    toast = _startup_toast(bot, monkeypatch)
    assert "Double-click: 🎤 voice" in toast
    assert "Right-click: menu" in toast


# ==========================================================================
# 4. Pointer-halo clamping math (extracted helper, pure)
# ==========================================================================

def _with_display(monkeypatch, display):
    import multi_monitor
    monkeypatch.setattr(multi_monitor, "display_for_point",
                        lambda x, y: display)


def test_helper_without_module_matches_historic_placement(monkeypatch):
    monkeypatch.setitem(sys.modules, "multi_monitor", None)    # import dies
    assert main.JarvisBot._clamp_pointer_to_display(500, 400, 80) == \
        (500 - 40, 400 - 40)


def test_helper_without_display_match_is_historic(monkeypatch):
    _with_display(monkeypatch, None)
    assert main.JarvisBot._clamp_pointer_to_display(500, 400, 80) == (460, 360)


def test_helper_clamps_inside_owning_display(monkeypatch):
    _with_display(monkeypatch,
                  {"x": 0, "y": 0, "width": 1920, "height": 1080})
    # Right edge: halo would poke off-screen; pulled flush inside.
    assert main.JarvisBot._clamp_pointer_to_display(1900, 540, 80) == \
        (1920 - 80, 500)
    # Left/top edges too.
    assert main.JarvisBot._clamp_pointer_to_display(10, 8, 80) == (0, 0)
    # Comfortably interior: centered placement preserved.
    assert main.JarvisBot._clamp_pointer_to_display(960, 540, 80) == (920, 500)


def test_helper_offsets_onto_secondary_display(monkeypatch):
    _with_display(monkeypatch,
                  {"x": 1920, "y": 0, "width": 1920, "height": 1080})
    x, y = main.JarvisBot._clamp_pointer_to_display(1940, 30, 80)
    assert 1920 <= x <= 1920 + 1920 - 80       # never drifts onto display 1
    assert 0 <= y <= 1080 - 80


def test_helper_degrades_softly_on_ragged_display_dicts(monkeypatch):
    _with_display(monkeypatch, {"width": 0, "height": 0})      # useless bounds
    assert main.JarvisBot._clamp_pointer_to_display(500, 400, 80) == (460, 360)
    _with_display(monkeypatch, "not-a-dict")
    assert main.JarvisBot._clamp_pointer_to_display(500, 400, 80) == (460, 360)


def test_show_pointer_ui_requests_geometry_from_helper(bot, monkeypatch):
    import multi_monitor
    monkeypatch.setattr(multi_monitor, "display_for_point",
                        lambda x, y: {"x": 0, "y": 0,
                                      "width": 1920, "height": 1080})
    requested = []
    orig_geom = main.tk.Toplevel.geometry

    def spy_geom(self, g=None):
        if g:
            requested.append(g)
        return orig_geom(self, g)

    monkeypatch.setattr(main.tk.Toplevel, "geometry", spy_geom)
    try:
        bot._show_pointer_ui(1900, 540)
        assert bot._overlay is not None
        assert "80x80+1840+500" in requested   # clamped flush inside bounds
    finally:
        bot._hide_pointer()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
