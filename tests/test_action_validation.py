"""The public engine boundary rejects actions outside ``legal_actions``."""

from dataclasses import replace

import pytest

from hdu.actions import ChooseColor, ChooseVictim, Pass, PlayCard, Reveal
from hdu.cards import Color
from hdu.engine import apply, card_count, legal_actions, new_hand
from hdu.state import Pending, Phase


def _assert_rejected_unchanged(state, action) -> None:
    before_count = card_count(state)
    assert action not in legal_actions(state)

    with pytest.raises(ValueError, match="not legal"):
        apply(state, action)

    # GameState is immutable, so a rejected action must leave the caller's state
    # and the deck-conservation invariant untouched.
    assert card_count(state) == before_count == 113


@pytest.mark.parametrize("hand_index", [-1, 999])
def test_play_card_rejects_out_of_range_indexes(hand_index):
    # Seed 6 is a useful regression case: before validation, PlayCard(-1) was
    # accepted and changed the total card count from 113 to 120.
    _assert_rejected_unchanged(new_hand(6), PlayCard(hand_index))


def test_pass_is_rejected_while_normal_actions_exist():
    _assert_rejected_unchanged(new_hand(0), Pass())


def test_choose_color_rejects_wild():
    state = replace(new_hand(0), phase=Phase.CHOOSE_COLOR)
    _assert_rejected_unchanged(state, ChooseColor(Color.WILD))


def test_choose_victim_rejects_negative_player_id():
    state = replace(new_hand(0), phase=Phase.CHOOSE_VICTIM, to_act=0)
    _assert_rejected_unchanged(state, ChooseVictim(-1))


def test_reveal_rejects_negative_hand_index():
    state = new_hand(0)
    state = replace(
        state,
        phase=Phase.RESPOND,
        to_act=0,
        pending=Pending(kind="spreader", target=0, origin=1, draw_total=2),
    )
    _assert_rejected_unchanged(state, Reveal(-1))
