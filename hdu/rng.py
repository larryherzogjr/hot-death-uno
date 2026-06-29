"""Seeded RNG helpers.

All engine randomness flows through a ``random.Random`` whose state is captured
in ``GameState.rng_state`` so any game replays deterministically. The engine
never touches the global ``random`` module or the wall clock.
"""

from __future__ import annotations

import random
from typing import Any

RngState = tuple[Any, ...]


def new_rng(seed: int | None = None) -> random.Random:
    return random.Random(seed)


def rng_from_state(state: RngState) -> random.Random:
    r = random.Random()
    r.setstate(state)
    return r


def state_of(rng: random.Random) -> RngState:
    return rng.getstate()
