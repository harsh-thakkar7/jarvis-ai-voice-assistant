"""COMMAND PALETTE add-on for JarvisBot's floating orb (bot_clicky pack member).

Adds a single runtime item ("⌘  Command Palette") to ``bot.menu`` that opens
a ⌘K-style launcher window listing every registered Brain skill name
(``bot._brain.skills``). A live filter box narrows the list using substring
scoring plus difflib fuzzy ranking; Up/Down move the selection (wrapping),
Enter runs the highlighted skill, Esc closes, and rows are clickable.

Running a command mirrors the ``_do_voice`` convention exactly: the chosen
trigger phrase goes through ``voice_history.append`` + ``bot._process`` on a
daemon worker thread, so the tkinter main loop never blocks. The generic
trigger phrase is derived PURELY from the skill name (``build_query``):
``ps_git_status`` -> ``"git status"`` when obviously mappable, otherwise an
input box prefilled with the raw skill name asks for the phrase.

Layout contract:
    - pure logic: ``gather_skills(bot)``, ``build_query(name)``,
      ``filter_rank(query, names)`` and ``SelectionModel``. Zero tkinter
      here, all unit-testable headless.
    - UI: one ``Toplevel(overrideredirect=True)`` kept topmost, docked to
      the left of the orb (position polled every 400 ms). The skill list
      is gathered on a background daemon thread; every widget operation is
      race-guarded against destruction mid-flight and all ``after`` loops
      are cancelled on close/detach.

Fail-soft everywhere: if the bot has no brain yet the palette opens with an
empty-state message instead of crashing, and a broken palette can never take
down the orb.
Integration (handled by bot_clicky.attach):
    import bot_command_palette; ctl = bot_command_palette.attach(bot)
    ctl.detach()
Idempotency guard: ``bot._clicky_palette``.
"""

from __future__ import annotations

import difflib
import re
import threading

try:
    from jarvis_logging import get_logger
    log = get_logger("bot_command_palette")
except Exception:  # pragma: no cover - logging bootstrap fallback
    import logging

    log = logging.getLogger(__name__)

# Theme (matches the orb/menu palette in main.py)
CYAN = "#00d4ff"
BG = "#161b22"
FG = "#c9d1d9"
MUTED = "#8b949e"
ACCENT = "#1f6feb"
FONT = "Helvetica Neue"

MENU_LABEL = "⌘  Command Palette"
FOLLOW_MS = 400
PALETTE_W = 430
LIST_ROWS = 14
FUZZ_MIN = 0.40
EMPTY_MSG = "No skills registered yet.\nWake JARVIS up and try again, sir."

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PACK_TAGS = frozenset({
    "ps", "nd", "fx", "br", "ml", "mail", "cb", "pro", "ad", "wd",
    "ls", "jr", "dft", "sec", "kb", "todo", "cal", "music", "cm",
})


# ==========================================================================
# Pure logic (NO tkinter - unit-testable headless)
# ==========================================================================

def gather_skills(bot) -> list[str]:
    """Best-effort ordered list of registered Brain skill names.

    Deduplicated, registration order preserved; ``[]`` when the bot has no
    brain yet or anything in the chain is missing/broken. Safe to call from
    any thread (plain attribute reads only).
    """
    try:
        brain = getattr(bot, "_brain", None)
        skills = getattr(brain, "skills", None) if brain is not None else None
        if not skills:
            return []
        names: list[str] = []
        seen: set[str] = set()
        for s in skills:
            name = getattr(s, "name", None)
            if not name:
                continue
            key = str(name)
            if key in seen:
                continue
            seen.add(key)
            names.append(key)
        return names
    except Exception:
        return []


