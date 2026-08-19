"""JARVIS STATEFUL MULTI-TURN GAMES ARENA: session-based skills.

The first session-based skills in the codebase: instead of answering a
single command they keep ONE active game alive in memory and resolve the
player's follow-ups ("e", "42", "b2") until the game ends. Eight skills:

    - gm_hangman    : "play hangman" -> hidden word, letter guesses.
    - gm_guess      : "guess the number" -> higher/lower, 7 attempts.
    - gm_mastermind : "play mastermind" -> crack the 4-digit code,
                      exact/misplaced peg feedback, 10 attempts.
    - gm_ttt        : "play tic tac toe" -> you are X, JARVIS is O,
                      minimax-lite AI (win > block > center > corner >
                      side) that never loses; moves like "play b2".
    - gm_move       : THE FOLLOW-UP ROUTER (priority). While a session is
                      active it claims short guess-shaped inputs (single
                      letters, bare digits, coordinates) and routes them
                      into the game. When NO session is active it always
                      returns None so ordinary chat and every other skill
                      keep working. Anchored patterns + a length cap make
                      sure sentences are never hijacked, and dice/coin/
                      trivia phrasings simply do not match.
    - gm_quit       : "give up" / "resign" -> abandon session (counts as
                      a loss, with a taunt).
    - gm_score      : "game score" -> persisted win/loss/draw record.
    - gm_status     : "show the board" -> render the current game state.

Only the SCORES persist (atomic temp + os.replace JSON at
``.jarvis_games.json``, lock-guarded, lazy-loaded, corrupt -> fresh);
the active session itself is deliberately in-memory only. Pure stdlib,
fully offline, deterministic given the seeded ``_RNG`` seam. This module
never imports main.
"""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from collections import Counter
from typing import Callable, Optional

try:
    from jarvis_logging import get_logger
except ImportError:  # pragma: no cover - standalone use
    import logging

    def get_logger(name: str) -> logging.Logger:  # type: ignore[misc]
        return logging.getLogger(name)


log = get_logger("skills_games")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SCORE_FILE = os.path.join(PROJECT_DIR, ".jarvis_games.json")

_RNG = random.Random()          # seam: tests seed or replace this
_now = time.time                # seam: tests freeze timestamps

# ==========================================================================
# Tunables
# ==========================================================================

HANGMAN_MAX_MISSES = 6
GUESS_LO = 1
GUESS_HI = 100
GUESS_MAX_TRIES = 7
MM_CODE_LEN = 4
MM_DIGITS = 6                   # code digits are 1..6
MM_MAX_TRIES = 10

_WORDS = (
    "stark", "arc", "reactor", "armor", "jarvis", "shield", "titanium",
    "repulsor", "malibu", "workshop", "satellite", "quantum", "neural",
    "circuit", "algorithm", "python", "keyboard", "monitor", "rocket",
    "orbit", "galaxy", "photon", "fusion", "matrix", "protocol",
    "firewall", "server", "kernel", "binary", "widget", "gadget",
    "mission", "hangar", "pilot", "radar", "laser", "robot", "sensor",
)

_MM_COLORS = {1: "red", 2: "green", 3: "blue",
              4: "yellow", 5: "orange", 6: "purple"}

_WIN_TAUNTS = (
    "A flawless victory, sir. Do try to contain your surprise.",
    "Victory logged, sir. The scoreboard grows embarrassingly one-sided.",
    "Well played, sir. I shall pretend I let you win.",
)
_LOSE_TAUNTS = (
    "Defeat, sir. Even my sarcasm circuits are struggling with this one.",
    "The house wins, sir. Better luck in the next simulation.",
    "Loss recorded, sir. I would offer a rematch, but why bother?",
)
_DRAW_TAUNTS = (
    "A stalemate, sir. How very diplomatic of us both.",
)

_ROUTER_MAX_LEN = 24            # guesses are short; sentences are not


def _taunt(bank: tuple[str, ...]) -> str:
    return bank[_RNG.randrange(len(bank))]


# ==========================================================================
# Session plumbing (single active game, in-memory, lock-guarded)
# ==========================================================================

_lock = threading.RLock()
_session: Optional[dict] = None


def _get_session() -> Optional[dict]:
    with _lock:
        return _session


def _set_session(state: Optional[dict]) -> None:
    global _session
    with _lock:
        _session = state


_KIND_LABELS = {
    "hangman": "Hangman",
    "guess": "Number Guess",
    "mm": "Mastermind",
    "ttt": "Tic-Tac-Toe",
}


