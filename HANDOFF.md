# Hot Death Uno — Python Engine Handoff

## 0. Read this first

You are building a single-player, AI-opponent implementation of **Hot Death Uno (HDU)**, a heavily modified Uno variant. The human player will play against programmed opponents in a text (CLI) harness.

There is one architectural rule that everything else serves: **the rules engine is a pure, framework-free Python module that knows nothing about the UI, the AI, or the network.** It exposes `apply(state, action) -> (new_state, events)` and `legal_actions(state)`. The AI and the CLI are *consumers* of that engine. We are deliberately keeping a clean seam so that "online multiplayer" can later be added as a transport layer (a websocket server feeding the same engine) without rewriting the rules.

Do **not** start by writing all the cards. Build vanilla Uno first against a dumb AI, prove a full hand plays end to end, then layer HDU's special cards in one at a time. The hardest part of the whole project — the response/defense stack — is the *last* milestone, built on top of a proven engine.

If a rule is ambiguous or a deck multiplicity is unspecified below, **ask rather than guess.** Several decisions are deliberately left open in Section 9.

---

## 1. Build milestones (do them in order)

Each milestone should end with the game in a runnable, tested state. Do not begin a milestone until the previous one is green.

**M0 — Skeleton & deck.** Dataclasses for `Card`, `GameState`, `PlayerState`. Construct a deck, shuffle (seeded), deal N cards each, flip the first discard. A CLI command prints the dealt state. No turns, no special cards yet.

**M1 — Vanilla Uno loop.** Numbers 0–9, Skip, Reverse, Draw Two, Wild. Turn advancement, play direction, match validation (color / number / wild), draw-from-pile, reshuffle the discard into the draw pile when it empties, and win detection (a player empties their hand). A dumb "random legal move" AI. Goal: a full hand plays start to finish in the CLI with 4 AI players.

**M2 — Scoring & multi-hand game.** End-of-hand point tally (losers sum the cards left in hand; winner scores 0), running scores across hands, dealer rotation, game ends when someone reaches 1000 points, and the **lowest** total wins (this is golf scoring — low is good). Now you have a complete, if vanilla, game.

**M3 — HDU cards with no defense interactions.** Add the special cards that don't touch the response stack: Double Skip, Reverse Skip, Spreader (+ Penn State protection), M.A.D., Quitter (basic), Glasnost, and all the *scoring-only* specials (Sixty Nine, AIDS cumulative penalty, Holy Defender halving, Fucker doubling, Shitter, Penn State point value, Luck o' the Irish, Mystery Draw). One card per change, each with tests.

**M4 — The response stack & Draw-Four defenses.** The hard milestone. Implement the pending-attack resolver (Section 4). Draw-Four-type stacking (Draw Four, Hot Death = 8, Delayed Blast = 4 + skip, Harvester = 4 + undefendable). Defenses: Fuck You/bounce (+ reverse), Holy Defender (pass), AIDS (split), Magic 5 (nullify Hot Death only).

**M5 — Edge cases & scoring order.** Bastard-card hand-end, Quitter+Fucker = 1000, two-player rule modifications, the deal special conditions, Mystery Draw reading the number underneath it, and the end-of-hand scoring order of operations.

---

## 2. Architecture & project layout

```
hdu/
  __init__.py
  cards.py        # Card, CardId, Color enums; deck construction
  state.py        # GameState, PlayerState (frozen dataclasses)
  actions.py      # Action variants (PlayCard, DrawCard, ChooseColor, ...)
  engine.py       # apply(state, action) -> EngineResult; legal_actions(state)
  effects.py      # per-card effect resolution + the response-stack resolver
  scoring.py      # end-of-hand scoring (ordered)
  view.py         # view_for(state, player_id) -> redacted PlayerView
  rng.py          # seeded RNG helpers
  players/
    base.py       # Player protocol: decide(view, legal_actions) -> Action
    random_ai.py  # dumb baseline opponent
  cli.py          # text harness to play a human vs AIs
tests/
  test_vanilla.py
  test_cards_*.py
  test_scoring.py
  test_golden_games.py
```

Design constraints:

