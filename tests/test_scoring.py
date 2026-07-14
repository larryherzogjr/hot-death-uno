"""M2 — end-of-hand scoring, running totals, dealer rotation, game end."""

from __future__ import annotations

import random

import pytest

from hdu.cards import Card, CardId, Color
from hdu.engine import WIN_THRESHOLD, new_hand, settle_hand
from hdu.play import play_game
from hdu.players.random_ai import RandomAI
from hdu.scoring import card_points, score_hand
from hdu.state import DiscardEntry, GameState, Phase, PlayerState
from tests.helpers import assert_conservation

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731


def test_card_points_vanilla_values():
    assert card_points(NUM(Color.RED, 7)) == 7
    assert card_points(NUM(Color.BLUE, 0)) == 0
    assert card_points(Card(CardId.SKIP, Color.RED)) == 20
    assert card_points(Card(CardId.REVERSE, Color.GREEN)) == 20
    assert card_points(Card(CardId.DRAW_TWO, Color.YELLOW)) == 20
    assert card_points(Card(CardId.WILD, Color.WILD)) == 40
    assert card_points(Card(CardId.DRAW_FOUR, Color.WILD)) == 50  # graduated in M4


def test_draw_four_type_held_values():
    assert card_points(Card(CardId.HOT_DEATH, Color.WILD)) == 100
    assert card_points(Card(CardId.DELAYED_BLAST, Color.WILD)) == 100
    assert card_points(Card(CardId.HARVESTER, Color.WILD)) == 0
    assert card_points(Card(CardId.MAGIC_5, Color.RED, 5)) == -5


def _hand_over_state(hands, winner):
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


def test_score_hand_winner_zero_losers_sum():
    st = _hand_over_state(
        [[], [NUM(Color.RED, 5), Card(CardId.SKIP, Color.RED)], [NUM(Color.BLUE, 9)], []],
        winner=0,
    )
    gains = score_hand(st)
    assert gains == {0: 0, 1: 25, 2: 9, 3: 0}


def test_settle_accumulates_and_rotates_dealer():
    st = _hand_over_state([[], [NUM(Color.RED, 5)], [NUM(Color.BLUE, 9)], []], winner=0)
    nxt, events = settle_hand(st)
    assert nxt.phase in (Phase.PLAY, Phase.CHOOSE_COLOR)  # next hand dealt
    assert [p.score for p in nxt.players] == [0, 5, 9, 0]
    assert nxt.dealer == 1  # rotated from 0
    assert_conservation(nxt)


def test_settle_ends_game_at_threshold_lowest_wins():
    # P2 crosses 1000; P0 has the lowest total and should win.
    players = (
        PlayerState(id=0, hand=(), score=120),
        PlayerState(id=1, hand=(NUM(Color.RED, 5),), score=300),
        PlayerState(id=2, hand=(Card(CardId.WILD, Color.WILD),), score=980),
        PlayerState(id=3, hand=(NUM(Color.BLUE, 9),), score=400),
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
        winner=0,
    )
    over, events = settle_hand(st)
    assert over.phase is Phase.GAME_OVER
    assert over.players[2].score == 980 + 40  # >= 1000
    assert over.winner == 0  # lowest total


def test_settle_requires_hand_over():
    st = new_hand(seed=1)
    with pytest.raises(ValueError):
        settle_hand(st)


@pytest.mark.parametrize("seed", range(15))
def test_full_game_terminates_and_conserves(seed):
    counts: list[int] = []

    def observer(s, events):
        counts.append(
            sum(len(p.hand) for p in s.players) + len(s.draw_pile) + len(s.discard)
        )

    players = [RandomAI(seed=200 + i) for i in range(4)]
    final = play_game(seed, players, observer=observer)

    assert final.phase is Phase.GAME_OVER
    assert max(p.score for p in final.players) >= WIN_THRESHOLD
    # Winner has the minimum running total.
    assert final.players[final.winner].score == min(p.score for p in final.players)
    assert all(c == 113 for c in counts)  # conservation every action, every hand


def test_full_game_is_deterministic():
    def run():
        players = [RandomAI(seed=200 + i) for i in range(4)]
        final = play_game(7, players)
        return final.winner, tuple(p.score for p in final.players)

    assert run() == run()