# ==========================================================================
# Score persistence (atomic JSON, lazy load, corrupt -> fresh)
# ==========================================================================

_scores: Optional[dict] = None


def _load_scores() -> dict:
    global _scores
    if _scores is not None:
        return _scores
    try:
        with open(SCORE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except Exception as exc:
        log.debug("score load starting fresh (%s)", exc)
        data = {}
    data.setdefault("games", {})
    data.setdefault("updated", 0.0)
    _scores = data
    return _scores


def _save_scores() -> None:
    tmp = SCORE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_scores or {}, fh)
        os.replace(tmp, SCORE_FILE)
    except Exception as exc:
        log.warning("score save failed: %s", exc)


def record_result(kind: str, outcome: str) -> None:
    """Persist one outcome ('won' | 'lost' | 'drew') for a game kind."""
    if outcome not in ("won", "lost", "drew"):
        return
    with _lock:
        scores = _load_scores()
        entry = scores["games"].setdefault(
            kind, {"won": 0, "lost": 0, "drew": 0})
        entry[outcome] = entry.get(outcome, 0) + 1
        scores["updated"] = _now()
        _save_scores()


def reset_for_tests(score_path: Optional[str] = None) -> None:
    """Test seam: drop cached state, optionally redirect the score file."""
    global _scores, SCORE_FILE, _session
    with _lock:
        _session = None
        _scores = None
        if score_path is not None:
            SCORE_FILE = score_path


# ==========================================================================
# Game engines (pure-ish helpers; seams for determinism)
# ==========================================================================

def _pick_word(rng: random.Random) -> str:
    return rng.choice(_WORDS)


def _pick_secret(rng: random.Random) -> int:
    return rng.randint(GUESS_LO, GUESS_HI)


def _make_code(rng: random.Random) -> list[int]:
    return [rng.randint(1, MM_DIGITS) for _ in range(MM_CODE_LEN)]


# --- Hangman ---------------------------------------------------------------

def _new_hangman() -> dict:
    word = _pick_word(_RNG)
    return {"kind": "hangman", "word": word,
            "found": set(), "misses": set(),
            "max_misses": HANGMAN_MAX_MISSES}


def _render_hangman(s: dict) -> str:
    masked = " ".join(ch if ch in s["found"] else "_" for ch in s["word"])
    left = s["max_misses"] - len(s["misses"])
    guessed = ", ".join(sorted(s["found"] | s["misses"])) or "-"
    return (f"Word: {masked}\nMisses left: {left} "
            f"(guessed: {guessed})")


def _h_hangman_guess(s: dict, token: str) -> str:
    """Apply a letter (or whole-word) guess; finish + score if needed."""
    word = s["word"]
    if len(token) > 1:
        if token == word:
            s["found"] = set(word)
        else:
            s["misses"].add(token[:1] + "*")
    elif token in s["found"] or token in s["misses"]:
        return (f"You have already tried '{token}', sir. The word remains:\n"
                + _render_hangman(s))
    elif token in word:
        s["found"].add(token)
    else:
        s["misses"].add(token)

    if set(word) <= s["found"]:
        _set_session(None)
        record_result("hangman", "won")
        return (f"'{word}' - you cracked it, sir! {_taunt(_WIN_TAUNTS)}")
    if len(s["misses"]) >= s["max_misses"]:
        _set_session(None)
        record_result("hangman", "lost")
        return (f"The man hangs, sir. The word was '{word}'. "
                f"{_taunt(_LOSE_TAUNTS)}")
    hint = "letter" if len(token) == 1 else "word"
    verdict = "hits" if (token in word or token in s["found"]) else "misses"
    return f"'{token}' {verdict}, sir. Next {hint}?\n" + _render_hangman(s)


# --- Number guess ----------------------------------------------------------

def _new_number() -> dict:
    return {"kind": "guess", "secret": _pick_secret(_RNG),
            "tries": 0, "limit": GUESS_MAX_TRIES}


def _h_number_guess(s: dict, value: int) -> str:
    s["tries"] += 1
    if value == s["secret"]:
        _set_session(None)
        record_result("guess", "won")
        return (f"{value} - dead centre, sir, in {s['tries']} attempt"
                f"{'s' if s['tries'] != 1 else ''}. {_taunt(_WIN_TAUNTS)}")
    if s["tries"] >= s["limit"]:
        secret = s["secret"]
        _set_session(None)
        record_result("guess", "lost")
        return (f"That was your last shot, sir - the number was {secret}. "
                f"{_taunt(_LOSE_TAUNTS)}")
    direction = "higher" if value < s["secret"] else "lower"
    return (f"{value} is too {'low' if direction == 'higher' else 'high'}, "
            f"sir - aim {direction}. attempt {s['tries']} of {s['limit']}.")