- **Engine is pure.** No `print`, no file/network I/O, no global state, no wall-clock or un-seeded randomness. All randomness comes from a seeded `random.Random` carried in `GameState` (or threaded through explicitly) so any game is fully replayable.
- **State transitions return events.** `apply` returns `(new_state, [Event, ...])`. Events are structured records (`PlayerDrew`, `DirectionReversed`, `PlayerEliminated`, `UnoCalled`, `ColorChosen`, ...). The CLI/AI/logger react to events; the engine never knows they exist.
- **`legal_actions(state)` is the single source of truth for what may happen next**, including response-window actions. Both the AI and a future network client are handed a view + the legal action list and return exactly one action. If `legal_actions` is correct, illegal states are unreachable.
- **Perspective filtering exists from day one.** `view_for(state, player_id)` returns a `PlayerView` that redacts other players' hands (showing counts only). The AI consumes the *view*, not the raw state. This costs little now and is mandatory for the future authoritative server.
- **Prefer frozen dataclasses and pure functions** over mutation. Returning new state objects keeps replay/testing trivial. (If performance ever matters — it won't at this scale — optimize later.)

Use Python 3.12+, full type hints, `enum.Enum` for `Color` and `CardId`, stdlib only in the engine (no third-party deps). `pytest` for tests.

---

## 3. Core data model

Sketch — adjust field names as you see fit, but keep the shape:

```python
class Color(Enum): RED; YELLOW; GREEN; BLUE; WILD

@dataclass(frozen=True)
class Card:
    id: CardId            # stable internal identity (see Section 6)
    color: Color          # WILD for wilds; the printed color otherwise
    number: int | None    # 0..9 for number cards, else None
    # display_name is NOT stored on the card; resolve via a name map (Section 6)

@dataclass(frozen=True)
class DiscardEntry:
    card: Card
    eff_color: Color      # current effective color (a wild/defense can set this)
    eff_number: int | None  # what the top card "counts as" — Mystery Draw reads this

@dataclass(frozen=True)
class PlayerState:
    id: int
    hand: tuple[Card, ...]
    score: int = 0            # running game score (low is good)
    aids_penalty: int = 0     # cumulative -10 per AIDS held at hand end
    eliminated: bool = False  # eliminated FROM THE CURRENT HAND (frozen hand)
    called_uno: bool = False

@dataclass(frozen=True)
class Pending:               # the response/attack stack — see Section 4
    kind: str               # "draw_stack" | "quitter" | "spreader" | "glasnost"
    target: int             # player who must respond
    origin: int             # player who started the attack
    draw_total: int = 0     # accumulated cards to draw (draw_stack)
    chain: tuple[CardId, ...] = ()
    undefendable: bool = False

@dataclass(frozen=True)
class GameState:
    players: tuple[PlayerState, ...]
    draw_pile: tuple[Card, ...]
    discard: tuple[DiscardEntry, ...]
    to_act: int             # whose decision the engine is waiting on
    direction: int          # +1 or -1
    pending: Pending | None # non-None => engine is in stack-resolution mode
    phase: str              # "play" | "choose_color" | "choose_victim" | "respond" | "hand_over" | "game_over"
    dealer: int
    rng_state: tuple        # so the whole game replays deterministically
```

`to_act` + `phase` + `pending` together tell `legal_actions` exactly what to offer. When `pending is not None`, the engine is resolving an attack and only stack-response actions are legal for `pending.target`.

---

## 4. The response stack (the load-bearing mechanic)

This is the part a naive implementation gets wrong. Treat it as a mini state machine, conceptually identical to the "stack" in Magic: The Gathering: an action is *announced* and opens a window for the next player to respond *before it resolves*.

When a player plays a Draw-Four-type card (Draw Four, Hot Death, Delayed Blast, Harvester of Sorrows), do **not** immediately make the next player draw. Instead:

1. Create/extend `pending` as a `draw_stack`: add this card's draw count to `draw_total` (Draw Four = 4, Hot Death = 8, Delayed Blast = 4, Harvester = 4), append to `chain`, set `target` to the next active player.
2. Enter `phase="respond"`. `legal_actions` now offers `target` only: stack another Draw-Four-type, play a valid defense, or **decline** (eat the whole `draw_total`).
3. Resolve based on the response:
   - **Stack** another Draw-Four-type → repeat from step 1 with the new next player. (Playtests have hit 32 accumulated cards.)
   - **Decline** → `target` draws `draw_total`, is skipped, stack clears.
   - **Fuck You (bounce)** → the draw goes back to the *last attacker*; play direction reverses; effective color becomes blue. The bounced-to player may themselves respond.
   - **Holy Defender** → the stack passes over `target` to the next player, who becomes the new `target`.
   - **AIDS** → `draw_total` is split evenly between `target` and the last attacker; both draw their half; stack clears. (Only works against defendable attacks.)
   - **Magic 5** → legal *only* when the top of the chain is Hot Death; nullifies Hot Death **and all draws stacked before it** (the whole stack evaporates). Magic 5 does not nullify a plain Draw Four stack.
   - **Harvester of Sorrows** is special: it adds 4 and is **undefendable** — set `pending.undefendable = True`. The next player takes the entire accumulated draw no matter what; no further defense is offered.
   - **Delayed Blast** additionally skips a player on resolution. A Fuck You bounced onto a Delayed Blast still follows bounce rules (it can come back to hit you).

Notes that bite if you forget them:
- **A non-Draw-Four card used as a defense changes the effective color to that card's color** (e.g. defending with the blue Fuck You makes the color blue).
- **Mystery Draw cannot enter a draw stack** in either direction — it is its own one-shot effect (Section 6) and has no defense.
- Quitter, Spreader, and Glasnost each open their *own* `pending` kind with their own response rules (Section 6) — model them with the same pending/respond machinery, not as instant effects.

---

## 5. Turn, direction, and elimination rules

- **Direction** is `+1` / `-1`. Reverse flips it. With 2 players, reverse behaves as a skip (Section 7).
- **Skips** advance past the next active player. Double Skip advances past two. Reverse Skip flips direction *then* skips one in the new direction.
- **Elimination is per-hand.** Quitter and M.A.D. set `eliminated=True` and freeze that player's hand until the hand ends. Turn advancement skips eliminated players.
- **A hand ends** when (a) a player empties their hand (they "win" the hand, scoring 0), **or** (b) all still-active players are eliminated (no winner — see scoring), **or** (c) a bastard-card / Quitter+Fucker terminal condition fires (Section 8).
- **Uno call.** When a player goes to one card they must call "Uno". If another player catches them before their next card is played, they draw 2. For the AI-only v1, model the call as automatic and add the catch mechanic as a later refinement (flag it as an open item — see Section 9).

---

## 6. Card reference (implementation spec)

Points are what the card is worth *to a player still holding it at hand end* unless noted. Identity is the printed color/number (matchable by color or number) or `WILD`. "Match rule" is when it may legally be played. Several names are deliberately crude in the source game; **store a stable internal `CardId` and resolve display strings through a `DISPLAY_NAMES` map** so labels are trivially swappable (the original ruleset itself suggests renaming). Suggested neutral IDs are given in parentheses.

### Tame cards (no defense exists against these)

- **Number 0–9** — match by color or number. Points = face value. No effect.
- **Skip** (`SKIP`) — 20 pts. Match by color or skip-symbol. Skips the next player.
- **Double Skip** (`DOUBLE_SKIP`) — 40 pts. Skips the next **two** players. (Treated as a single skip in 2-player.)
- **Reverse** (`REVERSE`) — 20 pts. Reverses direction.
- **Reverse Skip** (`REVERSE_SKIP`) — 40 pts. Reverses, then skips one player in the new direction.
- **Draw Two** (`DRAW_TWO`) — 20 pts. Next player draws 2 and is skipped. Does **not** stack with Draw-Fours; no defense.
- **Wild** (`WILD`) — 40 pts. Player chooses the next color (`phase="choose_color"`).

### Attacks that use the response stack

- **Draw Four** (`DRAW_FOUR`) — 50 pts. +4 to the draw stack, next player skipped, player chooses color. Defendable/stackable (Section 4). Not a unique card — multiple exist.
- **Hot Death** (`HOT_DEATH`, Wild) — 100 pts. A Draw **8** wild on the stack. Nullifiable only by Magic 5.
- **Delayed Blast** (`DELAYED_BLAST`, Wild) — 100 pts. Draw 4 that also skips a player. Bounce-able (a bounced Fuck You can return it to you).
- **Harvester of Sorrows** (`HARVESTER`, Wild) — 0 pts. Adds 4 and is **undefendable**; the next player eats the entire accumulated stack. Nastiest card; worth zero points to hold.

### Protective / defensive cards (also playable as normal cards by color/number)

- **Fuck You / Bounce** (`BOUNCE`, Blue 0) — used in defense, sends the punishment back to the sender and **reverses direction**; sets effective color blue. **Doubles your hand score if caught holding it** at hand end (or, with Quitter, the pair is worth 1000 — see Section 8).
- **Holy Defender** (`HOLY_DEFENDER`, Red 0) — defense: passes most punishments to the next player. **If caught holding it, your hand score is halved** (a negative total halved moves it toward zero, i.e. raises it).
- **AIDS / Share** (`SHARE`, Green 3) — 3 pts. Defense: splits a defendable punishment evenly between you and the inflicter. **If caught holding it, −10 to your hand this hand and every subsequent hand you lose, cumulative** (can be acquired multiple times). Store as `PlayerState.aids_penalty`.
- **Magic 5** (`MAGIC_5`, Red 5) — −5 pts. Playable on **any** card (wild placement). Nullifies Hot Death (and the stack beneath it). Negative value means it's usually held except to defend.
- **Penn State** (`PENN_STATE`, Blue 2) — protects only against Spreader (must be revealed). Point value when held = the value of the highest-point card in your hand.

### Eliminators

- **Quitter** (`QUITTER`, Green 0) — 100 pts (or 1000 with Fucker). Opens a `quitter` pending on the next player, who is eliminated (hand frozen) unless they respond: Fuck You → the Quitter player is eliminated instead; AIDS → both eliminated; Holy Defender → the elimination points to the following player.
- **M.A.D.** (`MUTUAL_DESTRUCT`, Yellow 1) — 75 pts. You are eliminated and you choose another player to be eliminated with you (`phase="choose_victim"`).

### Reveal / scoring specials

- **Glasnost** (`GLASNOST`, Red 2) — 75 pts. Choose a victim who must reveal their current hand to all. Defenses: AIDS → both reveal; Fuck You → the Glasnost player is affected and direction reverses; Holy Defender → passes to the next player.
- **Shitter / Dump** (`DUMP`, Yellow 0) — playable **only** on Holy Defender, Magic 5, or as your last card. At hand end, counts as 0 in your own total; but if you are *not* the highest scorer that hand, your hand score is bumped **up to equal** the highest scorer's. If you *are* the highest scorer, no effect.
- **Sixty Nine** (`SIXTY_NINE`, Yellow 9 marked) — lets you play a 6 on a 9 or a 9 on a 6 (must reveal). If caught holding it, you score **69 for the hand regardless of other cards** — but this can be modified by Magic 5 / Holy Defender / Fucker, or overridden by Shitter.
- **Mystery Draw** (`MYSTERY_DRAW`, Wild) — effect: the next player draws a number of cards equal to the **number on the discard card it was played on top of** (`DiscardEntry.eff_number`) and is skipped. If that underlying number is 0 or absent, it acts as a plain Wild with no draw and no skip. **Cannot stack** with Draw-Fours; no defense. Held value = 10 × your highest number card (or 10 if you hold no number card; note a held Magic 5 as "−5" makes this −50).
- **Luck o' the Irish** (`LUCK`, Green 4) — 75 pts. When revealed, reduces any *punishment* draw by 1 — **except** the draw you take for being unable to play on your own turn (that one is not reducible).
- **Holy Defender** and **Fucker/Bounce** above also belong to the "bastard cards" terminal set in Section 8.

---

## 7. Two-player rule modifications

When exactly two players remain in the game, override:

- Anything implying direction (any reverse) → treated as an ordinary skip.
- Double Skip → ordinary skip.
- Delayed Blast → a normal Draw Four.
- M.A.D. → both players eliminated.
- Penn State → still works against Spreader.
- Quitter → the player who plays it wins by default, **unless** AIDS is played in response, in which case both die.

---

## 8. Scoring & terminal conditions

**Per-hand tally.** The player who empties their hand scores 0. Everyone else sums the cards left in their hand, applying the scoring specials. Add the result to each player's running score.

**End-of-hand scoring — apply in a defined order** (the modifiers interact, so order matters):

1. Compute each player's raw hand total (face values + each special's held value: Skip 20, Draw Four 50, Hot Death 100, Penn State = highest card value, Sixty Nine = 69-override, Mystery Draw = 10× highest number card, AIDS = 3, Magic 5 = −5, Harvester = 0, etc.).
2. Apply **Sixty Nine** override (69 regardless) where present, before the multiplicative modifiers.
3. Apply **Shitter**: if the holder is not the highest scorer, bump them to the highest scorer's total; else no effect. (Determine "highest scorer" from the totals after step 2.)
4. Apply **Holy Defender** (halve) and **Fucker/Bounce** (double) to the holders' totals.
5. Apply cumulative **AIDS** penalty: −10 per AIDS the player has acquired, this and every subsequent lost hand.

