"""Contract the UI relies on: an eliminated player is only ever ``to_act`` for
the M.A.D. choose-victim step, and always has a legal action there.

If this held falsely — an eliminated seat left ``to_act`` with no move — the
game would deadlock (a human can't act, everyone else waits on them). The
front-end keeps the controls live for exactly this case; this guards the
invariant it trusts.
"""

from __future__ import annotations

import random

from hdu.engine import apply, legal_actions, new_hand, settle_hand
from hdu.state import Phase


def test_eliminated_to_act_only_at_choose_victim_and_always_has_actions():
    seen_elim_to_act = False
    for seed in range(400):
        st = new_hand(seed=seed, num_players=4, hand_size=7)
        rng = random.Random(seed * 7 + 1)
        guard = 0
        while st.phase is not Phase.GAME_OVER and guard < 6000:
            guard += 1
            if st.phase is Phase.HAND_OVER:
                st, _ = settle_hand(st)
                continue
            if st.players[st.to_act].eliminated:
                # The only legit reason: M.A.D. — you pick who dies with you.
                assert st.phase is Phase.CHOOSE_VICTIM, (
                    f"eliminated seat {st.to_act} to_act in {st.phase} (seed {seed})"
                )
                assert legal_actions(st), (
                    f"eliminated seat {st.to_act} has no move (seed {seed}) — deadlock"
                )
                seen_elim_to_act = True
            la = legal_actions(st)
            assert la  # never a non-terminal dead end
            st, _ = apply(st, rng.choice(la))
    assert seen_elim_to_act  # the scenario actually occurs in these playouts
