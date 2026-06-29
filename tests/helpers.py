"""Shared test helpers.

The card-conservation invariant is the single most valuable check in the suite
(HANDOFF §10): after *every* action the total card count must equal DECK_SIZE.
Wire :func:`assert_conservation` in after each ``apply`` as cards get added.
"""

from __future__ import annotations

from hdu.cards import DECK_SIZE
from hdu.engine import card_count
from hdu.state import GameState


def assert_conservation(state: GameState) -> None:
    total = card_count(state)
    assert total == DECK_SIZE, f"card conservation broken: {total} != {DECK_SIZE}"
