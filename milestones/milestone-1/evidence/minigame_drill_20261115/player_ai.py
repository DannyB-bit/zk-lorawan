# player_ai.py — mini-game PLAYER, coded by Researcher B (RakMiner-B).
# Sent to Researcher A over LoRa chirps (245B sealed frames, raw-byte mode).
#
# Contract: imports game_core (A's file) and plays the number-guessing game
# using ONLY the high/low feedback from Game.guess() — no peeking at the
# secret that Game.guess() happens to leak in its return tuple.
#
# Entry points:
#   play_game(game) -> dict   # play a given Game instance, return the transcript
#   main()                     # CLI: play a fresh game_core.Game(), print JSON
#
# Binary search over [lo, hi] needs at most floor(log2(hi-lo+1)) + 1 guesses.
# For the default 1..100 range that is 7 — exactly the core's `left = 7` budget.

import json
import math

try:
    from game_core import Game
except ImportError:  # allow running from a sibling directory
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from game_core import Game


def play_game(game):
    """Binary-search the secret. Uses only ('high'|'low'|'win'|'lose') feedback."""
    lo, hi = game.lo, game.hi
    transcript = []
    result = ("lose", None)
    guess_no = 0
    # worst-case guesses for this range
    budget = int(math.floor(math.log2(hi - lo + 1))) + 1 if hi >= lo else 1
    while lo <= hi and game.left > 0:
        guess_no += 1
        g = (lo + hi) // 2
        feedback, _secret = game.guess(g)   # secret deliberately ignored
        transcript.append({"guess_no": guess_no, "guess": g,
                           "feedback": feedback, "lo": lo, "hi": hi})
        if feedback == "win":
            result = ("win", g)
            break
        if feedback == "high":      # guess > secret
            hi = g - 1
        elif feedback == "low":     # guess < secret
            lo = g + 1
        else:                       # "lose" — out of guesses
            result = ("lose", None)
            break
    else:
        result = ("lose", None)
    return {
        "outcome": result[0],
        "guesses_used": guess_no,
        "worst_case_guesses": budget,
        "within_budget": guess_no <= budget and guess_no <= 7,
        "transcript": transcript,
    }


def main():
    game = Game()
    out = play_game(game)
    out["core_left_after"] = game.left
    print(json.dumps(out, indent=1))
    return 0 if out["outcome"] == "win" else 1


if __name__ == "__main__":
    raise SystemExit(main())
