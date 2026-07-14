"""M4 — Luck o' the Irish: shaves 1 off any punishment draw, but never the
draw you take for being unable to play on your own turn."""

from __future__ import annotations

import random

from hdu.actions import ChooseColor, Decline, DrawCard, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, legal_actions
from hdu.events import LuckRevealed
from hdu.state import DiscardEntry, GameState, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
DRAW_TWO = Card(CardId.DRAW_TWO, Color.RED)
DRAW_FOUR = Card(CardId.DRAW_FOUR, Color.WILD)
LUCK = Card(CardId.LUCK, Color.GREEN, 4)


def _state(hands, top=NUM(Color.RED, 3), *, draw_n=20, to_act=0):
    draw = tuple(NUM(Color.BLUE, i % 10) for i in range(draw_n))
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=draw,
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=to_act,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )


def test_luck_reduces_a_draw_two():
    hands = [[DRAW_TWO, NUM(Color.RED, 5)], [LUCK, NUM(Color.GREEN, 7)]] + [[NUM(Color.RED, 1)]] * 2
    st = _state(hands)
    st, events = apply(st, PlayCard(0))  # P0 plays Draw Two on P1
    assert len(st.players[1].hand) == 2 + 1  # drew 2 − 1 = 1
    assert any(isinstance(e, LuckRevealed) and e.player == 1 for e in events)
    assert LUCK in st.players[1].hand  # Luck retained, not discarded


def test_luck_reduces_a_draw_stack_eat():
    hands = [[DRAW_FOUR, NUM(Color.RED, 5)], [LUCK, NUM(Color.GREEN, 7)]] + [[NUM(Color.RED, 1)]] * 2
    st = _state(hands)
    st, _ = apply(st, PlayCard(0))
    st, _ = apply(st, ChooseColor(Color.RED))  # draw_total 4, target P1
    st, events = apply(st, Decline())
    assert len(st.players[1].hand) == 2 + 3  # 4 − 1 = 3
    assert any(isinstance(e, LuckRevealed) for e in events)


def test_luck_does_not_reduce_the_cant_play_draw():
    # P0 holds Luck but cannot play on a Blue 9 top; the voluntary draw is full.
    hands = [[LUCK, NUM(Color.RED, 5)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, top=NUM(Color.BLUE, 9))
    assert DrawCard() in legal_actions(st)
    st, events = apply(st, DrawCard())
    assert len(st.players[0].hand) == 3  # drew the full 1, no reduction
    assert not any(isinstance(e, LuckRevealed) for e in events)