# --- Mastermind ------------------------------------------------------------

def _mm_pegs(code: list[int], guess: list[int]) -> tuple[int, int]:
    """Return (exact, misplaced) pegs for a guess against the code."""
    exact = sum(1 for c, g in zip(code, guess) if c == g)
    from collections import Counter
    pool = Counter(code) - Counter(c for c, g in zip(code, guess) if c == g)
    loose = sum((Counter(guess) & pool).values())
    return exact, loose


_MM_LETTER_MAP = {"r": "1", "g": "2", "b": "3",
                  "y": "4", "o": "5", "p": "6"}


def _parse_mm_sequence(raw: str) -> Optional[list[int]]:
    """'3 1 4 1', '3141', 'r,g,b,y' -> [3,1,4,1]; anything else None."""
    compact = re.sub(r"[\s,-]", "", (raw or "")).lower()
    if not compact:
        return None
    if compact.isdigit():
        digits = list(compact)
    elif all(ch in _MM_LETTER_MAP for ch in compact):
        digits = [_MM_LETTER_MAP[ch] for ch in compact]
    else:
        return None
    if len(digits) != MM_CODE_LEN:
        return None
    return [int(d) for d in digits]


def _new_mastermind() -> dict:
    code = _make_code(_RNG)
    palette = ", ".join(f"{_MM_COLORS[i][0].upper()}={_MM_COLORS[i]}"
                        for i in sorted(_MM_COLORS))
    return {"kind": "mm", "code": code, "tries": 0,
            "limit": MM_MAX_TRIES, "palette": palette}


def _h_mastermind_guess(s: dict, raw: str) -> str:
    guess = _parse_mm_sequence(raw)
    if guess is None:
        return (f"I need exactly {MM_CODE_LEN} digits from 1 to "
                f"{MM_DIGITS}, sir - try '3 1 4 1'.")
    s["tries"] += 1
    exact, loose = _mm_pegs(s["code"], guess)
    if exact == MM_CODE_LEN:
        _set_session(None)
        record_result("mm", "won")
        return (f"Code broken in {s['tries']} tr{'y' if s['tries'] == 1 else 'ies'}, "
                f"sir! {_taunt(_WIN_TAUNTS)}")
    if s["tries"] >= s["limit"]:
        code_str = "".join(str(d) for d in s["code"])
        _set_session(None)
        record_result("mm", "lost")
        return (f"The vault stays shut, sir - the code was {code_str}. "
                f"{_taunt(_LOSE_TAUNTS)}")
    return (f"Guess {s['tries']}/{s['limit']}: {exact} exact, "
            f"{loose} misplaced. Again, sir.")


# --- Tic-tac-toe -----------------------------------------------------------

_WIN_LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8),
              (0, 3, 6), (1, 4, 7), (2, 5, 8),
              (0, 4, 8), (2, 4, 6))


def _ttt_winner(board: list[str]) -> Optional[str]:
    for a, b, c in _WIN_LINES:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    if " " not in board:
        return "draw"
    return None


def _ttt_finds(board: list[str], mark: str) -> Optional[int]:
    """Immediate winning square for ``mark``, scanning in fixed order."""
    for i in range(9):
        if board[i] != " ":
            continue
        trial = list(board)
        trial[i] = mark
        if _ttt_winner(trial) == mark:
            return i
    return None


_TTT_CENTER = (4,)
_TTT_CORNERS = (0, 2, 6, 8)
_TTT_SIDES = (1, 3, 5, 7)


def _ttt_ai_pick(board: list[str]) -> int:
    """Minimax-lite policy: win > block > center > corner > side."""
    spot = _ttt_finds(board, "O")
    if spot is not None:
        return spot
    spot = _ttt_finds(board, "X")
    if spot is not None:
        return spot
    for group in (_TTT_CENTER, _TTT_CORNERS, _TTT_SIDES):
        for i in group:
            if board[i] == " ":
                return i
    raise ValueError("no legal move on a non-full board")


def _render_ttt(board: list[str]) -> str:
    rows = []
    rows.append("      a   b   c")
    for r in range(3):
        cells = " | ".join(board[r * 3 + c] or " " for c in range(3))
        rows.append(f"    {r + 1}   {cells}")
        if r < 2:
            rows.append("   ----+---+----")
    return "\n".join(rows)


