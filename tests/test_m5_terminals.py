"""M5 — terminal & scoring conditions: bastard-four, Quitter+Fucker=1000, the
Magic 5 → Mystery Draw knock-on, and all-eliminated 'lowest deals next'."""

from __future__ import annotations

import random

from hdu.actions import PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, settle_hand
from hdu.events import BastardHand
from hdu.scoring import card_held_value, score_hand
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
QUITTER = Card(CardId.QUITTER, Color.GREEN, 0)
DUMP = Card(CardId.DUMP, Color.YELLOW, 0)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)
MYSTERY = Card(CardId.MYSTERY_DRAW, Color.WILD)
MAGIC_5 = Card(CardId.MAGIC_5, Color.RED, 5)


def _hand_over(hands, winner, aids=None):
    aids = aids or [0] * len(hands)
    players = tuple(
        PlayerState(id=i, hand=tuple(h), aids_count=aids[i]) for i, h in enumerate(hands)
    )
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


def test_bastard_four_ends_hand_and_holder_scores_zero():
    # P1 holds all four 0s; P0's next play triggers the during-play check.
    hands = [
        [NUM(Color.RED, 5), NUM(Color.RED, 6)],
        [QUITTER, DUMP, BOUNCE, HOLY_DEFENDER],
        [NUM(Color.GREEN, 1)],
        [NUM(Color.GREEN, 1)],
    ]
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    st = GameState(
        players=players,
        draw_pile=(),
        discard=(DiscardEntry(NUM(Color.RED, 3), Color.RED, 3),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )
    new, events = apply(st, PlayCard(0))  # P0 plays Red 5
    assert new.phase is Phase.HAND_OVER
    assert new.winner == 1
    assert any(isinstance(e, BastardHand) and e.holder == 1 for e in events)
    assert score_hand(new)[1] == 0  # the bastard holder scores 0


def test_quitter_plus_fucker_is_worth_1000():
    st = _hand_over([[], [QUITTER, BOUNCE, NUM(Color.RED, 5)]], winner=0)
    assert score_hand(st)[1] == 1000


def test_magic_5_makes_mystery_draw_negative_fifty():
    assert card_held_value(MYSTERY, (MYSTERY, MAGIC_5)) == -50


def test_all_eliminated_hand_is_dealt_by_lowest_total():
    # No winner; P2 has the smallest hand total, so P2 deals next.
    hands = [
        [NUM(Color.RED, 9)],   # 9
        [NUM(Color.RED, 8)],   # 8
        [NUM(Color.RED, 1)],   # 1 -> lowest
        [NUM(Color.RED, 7)],   # 7
    ]
    players = tuple(
        PlayerState(id=i, hand=tuple(h), eliminated=True) for i, h in enumerate(hands)
    )
    st = GameState(
        players=players,
        draw_pile=(),
        discard=(DiscardEntry(NUM(Color.RED, 3), Color.RED, 3),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
        phase=Phase.HAND_OVER,
        winner=None,
    )
    nxt, _ = settle_hand(st)
    assert nxt.dealer == 2  # lowest hand-total deals