**Terminal conditions (check during play, not just at hand end):**

- Holding all four **bastard cards** simultaneously — Quitter, Shitter, Fucker, Holy Defender — ends the hand immediately; that holder scores 0.
- Being caught with **Quitter + Fucker** together is worth **1000 points** (effectively game over for that player).

**Game end.** The game ends when any player reaches 1000 points. The player with the **lowest** running total is the winner. Negative totals are possible (the theoretical floor is −120). If a hand ends with *all* players eliminated, there is no hand-winner: everyone tallies as normal, and the lowest hand-total deals next (break ties with a deck cut, low deals).

**The deal (first flipped discard) special conditions:**

- If the flipped starter is a draw card, it affects the dealer, with direction proceeding clockwise.
- If it's a directed card (Glasnost, M.A.D.), the dealer chooses the target.
- If the dealer would have to resolve an AIDS effect on the deal, the "half/split" penalty goes to nobody.

---

## 9. Open decisions — ask before guessing

1. **Deck multiplicities.** The physical game is built from three Uno decks with hand-modified cards, and each special is a singleton (except Draw Fours). Propose a concrete programmatic composition (counts per number/action card, one of each special) and confirm it before locking it in. Mechanics matter more than exact counts for v1, but the deck must be fixed and documented.
2. **Uno call/catch in single-player.** Recommend auto-calling for v1, with the catch mechanic added in M5. Confirm.
3. **Dealt hand size.** The rules let the dealer pick 5–15. Pick a sensible default (e.g. 7) for v1 and make it configurable.
4. **AI strategy depth.** v1 AI is "random legal move, prefer dumping high-point cards, defend when attacked and able." Anything smarter is out of scope until the engine is proven — but it must live behind the `Player` protocol so it can be swapped without touching the engine.

