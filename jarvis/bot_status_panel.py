"""STATUS PANEL add-on for JarvisBot's floating orb (bot_clicky pack member).

Adds a single runtime item ("📊  Status Panel") to ``bot.menu`` that toggles
a borderless pop-out showing live status rows (timers, focus/pomodoro,
power, network, todos, last command). Every row whose command routed
through ``Brain.think`` offline is clickable: the click dispatches the text
command through the bot's normal pipeline (``voice_history.append`` +
``bot._process``) on a daemon worker thread, mirroring the ``_do_voice``
convention so the tkinter main loop never blocks.

Layout contract:
    - pure logic: ``gather_status(bot)`` -> ordered
      ``(icon, label, value, cmd_or_None)`` tuples and
      ``render_rows(rows)`` -> display strings. Zero tkinter here, so both
      are unit-testable headless.
    - UI: one ``Toplevel(overrideredirect=True)`` kept topmost, docked to
      the left of the orb (position polled every 400 ms), values refreshed
      every 2000 ms from a background gatherer thread. Refresh/follow
      ``after`` loops are cancelled on close/detach and every window
      operation is race-guarded against destruction mid-flight.

Fail-soft everywhere: a broken panel can never take down the orb.
Integration (handled by bot_clicky.attach):
    import bot_status_panel; ctl = bot_status_panel.attach(bot)
    ctl.detach()
Idempotency guard: ``bot._clicky_status``.
"""

from __future__ import annotations

import json
import os
import socket
import threading

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency
    psutil = None

# Theme (matches the orb/menu palette in main.py)
CYAN = "#00d4ff"
BG = "#161b22"
FG = "#c9d1d9"
MUTED = "#8b949e"
ACCENT = "#1f6feb"
FONT = "Helvetica Neue"

MENU_LABEL = "📊  Status Panel"
REFRESH_MS = 2000
FOLLOW_MS = 400
PANEL_W = 300

NET_PROBE = ("1.1.1.1", 443)
NET_TIMEOUT_S = 1.0
EMPTY = "—"
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "jarvis_memory.json")

_PHASE_LABELS = {
    "work": "deep work",
    "short_break": "short break",
    "long_break": "long break",
}

_ROW_TEMPLATE = (
    ("⏱", "Timers", None),
    ("🍅", "Focus", "focus status"),
    ("🔋", "Power", None),
    ("🌐", "Net", "run a speed test"),
    ("✅", "Todos", "show my todos"),
    ("🎙", "Last cmd", None),
)


# ==========================================================================
# Pure logic (NO tkinter - unit-testable headless)
# ==========================================================================

def _timers_value(bot) -> str:
    """Count active timers; show summed minutes when intervals are known."""
    try:
        timers = list(getattr(bot, "_active_timers", None) or [])
    except Exception:
        timers = []
    total_s = 0.0
    known = False
    for t in timers:
        interval = getattr(t, "interval", None)
        if isinstance(interval, (int, float)) and interval > 0:
            known = True
            total_s += float(interval)
    if not timers:
        return "0"
    if known:
        return "%d · %dm" % (len(timers), int(round(total_s / 60.0)))
    return str(len(timers))


def _focus_value() -> str:
    """Live pomodoro snapshot via focus_pomodoro_brain.get_manager()."""
    try:
        import focus_pomodoro_brain
        snap = focus_pomodoro_brain.get_manager().status() or {}
    except Exception:
        return "idle"
    try:
        if not snap.get("running"):
            return "idle"
        phase = _PHASE_LABELS.get(snap.get("phase") or "", snap.get("phase") or "?")
        remaining = int(snap.get("remaining") or 0)
        mins, secs = divmod(max(0, remaining), 60)
        return "%s · %d:%02d" % (phase, mins, secs)
    except Exception:
        return "idle"


def _power_value() -> str:
    """Battery percent/plug state + CPU load; psutil strictly optional."""
    if psutil is None:
        return "n/a"
    parts = []
    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            pct = int(round(float(getattr(bat, "percent", 0.0))))
            glyph = "⚡" if getattr(bat, "power_plugged", None) else ""
            parts.append("%d%%%s" % (pct, glyph))
    except Exception:
        pass
    try:
        cpu = psutil.cpu_percent(interval=None)
        parts.append("CPU %d%%" % int(round(float(cpu))))
    except Exception:
        pass
    return " · ".join(parts) if parts else "n/a"


