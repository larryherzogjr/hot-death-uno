"""M3 — Glasnost: choose a victim who reveals their hand to all. Defenses:
AIDS → both reveal; Fuck You → Glasnost player reveals + direction reverses;
Holy Defender → passes on. Worth 75 held."""

from __future__ import annotations

from hdu.actions import ChooseVictim, Decline, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, legal_actions
from hdu.events import GlasnostStarted, HandRevealed
from hdu.scoring import card_points
from hdu.state import DiscardEntry, GameState, Phase, PlayerState
from hdu.view import view_for

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
GLASNOST = Card(CardId.GLASNOST, Color.RED, 2)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)
SHARE = Card(CardId.SHARE, Color.GREEN, 3)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)


def _state(hands, top=NUM(Color.RED, 5), *, to_act=0, direction=1):
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


def _play_glasnost_on(victim, victim_hand=None):
    hands = [[GLASNOST, NUM(Color.RED, 9)]] + [[NUM(Color.RED, 1)]] * 3
    if victim_hand is not None:
        hands[victim] = victim_hand
    st = _state(hands)
    st, _ = apply(st, PlayCard(0))  # play Glasnost
    assert st.phase is Phase.CHOOSE_VICTIM
    st, events = apply(st, ChooseVictim(victim))
    return st, events


def test_glasnost_play_enters_choose_victim_excluding_self():
    st = _state([[GLASNOST, NUM(Color.RED, 9)]] + [[NUM(Color.RED, 1)]] * 3)
    st, _ = apply(st, PlayCard(0))
    assert st.phase is Phase.CHOOSE_VICTIM
    assert set(legal_actions(st)) == {ChooseVictim(1), ChooseVictim(2), ChooseVictim(3)}


def test_glasnost_victim_reveals_on_decline():
    st, events = _play_glasnost_on(2)
    assert st.phase is Phase.RESPOND and st.pending.kind == "glasnost"
    assert any(isinstance(e, GlasnostStarted) for e in events)
    st, events = apply(st, Decline())
    assert st.players[2].revealed is True
    assert any(isinstance(e, HandRevealed) and e.player == 2 for e in events)
    assert st.phase is Phase.PLAY and st.to_act == 1  # turn returns past origin
    # The revealed hand is now visible to others through the view.
    assert view_for(st, 0).opponents[1].revealed_hand == st.players[2].hand


def test_bounce_reverses_and_reveals_the_glasnost_player():
    st, _ = _play_glasnost_on(2, victim_hand=[BOUNCE, NUM(Color.RED, 7)])
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, play)
    assert st.players[0].revealed is True  # origin reveals
    assert st.players[2].revealed is False
    assert st.direction == -1  # reversed
    assert st.top.eff_color is Color.BLUE


def test_share_reveals_both():
    st, _ = _play_glasnost_on(2, victim_hand=[SHARE, NUM(Color.RED, 7)])
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, play)
    assert st.players[0].revealed is True
    assert st.players[2].revealed is True


def test_holy_defender_passes_to_following():
    st, _ = _play_glasnost_on(2, victim_hand=[HOLY_DEFENDER, NUM(Color.RED, 7)])
    play = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, play)
    assert st.players[2].revealed is False  # passed it on
    assert st.phase is Phase.RESPOND and st.pending.target == 3
    st, _ = apply(st, Decline())
    assert st.players[3].revealed is True


def test_glasnost_held_value_is_75():
    assert card_points(GLASNOST) == 75
