"""REPLY BUBBLE add-on for JarvisBot.

A speech-bubble panel that floats left of the orb and shows JARVIS's last
reply with quick actions (Copy / Replay / Dismiss). It hooks ``bot.say``
without altering its behaviour: the original bound method is kept intact,
called first, then the bubble refreshes.

Integration is fail-soft via bot_clicky:

    controller = bot_reply_bubble.attach(bot)
    ...
    controller.detach()   # restores bot.say, kills windows + after-loops

Pure text logic lives in module-level functions (``wrap_at``, ``format_reply``,
``hover_action``, ``should_autohide``, ``make_say_wrapper``) so it can be
tested without any tkinter involvement.
"""

import platform

# --- tunables ---------------------------------------------------------------
BUBBLE_WRAP_CHARS = 42        # soft wrap width for reply text
BUBBLE_MAX_LINES = 6          # more lines than this -> ellipsis
FOLLOW_INTERVAL_MS = 400      # how often the bubble re-docks to the orb
BUBBLE_X_GAP_PX = 8           # horizontal gap between bubble right edge and orb
BUBBLE_Y_OFFSET_PX = 120      # vertical offset below the orb top (clears bar)
AUTOHIDE_MS = 12000           # hide after 12s unless hovered
FADE_STEP_MS = 40             # fade-in tick
FADE_STEP_ALPHA = 0.15        # alpha gained per tick
FADE_START_ALPHA = 0.45       # fresh replies start semi-transparent
FADE_MAX_ALPHA = 0.96         # never fully opaque (matches toast style)
FALLBACK_WIDTH_PX = 320       # assumed width before the window is mapped
FALLBACK_HEIGHT_PX = 150      # assumed height before the window is mapped
MIN_SCREEN_GAP_PX = 8         # never park the bubble off-screen edge
ELLIPSIS = "..."
NO_REPLY_TEXT = "(no reply)"

# --- theme ------------------------------------------------------------------
CYAN = "#00d4ff"
PANEL_BG = "#161b22"
FG = "#c9d1d9"
ACCENT = "#1f6feb"
FONT_FAMILY = "Helvetica Neue"

_HOVER_ACTIONS = {"<Enter>": "cancel", "<Leave>": "restart"}


# ============================================================================
# Pure logic (no tkinter)
# ============================================================================
def wrap_at(text, width=BUBBLE_WRAP_CHARS, max_lines=BUBBLE_MAX_LINES):
    """Word-wrap *text* at *width* chars; hard-split overlong words;
    keep at most *max_lines* lines, ending with an ellipsis when trimmed."""
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for para in text.split("\n"):
        lines.extend(_wrap_paragraph(para, width))
    lines = [ln for ln in lines]
    if not lines:
        return ""
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    room = max(0, width - len(ELLIPSIS))
    tail = kept[-1]
    if len(tail) + len(ELLIPSIS) > width:
        kept[-1] = tail[:room].rstrip() + ELLIPSIS
    else:
        kept[-1] = tail + ELLIPSIS
    return "\n".join(kept)


def _wrap_paragraph(para, width):
    words = para.split()
    if not words:
        return [""]
    lines = []
    cur = ""
    for word in words:
        while len(word) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:width])
            word = word[width:]
        cand = word if not cur else cur + " " + word
        if len(cand) <= width:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or [""]


def format_reply(text):
    """Normalise a raw reply into bubble-ready display text."""
    s = NO_REPLY_TEXT if text is None else str(text)
    s = s.strip()
    if not s:
        s = NO_REPLY_TEXT
    return wrap_at(s)


def hover_action(event_name):
    """Map a hover event to the autohide-timer action ('cancel'/'restart'/None)."""
    return _HOVER_ACTIONS.get(event_name)


def should_autohide(visible=True, hovered=False):
    """True only when the bubble is showing AND the pointer is elsewhere."""
    return bool(visible) and not hovered


def make_say_wrapper(original_say, show_fn):
    """Build the hooked ``say``.

    The returned callable invokes *original_say* first (always, even if the
    bubble layer explodes), then pushes the formatted reply through
    *show_fn*. An exception inside show_fn can never break speaking.
    """
    def wrapped(text, *args, **kwargs):
        result = original_say(text, *args, **kwargs)
        try:
            show_fn(format_reply(text))
        except Exception:
            pass
        return result

    wrapped.__name__ = getattr(original_say, "__name__", "say")
    wrapped.__wrapped_say__ = original_say
    return wrapped


