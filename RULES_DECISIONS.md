# Rules decisions still requiring confirmation

The core M0–M5 mechanics are implemented and covered by deterministic tests, but
the following v1 choices are not fully aligned with `HANDOFF.md` or remain open.
They are documented here so “feature complete” does not conceal product decisions.

1. **Deck composition and card slots.** The implementation uses one modified
   108-card deck plus five singleton wild specials (113 cards total). Double Skip
   and Reverse Skip occupy red action slots; Spreader is a wild. Confirm this
   instead of the physical three-deck composition described in `HANDOFF.md`.
2. **Starter cards.** A Draw Two starter affects the dealer. Other draw-four and
   directed starters currently do not apply their full `HANDOFF.md` effects.
3. **Uno calls.** Calls are automatic; there is no catch-and-draw-two response
   window.
4. **Luck reveal.** Luck automatically reduces punishment draws whenever useful;
   the player cannot choose whether to reveal it.
5. **Last-card effects.** Draw effects still resolve after a player goes out;
   skip, reverse, wild, and directed effects are treated as moot.
6. **All-eliminated dealer ties.** Low seat ID breaks a lowest-score tie instead
   of simulating the specified deck cut.
Resolve these one at a time. Each accepted change should update `HANDOFF.md`, its
focused tests, and any affected golden-game results in the same commit.
