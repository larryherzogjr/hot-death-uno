"""M0 — deck composition and the seeded deal."""

from __future__ import annotations

from collections import Counter

import pytest

from hdu.cards import (
    DECK_SIZE,
    Card,
    CardId,
    Color,
    build_deck,
    display_name,
)
from hdu.engine import card_count, new_hand
from hdu.view import view_for

from tests.helpers import assert_conservation

# Specials that must appear exactly once in the deck.
SINGLETON_SPECIALS = [
    CardId.BOUNCE,
    CardId.HOLY_DEFENDER,
    CardId.QUITTER,
    CardId.DUMP,
    CardId.SHARE,
    CardId.MAGIC_5,
    CardId.PENN_STATE,
    CardId.MUTUAL_DESTRUCT,
    CardId.GLASNOST,
    CardId.SIXTY_NINE,
    CardId.LUCK,
    CardId.DOUBLE_SKIP,
    CardId.REVERSE_SKIP,
    CardId.HOT_DEATH,
    CardId.DELAYED_BLAST,
    CardId.HARVESTER,
    CardId.MYSTERY_DRAW,
    CardId.SPREADER,
]


def test_deck_size_is_113():
    assert DECK_SIZE == 113
    assert len(build_deck()) == 113


def test_singletons_appear_exactly_once():
    counts = Counter(c.id for c in build_deck())
    for cid in SINGLETON_SPECIALS:
        assert counts[cid] == 1, f"{cid} should be a singleton, found {counts[cid]}"


def test_draw_four_is_the_only_non_singleton_special():
    counts = Counter(c.id for c in build_deck())
    assert counts[CardId.DRAW_FOUR] == 4


def test_generic_card_counts():
    counts = Counter(c.id for c in build_deck())
    # One Skip/Reverse per non-red color stays generic plus one in red.
    assert counts[CardId.SKIP] == 8 - 1  # red's first skip became Double Skip
    assert counts[CardId.REVERSE] == 8 - 1  # red's first reverse became Reverse Skip
    assert counts[CardId.DRAW_TWO] == 8
    assert counts[CardId.WILD] == 4
    assert counts[CardId.NUMBER] == 76 - 11  # 11 number slots overlaid by specials


def test_overlays_keep_printed_identity():
    deck = build_deck()
    bounce = next(c for c in deck if c.id is CardId.BOUNCE)
    assert bounce.color is Color.BLUE and bounce.number == 0
    sixty_nine = next(c for c in deck if c.id is CardId.SIXTY_NINE)
    assert sixty_nine.color is Color.YELLOW and sixty_nine.number == 9


def test_every_color_zero_is_a_special():
    deck = build_deck()
    zeros = [c for c in deck if c.number == 0]
    assert len(zeros) == 4
    assert all(c.id is not CardId.NUMBER for c in zeros)


def test_display_names_resolvable_for_all_cards():
    for c in build_deck():
        name = display_name(c)
        assert name and isinstance(name, str)


def test_deal_shapes_and_conservation():
    state = new_hand(seed=42, num_players=4, hand_size=7)
    assert len(state.players) == 4
    assert all(len(p.hand) == 7 for p in state.players)
    assert len(state.discard) == 1
    assert len(state.draw_pile) == DECK_SIZE - (4 * 7) - 1
    assert state.to_act == 1  # left of dealer 0
    assert_conservation(state)


def test_deal_is_deterministic_for_a_seed():
    a = new_hand(seed=7, num_players=4, hand_size=7)
    b = new_hand(seed=7, num_players=4, hand_size=7)
    assert [p.hand for p in a.players] == [p.hand for p in b.players]
    assert a.draw_pile == b.draw_pile


def test_different_seeds_differ():
    a = new_hand(seed=1)
    b = new_hand(seed=2)
    assert [p.hand for p in a.players] != [p.hand for p in b.players]


@pytest.mark.parametrize("hand_size", [5, 7, 10, 15])
def test_various_hand_sizes_conserve(hand_size):
    state = new_hand(seed=3, num_players=4, hand_size=hand_size)
    assert all(len(p.hand) == hand_size for p in state.players)
    assert_conservation(state)


def test_hand_size_too_large_rejected():
    with pytest.raises(ValueError):
        new_hand(seed=0, num_players=4, hand_size=30)


def test_view_redacts_opponent_hands():
    state = new_hand(seed=5, num_players=4, hand_size=7)
    v = view_for(state, player_id=0)
    assert len(v.hand) == 7  # own hand visible
    assert len(v.opponents) == 3
    assert all(o.hand_count == 7 for o in v.opponents)
    # Opponent views expose counts, not cards.
    assert not hasattr(v.opponents[0], "hand")
