"""QUICK BAR add-on for JarvisBot (part of the clicky enhancement pack).

A vertical strip of round one-click chips that pops out to the LEFT of the
orb.  Integration is fail-soft from bot_clicky.py:

    try:
        import bot_quick_bar; bot_quick_bar.attach(self)
    except Exception:
        pass

Contract:
    * attach(bot) is idempotent (guarded by ``bot._clicky_quickbar``).
    * attach appends exactly ONE item ("⚡  Quick Bar") to bot.menu at
      runtime (Menu.add_command append only - the menu is never rebuilt)
      and returns a controller with ``detach()``.
    * Auto-shows when the pointer enters the orb area and auto-hides after
      the pointer has left the bar for more than HIDE_DELAY_MS.
    * Owns only its own widgets: an overrideredirect topmost Toplevel.
      Nothing is ever bound to bot.canvas or any other bot widget.
    * Follows the orb with a POLL_MS after-loop; all winfo calls are
      wrapped so destroyed windows can never raise into the orb.

Pure logic (action table, positioning math, show/hide state machine) lives
in module-level structures/classes free of any tkinter dependency so tests
can exercise it without a display.
"""

import functools
import platform
import threading
import time

import tkinter as tk

# ==========================================================================
# Theme (matches the orb / menu palette in main.py)
# ==========================================================================

CYAN = "#00d4ff"
PANEL = "#161b22"
TEXT_FG = "#c9d1d9"
HOVER = "#1f6feb"
FONT = ("Helvetica Neue", 11)

CHIP_SIZE = 34          # diameter of each round chip, px
CHIP_PAD = 5            # vertical padding between chips, px
BAR_PAD = 8             # inner padding of the panel, px
FOOTER_H = 22           # hover-label strip height, px

POLL_MS = 400           # follow-the-orb / pointer-watch loop interval
HIDE_DELAY_MS = 1500    # hide after pointer stays outside this long
GAP_PX = 8              # horizontal gap between orb and bar
Y_OFFSET_PX = -40       # bar y relative to orb y
MARGIN_PX = 4           # never closer than this to any screen edge


# ==========================================================================
# Pure logic: action table
# ==========================================================================
# Each entry: (glyph, label, action)
#   action str      -> text command sent through the exact same pipeline as
#                      voice (_process on a daemon thread).  Every phrase
#                      below was verified offline against Brain.think():
#                      "what's the weather" -> JarvisBot._process shortcut
#                                             -> _get_weather() (main.py);
#                      "start a focus session" -> fx_start;
#                      "run a speed test"      -> nd_speed_test;
#                      "how's my day"          -> br_day_digest;
#                      "check my email"        -> ml_unread;
#                      "clipboard history"     -> ps_clipboard_history.
#   action callable -> f(bot) -> zero-arg callable, invoked directly on the
#                      UI thread (these bot methods thread internally).

def _call_voice(bot):
    return bot._voice_input


def _call_screen(bot):
    return bot._ask_about_screen


def _call_timer5(bot):
    return functools.partial(bot._start_timer, 5)


def _call_help(bot):
    return bot._show_help


QUICK_ACTIONS = [
    ("🎤", "Voice", _call_voice),
    ("📸", "Screen", _call_screen),
    ("⛅", "Weather", "what's the weather"),
    ("⏱", "Timer 5m", _call_timer5),
    ("🍅", "Pomodoro", "start a focus session"),
    ("🚀", "Speed Test", "run a speed test"),
    ("📅", "My Agenda", "how's my day"),
    ("✉️", "Mail", "check my email"),
    ("📋", "Clipboard", "clipboard history"),
    ("❓", "Help", _call_help),
]


# ==========================================================================
# Pure logic: positioning math
# ==========================================================================

