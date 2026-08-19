"""Tests for skills_games.py — fully offline, fully deterministic.

The active game session lives in-memory (reset between tests via
``sg.reset_for_tests()``); scores are pointed at a tmp_path JSON file
through the ``SCORE_FILE`` seam. Words/secrets/codes come from
monkeypatchable seams (``_pick_word`` / ``_pick_secret`` / ``_make_code``)
so every win and loss path is scripted. No network, no sleeps.
"""

import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import skills_games as sg  # noqa: E402


class RecorderBrain:
    def __init__(self):
        self.skills = {}

    def register(self, name, detect, execute, priority=False):
        self.skills[name] = (detect, execute, priority)


class DummyApp:
    pass


EXPECTED_SKILLS = {
    "gm_hangman", "gm_guess", "gm_mastermind", "gm_ttt",
    "gm_move", "gm_quit", "gm_score", "gm_status",
}
PRIORITY_SKILLS = {"gm_hangman", "gm_guess", "gm_mastermind", "gm_ttt",
                   "gm_move"}


@pytest.fixture()
def brain(monkeypatch, tmp_path):
    monkeypatch.setattr(sg, "SCORE_FILE",
                        str(tmp_path / ".jarvis_games.json"))
    monkeypatch.setattr(sg, "_RNG", random.Random(2026))  # seeded taunts
    sg.reset_for_tests()
    b = RecorderBrain()
    sg.register(b)
    yield b
    sg.reset_for_tests()


def run(brain, name, cmd):
    detect, execute, _prio = brain.skills[name]
    ctx = detect(cmd)
    assert ctx is not None, f"{name} did not detect {cmd!r}"
    return execute(DummyApp(), ctx)


