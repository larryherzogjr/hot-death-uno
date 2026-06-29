"""Harness helper: drive a dealt hand to completion with a set of players.

A *consumer* of the engine — it loops over ``legal_actions`` / ``apply`` and
lets each seat's ``Player`` decide. Used by the CLI and by tests/golden games.
An optional ``observer(state, events)`` callback is invoked after every action.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .engine import apply, legal_actions, new_hand, settle_hand
from .events import Event
from .players.base import Player
from .state import GameState, Phase
from .view import view_for

Observer = Callable[[GameState, tuple[Event, ...]], None]

# Safety valve so a buggy loop can never hang a test run.
_MAX_ACTIONS = 100_000


def play_hand(
    state: GameState,
    players: Sequence[Player],
    observer: Observer | None = None,
) -> GameState:
    steps = 0
    while state.phase not in (Phase.HAND_OVER, Phase.GAME_OVER):
        steps += 1
        if steps > _MAX_ACTIONS:
            raise RuntimeError("play_hand exceeded action ceiling — likely a loop bug")
        actor = state.to_act
        action = players[actor].decide(view_for(state, actor), legal_actions(state))
        state, events = apply(state, action)
        if observer is not None:
            observer(state, events)
    return state


def play_game(
    seed: int,
    players: Sequence[Player],
    num_players: int = 4,
    hand_size: int = 7,
    observer: Observer | None = None,
) -> GameState:
    """Play hands until someone reaches the win threshold. Returns the final
    GAME_OVER state with running scores and ``winner`` set to the lowest total."""
    state = new_hand(seed, num_players=num_players, hand_size=hand_size)
    while True:
        state = play_hand(state, players, observer)  # runs to HAND_OVER
        state, events = settle_hand(state)
        if observer is not None:
            observer(state, events)
        if state.phase is Phase.GAME_OVER:
            return state
