"""M3 — Spreader (inferred-spec house rule): every other active player draws 2
unless they reveal a Penn State; worth 75 held. Uses the pending/respond
machinery, so it also exercises the M4 groundwork."""

from __future__ import annotations

from hdu.actions import ChooseColor, Decline, PlayCard, Reveal
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, card_count, legal_actions
from hdu.events import PennStateRevealed, SpreaderStarted
from hdu.scoring import card_points
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
SPREADER = Card(CardId.SPREADER, Color.WILD)
PENN_STATE = Card(CardId.PENN_STATE, Color.BLUE, 2)


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


def _play_spreader(st, color=Color.RED):
    """Drive P0 playing Spreader and choosing a color; return (state, events)."""
    st, e1 = apply(st, PlayCard(0))
    assert st.phase is Phase.CHOOSE_COLOR
    st, e2 = apply(st, ChooseColor(color))
    return st, e1 + e2


def test_spreader_opens_pending_on_first_victim():
    draw = [NUM(Color.BLUE, n) for n in range(9)]
    hands = [[SPREADER, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3), draw=draw)
    st, events = _play_spreader(st)
    assert st.phase is Phase.RESPOND
    assert st.pending.kind == "spreader"
    assert st.pending.target == 1 and st.pending.queue == (2, 3)
    assert any(isinstance(e, SpreaderStarted) for e in events)
    assert legal_actions(st) == [Decline()]  # no Penn State to reveal


def test_spreader_makes_everyone_draw_two_then_the_player_acts_again():
    draw = [NUM(Color.BLUE, n) for n in range(9)]
    hands = [[SPREADER, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3), draw=draw)
    before = card_count(st)
    st, _ = _play_spreader(st)
    for _ in range(3):  # P1, P2, P3 each decline
        st, _ = apply(st, Decline())
    assert st.phase is Phase.PLAY
    assert st.pending is None
    assert [len(st.players[i].hand) for i in (1, 2, 3)] == [3, 3, 3]  # each drew 2
    assert st.to_act == 0  # with no Penn State shown, the Spreader player goes again
    assert card_count(st) == before  # conservation across the whole spread


def test_penn_state_reveal_exempts_holder_punishes_spreader_and_takes_turn():
    draw = [NUM(Color.BLUE, n) for n in range(9)]
    hands = [
        [SPREADER, NUM(Color.RED, 5)],
        [NUM(Color.GREEN, 1)],
        [PENN_STATE, NUM(Color.GREEN, 7)],  # P2 can protect
        [NUM(Color.GREEN, 1)],
    ]
    st = _state(hands, NUM(Color.RED, 3), draw=draw)
    st, _ = _play_spreader(st)
    st, _ = apply(st, Decline())  # P1 draws 2
    assert st.pending.target == 2
    # P2 reveals Penn State.
    reveal = next(a for a in legal_actions(st) if isinstance(a, Reveal))
    st, events = apply(st, reveal)
    assert any(isinstance(e, PennStateRevealed) for e in events)
    assert PENN_STATE in st.players[2].hand  # retained, not discarded
    assert len(st.players[2].hand) == 2  # did not draw
    st, _ = apply(st, Decline())  # P3 draws 2
    assert st.phase is Phase.PLAY
    # Penn State was shown: the Spreader player (P0, holding Red 5) drew 2...
    assert len(st.players[0].hand) == 1 + 2
    # ...and the Penn State holder (P2) takes the turn.
    assert st.to_act == 2


def test_spreader_held_value_is_twenty_times_opponents():
    # In a 4-player game (3 opponents) a held Spreader is worth 60.
    hands = [[SPREADER], [NUM(Color.RED, 5)], [], []]
    st = _state(hands, NUM(Color.RED, 3))
    st = __import__("dataclasses").replace(st, phase=Phase.HAND_OVER, winner=1)
    from hdu.scoring import score_hand
    assert score_hand(st)[0] == 60
