"""M3 — Double Skip: skips the next two players; worth 40 held."""

from __future__ import annotations

from hdu.actions import PlayCard
from hdu.cards import Card, CardId, Color
from hdu.effects import matches
from hdu.engine import apply
from hdu.events import PlayerSkipped
from hdu.scoring import card_points
from hdu.state import DiscardEntry, GameState, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
DOUBLE_SKIP = Card(CardId.DOUBLE_SKIP, Color.RED)


def _state(hands, top, *, to_act=0, direction=1, draw=()):
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=tuple(draw),
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=to_act,
        direction=direction,
        dealer=0,
        rng_state=__import__("random").Random(0).getstate(),
    )


def test_double_skip_skips_two_players():
    hands = [[NUM(Color.RED, 5), DOUBLE_SKIP]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    new, events = apply(st, PlayCard(1))
    assert new.to_act == 3  # P1 and P2 both skipped
    skipped = {e.player for e in events if isinstance(e, PlayerSkipped)}
    assert skipped == {1, 2}


def test_double_skip_respects_direction():
    hands = [[NUM(Color.RED, 5), DOUBLE_SKIP]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3), direction=-1)
    new, _ = apply(st, PlayCard(1))
    assert new.to_act == 1  # from P0 going -1: skip P3, P2 -> land on P1


def test_double_skip_matches_plain_skip_by_symbol():
    skip_top = DiscardEntry(Card(CardId.SKIP, Color.BLUE), Color.BLUE, None)
    assert matches(DOUBLE_SKIP, skip_top)  # skip symbol
    assert matches(Card(CardId.SKIP, Color.GREEN), skip_top)


def test_double_skip_held_value_is_40():
    assert card_points(DOUBLE_SKIP) == 40