def compute_bar_position(orb_x, orb_y, bar_w, bar_h,
                         screen_w, screen_h,
                         gap=GAP_PX, y_offset=Y_OFFSET_PX,
                         margin=MARGIN_PX):
    """Return the (x, y) for the bar's top-left corner.

    Preferred spot is left of the orb: ``(orb_x - bar_w - gap,
    orb_y + y_offset)``, clamped so the bar always stays fully on screen
    even when the orb hugs a screen edge.
    """
    x = orb_x - bar_w - gap
    y = orb_y + y_offset
    x = max(margin, min(x, screen_w - bar_w - margin))
    y = max(margin, min(y, screen_h - bar_h - margin))
    return x, y


# ==========================================================================
# Pure logic: show/hide state machine (no tkinter)
# ==========================================================================

class BarState:
    """Show/hide state machine for the quick bar.

    States:
        HIDDEN  bar not visible
        SHOWN   bar visible, pointer may be anywhere
        WAITING bar visible but pointer left it; hides after delay_ms

    Methods return an action string ('show' | 'hide' | 'watch') or None so
    the tk layer just executes what it is told.
    """

    HIDDEN = "hidden"
    SHOWN = "shown"
    WAITING = "waiting"

    def __init__(self, delay_ms=HIDE_DELAY_MS):
        self.state = self.HIDDEN
        self.delay_ms = delay_ms
        self.left_at_ms = None

    def request_show(self):
        """Pointer entered the orb or the bar."""
        self.left_at_ms = None
        if self.state != self.SHOWN:
            self.state = self.SHOWN
            return "show"
        return None

    # alias used by the <Enter> bindings
    bar_entered = request_show

    def bar_left(self, now_ms):
        """Pointer left the bar; start (or keep) the hide countdown."""
        if self.state == self.SHOWN:
            self.state = self.WAITING
            self.left_at_ms = now_ms
            return "watch"
        if self.state == self.WAITING:
            return "watch"
        return None

    def tick(self, now_ms):
        """Called periodically; returns 'hide' once the countdown expired."""
        if (self.state == self.WAITING and self.left_at_ms is not None
                and now_ms - self.left_at_ms >= self.delay_ms):
            return self.force_hide()
        return None

    def force_hide(self):
        """Immediate hide (menu toggle on visible bar, chip clicked...)."""
        was_visible = self.state != self.HIDDEN
        self.state = self.HIDDEN
        self.left_at_ms = None
        return "hide" if was_visible else None

    def toggle(self):
        """Menu-item flip: hidden/waiting -> show, shown -> hide."""
        if self.state == self.SHOWN:
            return self.force_hide()
        return self.request_show()


# ==========================================================================
# Tk layer: controller + chips window
# ==========================================================================

def _now_ms():
    return time.monotonic() * 1000.0