_TTT_COORD_RE = re.compile(r"^([abc])([123])$", re.I)


def _coord_to_index(coord: str) -> Optional[int]:
    m = _TTT_COORD_RE.match(coord.strip())
    if not m:
        return None
    col = "abc".index(m.group(1).lower())
    row = int(m.group(2)) - 1
    return row * 3 + col


def _new_ttt() -> str:
    board = [" "] * 9
    _set_session({"kind": "ttt", "board": board})
    return ("Tic-tac-toe, sir. You are X and move first; call squares "
            "like 'a1' through 'c3'.\n" + _render_ttt(board))


def _h_ttt_play(s: dict, coord: str) -> str:
    board = s["board"]
    idx = _coord_to_index(coord)
    if idx is None or board[idx] != " ":
        return ("That square is off the menu or already taken, sir - "
                "pick an open one.\n" + _render_ttt(board))
    board[idx] = "X"
    result = _ttt_winner(board)
    if result is None:
        ai_idx = _ttt_ai_pick(board)
        board[ai_idx] = "O"
        result = _ttt_winner(board)
    if result == "X":
        _set_session(None)
        record_result("ttt", "lost")
        return (f"Three in a row for you at '{coord.lower()}', sir?! "
                f"Recalibrating. {_taunt(_LOSE_TAUNTS)}")
    if result == "O":
        _set_session(None)
        record_result("ttt", "won")
        return ("My game, sir. " + _taunt(_WIN_TAUNTS) + "\n"
                + _render_ttt(board))
    if result == "draw":
        _set_session(None)
        record_result("ttt", "drew")
        return ("A draw, sir. " + _taunt(_DRAW_TAUNTS) + "\n"
                + _render_ttt(board))
    return "Board after your move, sir:\n" + _render_ttt(board)


# ==========================================================================
# Start detectors (anchored, specific phrases only)
# ==========================================================================

_ANCHOR = (r"^(?:(?:hey|hi|hello|yo|ok|okay|please|jarvis|lets|let\s*us)"
           r"[\s,]*"
           r"|(?:(?:can|could|would|will)\s+you\s+))*")

_HANGMAN_RE = re.compile(
    _ANCHOR + r"(?:play|start|begin|new)\s+(?:a\s+)?(?:game\s+of\s+)?"
              r"hangman\b|^hangman$", re.I)
_GUESS_RE = re.compile(
    _ANCHOR + r"(?:play\s+(?:a\s+)?|start\s+(?:a\s+)?)?(?:the\s+)?"
              r"(?:number\s+guess(?:ing)?(?:\s+game)?|"
              r"guess(?:ing)?\s+(?:the\s+)?number\b|guessing\s+game\b|"
              r"number\s+game\b)", re.I)
_MM_RE = re.compile(
    _ANCHOR + r"(?:play\s+|start\s+)?(?:a\s+game\s+of\s+)?"
              r"(?:mastermind|code\s*-?\s*breaker)\b", re.I)
_TTT_RE = re.compile(
    _ANCHOR + r"(?:play\s+|start\s+)?(?:a\s+game\s+of\s+)?"
              r"(?:tic[-\s]?tac[-\s]?toe|ttt)\b", re.I)

_BANNER = {
    "hangman": "Hangman, sir. Guess letters with 'guess e' or just the "
               "letter; six misses and the man swings.",
    "guess": f"Very well, sir - I have chosen a number between {GUESS_LO} "
             f"and {GUESS_HI}. You get {GUESS_MAX_TRIES} attempts; say "
             "'guess 50' or just the number.",
    "mm": "Mastermind, sir. Crack my %d-digit code (digits 1-%d, repeats "
          "allowed) in %d tries. Feedback: exact vs misplaced. Fire with "
          "'%s'."
          % (MM_CODE_LEN, MM_DIGITS, MM_MAX_TRIES,
             " ".join("1" for _ in range(MM_CODE_LEN))),
}


def _start(kind: str) -> str:
    """Shared starter: swap out any running session, install fresh game."""
    old = _get_session()
    builders: dict[str, Callable[[], dict]] = {
        "hangman": _new_hangman,
        "guess": _new_number,
        "mm": _new_mastermind,
    }
    if kind == "ttt":
        swapped = old is not None and old["kind"] != "ttt"
        if old is not None:
            log.info("replacing active %s session", old["kind"])
        return ("Scrapped the previous game, sir. " if swapped else "") \
            + _new_ttt()
    state = builders[kind]()
    _set_session(state)
    prefix = ""
    if old is not None and old["kind"] != kind:
        prefix = "Scrapped the previous game, sir. "
    body = _BANNER[kind]
    extra = ""
    if kind == "hangman":
        extra = "\n" + _render_hangman(state)
    elif kind == "mm":
        extra = f"\nPalette: {state['palette']}"
    return prefix + body + extra


