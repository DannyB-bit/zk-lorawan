# game_core.py — mini-game CORE, coded by Researcher A (RakMiner-A).
# Sent to Researcher B over LoRa chirps (245B sealed frames, raw-byte mode).
import random


class Game:
    """Number-guessing game core. Deterministic via seed."""

    def __init__(self, lo=1, hi=100, seed=1337):
        self.lo, self.hi = lo, hi
        self.secret = random.Random(seed).randint(lo, hi)
        self.left = 7  # max guesses

    def guess(self, g):
        """Return (result, secret): result in win/lose/high/low."""
        if self.left <= 0:
            return ("lose", self.secret)
        self.left -= 1
        if g == self.secret:
            return ("win", self.secret)
        return ("low" if g < self.secret else "high", self.secret)

    def won(self, result):
        return result[0] == "win"


if __name__ == "__main__":
    g = Game()
    print("core self-test: secret in", g.lo, "-", g.hi, "left", g.left)
