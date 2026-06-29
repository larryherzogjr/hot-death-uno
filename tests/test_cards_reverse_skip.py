"""M3 — Reverse Skip: reverse direction, then skip one in the new direction; 40 held."""

from __future__ import annotations

from hdu.actions import PlayCard
from hdu.cards import Card, CardId, Color
from hdu.effects import matches
from hdu.engine import apply
from hdu.events import DirectionReversed, PlayerSkipped
from hdu.scoring import card_points
from hdu.state import DiscardEntry, GameState, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
REVERSE_SKIP = Card(CardId.REVERSE_SKIP, Color.RED)


def _state(hands, top, *, to_act=0, direction=1):
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=(),
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=to_act,
        direction=direction,
        dealer=0,
        rng_state=__import__("random").Random(0).getstate(),
    )


def test_reverse_skip_flips_then_skips_one():
    hands = [[NUM(Color.RED, 5), REVERSE_SKIP]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))  # direction +1
    new, events = apply(st, PlayCard(1))
    assert new.direction == -1
    # New direction -1 from P0: skip P3, land on P2.
    assert new.to_act == 2
    assert any(isinstance(e, DirectionReversed) for e in events)
    assert {e.player for e in events if isinstance(e, PlayerSkipped)} == {3}


def test_reverse_skip_from_negative_direction():
    hands = [[NUM(Color.RED, 5), REVERSE_SKIP]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3), direction=-1)
    new, _ = apply(st, PlayCard(1))
    assert new.direction == 1
    # New direction +1 from P0: skip P1, land on P2.
    assert new.to_act == 2


def test_reverse_skip_matches_plain_reverse_by_symbol():
    rev_top = DiscardEntry(Card(CardId.REVERSE, Color.BLUE), Color.BLUE, None)
    assert matches(REVERSE_SKIP, rev_top)


def test_reverse_skip_held_value_is_40():
    assert card_points(REVERSE_SKIP) == 40