def unwrap_say(current, wrapper, original):
    """Restore *original* say through (possibly nested) wrappers."""
    if current is wrapper:
        return original
    node = current
    seen = set()
    while id(node) not in seen and hasattr(node, "__wrapped_say__"):
        seen.add(id(node))
        nxt = node.__wrapped_say__
        if nxt is wrapper:
            node.__wrapped_say__ = original
            break
        node = nxt
    return current


# ============================================================================
# Tk layer
# ============================================================================
class ReplyBubbleController:
    """Owns the bubble Toplevel(s), the follow loop and the say hook."""

    def __init__(self, bot, original_say):
        self._bot = bot
        self._original_say = original_say
        self._wrapper = None
        self._win = None
        self._body_lbl = None
        self._stopped = False
        self._visible = False
        self._dragging = False
        self.last_raw = ""
        self.last_formatted = ""
        self._autohide_id = None
        self._follow_id = None
        self._fade_id = None
        self._grab_dx = 0
        self._grab_dy = 0
        self._drag_dx = 0
        self._drag_dy = 0
        self._drag_width = FALLBACK_WIDTH_PX
        try:
            self._wrapper = make_say_wrapper(original_say, self._on_said)
            bot.say = self._wrapper
        except Exception:
            self._wrapper = None
        try:
            self._build_window()
        except Exception:
            self._win = None
        self._start_follow()

    # -- say hook -----------------------------------------------------------
    def _on_said(self, formatted):
        raw = getattr(self._bot, "last_reply", "")
        self.last_raw = raw if isinstance(raw, str) and raw.strip() \
            else formatted.replace("\n", " ")
        self.last_formatted = formatted
        self._marshal(self._show_sync)

    def _marshal(self, fn):
        ui = getattr(self._bot, "_ui", None)
        if callable(ui):
            try:
                ui(fn)
                return
            except Exception:
                pass
        try:
            fn()
        except Exception:
            pass

    # -- window plumbing ----------------------------------------------------
    def _alive(self, win):
        try:
            return win is not None and bool(win.winfo_exists())
        except Exception:
            return False

    def _root(self):
        root = getattr(self._bot, "root", None)
        return root if hasattr(root, "after") else None

    def _after(self, ms, fn):
        root = self._root()
        if root is None or self._stopped:
            return None
        try:
            return root.after(ms, fn)
        except Exception:
            return None

    def _cancel_after(self, after_id):
        if after_id is None:
            return
        root = self._root()
        if root is None:
            return
        try:
            root.after_cancel(after_id)
        except Exception:
            pass

    def _orb_xy(self):
        root = self._root()
        if root is None:
            return None, None
        try:
            return root.winfo_x(), root.winfo_y()
        except Exception:
            return None, None

    def _build_window(self):
        if self._root() is None:
            return False
        import tkinter as tk
        win = tk.Toplevel(self._bot.root)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        win.configure(bg="black")
        if platform.system() == "Windows":
            try:
                win.attributes("-transparentcolor", "black")
            except Exception:
                pass
        outer = tk.Frame(win, bg="black")
        outer.pack(fill="both", expand=True, padx=3, pady=3)
        panel = tk.Frame(outer, bg=PANEL_BG, highlightthickness=1,
                         highlightbackground=CYAN)
        panel.pack(fill="both", expand=True)
        header = tk.Frame(panel, bg=ACCENT)
        header.pack(fill="x")
        tag = tk.Label(header, text="JARVIS", bg=ACCENT, fg="white",
                       font=(FONT_FAMILY, 8, "bold"), padx=6, pady=2)
        tag.pack(side="left")
        body = tk.Label(panel, text=self.last_formatted or NO_REPLY_TEXT,
                        bg=PANEL_BG, fg=FG, font=(FONT_FAMILY, 11),
                        justify="left", anchor="w",
                        wraplength=FALLBACK_WIDTH_PX - 28, padx=12, pady=8)
        body.pack(fill="both", expand=True)
        self._body_lbl = body
        btnrow = tk.Frame(panel, bg=PANEL_BG)
        btnrow.pack(fill="x", pady=(0, 6))
        for label, cmd in (("Copy", self._copy), ("Replay", self._replay),
                           ("Dismiss", self._dismiss)):
            b = tk.Button(btnrow, text=label, command=cmd, relief="flat",
                          bd=0, bg=PANEL_BG, fg=CYAN, activebackground=ACCENT,
                          activeforeground="white",
                          font=(FONT_FAMILY, 9))
            b.pack(side="right", padx=4)
        for wdg in (header, tag):
            wdg.bind("<Button-1>", self._drag_start)
            wdg.bind("<B1-Motion>", self._drag_move)
            wdg.bind("<ButtonRelease-1>", self._drag_end)
        for wdg in (outer, panel, header, tag, body, btnrow):
            wdg.bind("<Enter>", self._on_enter)
            wdg.bind("<Leave>", self._on_leave)
        self._win = win
        try:
            win.withdraw()
        except Exception:
            pass
        return True

    def _ensure_window(self):
        if self._alive(self._win):
            return True
        self._win = None
        try:
            return self._build_window()
        except Exception:
            return False

    def _refresh_content(self):
        if self._body_lbl is not None:
            try:
                self._body_lbl.config(text=self.last_formatted)
            except Exception:
                pass

    # -- positioning ----------------------------------------------------------
    def _start_follow(self):
        if self._follow_id is None:
            self._follow_id = self._after(FOLLOW_INTERVAL_MS, self._follow_tick)

    def _follow_tick(self):
        self._follow_id = None
        if self._stopped:
            return
        if not self._visible or not self._alive(self._win):
            self._follow_id = self._after(FOLLOW_INTERVAL_MS, self._follow_tick)
            return
        if not self._dragging:
            self._move_next_to_orb()
        self._follow_id = self._after(FOLLOW_INTERVAL_MS, self._follow_tick)

    def _move_next_to_orb(self):
        if self._stopped or not self._visible:
            return
        ox, oy = self._orb_xy()
        win = self._win
        if ox is None or not self._alive(win):
            return
        try:
            w = win.winfo_width()
            h = win.winfo_height()
        except Exception:
            w = h = 1
        if w <= 1:
            w = FALLBACK_WIDTH_PX
        if h <= 1:
            h = FALLBACK_HEIGHT_PX
        x = ox - w - BUBBLE_X_GAP_PX + self._drag_dx
        y = oy + BUBBLE_Y_OFFSET_PX + self._drag_dy
        x = max(MIN_SCREEN_GAP_PX, x)
        y = max(MIN_SCREEN_GAP_PX, y)
        y = self._clear_siblings(x, y, w)
        try:
            win.geometry("+%d+%d" % (int(x), int(y)))
        except Exception:
            pass

    def _clear_siblings(self, x, y, w):
        """Slide below any visible sibling clicky window sharing our column."""
        for attr in ("_clicky_quickbar", "_clicky_status"):
            sib = getattr(getattr(self._bot, attr, None), "_win", None)
            if sib is None:
                continue
            try:
                if not sib.winfo_viewable():
                    continue
                bottom = sib.winfo_y() + sib.winfo_height() + BUBBLE_X_GAP_PX
                if y < bottom and x < sib.winfo_x() + sib.winfo_width() \
                        and sib.winfo_x() < x + w:
                    y = max(y, bottom)
            except Exception:
                continue
        try:
            sh = self._bot.root.winfo_screenheight()
            y = min(y, max(MIN_SCREEN_GAP_PX, sh - FALLBACK_HEIGHT_PX))
        except Exception:
            pass
        return y

    # -- show / hide / fade ---------------------------------------------------
    def _show_sync(self):
        if self._stopped:
            return
        try:
            if not self._ensure_window():
                return
            self._refresh_content()
            self._drag_dx = 0
            self._drag_dy = 0
            self._move_next_to_orb()
            try:
                self._win.deiconify()
                self._win.lift()
            except Exception:
                pass
            self._visible = True
            self._fade_in()
            self._after(FADE_STEP_MS * 2, self._move_next_to_orb)
            self._arm_autohide()
        except Exception:
            pass

    def _fade_in(self):
        self._cancel_after(self._fade_id)
        self._fade_id = None
        state = {"alpha": FADE_START_ALPHA}

        def _step():
            self._fade_id = None
            if self._stopped or not self._alive(self._win):
                return
            state["alpha"] = min(FADE_MAX_ALPHA,
                                 state["alpha"] + FADE_STEP_ALPHA)
            try:
                self._win.attributes("-alpha", state["alpha"])
            except Exception:
                return
            if state["alpha"] < FADE_MAX_ALPHA:
                self._fade_id = self._after(FADE_STEP_MS, _step)

        _step()

    # -- autohide -------------------------------------------------------------
    def _arm_autohide(self):
        self._cancel_after(self._autohide_id)
        self._autohide_id = self._after(AUTOHIDE_MS, self._autohide_tick)

    def _cancel_autohide(self):
        self._cancel_after(self._autohide_id)
        self._autohide_id = None

    def _autohide_tick(self):
        self._autohide_id = None
        if should_autohide(self._visible, self._dragging):
            self.hide()

    def _on_enter(self, _event=None):
        if hover_action("<Enter>") == "cancel":
            self._cancel_autohide()

    def _on_leave(self, _event=None):
        if hover_action("<Leave>") == "restart":
            self._arm_autohide()

    def hide(self):
        self._visible = False
        self._cancel_autohide()
        self._cancel_after(self._fade_id)
        self._fade_id = None
        if self._alive(self._win):
            try:
                self._win.withdraw()
            except Exception:
                pass

    def _dismiss(self):
        self.hide()

    # -- drag (header only) -----------------------------------------------------
    def _drag_start(self, event):
        try:
            self._grab_dx = event.x_root - self._win.winfo_x()
            self._grab_dy = event.y_root - self._win.winfo_y()
            w = self._win.winfo_width()
            self._drag_width = w if w > 1 else FALLBACK_WIDTH_PX
            self._dragging = True
            self._on_enter()
        except Exception:
            self._dragging = False

    def _drag_move(self, event):
        if not self._dragging:
            return
        try:
            nx = event.x_root - self._grab_dx
            ny = event.y_root - self._grab_dy
            ox, oy = self._orb_xy()
            base_x = (ox - self._drag_width - BUBBLE_X_GAP_PX) if ox is not None else nx
            base_y = (oy + BUBBLE_Y_OFFSET_PX) if oy is not None else ny
            self._drag_dx = nx - base_x
            self._drag_dy = ny - base_y
            self._win.geometry("+%d+%d" % (max(0, int(nx)), max(0, int(ny))))
        except Exception:
            pass

    def _drag_end(self, _event=None):
        self._dragging = False
        self._on_leave()

    # -- button actions ---------------------------------------------------------
    def _copy(self):
        text = self.last_raw or getattr(self._bot, "last_reply", "") \
            or self.last_formatted
        if not text:
            return
        try:
            import pyperclip
            pyperclip.copy(text)
            return
        except Exception:
            pass
        try:
            root = self._root()
            if root is not None:
                root.clipboard_clear()
                root.clipboard_append(text)
        except Exception:
            pass

    def _replay(self):
        text = getattr(self._bot, "last_reply", "") or self.last_raw
        speak = getattr(self._bot, "_speak", None)
        if callable(speak) and text:
            try:
                speak(text)
            except Exception:
                pass

    # -- teardown ---------------------------------------------------------------
    def detach(self):
        self._stopped = True
        self._visible = False
        self._cancel_autohide()
        self._cancel_after(self._fade_id)
        self._fade_id = None
        self._cancel_after(self._follow_id)
        self._follow_id = None
        self._restore_say()
        if self._alive(self._win):
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        try:
            delattr(self._bot, "_clicky_bubble")
        except Exception:
            pass

    def _restore_say(self):
        try:
            cur = getattr(self._bot, "say", None)
            restored = unwrap_say(cur, self._wrapper, self._original_say)
            if restored is not cur:
                self._bot.say = restored
        except Exception:
            pass


def attach(bot):
    """Hook the bubble onto *bot* (idempotent). Returns the controller."""
    existing = getattr(bot, "_clicky_bubble", None)
    if existing is not None and hasattr(existing, "detach"):
        return existing
    original = getattr(bot, "say", None)
    if not callable(original):
        return None
    controller = ReplyBubbleController(bot, original)
    bot._clicky_bubble = controller
    return controller
