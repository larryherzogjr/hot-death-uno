"""M3 — the scoring-only specials and their play-rule tweaks (HANDOFF §6/§8).

Penn State value, Sixty Nine (override + 6/9 play), AIDS cumulative −10, Holy
Defender halving, Fucker/Bounce doubling, Shitter (bump + restricted play),
Luck held value, Mystery Draw (draw underlying + held value)."""

from __future__ import annotations

import random

from hdu.actions import ChooseColor, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.effects import matches
from hdu.engine import apply, legal_actions
from hdu.scoring import card_held_value, card_points, new_aids_counts, score_hand
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
SKIP = Card(CardId.SKIP, Color.RED)
WILD = Card(CardId.WILD, Color.WILD)
PENN_STATE = Card(CardId.PENN_STATE, Color.BLUE, 2)
SIXTY_NINE = Card(CardId.SIXTY_NINE, Color.YELLOW, 9)
SHARE = Card(CardId.SHARE, Color.GREEN, 3)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)
DUMP = Card(CardId.DUMP, Color.YELLOW, 0)
LUCK = Card(CardId.LUCK, Color.GREEN, 4)
MYSTERY = Card(CardId.MYSTERY_DRAW, Color.WILD)


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


def _play_state(hands, top, *, draw=()):
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=tuple(draw),
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )


# --- Penn State -------------------------------------------------------------

def test_penn_state_is_worth_highest_other_card():
    hand = (PENN_STATE, SKIP, NUM(Color.RED, 9))  # max other = Skip (20)
    assert card_held_value(PENN_STATE, hand) == 20
    assert card_held_value(PENN_STATE, (PENN_STATE,)) == 0  # alone


# --- Sixty Nine -------------------------------------------------------------

def test_sixty_nine_overrides_hand_total_to_69():
    gains = score_hand(_hand_over([[], [SIXTY_NINE, NUM(Color.RED, 9), SKIP]], winner=0))
    assert gains[1] == 69


def test_sixty_nine_can_play_on_a_six_or_nine():
    on_six = DiscardEntry(NUM(Color.RED, 6), Color.RED, 6)
    on_nine = DiscardEntry(NUM(Color.BLUE, 9), Color.BLUE, 9)
    assert matches(SIXTY_NINE, on_six)
    assert matches(SIXTY_NINE, on_nine)


# --- AIDS / Share -----------------------------------------------------------

def test_aids_applies_cumulative_minus_ten_and_persists():
    st = _hand_over([[], [SHARE, NUM(Color.RED, 5)]], winner=0)
    gains = score_hand(st)
    assert gains[1] == 3 + 5 - 10  # base 8, minus 10 for the acquired Share
    assert new_aids_counts(st)[1] == 1


def test_aids_penalty_recurs_on_later_lost_hands():
    # P1 holds no Share now but acquired 2 earlier -> -20 this lost hand.
    st = _hand_over([[], [NUM(Color.RED, 5)]], winner=0, aids=[0, 2])
    assert score_hand(st)[1] == 5 - 20


def test_winner_takes_no_aids_penalty():
    st = _hand_over([[], [NUM(Color.RED, 5)]], winner=1, aids=[0, 3])
    assert score_hand(st)[1] == 0  # winner scores 0 regardless of aids count


# --- Holy Defender / Fucker -------------------------------------------------

def test_holy_defender_halves_toward_zero():
    gains = score_hand(_hand_over([[], [HOLY_DEFENDER, NUM(Color.RED, 5), SKIP]], winner=0))
    assert gains[1] == int(25 / 2)  # 0 + 5 + 20 = 25 -> 12


def test_bounce_doubles():
    gains = score_hand(_hand_over([[], [BOUNCE, NUM(Color.RED, 5)]], winner=0))
    assert gains[1] == 10  # (0 + 5) * 2


# --- Shitter / Dump ---------------------------------------------------------

def test_shitter_bumps_non_top_scorer_to_the_top():
    # P1 holds Dump with a tiny hand; P2 is the top scorer at 40.
    st = _hand_over([[], [DUMP, NUM(Color.RED, 1)], [WILD]], winner=0)
    gains = score_hand(st)
    assert gains[2] == 40
    assert gains[1] == 40  # bumped up from 1


def test_shitter_no_effect_when_already_top():
    st = _hand_over([[], [DUMP, NUM(Color.RED, 9)], [NUM(Color.RED, 1)]], winner=0)
    gains = score_hand(st)
    assert gains[1] == 9  # already the highest; unchanged


def test_dump_only_plays_on_holy_defender_magic5_or_last_card():
    on_hd = DiscardEntry(HOLY_DEFENDER, Color.RED, 0)
    on_num = DiscardEntry(NUM(Color.YELLOW, 5), Color.YELLOW, 5)
    assert matches(DUMP, on_hd)  # on Holy Defender
    assert not matches(DUMP, on_num)  # not by ordinary color/number
    assert matches(DUMP, on_num, is_only_card=True)  # as last card


# --- Luck -------------------------------------------------------------------

def test_luck_held_value_is_75():
    assert card_points(LUCK) == 75


# --- Mystery Draw -----------------------------------------------------------

def test_mystery_draw_makes_next_player_draw_the_underlying_number():
    draw = [NUM(Color.BLUE, n) for n in range(6)]
    hands = [[MYSTERY, NUM(Color.RED, 9)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _play_state(hands, NUM(Color.RED, 5), draw=draw)  # underlying number = 5
    st, _ = apply(st, PlayCard(0))  # play Mystery Draw (wild)
    st, _ = apply(st, ChooseColor(Color.RED))
    assert len(st.players[1].hand) == 1 + 5  # drew 5
    assert st.to_act == 2  # P1 skipped


def test_mystery_draw_on_zero_acts_as_plain_wild():
    hands = [[MYSTERY, NUM(Color.RED, 9)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _play_state(hands, NUM(Color.RED, 0))  # underlying number = 0
    st, _ = apply(st, PlayCard(0))
    st, _ = apply(st, ChooseColor(Color.RED))
    assert len(st.players[1].hand) == 1  # no draw
    assert st.to_act == 1  # no skip, just advance


def test_mystery_draw_held_value_is_ten_times_highest_number():
    hand = (MYSTERY, NUM(Color.RED, 5), NUM(Color.BLUE, 2))
    assert card_held_value(MYSTERY, hand) == 50
    assert card_held_value(MYSTERY, (MYSTERY,)) == 10  # no number card