def _d_start(pattern: "re.Pattern[str]", kind: str, cmd: str):
    if pattern.search(cmd):
        return {"cmd": cmd, "kind": kind}
    return None


def _e_start(app, ctx) -> str:
    try:
        return _start(ctx["kind"])
    except Exception as exc:  # defensive containment
        log.exception("could not start %s", ctx.get("kind"))
        return f"My game engine refuses to boot ({str(exc)[:120]}), sir."


# ==========================================================================
# gm_move - the follow-up router (claims input ONLY while a session lives)
# ==========================================================================

_LETTER_RE = re.compile(r"^(?:guess\s+|letter\s+)?([a-z])$", re.I)
_WORDGUESS_RE = re.compile(r"^guess\s+([a-z]{2,15})$", re.I)
_NUMBER_RE = re.compile(r"^(?:guess\s+|answer\s+|is\s+it\s+)?(\d{1,3})$",
                        re.I)
_MMSEQ_RE = re.compile(
    r"^(?:guess\s+)?((?:[1-6][\s,-]){3}[1-6]|[1-6]{4}|"
    r"(?:[rgbyop][\s,-]){3}[rgbyop]|[rgbyop]{4})$", re.I)
_COORD_RE = re.compile(
    r"^(?:play\s+|move\s+|place\s+)?([abc][123])$", re.I)
_NEVER_CLAIM = {"a", "i"}      # bare articles must reach normal chat


def _d_move(cmd: str):
    cmd = (cmd or "").strip()
    if not cmd or len(cmd) > _ROUTER_MAX_LEN:
        return None
    s = _get_session()
    if not s:
        return None                     # idle: never hijack anything
    kind = s["kind"]
    m = _LETTER_RE.match(cmd)
    if m:
        letter = m.group(1).lower()
        if kind == "hangman" and (letter not in _NEVER_CLAIM
                                  or m.group(0).lower().startswith(
                                      ("guess", "letter"))):
            return {"cmd": cmd, "game": "hangman", "token": letter}
        return None
    m = _WORDGUESS_RE.match(cmd)
    if m and kind == "hangman":
        return {"cmd": cmd, "game": "hangman", "token": m.group(1).lower()}
    m = _NUMBER_RE.match(cmd)
    if m and kind == "guess":
        return {"cmd": cmd, "game": "guess", "value": int(m.group(1))}
    m = _MMSEQ_RE.match(cmd)
    if m and kind == "mm":
        return {"cmd": cmd, "game": "mm", "raw": m.group(1)}
    m = _COORD_RE.match(cmd)
    if m and kind == "ttt":
        return {"cmd": cmd, "game": "ttt", "coord": m.group(1)}
    return None


def _e_move(app, ctx) -> str:
    s = _get_session()
    if not s:
        return "The arcade has gone quiet, sir - name a game to begin."
    handlers = {
        "hangman": lambda: _h_hangman_guess(s, ctx["token"]),
        "guess": lambda: _h_number_guess(s, ctx["value"]),
        "mm": lambda: _h_mastermind_guess(s, ctx["raw"]),
        "ttt": lambda: _h_ttt_play(s, ctx["coord"]),
    }
    handler = handlers.get(ctx["game"])
    if handler is None:
        return None
    return handler()


# ==========================================================================
# gm_quit / gm_score / gm_status - meta skills
# ==========================================================================

_QUIT_RE = re.compile(
    r"^(?:i\s+)?(?:resign|concede|forfeit)$"
    r"|^(?:i\s+)?give\s+up$"
    r"|^(?:i\s+)?(?:quit|exit|abandon|stop|end)"
    r"(?:\s+(?:this|the)?\s*game)?$"
    r"|\b(?:quit|abandon|stop|end)\s+(?:the\s+)?game\b", re.I)


def _d_quit(cmd: str):
    return {"cmd": cmd} if _QUIT_RE.search(cmd.strip()) else None


