# CLAUDE.md (legacy compatibility)

Codex and other maintainers should read `AGENTS.md` first. This file remains for
Claude Code compatibility and historical project notes. Run the suite rather
than maintaining a test-count claim here; counts below are historical snapshots.

Standing conventions for this repo. Read every session. The detailed build spec — milestones, full card mechanics, the response-stack design, scoring order — lives in `HANDOFF.md`; this file is only the durable rules. When the two disagree, `HANDOFF.md` wins on *what* to build and this file wins on *how* to work.

## What this is

A deterministic **Hot Death Uno** rules engine with an all-AI CLI harness and an
authoritative FastAPI/WebSocket multiplayer server. The rules kernel remains
transport-agnostic; `server/` and the browser client are consumers.

## Project status

- Current milestone: **the M0–M5 core is implemented and regression-tested, but
  product-level rules decisions remain.** See `RULES_DECISIONS.md`; do not call
  the rules feature-complete until those choices are confirmed. M5 added the
  bastard-four terminal, Quitter+Fucker scoring, Magic 5/Mystery Draw interaction,
  all-eliminated dealing, two-player variants, last-card draws, and Draw Two starters.

  Prior: **M4** response stack (`pending.kind == "draw_stack"`: Draw Four/Hot Death/Delayed Blast/Harvester; defenses bounce/Holy-Defender/AIDS-split/Magic-5; Luck shaves punishment draws). **M3** Double/Reverse Skip, Spreader, M.A.D., Quitter, Glasnost, and the scoring-only specials as the ordered §8 pipeline in `scoring.py`. **M2** golf scoring + multi-hand. **M1** vanilla loop. **M0** 113-card deck. Engine surface: `Phase` {play, choose_color, choose_victim, respond, hand_over, game_over}; `Pending` kinds {draw_stack, spreader, quitter, glasnost, glasnost_choose}; actions PlayCard/DrawCard/ChooseColor/Pass/Reveal/Decline/ChooseVictim.

  **Wiki cross-check (phoneboy.com/hdu) decisions:** Verified consistent against the wiki except three items. **Fixed:** a defensive **Fuck You now reverses direction in every context** including a Quitter bounce (wiki: "whenever this is used to thwart a punishment, the direction of play will change") — previously only draw-stack/Glasnost bounces reversed. **Deliberately kept as-is** (user prefers ours): **Sixty Nine** is modelled as the card itself matching on a 6 or 9, rather than the wiki's held-enabler reading ("show it to play a regular 6 on a 9"); **Double Skip** skips **two** (wiki text is terse "skips the next person", but the card name and the 2-player "treated as a regular skip" downgrade both imply two). Note: the wiki specifies **no** end-of-hand scoring order, so the §8 step order is HANDOFF's own (not contradicted).

  **Documented v1 simplifications (deliberate, all noted in code):** Uno is auto-called, no catch (§9 sanctioned this for v1 — a manual call+catch window is the refinement). Deal conditions implement only the Draw Two starter; wild/draw-four starters open the color choice without a dealer-draw, directed-card (Glasnost/M.A.D.) starters seat without firing, and AIDS-on-deal naturally penalises nobody. Last-card effects apply only *draws* (skip/reverse/wild/directed are moot once the hand's over). Luck auto-reveals whenever beneficial. Spreader follows the phoneboy.com/hdu ruleset (every opponent draws 2 unless they show Penn State; no Penn State → Spreader player acts again; Penn State shown → Spreader player draws 2 and the Penn State holder takes the turn; held value = 20 × opponents), implemented via `Pending.penn_revealer`; its card identity/color is still an open placement choice. The AI is the random-legal baseline behind the `Player` protocol. Golden games (`tests/test_golden_games.py`, 4-player + 2-player) are regenerated **deliberately** whenever flow changes.

  Prior milestones: **M2 — done** (golf scoring; `settle_hand` carries scores / rotates dealer +1 / one continuous RNG / ends at 1000, lowest wins; `play_game`; CLI `--game`). **M1 — done** (vanilla turn loop). **M0 — done** (113-card deck). Golden games in `tests/test_golden_games.py` are regenerated **deliberately** whenever a special's effect/held-value shifts flow. Milestones are defined in `HANDOFF.md` §1.

  Toolchain note: use Python 3.12 and install the checked development environment
  as documented in `README.md`.

## The cardinal rule: the engine is pure

`hdu/engine.py` exposes `apply(state, action) -> (new_state, events)` and `legal_actions(state)`, and that's the whole contract. The engine must contain **no** I/O, no `print`, no UI, no networking, no global mutable state, and no un-seeded randomness. All randomness comes from a seeded RNG carried in `GameState`, so every game replays deterministically.

Heuristic: **if you are deciding what is legal, or resolving a card's effect, anywhere other than the engine layer — stop and move it into the engine.** The CLI and the AI are consumers; they receive a state view plus `legal_actions` and return one action. Keeping this seam clean is what keeps the multiplayer door open.

## How to work

- **Build in milestone order** (`HANDOFF.md` §1). Do not start a milestone until the previous one is green.
- **One card at a time** in M3–M5. Add a single card, write its tests, get them passing, then move on. Never batch the special cards.
- **Run the tests before moving on.** A change isn't done until the checklist below passes.
- **Ask, don't guess**, on the open decisions in `HANDOFF.md` §9 (deck composition, Uno catch, hand size, AI depth). Surface a proposal and wait for confirmation rather than silently picking.

## Definition of done (every change)

1. Ruff, mypy, `python -m pytest -q`, and `python -m pip check` are green.
2. The **card-conservation invariant** holds after every action: `sum(len(p.hand) for p in players) + len(draw_pile) + len(discard) == DECK_SIZE`. Cards are never created or destroyed. Run this assertion in a test helper after each `apply`.
3. `legal_actions(state)` is non-empty unless `phase` is `hand_over` or `game_over`.
4. The golden-game replay tests still produce identical final scores (or you changed them deliberately and said so).
5. No rules logic leaked outside `engine.py` / `effects.py`.

## Conventions

- Python **3.12+**, full type hints, `enum.Enum` for `Color` and `CardId`.
- **Stdlib only inside the `hdu` rules kernel.** The colocated CLI/play/AI
  consumers also use the standard library; web dependencies stay in `server/`.
- Prefer **frozen dataclasses and pure functions**; `apply` returns new state rather than mutating in place.
- The engine emits structured **events**; consumers react to events, the engine never knows they exist.
- **Card identity is stable; display names are not.** Store an internal `CardId` enum and resolve labels through a `DISPLAY_NAMES` map. Renaming a card must never touch rules logic. (Several source names are deliberately crude — the rename layer is how you swap them.)
- Perspective filtering exists from the start: the AI consumes `view_for(state, player_id)`, which redacts other hands — not raw `GameState`.

## Commands

Assumes the layout in `HANDOFF.md` §2 and a virtualenv with `pytest` installed.

```bash
.venv/bin/python -m pytest -q            # run the test suite (3.12 venv)
.venv/bin/python -m pytest -q -k NAME    # focused test while iterating
.venv/bin/ruff check hdu server tests
.venv/bin/mypy hdu server
.venv/bin/python -m hdu.cli              # CLI: play a hand vs AI opponents
.venv/bin/python -m hdu.cli --game       # CLI: full game to 1000
.venv/bin/uvicorn server.app:app --reload  # web API (REST + WebSocket) at :8000
```

Web tooling dependencies are declared in `pyproject.toml` and mirrored in
`requirements.txt`; exact resolutions live in `constraints.txt`. The API lives
under `/api/*`, and the SPA mounts at `/` from `server/static/`.

## Project phase

The project is in the **front-end / transport hardening phase**. The web layer
lives in `server/`; the vanilla-JS SPA lives in `server/static/`. It supports
multi-human lobbies, per-seat tokens and redacted views, optional passcodes and
Google OAuth, chat, card help, paced AI turns, and end-of-hand review. Deployment
uses the locally verified Python 3.12 Docker image, nginx/TLS, a health check, and
one Uvicorn worker because sessions remain in memory.

## Do not (still standing)

- **The `hdu/` rules kernel stays pure**: stdlib only, no I/O, no networking,
  and no unseeded randomness. I/O and transport live in consumers. This rule is
  permanent.
- No "smart" AI — random-legal baseline behind the `Player` protocol. Strategy is out of scope until the engine is proven.
- Don't implement all the special cards at once (engine work is done, but the discipline holds for any future card tweaks).
