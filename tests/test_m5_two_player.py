"""M5 — two-player rule modifications (HANDOFF §7), triggered whenever exactly
two players are still active."""

from __future__ import annotations

import random

from hdu.actions import ChooseColor, Decline, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, legal_actions
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
REVERSE = Card(CardId.REVERSE, Color.RED)
DOUBLE_SKIP = Card(CardId.DOUBLE_SKIP, Color.RED)
DELAYED_BLAST = Card(CardId.DELAYED_BLAST, Color.WILD)
MAD = Card(CardId.MUTUAL_DESTRUCT, Color.YELLOW, 1)
QUITTER = Card(CardId.QUITTER, Color.GREEN, 0)
SHARE = Card(CardId.SHARE, Color.GREEN, 3)


def _duel(p0_hand, p1_hand, top=NUM(Color.RED, 3), draw_n=12):
    """P0 and P1 active; P2 and P3 already eliminated."""
    draw = tuple(NUM(Color.BLUE, i % 10) for i in range(draw_n))
    players = (
        PlayerState(id=0, hand=tuple(p0_hand)),
        PlayerState(id=1, hand=tuple(p1_hand)),
        PlayerState(id=2, hand=(NUM(Color.RED, 1),), eliminated=True),
        PlayerState(id=3, hand=(NUM(Color.RED, 1),), eliminated=True),
    )
    return GameState(
        players=players,
        draw_pile=draw,
        discard=(DiscardEntry(top, top.color, top.number),),
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )


def test_reverse_acts_as_skip_you_play_again():
    st = _duel([REVERSE, NUM(Color.RED, 5)], [NUM(Color.RED, 1)])
    new, _ = apply(st, PlayCard(0))
    assert new.to_act == 0  # opponent skipped, P0 plays again


def test_double_skip_acts_as_single_skip():
    st = _duel([DOUBLE_SKIP, NUM(Color.RED, 5)], [NUM(Color.RED, 1)])
    new, _ = apply(st, PlayCard(0))
    assert new.to_act == 0


def test_delayed_blast_has_no_extra_skip():
    st = _duel([DELAYED_BLAST, NUM(Color.RED, 5)], [NUM(Color.RED, 1)])
    st, _ = apply(st, PlayCard(0))
    st, _ = apply(st, ChooseColor(Color.RED))  # target P1
    st, _ = apply(st, Decline())
    assert len(st.players[1].hand) == 1 + 4  # drew 4
    assert st.to_act == 0  # back to the attacker, no extra skip


def test_mad_eliminates_both_without_a_choice():
    st = _duel([MAD, NUM(Color.RED, 5)], [NUM(Color.RED, 1)], top=NUM(Color.YELLOW, 4))
    new, _ = apply(st, PlayCard(0))
    assert new.phase is Phase.HAND_OVER
    assert new.winner is None  # all active eliminated
    assert new.players[0].eliminated and new.players[1].eliminated


def test_quitter_wins_by_default_unless_aids():
    # Decline -> the Quitter player wins.
    st = _duel([QUITTER, NUM(Color.RED, 5)], [NUM(Color.GREEN, 7)], top=NUM(Color.GREEN, 4))
    st, _ = apply(st, PlayCard(0))
    assert st.phase is Phase.RESPOND and st.pending.kind == "quitter"
    assert legal_actions(st) == [Decline()]  # no Bounce/Holy Defender, no Share held
    won, _ = apply(st, Decline())
    assert won.phase is Phase.HAND_OVER and won.winner == 0

    # ...but AIDS kills both.
    st2 = _duel([QUITTER, NUM(Color.RED, 5)], [SHARE, NUM(Color.GREEN, 7)], top=NUM(Color.GREEN, 4))
    st2, _ = apply(st2, PlayCard(0))
    share = [a for a in legal_actions(st2) if isinstance(a, PlayCard)][0]
    both, _ = apply(st2, share)
    assert both.phase is Phase.HAND_OVER and both.winner is None
    assert both.players[0].eliminated and both.players[1].eliminated
