"""Action variants — the inputs to ``apply``.

A consumer (CLI or AI) is handed a ``PlayerView`` plus ``legal_actions(state)``
and returns exactly one of these. If ``legal_actions`` is correct, illegal
states are unreachable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import Color


@dataclass(frozen=True)
class PlayCard:
    hand_index: int  # index into the acting player's hand


@dataclass(frozen=True)
class DrawCard:
    pass


@dataclass(frozen=True)
class ChooseColor:
    color: Color


@dataclass(frozen=True)
class Pass:
    """Only offered when a player can neither play nor draw (rare corner)."""


@dataclass(frozen=True)
class Reveal:
    """Reveal a card from hand to satisfy a response window (e.g. Penn State vs
    Spreader). The card is shown, not discarded — it stays in hand."""

    hand_index: int


@dataclass(frozen=True)
class Decline:
    """In a response window, decline to defend and take the punishment."""


@dataclass(frozen=True)
class ChooseVictim:
    """Name a player to be eliminated (e.g. M.A.D.)."""

    player: int


Action = PlayCard | DrawCard | ChooseColor | Pass | Reveal | Decline | ChooseVictim
