"""Perspective filtering — present from day one (HANDOFF §2).

``view_for(state, player_id)`` redacts other players' hands down to counts. The
AI and network clients consume the *view*, never raw ``GameState``.
Turn/legal-action logic is layered on in M1+; M0 establishes the seam.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import Card
from .state import DiscardEntry, GameState, Pending, Phase


@dataclass(frozen=True)
class OpponentView:
    id: int
    hand_count: int
    score: int
    eliminated: bool
    called_uno: bool
    revealed_hand: tuple[Card, ...] | None = None  # set when Glasnost revealed it


@dataclass(frozen=True)
class PlayerView:
    me: int
    hand: tuple[Card, ...]
    opponents: tuple[OpponentView, ...]
    top: DiscardEntry
    to_act: int
    direction: int
    phase: Phase
    pending: Pending | None
    draw_count: int


def view_for(state: GameState, player_id: int) -> PlayerView:
    me = state.players[player_id]
    opponents = tuple(
        OpponentView(
            id=p.id,
            hand_count=len(p.hand),
            score=p.score,
            eliminated=p.eliminated,
            called_uno=p.called_uno,
            revealed_hand=p.hand if p.revealed else None,
        )
        for p in state.players
        if p.id != player_id
    )
    return PlayerView(
        me=player_id,
        hand=me.hand,
        opponents=opponents,
        top=state.top,
        to_act=state.to_act,
        direction=state.direction,
        phase=state.phase,
        pending=state.pending,
        draw_count=len(state.draw_pile),
    )