def build_query(skill_name) -> str | None:
    """Humanize a skill name into a candidate trigger phrase.

    ``ps_git_status`` -> ``"git status"``. Conservative by design: a leading
    pack tag is stripped, then ALL remaining tokens must be plain alphabetic
    words (>= 2 chars) and at least two of them must remain. Anything else
    (single-token verbs, digits, odd shapes) returns ``None`` so the UI asks
    via an input box instead of guessing.
    """
    try:
        text = str(skill_name or "").strip().lower()
    except Exception:
        return None
    if not text:
        return None
    tokens = _TOKEN_RE.findall(text)
    if tokens and tokens[0] in _PACK_TAGS:
        tokens = tokens[1:]
    if len(tokens) < 2:
        return None
    if any(not t.isalpha() or len(t) < 2 for t in tokens):
        return None
    return " ".join(tokens)


def filter_rank(query, names) -> list[str]:
    """Rank skill names against ``query``: substring hits beat fuzzy hits.

    Exact match > prefix match > substring match > difflib similarity
    (whole-string and squashed-token ratios). Below-threshold noise is
    dropped entirely; an empty query returns the names unfiltered, in order.
    """
    q = str(query or "").strip().lower()
    pool = [str(n) for n in (names or [])]
    if not q:
        return pool
    scored: list[tuple[float, int, str]] = []
    squash_q = re.sub(r"\s+", "", q)
    for i, n in enumerate(pool):
        nl = n.lower()
        squash_n = re.sub(r"[_\s]+", "", nl)
        bonus = 0.0
        if nl == q:
            bonus = 4.0
        elif nl.startswith(q):
            bonus = 3.0
        elif q in nl:
            bonus = 2.0
        ratio = max(difflib.SequenceMatcher(None, q, nl).ratio(),
                    difflib.SequenceMatcher(None, squash_q, squash_n).ratio())
        score = ratio + bonus
        if bonus or ratio >= FUZZ_MIN:
            scored.append((score, i, n))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [n for _s, _i, n in scored]


class SelectionModel:
    """Wrap-around selection over a list of items (pure, no tkinter)."""

    def __init__(self, items=()):
        self.items: list[str] = list(items or [])
        self.index: int = 0 if self.items else -1

    def reset(self, items=()) -> None:
        self.items = list(items or [])
        self.index = 0 if self.items else -1

    def selected(self) -> str | None:
        if not self.items or not 0 <= self.index < len(self.items):
            return None
        return self.items[self.index]

    def move(self, delta: int) -> str | None:
        """Move by ``delta`` positions, wrapping at both ends."""
        if not self.items:
            return None
        self.index = (self.index + delta) % len(self.items)
        return self.selected()


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
                     name="jarvis-command-palette-cmd").start()


# ==========================================================================
# Palette UI (tkinter imported lazily so headless import stays clean)
# ==========================================================================

