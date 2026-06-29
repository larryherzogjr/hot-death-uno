"""Structured events emitted by ``apply``.

Consumers (CLI, AI, a future logger/network layer) react to events; the engine
never knows they exist. New event types are added as milestones add mechanics.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import Card, Color


@dataclass(frozen=True)
class CardPlayed:
    player: int
    card: Card


@dataclass(frozen=True)
class PlayerDrew:
    player: int
    count: int


@dataclass(frozen=True)
class PlayerSkipped:
    player: int


@dataclass(frozen=True)
class DirectionReversed:
    direction: int


@dataclass(frozen=True)
class ColorChosen:
    player: int
    color: Color


@dataclass(frozen=True)
class DeckReshuffled:
    new_draw_count: int


@dataclass(frozen=True)
class UnoCalled:
    player: int


@dataclass(frozen=True)
class PlayerWonHand:
    player: int


@dataclass(frozen=True)
class TurnPassed:
    player: int


@dataclass(frozen=True)
class PlayerEliminated:
    player: int


@dataclass(frozen=True)
class QuitterStarted:
    origin: int
    target: int


@dataclass(frozen=True)
class GlasnostStarted:
    origin: int
    target: int


@dataclass(frozen=True)
class HandRevealed:
    player: int


@dataclass(frozen=True)
class SpreaderStarted:
    origin: int


@dataclass(frozen=True)
class PennStateRevealed:
    player: int


@dataclass(frozen=True)
class LuckRevealed:
    player: int  # revealed Luck o' the Irish to shave 1 off a punishment draw


@dataclass(frozen=True)
class HandScored:
    hand_winner: int | None
    gains: tuple[tuple[int, int], ...]  # (player_id, points gained this hand)


@dataclass(frozen=True)
class BastardHand:
    holder: int  # held all four bastard cards — hand ends, they score 0


@dataclass(frozen=True)
class GameOver:
    winner: int  # lowest running total
    scores: tuple[tuple[int, int], ...]  # (player_id, final running total)


Event = (
    CardPlayed
    | PlayerDrew
    | PlayerSkipped
    | DirectionReversed
    | ColorChosen
    | DeckReshuffled
    | UnoCalled
    | PlayerWonHand
    | TurnPassed
    | PlayerEliminated
    | QuitterStarted
    | GlasnostStarted
    | HandRevealed
    | SpreaderStarted
    | PennStateRevealed
    | LuckRevealed
    | BastardHand
    | HandScored
    | GameOver
)
