"""M5 — last-card draw effects, the Draw Two deal condition, and §8 ordering."""

from __future__ import annotations

import random

import pytest

from hdu.actions import PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, new_hand
from hdu.scoring import score_hand
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
DRAW_TWO = Card(CardId.DRAW_TWO, Color.RED)
DRAW_FOUR = Card(CardId.DRAW_FOUR, Color.WILD)
SIXTY_NINE = Card(CardId.SIXTY_NINE, Color.YELLOW, 9)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)


def _play_state(hands, top, *, draw_n=8):
    draw = tuple(NUM(Color.BLUE, i % 10) for i in range(draw_n))
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=draw,
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )


def _hand_over(hands, winner):
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=(),
        discard=(DiscardEntry(NUM(Color.RED, 3), Color.RED, 3),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
        phase=Phase.HAND_OVER,
        winner=winner,
    )


def test_last_card_draw_two_still_hits_next_player():
    st = _play_state([[DRAW_TWO], [NUM(Color.GREEN, 1)]] + [[NUM(Color.GREEN, 1)]] * 2,
                     top=NUM(Color.RED, 5))
    new, _ = apply(st, PlayCard(0))
    assert new.phase is Phase.HAND_OVER and new.winner == 0
    assert len(new.players[1].hand) == 1 + 2  # next player drew 2


def test_last_card_draw_four_still_hits_next_player():
    st = _play_state([[DRAW_FOUR], [NUM(Color.GREEN, 1)]] + [[NUM(Color.GREEN, 1)]] * 2,
                     top=NUM(Color.RED, 3))
    new, _ = apply(st, PlayCard(0))
    assert new.phase is Phase.HAND_OVER and new.winner == 0
    assert len(new.players[1].hand) == 1 + 4  # no stack, just a direct draw


def test_draw_two_starter_makes_dealer_draw_two():
    for seed in range(300):
        st = new_hand(seed, num_players=4, hand_size=7)
        if st.top.card.id is CardId.DRAW_TWO:
            assert len(st.players[st.dealer].hand) == 7 + 2
            return
    pytest.skip("no Draw Two starter in the searched seeds")


def test_sixty_nine_override_applies_before_halving():
    # Step 2 (69) then step 4 (halve): 69 -> 34, proving the order.
    st = _hand_over([[], [SIXTY_NINE, HOLY_DEFENDER, NUM(Color.RED, 5)]], winner=0)
    assert score_hand(st)[1] == int(69 / 2)


def test_sixty_nine_override_then_double():
    st = _hand_over([[], [SIXTY_NINE, BOUNCE, NUM(Color.RED, 5)]], winner=0)
    assert score_hand(st)[1] == 69 * 2