class CommandPalette:
    """⌘K-style launcher window bound to a JarvisBot instance."""

    def __init__(self, bot):
        self.bot = bot
        self._win = None
        self._prompt = None
        self._names: list[str] = []
        self._model = SelectionModel()
        self._entry = None
        self._lb = None
        self._hint = None
        self._body = None
        self._empty = None
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
            win.attributes("-alpha", 0.97)
            win.configure(bg=BG)
            win.protocol("WM_DELETE_WINDOW", self.close)
            win.bind("<Escape>", lambda _e: self.close())

            head = tk.Frame(win, bg=BG)
            head.pack(fill="x", padx=12, pady=(8, 2))
            tk.Label(head, text="⌘ COMMAND PALETTE", bg=BG, fg=CYAN,
                     font=(FONT, 11, "bold")).pack(side="left")
            tk.Button(head, text="✕", command=self.close, bd=0,
                      bg=BG, fg=MUTED, activebackground=ACCENT,
                      activeforeground="white",
                      font=(FONT, 10, "bold")).pack(side="right")
            tk.Frame(win, height=1, bg=ACCENT).pack(fill="x", padx=10)

            entry = tk.Entry(win, bg="#0d1117", fg=FG, insertbackground=CYAN,
                             relief="flat", font=(FONT, 12))
            entry.pack(fill="x", padx=10, pady=(8, 4))
            entry.insert(0, "")
            entry.focus_set()
            entry.bind("<KeyRelease>", lambda _e: self._apply_filter())
            entry.bind("<Up>", lambda _e: self._step(-1))
            entry.bind("<Down>", lambda _e: self._step(1))
            entry.bind("<Return>", lambda _e: self._activate())
            self._entry = entry

            body = tk.Frame(win, bg=BG)
            body.pack(fill="both", expand=True, padx=6, pady=(2, 2))
            self._body = body

            hint = tk.Label(win, text="", bg=BG, fg=MUTED,
                            font=(FONT, 9), anchor="w")
            hint.pack(fill="x", padx=12, pady=(0, 6))
            self._hint = hint

            self._place(win)
            self._schedule(FOLLOW_MS, self._follow)

            self._gen += 1
            gen = self._gen

            def _work():
                names = gather_skills(self.bot)
                if gen != self._gen or self._win is None:
                    return
                try:
                    win.after(0, lambda: self._apply_names(gen, names))
                except Exception:
                    pass

            threading.Thread(target=_work, daemon=True,
                             name="jarvis-palette-gather").start()
        except Exception:
            self.close()

    def _apply_names(self, gen, names) -> None:
        if gen != self._gen or self._win is None:
            return
        import tkinter as tk

        self._names = list(names or [])
        body = self._body
        if body is None:
            return
        try:
            if self._names:
                lb = tk.Listbox(body, bg=BG, fg=FG, relief="flat",
                                highlightthickness=0, selectbackground=ACCENT,
                                selectforeground="white",
                                font=(FONT, 11), activestyle="none")
                lb.pack(fill="both", expand=True)
                lb.bind("<Button-1>", self._on_click)
                lb.bind("<Double-Button-1>", self._on_click)
                lb.bind("<Up>", lambda _e: self._step(-1))
                lb.bind("<Down>", lambda _e: self._step(1))
                lb.bind("<Return>", lambda _e: self._activate())
                lb.bind("<Escape>", lambda _e: self.close())
                self._lb = lb
                self._model.reset(self._names)
                for n in self._names:
                    lb.insert("end", n)
                self._sync_selection()
            else:
                self._empty = tk.Label(
                    body, text=EMPTY_MSG, bg=BG, fg=MUTED,
                    font=(FONT, 11), justify="center")
                self._empty.pack(expand=True, pady=20)
                self._model.reset([])
            self._update_hint()
        except Exception:
            pass

    # -- filtering / selection ----------------------------------------------

    def _apply_filter(self) -> None:
        lb = self._lb
        if lb is None:
            return
        try:
            query = self._entry.get() if self._entry is not None else ""
            matches = filter_rank(query, self._names)
        except Exception:
            matches = list(self._names)
        self._model.reset(matches)
        try:
            lb.delete(0, "end")
            for n in matches:
                lb.insert("end", n)
            self._sync_selection()
            self._update_hint()
        except Exception:
            pass

    def _step(self, delta: int) -> None:
        try:
            self._model.move(delta)
            self._sync_selection()
            self._update_hint()
        except Exception:
            pass

    def _sync_selection(self) -> None:
        lb = self._lb
        if lb is None:
            return
        try:
            lb.selection_clear(0, "end")
            idx = self._model.index
            if 0 <= idx < lb.size():
                lb.selection_set(idx)
                lb.see(idx)
        except Exception:
            pass

    def _update_hint(self) -> None:
        hint = self._hint
        if hint is None:
            return
        try:
            name = self._model.selected()
            if not name:
                hint.configure(text="")
                return
            query = build_query(name)
            if query:
                hint.configure(text="%s   ↦  \"%s\"" % (name, query))
            else:
                hint.configure(text="%s   ↦  ⏎ to enter a phrase…" % name)
        except Exception:
            pass

    # -- activation ----------------------------------------------------------

    def _on_click(self, event) -> None:
        try:
            lb = self._lb
            if lb is None:
                return
            idx = lb.nearest(event.y)
            if idx < 0:
                return
            self._model.index = idx
            self._sync_selection()
            self._update_hint()
            self._activate()
        except Exception:
            pass

    def _activate(self) -> None:
        try:
            name = self._model.selected()
            if not name:
                return
            query = build_query(name)
            if query:
                self.close()
                _dispatch_text(self.bot, query)
            else:
                self._open_prompt(name)
        except Exception:
            pass

    def _open_prompt(self, skill_name) -> None:
        """Ask for the trigger phrase, prefilled with the skill name."""
        import tkinter as tk

        try:
            self._close_prompt()
            root = getattr(self.bot, "root", None)
            win = self._win
            if root is None or win is None:
                return
            prompt = tk.Toplevel(root)
            self._prompt = prompt
            prompt.overrideredirect(True)
            prompt.attributes("-topmost", True)
            prompt.configure(bg=BG)
            prompt.transient(win)
            ox, oy = win.winfo_x(), win.winfo_y()
            prompt.geometry("+%d+%d" % (max(8, ox), max(8, oy - 46)))

            tk.Label(prompt, text="Phrase to run for %s:" % skill_name,
                     bg=BG, fg=MUTED, font=(FONT, 9)).pack(
                fill="x", padx=10, pady=(6, 0))
            entry = tk.Entry(prompt, bg="#0d1117", fg=FG,
                             insertbackground=CYAN, relief="flat",
                             font=(FONT, 11), width=34)
            entry.pack(fill="x", padx=10, pady=(2, 8))
            entry.insert(0, str(skill_name))
            entry.focus_set()

            def _run(_e=None) -> None:
                try:
                    value = entry.get().strip()
                except Exception:
                    value = ""
                self._close_prompt()
                self.close()
                if value:
                    _dispatch_text(self.bot, value)

            def _cancel(_e=None) -> None:
                self._close_prompt()

            entry.bind("<Return>", _run)
            entry.bind("<Escape>", _cancel)
            prompt.protocol("WM_DELETE_WINDOW", _cancel)
        except Exception:
            self._close_prompt()

    def _close_prompt(self) -> None:
        prompt, self._prompt = self._prompt, None
        if prompt is None:
            return
        try:
            prompt.destroy()
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
            win.geometry("+%d+%d" % (max(8, ox - PALETTE_W - 14),
                                     max(8, oy)))
        except Exception:
            pass

    def _follow(self) -> None:
        win = self._win
        if win is None:
            return
        self._place(win)
        self._schedule(FOLLOW_MS, self._follow)

    # -- teardown ------------------------------------------------------------

    def close(self, *_args) -> None:
        self._gen += 1
        win, self._win = self._win, None
        for aid in list(self._aids):
            if win is not None:
                try:
                    win.after_cancel(aid)
                except Exception:
                    pass
        self._aids.clear()
        self._close_prompt()
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        self._entry = None
        self._lb = None
        self._hint = None
        self._body = None
        self._empty = None

    def detach(self) -> None:
        try:
            self.close()
        except Exception:
            pass
        try:
            if getattr(self.bot, "_clicky_palette", None) is self:
                self.bot._clicky_palette = None
        except Exception:
            pass


# ==========================================================================
# Entry point (called by bot_clicky.attach)
# ==========================================================================

def attach(bot):
    """Attach the command palette to ``bot``; idempotent, fail-soft.

    Returns the controller (with ``.detach()``); attaching twice yields
    the same controller and never duplicates the menu item.
    """
    existing = getattr(bot, "_clicky_palette", None)
    if existing is not None:
        return existing
    controller = CommandPalette(bot)
    try:
        bot._clicky_palette = controller
    except Exception:
        pass
    try:
        menu = getattr(bot, "menu", None)
        if menu is not None:
            menu.add_command(label=MENU_LABEL, command=controller.toggle)
    except Exception as exc:
        log.warning("command palette menu append failed: %s", exc)
    return controller
