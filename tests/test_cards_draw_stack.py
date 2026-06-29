"""M4 — the draw stack (HANDOFF §4): Draw Four / Hot Death / Delayed Blast /
Harvester stacking, and the defenses bounce / Holy Defender / AIDS / Magic 5."""

from __future__ import annotations

import random

from hdu.actions import ChooseColor, Decline, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.engine import apply, card_count, legal_actions
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731
DRAW_FOUR = Card(CardId.DRAW_FOUR, Color.WILD)
HOT_DEATH = Card(CardId.HOT_DEATH, Color.WILD)
DELAYED_BLAST = Card(CardId.DELAYED_BLAST, Color.WILD)
HARVESTER = Card(CardId.HARVESTER, Color.WILD)
BOUNCE = Card(CardId.BOUNCE, Color.BLUE, 0)
SHARE = Card(CardId.SHARE, Color.GREEN, 3)
HOLY_DEFENDER = Card(CardId.HOLY_DEFENDER, Color.RED, 0)
MAGIC_5 = Card(CardId.MAGIC_5, Color.RED, 5)
FILLER = NUM(Color.RED, 7)  # keeps a hand from emptying


def _state(hands, *, to_act=0, direction=1, draw_n=40):
    draw = tuple(NUM(Color.BLUE, i % 10) for i in range(draw_n))
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    return GameState(
        players=players,
        draw_pile=draw,
        discard=(DiscardEntry(NUM(Color.RED, 3), Color.RED, 3),),
        to_act=to_act,
        direction=direction,
        dealer=0,
        rng_state=random.Random(0).getstate(),
    )


def _play_attack(st, idx, color=Color.RED):
    """Play a Draw-Four-type at hand index ``idx`` and choose a color."""
    st, e1 = apply(st, PlayCard(idx))
    assert st.phase is Phase.CHOOSE_COLOR
    st, e2 = apply(st, ChooseColor(color))
    return st, e1 + e2


def test_three_deep_stack_declined():
    hands = [
        [DRAW_FOUR, FILLER],
        [DRAW_FOUR, FILLER],
        [DRAW_FOUR, FILLER],
        [FILLER, FILLER],  # P3 has no draw four -> must decline
    ]
    st = _state(hands)
    before = card_count(st)
    st, _ = _play_attack(st, 0)  # P0
    assert st.pending.draw_total == 4 and st.pending.target == 1
    st, _ = _play_attack(st, 0)  # P1 stacks
    assert st.pending.draw_total == 8 and st.pending.target == 2
    st, _ = _play_attack(st, 0)  # P2 stacks
    assert st.pending.draw_total == 12 and st.pending.target == 3
    st, _ = apply(st, Decline())  # P3 eats 12
    assert st.pending is None and st.phase is Phase.PLAY
    assert len(st.players[3].hand) == 2 + 12
    assert st.to_act == 0  # P3 skipped, back round to P0
    assert card_count(st) == before


def test_bounce_sends_stack_back_and_reverses():
    hands = [[DRAW_FOUR, FILLER], [BOUNCE, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # P0 -> target P1
    bounce = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, bounce)  # P1 bounces
    assert st.direction == -1
    assert st.top.eff_color is Color.BLUE
    assert st.pending.target == 0 and st.pending.origin == 1  # back to P0
    st, _ = apply(st, Decline())  # P0 eats it
    assert len(st.players[0].hand) == 1 + 4  # played the draw four, drew 4


def test_aids_splits_the_draw():
    hands = [[DRAW_FOUR, FILLER], [SHARE, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # draw_total 4, target P1, origin P0
    share = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, share)
    # 4 split evenly: P1 took 2, P0 took 2. P1 also played Share.
    assert len(st.players[1].hand) == 1 + 2
    assert len(st.players[0].hand) == 1 + 2  # P0 had played the draw four
    assert st.pending is None and st.phase is Phase.PLAY


def test_holy_defender_passes_stack_to_next():
    hands = [[DRAW_FOUR, FILLER], [HOLY_DEFENDER, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # target P1
    hd = [a for a in legal_actions(st) if isinstance(a, PlayCard)][0]
    st, _ = apply(st, hd)
    assert st.pending.target == 2  # passed over P1 to P2
    assert st.top.eff_color is Color.RED
    st, _ = apply(st, Decline())  # P2 eats 4
    assert len(st.players[2].hand) == 2 + 4


def test_magic_5_nullifies_hot_death_only():
    hands = [[HOT_DEATH, FILLER], [MAGIC_5, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # Hot Death, draw_total 8, target P1
    plays = [a for a in legal_actions(st) if isinstance(a, PlayCard)]
    assert plays, "Magic 5 should be offered against Hot Death"
    st, _ = apply(st, plays[0])  # play Magic 5
    assert st.pending is None and st.phase is Phase.PLAY
    assert len(st.players[1].hand) == 1  # only Magic 5 left after... played it, no draw
    # Magic 5 is NOT offered against a plain Draw Four stack.
    st2 = _state([[DRAW_FOUR, FILLER], [MAGIC_5, FILLER]] + [[FILLER, FILLER]] * 2)
    st2, _ = _play_attack(st2, 0)
    assert all(
        st2.players[1].hand[a.hand_index].id is not CardId.MAGIC_5
        for a in legal_actions(st2)
        if isinstance(a, PlayCard)
    )


def test_harvester_is_undefendable_and_immediate():
    hands = [[HARVESTER, FILLER], [BOUNCE, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # Harvester from P0
    # No response window: P1 eats 4 right away despite holding a Bounce.
    assert st.pending is None and st.phase is Phase.PLAY
    assert len(st.players[1].hand) == 2 + 4
    assert st.to_act == 2  # P1 skipped


def test_harvester_stacked_makes_whole_stack_undefendable():
    hands = [[DRAW_FOUR, FILLER], [HARVESTER, FILLER]] + [[FILLER, FILLER]] * 2
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # P0 draw four, target P1
    st, _ = _play_attack(st, 0)  # P1 stacks Harvester -> 8, undefendable
    assert st.pending is None  # resolved immediately
    assert len(st.players[2].hand) == 2 + 8  # P2 eats all 8


def test_delayed_blast_adds_an_extra_skip_on_resolution():
    hands = [[DELAYED_BLAST, FILLER]] + [[FILLER, FILLER]] * 3
    st = _state(hands)
    st, _ = _play_attack(st, 0)  # target P1, draw_total 4
    st, _ = apply(st, Decline())  # P1 eats 4
    assert len(st.players[1].hand) == 2 + 4
    assert st.to_act == 3  # P1 skipped (ate it) + one extra skip past P2