def _e_quit(app, ctx) -> str:
    s = _get_session()
    if not s:
        return ("There is no game in progress to abandon, sir - though "
                "I admire the preemptive surrender.")
    kind = s["kind"]
    _set_session(None)
    record_result(kind, "lost")
    label = _KIND_LABELS.get(kind, kind)
    return (f"{label} abandoned and chalked up as a loss, sir. "
            f"{_taunt(_LOSE_TAUNTS)}")


_SCORE_RE = re.compile(
    r"\bgame\s+(?:score|stats?|statistics|record)\b"
    r"|\b(?:my\s+)?(?:win\s*/?\s*loss|scoreboard|leaderboard)\b"
    r"|\bscore\b.*\bgames?\b|\bgames?\b.*\bscore\b"
    r"|\bhow\s+(?:many\s+games\s+have\s+i\s+|am\s+i\s+doing)\b", re.I)


def _d_score(cmd: str):
    return {"cmd": cmd} if _SCORE_RE.search(cmd) else None


def _e_score(app, ctx) -> str:
    with _lock:
        games = dict(_load_scores()["games"])
    if not games:
        return ("The scoreboard is blank, sir - not a single game has "
                "been fought yet.")
    lines = []
    tot_won = tot_lost = tot_drew = 0
    for kind in sorted(games):
        g = games[kind]
        w, l, d = g.get("won", 0), g.get("lost", 0), g.get("drew", 0)
        tot_won += w
        tot_lost += l
        tot_drew += d
        label = _KIND_LABELS.get(kind, kind)
        lines.append(f"- {label}: {w}W / {l}L / {d}D")
    total = tot_won + tot_lost + tot_drew
    rate = (100.0 * tot_won / total) if total else 0.0
    lines.append(f"Overall: {tot_won}W / {tot_lost}L / {tot_drew}D "
                 f"({rate:.0f}% win rate)")
    return "Career record, sir:\n" + "\n".join(lines)


_STATUS_RE = re.compile(
    r"\bgame\s+(?:status|state)\b|\bshow\s+(?:me\s+)?(?:the\s+)?board\b"
    r"|\bcurrent\s+game\b|\bwhere\s+(?:are\s+we|were\s+we)\b", re.I)


def _d_status(cmd: str):
    return {"cmd": cmd} if _STATUS_RE.search(cmd) else None


def _e_status(app, ctx) -> str:
    s = _get_session()
    if not s:
        return ("No active game right now, sir. Say 'play hangman', "
                "'guess the number', 'play mastermind' or 'tic tac toe'.")
    renderers = {
        "hangman": lambda: _render_hangman(s),
        "ttt": lambda: _render_ttt(s["board"]),
        "guess": lambda: f"Secret number hunt, attempt {s['tries']} "
                         f"of {s['limit']} so far.",
        "mm": lambda: f"Mastermind: attempt {s['tries']} of {s['limit']} "
                      f"burned.",
    }
    label = _KIND_LABELS.get(s["kind"], s["kind"])
    return f"{label}, in progress, sir:\n" + renderers[s["kind"]]()


# ==========================================================================
# Registration
# ==========================================================================

_SKILLS: tuple[tuple[str, object, object, bool], ...] = (
    ("gm_hangman", lambda c: _d_start(_HANGMAN_RE, "hangman", c),
     _e_start, True),
    ("gm_guess", lambda c: _d_start(_GUESS_RE, "guess", c), _e_start, True),
    ("gm_mastermind", lambda c: _d_start(_MM_RE, "mm", c), _e_start, True),
    ("gm_ttt", lambda c: _d_start(_TTT_RE, "ttt", c), _e_start, True),
    ("gm_move", _d_move, _e_move, True),
    ("gm_quit", _d_quit, _e_quit, False),
    ("gm_score", _d_score, _e_score, False),
    ("gm_status", _d_status, _e_status, False),
)


def register(brain) -> None:  # noqa: ANN001 - duck-typed Brain
    """Register every game skill with the given Brain (fail-soft)."""
    for name, detect, execute, priority in _SKILLS:
        brain.register(name, detect, _wrap(execute, name), priority=priority)
    log.info("games arena registered (%d skills)", len(_SKILLS))


def _wrap(execute, name):  # noqa: ANN001
    def safe(app, ctx):
        try:
            return execute(app, ctx)
        except Exception as exc:  # defensive containment
            log.exception("skill %s failed", name)
            return (f"Something jammed in my games arena "
                    f"({str(exc)[:120]}), sir.")
    safe.__name__ = f"safe_{name}"
    return safe


if __name__ == "__main__":  # smoke demo
    class _B:
        def register(self, name, detect, execute, priority=False):
            print(f"would register {name}")

    register(_B())
