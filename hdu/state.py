"""Core state model: frozen dataclasses describing a game in progress.

These mirror HANDOFF §3. Everything is immutable; the engine returns new state
objects rather than mutating. ``Pending`` carries every response/attack window.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .cards import Card, CardId, Color
from .rng import RngState


class Phase(str, Enum):
    """What kind of decision the engine is waiting on. ``str`` mixin keeps it
    cheap to compare/serialize while staying type-safe."""

    PLAY = "play"
    CHOOSE_COLOR = "choose_color"
    CHOOSE_VICTIM = "choose_victim"
    RESPOND = "respond"
    HAND_OVER = "hand_over"
    GAME_OVER = "game_over"


@dataclass(frozen=True)
class DiscardEntry:
    """A card on the discard pile plus what it currently *counts as*.

    ``eff_color`` / ``eff_number`` can diverge from the printed card: a wild sets
    the effective color, and Mystery Draw reads ``eff_number`` of the card it
    lands on.
    """

    card: Card
    eff_color: Color
    eff_number: int | None


@dataclass(frozen=True)
class PlayerState:
    id: int
    hand: tuple[Card, ...]
    score: int = 0  # running game score; low is good (golf scoring)
    aids_count: int = 0  # AIDS/Share cards acquired; −10 each per lost hand
    eliminated: bool = False  # eliminated from the current hand (frozen hand)
    called_uno: bool = False
    revealed: bool = False  # hand shown to all (Glasnost)


@dataclass(frozen=True)
class Pending:
    """The response/attack stack. ``None`` on GameState means we are not in
    stack-resolution mode."""

    kind: str  # "draw_stack" | "quitter" | "spreader" | "glasnost"
    target: int  # player who must respond
    origin: int  # player who started the attack
    draw_total: int = 0  # draw_stack: accumulated cards; spreader: per-victim count
    chain: tuple[CardId, ...] = ()
    undefendable: bool = False
    queue: tuple[int, ...] = ()  # remaining targets after `target` (spreader, …)
    penn_revealer: int | None = None  # spreader: first player to show Penn State


@dataclass(frozen=True)
class GameState:
    players: tuple[PlayerState, ...]
    draw_pile: tuple[Card, ...]
    discard: tuple[DiscardEntry, ...]
    to_act: int  # whose decision the engine is waiting on
    direction: int  # +1 or -1
    dealer: int
    rng_state: RngState
    phase: Phase = Phase.PLAY
    pending: Pending | None = None
    winner: int | None = None  # hand winner at HAND_OVER; game winner at GAME_OVER
    hand_size: int = 7  # config carried so the engine can deal the next hand

    @property
    def top(self) -> DiscardEntry:
        return self.discard[-1]
