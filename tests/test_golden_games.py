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
# Last regenerated when Spreader was corrected to the phoneboy.com/hdu spec
# (act-again, 20×opponents, Penn State punishes the spreader). Regenerate
# deliberately when flow changes.
GOLDEN = {
    1: (3, (1057, 529, 365, 231)),
    7: (2, (902, 1126, 178, 554)),
    42: (1, (1067, 697, 1117, 1134)),
}


@pytest.mark.parametrize("seed,expected", GOLDEN.items())
def test_golden_full_game(seed, expected):
    players = [RandomAI(seed=200 + i) for i in range(4)]
    final = play_game(seed, players)
    assert final.phase is Phase.GAME_OVER
    assert (final.winner, tuple(p.score for p in final.players)) == expected


# Two-player games exercise the §7 rule modifications end to end.
GOLDEN_2P = {
    1: (0, (757, 1155)),
    5: (1, (2011, 440)),
}


@pytest.mark.parametrize("seed,expected", GOLDEN_2P.items())
def test_golden_two_player_game(seed, expected):
    players = [RandomAI(seed=200 + i) for i in range(2)]
    final = play_game(seed, players, num_players=2)
    assert final.phase is Phase.GAME_OVER
    assert (final.winner, tuple(p.score for p in final.players)) == expected
