"""Golden-game replays — the regression net (HANDOFF §10).

Each entry pins a fully deterministic game (deal seed + per-seat AI seeds) to its
final scores and winner. Because the engine RNG and the AIs are all seeded, the
whole game replays bit-for-bit.

These freeze the **M1/M2 vanilla baseline**. When a special card gains its real
effect or held-value in M3–M5, some of these will change — update them
*deliberately* (regenerate and eyeball the diff), never silently.
"""

from __future__ import annotations

import pytest

from hdu.play import play_game
from hdu.players.random_ai import RandomAI
from hdu.state import Phase

# seed -> (winner, final scores per player)
# Last regenerated when the baseline AI began preferring its highest-value legal
# play, as specified by HANDOFF §9. Regenerate deliberately when flow changes.
GOLDEN = {
    1: (3, (1097, 756, 850, 498)),
    7: (1, (1019, 928, 1063, 989)),
    42: (3, (490, 792, 1006, 373)),
}


@pytest.mark.parametrize("seed,expected", GOLDEN.items())
def test_golden_full_game(seed, expected):
    players = [RandomAI(seed=200 + i) for i in range(4)]
    final = play_game(seed, players)
    assert final.phase is Phase.GAME_OVER
    assert (final.winner, tuple(p.score for p in final.players)) == expected


# Two-player games exercise the §7 rule modifications end to end.
GOLDEN_2P = {
    1: (0, (506, 1057)),
    5: (1, (1831, 364)),
}


@pytest.mark.parametrize("seed,expected", GOLDEN_2P.items())
def test_golden_two_player_game(seed, expected):
    players = [RandomAI(seed=200 + i) for i in range(2)]
    final = play_game(seed, players, num_players=2)
    assert final.phase is Phase.GAME_OVER
    assert (final.winner, tuple(p.score for p in final.players)) == expected