class QuickBarController:
    """Owns the chips Toplevel and its after-loops. Fail-soft throughout."""

    def __init__(self, bot):
        self.bot = bot
        self.state_machine = BarState(HIDE_DELAY_MS)
        self._win = None
        self._footer = None
        self._chips = []          # (canvas, oval_id, glyph_id, action, label)
        self._after_id = None
        self._hover_depth = 0
        self._detached = False
        self._last_geom = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self):
        try:
            self._schedule_tick()
        except Exception:
            self._after_id = None

    def detach(self):
        """Destroy our Toplevel, cancel after-loops, drop the guard attr."""
        self._detached = True
        try:
            if self._after_id is not None:
                self.bot.root.after_cancel(self._after_id)
        except Exception:
            pass
        self._after_id = None
        try:
            if self._win is not None:
                self._win.destroy()
        except Exception:
            pass
        self._win = None
        self._chips = []
        try:
            setattr(self.bot, "_clicky_quickbar", None)
        except Exception:
            pass

    def toggle(self):
        """Bound to the '⚡  Quick Bar' menu item."""
        act = self.state_machine.toggle()
        try:
            if act == "show":
                self._show_bar()
            elif act == "hide":
                self._hide_bar()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # polling loop: orb-hover auto-show, hide countdown, follow the orb
    # ------------------------------------------------------------------
    def _schedule_tick(self):
        if self._detached:
            return
        try:
            self._after_id = self.bot.root.after(POLL_MS, self._tick)
        except Exception:
            self._after_id = None

    def _tick(self):
        self._after_id = None
        try:
            self._tick_body()
        except Exception:
            pass
        finally:
            self._schedule_tick()

    def _tick_body(self):
        now = _now_ms()

        # auto-show when the pointer enters the orb area (we cannot bind to
        # bot.canvas, so the pointer position is polled instead)
        pos = self._pointer_pos()
        if pos is not None and self._inside_orb(*pos):
            if self.state_machine.request_show() == "show":
                self._show_bar()

        # auto-hide countdown while the pointer stays away
        if self.state_machine.tick(now) == "hide":
            self._hide_bar()

        # follow the orb around
        if self.state_machine.state == BarState.SHOWN:
            self._reposition()

    def _pointer_pos(self):
        try:
            root = self.bot.root
            px = root.winfo_pointerx()
            py = root.winfo_pointery()
            if px <= 0 and py <= 0:
                return None
            return px, py
        except Exception:
            return None

    def _inside_orb(self, px, py):
        try:
            ox = self.bot.root.winfo_x()
            oy = self.bot.root.winfo_y()
        except Exception:
            return False
        size = getattr(self.bot, "ORB_SIZE", 56)
        return ox <= px <= ox + size and oy <= py <= oy + size

    def _reposition(self):
        win = self._ensure_window()
        if win is None:
            return
        try:
            try:
                win.update_idletasks()
                w = win.winfo_reqwidth()
                h = win.winfo_reqheight()
            except Exception:
                w, h = self._bar_size()
            x, y = self._target_position(w, h)
            mapped = False
            try:
                mapped = bool(win.winfo_ismapped())
            except Exception:
                pass
            geom = "+%d+%d" % (x, y)
            if geom != self._last_geom or not mapped:
                self._last_geom = geom
                win.geometry("%dx%d%s" % (w, h, geom))
        except Exception:
            pass

    def _target_position(self, w=None, h=None):
        sw = self.bot.root.winfo_screenwidth()
        sh = self.bot.root.winfo_screenheight()
        if w is None or h is None:
            w, h = self._bar_size()
        return compute_bar_position(
            self.bot.root.winfo_x(), self.bot.root.winfo_y(),
            w, h, sw, sh)

    def _bar_size(self):
        n = len(QUICK_ACTIONS)
        w = CHIP_SIZE + 2 * BAR_PAD + 2
        h = 2 * BAR_PAD + n * (CHIP_SIZE + CHIP_PAD) + FOOTER_H
        return w, h

    # ------------------------------------------------------------------
    # window construction
    # ------------------------------------------------------------------
    def _ensure_window(self):
        if self._win is not None:
            return self._win
        try:
            win = tk.Toplevel(self.bot.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="black")
            if platform.system() == "Windows":
                try:
                    win.wm_attributes("-transparentcolor", "black")
                except Exception:
                    pass
            frame = tk.Frame(win, bg=PANEL)
            frame.pack(fill="both", expand=True)
            self._footer = tk.Label(frame, text="", bg=PANEL, fg=TEXT_FG,
                                    font=("Helvetica Neue", 9))
            for glyph, label, action in QUICK_ACTIONS:
                self._make_chip(frame, glyph, label, action)
            self._footer.pack(side="bottom", pady=(0, 2))

            # Enter/Leave tracking on OUR OWN widgets only.  Every child is
            # bound too so moving between chips does not count as leaving;
            # the depth counter only reaches zero when the pointer truly
            # exits the bar.
            self._bind_hover(win)
            self._bind_hover(frame)
            for canvas, _oval, _glyph, _action, _label in self._chips:
                self._bind_hover(canvas)

            win.withdraw()
            self._win = win
        except Exception:
            self._win = None
        return self._win

    def _bind_hover(self, widget):
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")

    def _on_enter(self, _event=None):
        self._hover_depth += 1
        try:
            if self.state_machine.bar_entered() == "show":
                self._show_bar()
        except Exception:
            pass

    def _on_leave(self, _event=None):
        self._hover_depth = max(0, self._hover_depth - 1)
        if self._hover_depth == 0:
            try:
                self.state_machine.bar_left(_now_ms())
            except Exception:
                pass

    def _make_chip(self, parent, glyph, label, action):
        d = CHIP_SIZE
        cv = tk.Canvas(parent, width=d, height=d, bg=PANEL,
                       highlightthickness=0)
        oval = cv.create_oval(2, 2, d - 2, d - 2, fill="#0d1117",
                              outline=PANEL, width=2)
        gl = cv.create_text(d // 2, d // 2, text=glyph, fill=TEXT_FG,
                            font=("Helvetica Neue", 13))

        def _enter(_e, cv=cv, oval=oval, label=label):
            try:
                cv.itemconfig(oval, outline=CYAN, width=2)
                if self._footer is not None:
                    self._footer.config(text=label)
            except Exception:
                pass
            self._on_enter()

        def _leave(_e, cv=cv, oval=oval):
            try:
                cv.itemconfig(oval, outline=PANEL, width=2)
            except Exception:
                pass
            self._on_leave()

        cv.bind("<Enter>", _enter, add="+")
        cv.bind("<Leave>", _leave, add="+")
        cv.bind("<Button-1>",
                lambda _e, a=action, l=label: self._activate(a, l), add="+")
        cv.pack(padx=(BAR_PAD, BAR_PAD), pady=(BAR_PAD, 0))
        self._chips.append((cv, oval, gl, action, label))

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _activate(self, action, label):
        """Run a chip: callables run directly on the UI thread; text
        commands go through the same off-main-thread path as voice."""
        try:
            if isinstance(action, str):
                bot = self.bot
                threading.Thread(
                    target=self._run_text_cmd, args=(bot, action),
                    daemon=True).start()
            else:
                fn = action(self.bot)
                if callable(fn):
                    fn()
        except Exception as exc:
            print("WARNING: quick bar chip %r failed: %s" % (label, exc))
        finally:
            try:
                if self.state_machine.force_hide() == "hide":
                    self._hide_bar()
            except Exception:
                pass

    @staticmethod
    def _run_text_cmd(bot, cmd):
        """Mirror JarvisBot._do_voice: heavy work on a daemon thread; every
        UI touch inside _process is marshalled through bot._ui itself."""
        try:
            bot._process(cmd)
        except Exception as exc:
            print("WARNING: quick bar command %r failed: %s" % (cmd, exc))

    # ------------------------------------------------------------------
    # visibility
    # ------------------------------------------------------------------
    def _show_bar(self):
        win = self._ensure_window()
        if win is None:
            return
        self._reposition()
        try:
            win.deiconify()
            win.lift()
        except Exception:
            pass

    def _hide_bar(self):
        self._hover_depth = 0
        win = self._win
        if win is None:
            return
        try:
            win.withdraw()
        except Exception:
            pass


def attach(bot):
    """Attach the quick bar to JarvisBot. Idempotent and fail-soft.

    Appends ONE '⚡  Quick Bar' toggle item to bot.menu (runtime append
    only) and stores the controller on ``bot._clicky_quickbar``.
    Returns the controller; every tk touch inside it fails soft.
    """
    existing = getattr(bot, "_clicky_quickbar", None)
    if existing is not None:
        return existing
    controller = QuickBarController(bot)
    setattr(bot, "_clicky_quickbar", controller)
    try:
        bot.menu.add_command(label="⚡  Quick Bar", command=controller.toggle)
    except Exception as exc:
        print("WARNING: quick bar menu item failed: %s" % exc)
    controller.start()
    return controller
