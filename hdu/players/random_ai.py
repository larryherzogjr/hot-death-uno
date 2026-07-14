"""Random-legal baseline opponent (HANDOFF §9).

Deliberately dumb: it prefers playing a card over drawing, and when choosing a
color it picks the one it holds most of — but otherwise chooses at random. All
randomness is seeded so games replay. Strategy lives entirely here, behind the
``Player`` protocol; the engine knows nothing about it.
"""

from __future__ import annotations

import random

from ..actions import Action, ChooseColor, ChooseVictim, PlayCard, Reveal
from ..cards import Color
from ..scoring import card_held_value
from ..view import PlayerView


class RandomAI:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)

    def decide(self, view: PlayerView, legal_actions: list[Action]) -> Action:
        colors = [a for a in legal_actions if isinstance(a, ChooseColor)]
        if colors:
            return self._choose_color(view, colors)

        victims = [a for a in legal_actions if isinstance(a, ChooseVictim)]
        if victims:
            # Target the opponent with the fewest cards (closest to going out).
            counts = {o.id: o.hand_count for o in view.opponents}
            return min(victims, key=lambda a: counts.get(a.player, 0))

        # Revealing a protective card (e.g. Penn State vs Spreader) is free — take it.
        reveals = [a for a in legal_actions if isinstance(a, Reveal)]
        if reveals:
            return reveals[0]

        plays = [a for a in legal_actions if isinstance(a, PlayCard)]
        if plays:
            # The v1 strategy is still deliberately shallow, but it sheds the
            # costliest legal card first instead of choosing every play equally.
            # Randomness only breaks equal-value ties and remains seeded.
            values = {
                a: card_held_value(
                    view.hand[a.hand_index], view.hand, len(view.opponents)
                )
                for a in plays
            }
            highest = max(values.values())
            return self._rng.choice([a for a in plays if values[a] == highest])

        # Only drawing, declining, or passing remains.
        return legal_actions[0]

    def _choose_color(self, view: PlayerView, colors: list[ChooseColor]) -> Action:
        counts: dict[Color, int] = {}
        for card in view.hand:
            if not card.is_wild:
                counts[card.color] = counts.get(card.color, 0) + 1
        if counts:
            best = max(counts, key=lambda color: counts[color])
            for a in colors:
                if a.color is best:
                    return a
        return self._rng.choice(colors)