---

## 10. Testing strategy

- **`pytest`, deterministic seeds.** Every test constructs a game from a fixed seed so shuffles and draws are reproducible.
- **Per-card unit tests.** For each card, assert its effect on a hand-built `GameState` (direction flips, draw counts, eliminations, color changes).
- **Conservation invariant.** After *every* `apply`, assert `sum(len(hand)) + len(draw_pile) + len(discard) == DECK_SIZE`. Cards must never be created or lost. This single invariant catches a huge class of bugs — wire it into a test helper that runs after each action.
- **`legal_actions` is never empty** unless `phase in {"hand_over", "game_over"}`.
- **Golden-game replays.** Record `(seed, [action, ...]) -> expected final scores` for a handful of full games (including ones that exercise the stack, eliminations, and each terminal condition). These are your regression net — when you add a card in M3–M5, the golden games must still produce identical results (or you update them deliberately).
- **Stack-specific tests** in M4: a 3-deep Draw-Four stack resolved by decline; the same bounced by Fuck You; split by AIDS; nullified by Magic 5 on Hot Death; and a Harvester that ignores all of it.

---

## 11. What NOT to do in this phase

- No networking, no Flask, no web UI. CLI only.
- No "smart" AI. Random-legal baseline behind the `Player` protocol.
- Do not put rules logic in the CLI or the AI — if you find yourself deciding legality outside `engine.py`, stop and move it in.
- Do not implement all special cards at once. One card, one change, tests green, next card.
- Do not introduce un-seeded randomness or any I/O into the engine.

The north star: at the end of M5 you have a pure `hdu` engine that a websocket server could wrap unchanged. Keep that seam clean and the multiplayer door stays open.
