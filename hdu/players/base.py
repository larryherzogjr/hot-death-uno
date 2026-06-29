"""The Player protocol. Any object with ``decide`` can drive a seat."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..actions import Action
from ..view import PlayerView


@runtime_checkable
class Player(Protocol):
    def decide(self, view: PlayerView, legal_actions: list[Action]) -> Action:
        """Choose exactly one action from ``legal_actions`` given the (redacted)
        view of the game. Must return one of the offered actions."""
        ...
