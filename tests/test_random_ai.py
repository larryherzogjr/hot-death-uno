"""The baseline AI follows its documented deterministic heuristics."""

from dataclasses import replace

from hdu.actions import Decline, DrawCard, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import new_hand
from hdu.players.random_ai import RandomAI
from hdu.view import view_for


def test_ai_prefers_the_highest_value_legal_play():
    state = new_hand(0)
    view = replace(
        view_for(state, state.to_act),
        hand=(
            Card(CardId.NUMBER, Color.RED, 1),
            Card(CardId.DRAW_FOUR, Color.WILD),
        ),
    )

    action = RandomAI(seed=1).decide(
        view,
        [PlayCard(0), DrawCard(), PlayCard(1)],
    )

    assert action == PlayCard(1)


def test_ai_uses_an_available_defense_instead_of_declining():
    state = new_hand(0)
    view = replace(
        view_for(state, state.to_act),
        hand=(Card(CardId.HOLY_DEFENDER, Color.RED, 0),),
    )

    action = RandomAI(seed=1).decide(view, [Decline(), PlayCard(0)])

    assert action == PlayCard(0)
