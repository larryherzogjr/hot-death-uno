"""M3 — M.A.D.: the player is eliminated and drags a chosen victim down too.
Worth 75 held."""

from __future__ import annotations

from hdu.actions import ChooseVictim, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, card_count, legal_actions
from hdu.events import PlayerEliminated
from hdu.scoring import card_points, score_hand
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
MAD = Card(CardId.MUTUAL_DESTRUCT, Color.YELLOW, 1)


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


def test_mad_eliminates_self_and_enters_choose_victim():
    hands = [[MAD, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _state(hands, NUM(Color.YELLOW, 3))  # MAD matches as Yellow 1
    new, events = apply(st, PlayCard(0))
    assert new.phase is Phase.CHOOSE_VICTIM
    assert new.players[0].eliminated is True
    assert new.players[0].hand == (NUM(Color.RED, 5),)  # remaining hand frozen
    assert any(isinstance(e, PlayerEliminated) and e.player == 0 for e in events)
    # The chooser picks among the other active players.
    assert set(legal_actions(new)) == {ChooseVictim(1), ChooseVictim(2), ChooseVictim(3)}


def test_mad_victim_eliminated_and_turn_advances():
    hands = [[MAD, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _state(hands, NUM(Color.YELLOW, 3))
    st, _ = apply(st, PlayCard(0))
    st, events = apply(st, ChooseVictim(2))
    assert st.players[2].eliminated is True
    assert st.phase is Phase.PLAY
    assert st.to_act == 1  # next active after the (eliminated) MAD player P0
    assert any(isinstance(e, PlayerEliminated) and e.player == 2 for e in events)


def test_turn_advance_skips_eliminated_players():
    hands = [[MAD, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _state(hands, NUM(Color.YELLOW, 3))
    st, _ = apply(st, PlayCard(0))
    st, _ = apply(st, ChooseVictim(1))  # eliminate P1
    # Active players are now P2, P3. Turn went from P0 to next active = P2.
    assert st.to_act == 2


def test_eliminated_players_still_score_their_frozen_hand():
    # P0 played MAD (discarded) and is eliminated holding Red 5; P2 eliminated.
    hands = [[MAD, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 7)]] * 3
    st = _state(hands, NUM(Color.YELLOW, 3))
    before = card_count(st)
    st, _ = apply(st, PlayCard(0))
    st, _ = apply(st, ChooseVictim(2))
    gains = score_hand(st)
    assert gains[0] == 5  # frozen Red 5, the played MAD is not in hand
    assert gains[2] == 7
    assert card_count(st) == before  # cards conserved (played MAD moved to discard)


def test_mad_held_value_is_75():
    assert card_points(MAD) == 75