def _net_value() -> str:
    """1 s-max TCP probe to 1.1.1.1:443 -> Online/Offline."""
    sock = None
    try:
        sock = socket.create_connection(NET_PROBE, timeout=NET_TIMEOUT_S)
        return "Online"
    except Exception:
        return "Offline"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def _todos_value(path: str = MEMORY_FILE) -> str:
    """Count incomplete todos in jarvis_memory.json; 0 when unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        todos = data.get("todos") if isinstance(data, dict) else None
        if not isinstance(todos, list):
            return "none"
        n = sum(1 for t in todos
                if isinstance(t, dict) and not t.get("done"))
        return "%d open" % n if n else "none"
    except Exception:
        return "none"


def _last_cmd_value(bot) -> str:
    """Most recent voice/command, or the em-dash placeholder."""
    try:
        hist = getattr(bot, "voice_history", None)
        last = hist[-1] if hist else None
    except Exception:
        last = None
    if not last:
        return EMPTY
    text = str(last)
    return text[:28] + "…" if len(text) > 29 else text


def gather_status(bot) -> list:
    """Ordered ``(icon, label, value, cmd_or_None)`` snapshots.

    ``cmd`` is a text command that verifiably routes through the brain
    (checked offline against ``Brain.think``); ``None`` rows are inert.
    """
    rows = [
        ("⏱", "Timers", _timers_value(bot), None),
        ("🍅", "Focus", _focus_value(), "focus status"),
        ("🔋", "Power", _power_value(), None),
        ("🌐", "Net", _net_value(), "run a speed test"),
        ("✅", "Todos", _todos_value(), "show my todos"),
        ("🎙", "Last cmd", _last_cmd_value(bot), None),
    ]
    return rows


def render_rows(rows) -> list:
    """Format gathered rows into aligned single-line display strings."""
    out = []
    for icon, label, value, _cmd in rows or []:
        out.append(("%s  %-9s%s" % (icon, label, value)).rstrip())
    return out


# ==========================================================================
# Command dispatch (mirrors _do_voice/_process conventions in main.py)
# ==========================================================================

def _dispatch_text(bot, cmd) -> None:
    """Run a text command through the bot pipeline OFF the main thread."""
    if not cmd:
        return

    def _worker():
        try:
            hist = getattr(bot, "voice_history", None)
            if hist is not None:
                hist.append(cmd)
        except Exception:
            pass
        try:
            process = getattr(bot, "_process", None)
            if callable(process):
                process(cmd)
            else:
                say = getattr(bot, "say", None)
                if callable(say):
                    say(str(cmd))
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True,
                     name="jarvis-status-panel-cmd").start()


# ==========================================================================
# Panel UI (tkinter imported lazily so headless import stays clean)
# ==========================================================================

class StatusPanel:
    """Pop-out status window bound to a JarvisBot instance."""

    def __init__(self, bot):
        self.bot = bot
        self._win = None
        self._vals = []
        self._aids = set()
        self._gen = 0

    # -- lifecycle ---------------------------------------------------------

    def toggle(self) -> None:
        try:
            if self._win is not None:
                self.close()
            else:
                self._open()
        except Exception:
            try:
                self.close()
            except Exception:
                pass

    def _open(self) -> None:
        if self._win is not None:
            return
        import tkinter as tk

        root = getattr(self.bot, "root", None)
        if root is None:
            return
        win = tk.Toplevel(root)
        self._win = win
        try:
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.attributes("-alpha", 0.96)
            win.configure(bg=BG)
            win.protocol("WM_DELETE_WINDOW", self.close)
            win.bind("<Escape>", lambda _e: self.close())

            head = tk.Frame(win, bg=BG)
            head.pack(fill="x", padx=12, pady=(8, 2))
            tk.Label(head, text="📊 JARVIS STATUS", bg=BG, fg=CYAN,
                     font=(FONT, 11, "bold")).pack(side="left")
            tk.Button(head, text="✕", command=self.close, bd=0,
                      bg=BG, fg=MUTED, activebackground=ACCENT,
                      activeforeground="white",
                      font=(FONT, 10, "bold")).pack(side="right")
            tk.Frame(win, height=1, bg=ACCENT).pack(fill="x", padx=10)

            body = tk.Frame(win, bg=BG)
            body.pack(fill="both", expand=True, padx=6, pady=(4, 8))
            self._vals = []
            for icon, label, cmd in _ROW_TEMPLATE:
                self._build_row(tk, body, icon, label, cmd)

            self._place(win)
            self._schedule(FOLLOW_MS, self._follow)
            self._schedule(REFRESH_MS, self._refresh)
            self._refresh()
        except Exception:
            self.close()

    def _build_row(self, tk, body, icon, label, cmd) -> None:
        row = tk.Frame(body, bg=BG,
                       cursor="hand2" if cmd else "arrow")
        row.pack(fill="x", pady=2, ipady=2)
        widgets = [
            tk.Label(row, text=icon, bg=BG, fg=CYAN,
                     font=(FONT, 12), width=2),
            tk.Label(row, text=label, bg=BG,
                     fg=FG if cmd else MUTED,
                     font=(FONT, 11), width=10, anchor="w"),
        ]
        val = tk.Label(row, text="…", bg=BG, fg=FG,
                       font=(FONT, 11), anchor="w")
        widgets.append(val)
        for w in widgets:
            w.pack(side="left", padx=(8, 0))
        self._vals.append(val)
        on_click = (lambda _e, c=cmd: self._clicked(c)) if cmd else \
                   (lambda _e: None)
        for w in [row] + widgets:
            w.bind("<Button-1>", on_click)
            if cmd:
                w.bind("<Enter>",
                       lambda _e, r=row, ws=[row] + widgets:
                       self._paint(r, ws, ACCENT))
                w.bind("<Leave>",
                       lambda _e, r=row, ws=[row] + widgets:
                       self._paint(r, ws, BG))

    @staticmethod
    def _paint(row, widgets, color) -> None:
        try:
            for w in widgets:
                w.configure(bg=color)
        except Exception:
            pass

    def _clicked(self, cmd) -> None:
        self.close()
        _dispatch_text(self.bot, cmd)

    def dispatch(self, cmd) -> None:
        """Public hook: send a text command through the bot pipeline."""
        _dispatch_text(self.bot, cmd)

    def close(self, *_args) -> None:
        self._gen += 1
        win, self._win = self._win, None
        self._vals = []
        if win is None:
            return
        for aid in list(self._aids):
            try:
                win.after_cancel(aid)
            except Exception:
                pass
        self._aids.clear()
        try:
            win.destroy()
        except Exception:
            pass

    def detach(self) -> None:
        try:
            self.close()
        except Exception:
            pass
        try:
            if getattr(self.bot, "_clicky_status", None) is self:
                self.bot._clicky_status = None
        except Exception:
            pass

    # -- loops (every callback re-checks the window still exists) ----------

    def _schedule(self, delay_ms, fn) -> None:
        win = self._win
        if win is None:
            return
        try:
            aid = win.after(delay_ms, fn)
            self._aids.add(aid)
        except Exception:
            pass

    def _place(self, win) -> None:
        try:
            ox = self.bot.root.winfo_x()
            oy = self.bot.root.winfo_y()
            win.geometry("+%d+%d" % (max(8, ox - PANEL_W - 14),
                                     max(8, oy)))
        except Exception:
            pass

    def _follow(self) -> None:
        win = self._win
        if win is None:
            return
        self._place(win)
        self._schedule(FOLLOW_MS, self._follow)

    def _refresh(self) -> None:
        win = self._win
        if win is None:
            return
        self._gen += 1
        gen = self._gen

        def _work():
            try:
                rows = gather_status(self.bot)
            except Exception:
                rows = []
            if gen != self._gen or self._win is None:
                return
            try:
                win.after(0, lambda: self._apply_rows(gen, rows))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True,
                         name="jarvis-status-gather").start()
        self._schedule(REFRESH_MS, self._refresh)

    def _apply_rows(self, gen, rows) -> None:
        if gen != self._gen or self._win is None:
            return
        for lbl, entry in zip(self._vals, rows):
            try:
                lbl.configure(text=str(entry[2]))
            except Exception:
                pass


# ==========================================================================
# Entry point (called by bot_clicky.attach)
# ==========================================================================

def attach(bot):
    """Attach the status panel to ``bot``; idempotent, fail-soft.

    Returns the controller (with ``.detach()``); attaching twice yields
    the same controller and never duplicates the menu item.
    """
    existing = getattr(bot, "_clicky_status", None)
    if existing is not None:
        return existing
    controller = StatusPanel(bot)
    try:
        bot._clicky_status = controller
    except Exception:
        pass
    try:
        menu = getattr(bot, "menu", None)
        if menu is not None:
            menu.add_command(label=MENU_LABEL, command=controller.toggle)
    except Exception as exc:
        print("WARNING: status panel menu append failed: %s" % exc)
    return controller
