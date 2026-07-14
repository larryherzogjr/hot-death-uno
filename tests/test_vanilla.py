"""M1 — the vanilla Uno turn loop: effects, matching, draw/reshuffle, win."""

from __future__ import annotations

import pytest

from hdu.actions import ChooseColor, DrawCard, PlayCard
from hdu.cards import Card, CardId, Color
from hdu.effects import matches
from hdu.engine import apply, card_count, legal_actions, new_hand
from hdu.play import play_hand
from hdu.players.random_ai import RandomAI
from hdu.state import DiscardEntry, GameState, Phase, PlayerState

# --------------------------------------------------------------------------- #
# Hand-built states for precise effect assertions. We don't need a full deck in
# the draw pile; conservation tests use real deals separately.
# --------------------------------------------------------------------------- #

NUM = lambda color, n: Card(CardId.NUMBER, color, n)  # noqa: E731


def _state(hands, top, *, to_act=0, direction=1, draw=()):
    players = tuple(PlayerState(id=i, hand=tuple(h)) for i, h in enumerate(hands))
    discard = (DiscardEntry(top, top.color, top.number),)
    return GameState(
        players=players,
        draw_pile=tuple(draw),
        discard=discard,
        to_act=to_act,
        direction=direction,
        dealer=0,
        rng_state=__import__("random").Random(0).getstate(),
    )


def test_match_by_color_number_and_symbol():
    top = DiscardEntry(NUM(Color.RED, 5), Color.RED, 5)
    assert matches(NUM(Color.RED, 9), top)  # color
    assert matches(NUM(Color.BLUE, 5), top)  # number
    assert matches(Card(CardId.WILD, Color.WILD), top)  # wild
    assert not matches(NUM(Color.BLUE, 9), top)  # neither
    skip_top = DiscardEntry(Card(CardId.SKIP, Color.RED), Color.RED, None)
    assert matches(Card(CardId.SKIP, Color.BLUE), skip_top)  # symbol match


def test_number_card_advances_one():
    st = _state([[NUM(Color.RED, 5)], [NUM(Color.RED, 1)], [], []], NUM(Color.RED, 3))
    # give players 2 cards so nobody wins
    st = _state(
        [[NUM(Color.RED, 5), NUM(Color.GREEN, 2)], [NUM(Color.RED, 1)], [NUM(Color.RED, 1)], [NUM(Color.RED, 1)]],
        NUM(Color.RED, 3),
    )
    new, events = apply(st, PlayCard(0))
    assert new.to_act == 1
    assert new.top.card.number == 5


