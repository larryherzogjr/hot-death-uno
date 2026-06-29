"""M3 — Quitter (basic): opens a pending eliminating the next player, who may
defend with Fuck You (origin dies), AIDS/Share (both die), or Holy Defender
(passes on). Worth 100 held. M5 adds Quitter+Fucker=1000 and the 2-player rule."""

from __future__ import annotations

from hdu.actions import Decline, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, legal_actions
from hdu.events import PlayerEliminated, QuitterStarted
from hdu.scoring import card_points
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
QUITTER = Card(CardId.QUITTER, Color.GREEN, 0)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)
SHARE = Card(CardId.SHARE, Color.GREEN, 3)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)


def _state(hands, top=NUM(Color.GREEN, 5), *, to_act=0, direction=1):
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


def _play_quitter(hands):
    st = _state(hands)
    st, events = apply(st, PlayCard(0))  # P0 plays Quitter
    return st, events


def test_quitter_opens_pending_on_next_player():
    st, events = _play_quitter([[QUITTER, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3)
    assert st.phase is Phase.RESPOND
    assert st.pending.kind == "quitter"
    assert st.pending.origin == 0 and st.pending.target == 1
    assert any(isinstance(e, QuitterStarted) for e in events)
    assert legal_actions(st) == [Decline()]  # P1 has no defense


def test_decline_eliminates_target():
    st, _ = _play_quitter([[QUITTER, NUM(Color.RED, 5)]] + [[NUM(Color.GREEN, 1)]] * 3)
    st, events = apply(st, Decline())
    assert st.players[1].eliminated is True
    assert st.players[0].eliminated is False  # the quitter survives
    assert st.phase is Phase.PLAY
    assert st.to_act == 2  # next active after origin, skipping eliminated P1
    assert any(isinstance(e, PlayerEliminated) and e.player == 1 for e in events)


def test_bounce_eliminates_the_quitter_instead():
    hands = [[QUITTER, NUM(Color.RED, 5)], [BOUNCE, NUM(Color.GREEN, 7)]] + [[NUM(Color.GREEN, 1)]] * 2
    st, _ = _play_quitter(hands)
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, events = apply(st, play)
    assert st.players[0].eliminated is True  # origin dies
    assert st.players[1].eliminated is False  # target survives
    assert st.top.eff_color is Color.BLUE  # defense set the color
    assert st.direction == -1  # defensive Fuck You reverses direction
    assert st.phase is Phase.PLAY


def test_share_eliminates_both():
    hands = [[QUITTER, NUM(Color.RED, 5)], [SHARE, NUM(Color.GREEN, 7)]] + [[NUM(Color.GREEN, 1)]] * 2
    st, _ = _play_quitter(hands)
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, play)
    assert st.players[0].eliminated is True
    assert st.players[1].eliminated is True
    assert st.top.eff_color is Color.GREEN
    assert st.to_act == 2  # remaining active player


def test_holy_defender_passes_to_following_player():
    hands = [[QUITTER, NUM(Color.RED, 5)], [HOLY_DEFENDER, NUM(Color.GREEN, 7)]] + [[NUM(Color.GREEN, 1)]] * 2
    st, _ = _play_quitter(hands)
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, play)
    assert st.players[1].eliminated is False  # passed, not eliminated
    assert st.phase is Phase.RESPOND
    assert st.pending.target == 2  # the following player now faces it
    assert st.top.eff_color is Color.RED
    # P2 declines and is eliminated.
    st, _ = apply(st, Decline())
    assert st.players[2].eliminated is True


def test_quitter_held_value_is_100():
    assert card_points(QUITTER) == 100