def score_file(brain):
    with open(sg.SCORE_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ==========================================================================
# Registration & wiring
# ==========================================================================

def test_registers_all_eight_skills(brain):
    assert set(brain.skills) == EXPECTED_SKILLS


def test_wrap_names_and_priorities(brain):
    for name in EXPECTED_SKILLS:
        detect, execute, prio = brain.skills[name]
        assert callable(detect) and callable(execute)
        assert execute.__name__ == f"safe_{name}"
        assert prio is (name in PRIORITY_SKILLS)


# ==========================================================================
# The idle guard — routers must NEVER hijack when no session is live
# ==========================================================================

@pytest.mark.parametrize("cmd", [
    "e", "z", "5", "42", "b2", "1234", "rgby", "1 2 3 4",
    "guess e", "guess stark", "play b2", "answer 7",
])
def test_router_idle_returns_none(brain, cmd):
    assert brain.skills["gm_move"][0](cmd) is None, \
        f"router hijacked {cmd!r} while idle"


@pytest.mark.parametrize("cmd", [
    "tell me a joke", "flip a coin", "roll a die", "what time is it",
    "what's the weather like", "remember that my wifi password is hunter2",
])
def test_all_detectors_ignore_unrelated_sentences_idle(brain, cmd):
    for name, (detect, _exec, _prio) in brain.skills.items():
        assert detect(cmd) is None, f"{name} falsely detected {cmd!r}"


def test_router_never_shadows_existing_skills_while_active(brain):
    run(brain, "gm_ttt", "play tic tac toe")           # session live now
    d = brain.skills["gm_move"][0]
    for cmd in ("tell me a joke", "flip a coin", "roll a die",
                "what time is it"):
        assert d(cmd) is None, f"router hijacked {cmd!r} mid-game"


def test_router_ignores_long_and_empty_input(brain):
    run(brain, "gm_guess", "guess the number")
    d = brain.skills["gm_move"][0]
    assert d("") is None
    assert d("x" * 60) is None
    assert d("please find the number forty two right now sir") is None


def test_router_routes_only_to_the_active_game(brain):
    run(brain, "gm_ttt", "play ttt")
    assert brain.skills["gm_move"][0]("e") is None      # letters belong
    # to hangman, not ttt; bare digits belong to number-guess, not ttt.
    assert brain.skills["gm_move"][0]("77") is None


# ==========================================================================
# Hangman — start, mid-game routing, full win, full loss, repeats
# ==========================================================================

def test_start_hangman_shows_masked_board(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_word", lambda rng: "arc")
    reply = run(brain, "gm_hangman", "play hangman")
    assert "Hangman" in reply and ", sir" in reply
    assert "_" in reply                                  # masked word shown


def test_hangman_full_win_via_bare_letter_routing(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_word", lambda rng: "arc")
    run(brain, "gm_hangman", "hangman")
    assert brain.skills["gm_move"][0]("r") is not None   # router claims it
    run(brain, "gm_move", "r")
    run(brain, "gm_move", "c")                           # bare letter again
    final = run(brain, "gm_move", "guess a")             # guarded article
    assert "'arc'" in final and "cracked it" in final
    data = score_file(brain)
    assert data["games"]["hangman"]["won"] == 1
    # session ended: router goes quiet again
    assert brain.skills["gm_move"][0]("q") is None


def test_hangman_full_loss_reveals_word(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_word", lambda rng: "quantum")
    run(brain, "gm_hangman", "let us play hangman")
    final = ""
    for letter in "bdfghl":                              # six clean misses
        final = run(brain, "gm_move", letter)
    assert "quantum" in final and "hangs" in final
    assert score_file(brain)["games"]["hangman"]["lost"] == 1


def test_hangman_repeat_letter_costs_nothing(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_word", lambda rng: "radar")
    run(brain, "gm_hangman", "play hangman")
    first = run(brain, "gm_move", "d")
    again = run(brain, "gm_move", "guess d")
    assert "already tried" in again
    assert first.splitlines()[1] == again.splitlines()[1]  # misses unchanged


# ==========================================================================
# Number guess — higher/lower feedback, attempt count, win & loss paths
# ==========================================================================

def test_start_number_game_banner(brain):
    reply = run(brain, "gm_guess", "guess the number")
    assert "between 1 and 100" in reply
    assert "7 attempts" in reply or "7 attempts" in reply.replace(
        f"{sg.GUESS_MAX_TRIES}", "7")


def test_number_midgame_routing_with_feedback(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_secret", lambda rng: 73)
    run(brain, "gm_guess", "number guessing game")
    assert brain.skills["gm_move"][0]("50") is not None
    low = run(brain, "gm_move", "50")
    assert "higher" in low and "attempt 1 of 7" in low
    high = run(brain, "gm_move", "guess 90")
    assert "lower" in high and "attempt 2 of 7" in high


def test_number_win_path_records_victory(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_secret", lambda rng: 73)
    run(brain, "gm_guess", "start guess the number")
    final = run(brain, "gm_move", "73")
    assert "73" in final and "1 attempt" in final        # one try taken
    assert "dead centre" in final and "sir" in final.lower()
    assert score_file(brain)["games"]["guess"]["won"] == 1


def test_number_loss_path_after_seven_attempts(brain, monkeypatch):
    monkeypatch.setattr(sg, "_pick_secret", lambda rng: 73)
    run(brain, "gm_guess", "guess the number")
    final = ""
    for _ in range(7):
        final = run(brain, "gm_move", "80")
    assert "the number was 73" in final
    assert score_file(brain)["games"]["guess"]["lost"] == 1
    assert brain.skills["gm_move"][0]("50") is None       # game over


# ==========================================================================
# Mastermind — peg math, digit + colour input, win & loss paths
# ==========================================================================

@pytest.mark.parametrize("code,guess,exact,misplaced", [
    ([1, 2, 3, 4], [4, 3, 2, 1], 0, 4),
    ([1, 2, 3, 4], [1, 2, 3, 4], 4, 0),
    ([1, 1, 2, 2], [2, 2, 3, 3], 0, 2),
    ([5, 5, 5, 1], [5, 5, 5, 5], 3, 0),
])
def test_mm_pegs_math(code, guess, exact, misplaced):
    assert sg._mm_pegs(code, guess) == (exact, misplaced)


def test_mm_start_banner(brain, monkeypatch):
    monkeypatch.setattr(sg, "_make_code", lambda rng: [1, 2, 3, 4])
    reply = run(brain, "gm_mastermind", "play mastermind")
    assert "4-digit code" in reply and "Palette" in reply


def test_mm_digit_guess_feedback_routing(brain, monkeypatch):
    monkeypatch.setattr(sg, "_make_code", lambda rng: [1, 2, 3, 4])
    run(brain, "gm_mastermind", "code breaker")
    assert brain.skills["gm_move"][0]("4321") is not None
    reply = run(brain, "gm_move", "4 3 2 1")
    assert "0 exact" in reply and "4 misplaced" in reply
    assert "1/10" in reply


def test_mm_win_by_digits_and_colour_initials(brain, monkeypatch):
    monkeypatch.setattr(sg, "_make_code", lambda rng: [1, 2, 3, 4])
    run(brain, "gm_mastermind", "mastermind")
    win = run(brain, "gm_move", "1234")
    assert "Code broken" in win
    assert score_file(brain)["games"]["mm"]["won"] == 1

    sg.reset_for_tests()
    monkeypatch.setattr(sg, "_make_code", lambda rng: [1, 2, 3, 4])
    run(brain, "gm_mastermind", "mastermind")
    win2 = run(brain, "gm_move", "r g b y")              # red green blue yellow
    assert "Code broken" in win2


def test_mm_loss_after_ten_failed_tries(brain, monkeypatch):
    monkeypatch.setattr(sg, "_make_code", lambda rng: [2, 3, 4, 5])
    run(brain, "gm_mastermind", "mastermind")
    final = ""
    for _ in range(10):
        final = run(brain, "gm_move", "1111")
    assert "the code was 2345" in final
    assert score_file(brain)["games"]["mm"]["lost"] == 1


# ==========================================================================
# Tic-tac-toe — ASCII board, AI policy, full games
# ==========================================================================

def test_ttt_start_renders_ascii_grid(brain):
    reply = run(brain, "gm_ttt", "play tic tac toe")
    assert "You are X" in reply
    assert "a   b   c" in reply                          # column header
    assert "|" in reply and "1" in reply                 # grid rows


def test_ttt_ai_policy_pure_functions(brain):
    # takes an immediate win...
    board = ["O", "O", " ", "X", "X", " ", " ", " ", " "]
    assert sg._ttt_ai_pick(board) == 2
    # ...blocks an immediate threat when it cannot win itself...
    board = ["X", "X", " ", " ", " ", " ", " ", " ", " "]
    assert sg._ttt_ai_pick(board) == 2
    # ...prefers centre over corner over side on an empty board.
    assert sg._ttt_ai_pick([" "] * 9) == 4
    assert sg._coord_to_index("b2") == 4
    assert sg._coord_to_index("C3") == 8
    assert sg._coord_to_index("d9") is None


def test_ttt_full_game_via_routing_ends_cleanly(brain):
    run(brain, "gm_ttt", "play ttt")
    moves = ["b2", "a3", "a1", "c1", "b3"]
    last = ""
    for mv in moves:
        if brain.skills["gm_move"][0](mv) is None:
            break                                        # game already over
        last = run(brain, "gm_move", mv)
    assert any(w in last for w in ("My game", "draw", "Three in a row"))


def test_ttt_never_loses_optimal_play_sim(brain):
    """Exhaustive sweep: with its heuristic policy JARVIS never loses."""
    stats = {"ai": 0, "draw": 0}

    def human_turn(board):
        result = sg._ttt_winner(board)
        if result is not None:
            return result
        for i in range(9):
            if board[i] != " ":
                continue
            trial = list(board)
            trial[i] = "X"
            outcome = ai_turn(trial)
            if outcome is None:
                return None                              # X won somewhere
            stats["ai" if outcome == "O" else "draw"] += 1
        return "pending"

    def ai_turn(board):
        result = sg._ttt_winner(board)
        if result is not None:
            return result
        board[sg._ttt_ai_pick(board)] = "O"
        return human_turn(board)

    empty = [" "] * 9
    for first in range(9):
        board = list(empty)
        board[first] = "X"
        board[sg._ttt_ai_pick(board)] = "O"
        outcome = human_turn(board)
        assert outcome != "X", f"human victory found from opening {first}"
    assert stats["ai"] + stats["draw"] > 100            # sweep was real


# ==========================================================================
# gm_quit / gm_score / gm_status - meta behaviour
# ==========================================================================

def test_quit_counts_as_loss_then_reports_idle(brain):
    run(brain, "gm_guess", "guess the number")
    reply = run(brain, "gm_quit", "resign")
    assert "abandoned" in reply and "loss" in reply.lower()
    assert score_file(brain)["games"]["guess"]["lost"] == 1
    again = run(brain, "gm_quit", "give up")
    assert "no game in progress" in again


def test_score_roundtrip_persists_across_reset(brain):
    run(brain, "gm_hangman", "play hangman")
    run(brain, "gm_quit", "quit the game")               # hangman loss
    run(brain, "gm_ttt", "tic tac toe")
    run(brain, "gm_quit", "i give up")                   # ttt loss
    raw = score_file(brain)
    assert raw["games"]["hangman"]["lost"] == 1
    assert raw["games"]["ttt"]["lost"] == 1
    # Simulate a restart: drop caches, keep the same file on disk.
    sg.reset_for_tests()
    report = run(brain, "gm_score", "what's my game score")
    assert "Hangman: 0W / 1L / 0D" in report
    assert "Tic-Tac-Toe: 0W / 1L / 0D" in report
    assert "Overall: 0W / 2L / 0D" in report
    assert "win rate" in report


def test_gm_score_blank_scoreboard_message(brain):
    reply = run(brain, "gm_score", "show my scoreboard")
    assert "blank" in reply and reply.endswith(".")


def test_corrupt_scores_recover_fresh_and_rewrite(brain):
    with open(sg.SCORE_FILE, "w", encoding="utf-8") as fh:
        fh.write("{this is definitely not json")
    sg.reset_for_tests()
    reply = run(brain, "gm_score", "game record")
    assert "blank" in reply                              # no crash, fresh
    sg.record_result("hangman", "won")
    assert score_file(brain)["games"]["hangman"]["won"] == 1


def test_status_idle_and_active(brain):
    idle = run(brain, "gm_status", "show me the board")
    assert "No active game" in idle
    run(brain, "gm_ttt", "ttt")
    live = run(brain, "gm_status", "current game")
    assert "Tic-Tac-Toe, in progress" in live and "a   b   c" in live
    run(brain, "gm_guess", "number game")
    hunt = run(brain, "gm_status", "game status")
    assert "attempt 0 of 7" in hunt


def test_starting_new_game_scraps_the_old_one(brain):
    run(brain, "gm_hangman", "hangman")
    reply = run(brain, "gm_mastermind", "play mastermind")
    assert "Scrapped the previous game" in reply
    assert brain.skills["gm_move"][0]("1111") is not None  # mm now active


# ==========================================================================
# Containment
# ==========================================================================

def test_wrap_contains_crashes_in_persona(brain, monkeypatch):
    def boom(_s, _t):
        raise RuntimeError("board exploded")

    monkeypatch.setattr(sg, "_render_hangman", boom)
    run(brain, "gm_hangman", "play hangman")
    reply = run(brain, "gm_move", "e")
    assert "jammed" in reply and reply.endswith(", sir.")