def test_skip_advances_two():
    hands = [[NUM(Color.RED, 5), Card(CardId.SKIP, Color.RED)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    new, events = apply(st, PlayCard(1))  # play the Skip
    assert new.to_act == 2  # P1 skipped


def test_reverse_flips_direction():
    hands = [[NUM(Color.RED, 5), Card(CardId.REVERSE, Color.RED)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    new, events = apply(st, PlayCard(1))
    assert new.direction == -1
    assert new.to_act == 3  # one step counter-clockwise from P0


def test_draw_two_target_draws_and_is_skipped():
    draw = [NUM(Color.BLUE, 7), NUM(Color.BLUE, 8), NUM(Color.GREEN, 9)]
    hands = [[NUM(Color.RED, 5), Card(CardId.DRAW_TWO, Color.RED)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3), draw=draw)
    new, events = apply(st, PlayCard(1))
    assert len(new.players[1].hand) == 3  # had 1, drew 2
    assert new.to_act == 2  # P1 skipped
    assert_conservation_like(st, new)


def test_wild_sets_color_and_advances():
    hands = [[NUM(Color.RED, 5), Card(CardId.WILD, Color.WILD)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    mid, _ = apply(st, PlayCard(1))
    assert mid.phase is Phase.CHOOSE_COLOR
    assert mid.to_act == 0  # still the same player choosing
    new, events = apply(mid, ChooseColor(Color.GREEN))
    assert new.phase is Phase.PLAY
    assert new.top.eff_color is Color.GREEN
    assert new.to_act == 1  # now advances


def test_winning_empties_hand_and_ends():
    hands = [[NUM(Color.RED, 5)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    new, events = apply(st, PlayCard(0))
    assert new.phase is Phase.HAND_OVER
    assert new.winner == 0
    assert len(new.players[0].hand) == 0


def test_uno_called_at_one_card():
    hands = [[NUM(Color.RED, 5), NUM(Color.GREEN, 2)]] + [[NUM(Color.RED, 1)]] * 3
    st = _state(hands, NUM(Color.RED, 3))
    new, events = apply(st, PlayCard(0))
    assert new.players[0].called_uno is True


def assert_conservation_like(before: GameState, after: GameState) -> None:
    assert card_count(before) == card_count(after)


# --------------------------------------------------------------------------- #
# Reshuffle.
# --------------------------------------------------------------------------- #

def test_reshuffle_when_draw_pile_empty():
    # Empty draw pile, but a discard with history to reshuffle.
    players = (
        PlayerState(id=0, hand=(NUM(Color.RED, 5),)),
        PlayerState(id=1, hand=(NUM(Color.GREEN, 2),)),
    )
    discard = (
        DiscardEntry(NUM(Color.BLUE, 1), Color.BLUE, 1),
        DiscardEntry(NUM(Color.BLUE, 2), Color.BLUE, 2),
        DiscardEntry(NUM(Color.BLUE, 3), Color.BLUE, 3),
    )
    st = GameState(
        players=players,
        draw_pile=(),
        discard=discard,
        to_act=0,
        direction=1,
        dealer=0,
        rng_state=__import__("random").Random(0).getstate(),
    )
    before = card_count(st)
    new, events = apply(st, DrawCard())
    assert card_count(new) == before  # conserved across reshuffle
    assert len(new.players[0].hand) == 2  # drew one
    assert len(new.discard) == 1  # collapsed to just the top


# --------------------------------------------------------------------------- #
# Full-game properties driven by the random AI.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("seed", range(25))
def test_full_hand_conserves_and_terminates(seed):
    state = new_hand(seed=seed, num_players=4, hand_size=7)
    counts: list[int] = []

    def observer(s, events):
        counts.append(card_count(s))
        # legal_actions is non-empty until the hand is over.
        if s.phase not in (Phase.HAND_OVER, Phase.GAME_OVER):
            assert legal_actions(s), "legal_actions empty mid-hand"

    players = [RandomAI(seed=100 + i) for i in range(4)]
    final = play_hand(state, players, observer=observer)

    assert final.phase is Phase.HAND_OVER
    assert all(c == card_count(state) for c in counts)  # conservation throughout
    winners = [p.id for p in final.players if len(p.hand) == 0]
    if final.winner is None:
        # Possible once eliminators are in play: every active player eliminated.
        assert winners == []
        assert all(p.eliminated for p in final.players)
    else:
        assert final.winner in range(len(final.players))
        # A winner either emptied their hand or won via a terminal (2-player
        # Quitter default-win, bastard-four) while still holding cards.
        assert winners in ([], [final.winner])


def test_full_game_is_deterministic():
    def run():
        state = new_hand(seed=99, num_players=4, hand_size=7)
        players = [RandomAI(seed=100 + i) for i in range(4)]
        final = play_hand(state, players)
        return final.winner, tuple(len(p.hand) for p in final.players)

    assert run() == run()


def test_legal_actions_empty_only_when_over():
    state = new_hand(seed=3, num_players=4, hand_size=7)
    assert legal_actions(state)  # play or choose-color at start
    players = [RandomAI(seed=i) for i in range(4)]
    final = play_hand(state, players)
    assert legal_actions(final) == []
