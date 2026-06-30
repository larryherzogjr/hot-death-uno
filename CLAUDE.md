# CLAUDE.md

Standing conventions for this repo. Read every session. The detailed build spec — milestones, full card mechanics, the response-stack design, scoring order — lives in `HANDOFF.md`; this file is only the durable rules. When the two disagree, `HANDOFF.md` wins on *what* to build and this file wins on *how* to work.

## What this is

A single-player, AI-opponent implementation of **Hot Death Uno** (a modified Uno variant) in pure Python, played through a text CLI. The long-term goal is for the same engine to later sit behind a websocket server for online multiplayer — so the engine must stay transport-agnostic from day one.

## Project status

- Current milestone: **M5 — done. All milestones complete; the engine is feature-complete per HANDOFF.** 148 tests green; 240/240 mixed 4-player + 2-player games conserve 113 and terminate. M5 added: the **bastard-four terminal** (all four 0s — Quitter/Dump/Bounce/Holy-Defender — held → hand ends, holder scores 0; checked after every `apply` via the `_bastard_holder` chokepoint), **Quitter+Fucker = 1000** (scoring override), the **Magic 5 → Mystery Draw** knock-on (Mystery uses held values, so Magic 5 = −5 → −50), **all-eliminated "lowest deals next"** in `settle_hand`, the **2-player rules** (§7, gated on `_two_player` = 2 active: every reverse/skip variant → skip-and-play-again, Delayed Blast → no extra skip, M.A.D. → both die, Quitter → play-and-win unless AIDS), **last-card draw effects** (Draw Two / draw-four-types still hit the next player; other last-card effects moot), and the **Draw Two starter** deal condition.

  Prior: **M4** response stack (`pending.kind == "draw_stack"`: Draw Four/Hot Death/Delayed Blast/Harvester; defenses bounce/Holy-Defender/AIDS-split/Magic-5; Luck shaves punishment draws). **M3** Double/Reverse Skip, Spreader, M.A.D., Quitter, Glasnost, and the scoring-only specials as the ordered §8 pipeline in `scoring.py`. **M2** golf scoring + multi-hand. **M1** vanilla loop. **M0** 113-card deck. Engine surface: `Phase` {play, choose_color, choose_victim, respond, hand_over, game_over}; `Pending` kinds {draw_stack, spreader, quitter, glasnost, glasnost_choose}; actions PlayCard/DrawCard/ChooseColor/Pass/Reveal/Decline/ChooseVictim.

  **Wiki cross-check (phoneboy.com/hdu) decisions:** Verified consistent against the wiki except three items. **Fixed:** a defensive **Fuck You now reverses direction in every context** including a Quitter bounce (wiki: "whenever this is used to thwart a punishment, the direction of play will change") — previously only draw-stack/Glasnost bounces reversed. **Deliberately kept as-is** (user prefers ours): **Sixty Nine** is modelled as the card itself matching on a 6 or 9, rather than the wiki's held-enabler reading ("show it to play a regular 6 on a 9"); **Double Skip** skips **two** (wiki text is terse "skips the next person", but the card name and the 2-player "treated as a regular skip" downgrade both imply two). Note: the wiki specifies **no** end-of-hand scoring order, so the §8 step order is HANDOFF's own (not contradicted).

  **Documented v1 simplifications (deliberate, all noted in code):** Uno is auto-called, no catch (§9 sanctioned this for v1 — a manual call+catch window is the refinement). Deal conditions implement only the Draw Two starter; wild/draw-four starters open the color choice without a dealer-draw, directed-card (Glasnost/M.A.D.) starters seat without firing, and AIDS-on-deal naturally penalises nobody. Last-card effects apply only *draws* (skip/reverse/wild/directed are moot once the hand's over). Luck auto-reveals whenever beneficial. Spreader follows the phoneboy.com/hdu ruleset (every opponent draws 2 unless they show Penn State; no Penn State → Spreader player acts again; Penn State shown → Spreader player draws 2 and the Penn State holder takes the turn; held value = 20 × opponents), implemented via `Pending.penn_revealer`; its card identity/color is still an open placement choice. The AI is the random-legal baseline behind the `Player` protocol. Golden games (`tests/test_golden_games.py`, 4-player + 2-player) are regenerated **deliberately** whenever flow changes.

  Prior milestones: **M2 — done** (golf scoring; `settle_hand` carries scores / rotates dealer +1 / one continuous RNG / ends at 1000, lowest wins; `play_game`; CLI `--game`). **M1 — done** (vanilla turn loop). **M0 — done** (113-card deck). Golden games in `tests/test_golden_games.py` are regenerated **deliberately** whenever a special's effect/held-value shifts flow. Milestones are defined in `HANDOFF.md` §1.

  Toolchain note: system Python is 3.9; the 3.12 venv lives at `.venv/` (`python3.12 -m venv .venv`). Run tests with `.venv/bin/python -m pytest`.

## The cardinal rule: the engine is pure

`hdu/engine.py` exposes `apply(state, action) -> (new_state, events)` and `legal_actions(state)`, and that's the whole contract. The engine must contain **no** I/O, no `print`, no UI, no networking, no global mutable state, and no un-seeded randomness. All randomness comes from a seeded RNG carried in `GameState`, so every game replays deterministically.

Heuristic: **if you are deciding what is legal, or resolving a card's effect, anywhere other than the engine layer — stop and move it into the engine.** The CLI and the AI are consumers; they receive a state view plus `legal_actions` and return one action. Keeping this seam clean is what keeps the multiplayer door open.

## How to work

- **Build in milestone order** (`HANDOFF.md` §1). Do not start a milestone until the previous one is green.
- **One card at a time** in M3–M5. Add a single card, write its tests, get them passing, then move on. Never batch the special cards.
- **Run the tests before moving on.** A change isn't done until the checklist below passes.
- **Ask, don't guess**, on the open decisions in `HANDOFF.md` §9 (deck composition, Uno catch, hand size, AI depth). Surface a proposal and wait for confirmation rather than silently picking.

## Definition of done (every change)

1. `python -m pytest -q` is green.
2. The **card-conservation invariant** holds after every action: `sum(len(p.hand) for p in players) + len(draw_pile) + len(discard) == DECK_SIZE`. Cards are never created or destroyed. Run this assertion in a test helper after each `apply`.
3. `legal_actions(state)` is non-empty unless `phase` is `hand_over` or `game_over`.
4. The golden-game replay tests still produce identical final scores (or you changed them deliberately and said so).
5. No rules logic leaked outside `engine.py` / `effects.py`.

## Conventions

- Python **3.12+**, full type hints, `enum.Enum` for `Color` and `CardId`.
- **Stdlib only inside the `hdu` engine package.** Third-party deps (e.g. `pytest`, and later a server framework) live in tooling/tests, never imported by the engine.
- Prefer **frozen dataclasses and pure functions**; `apply` returns new state rather than mutating in place.
- The engine emits structured **events**; consumers react to events, the engine never knows they exist.
- **Card identity is stable; display names are not.** Store an internal `CardId` enum and resolve labels through a `DISPLAY_NAMES` map. Renaming a card must never touch rules logic. (Several source names are deliberately crude — the rename layer is how you swap them.)
- Perspective filtering exists from the start: the AI consumes `view_for(state, player_id)`, which redacts other hands — not raw `GameState`.

## Commands

Assumes the layout in `HANDOFF.md` §2 and a virtualenv with `pytest` installed.

```bash
.venv/bin/python -m pytest -q            # run the test suite (3.12 venv)
.venv/bin/python -m pytest -q -k NAME    # focused test while iterating
.venv/bin/python -m hdu.cli              # CLI: play a hand vs AI opponents
.venv/bin/python -m hdu.cli --game       # CLI: full game to 1000
.venv/bin/uvicorn server.app:app --reload  # web API (REST + WebSocket) at :8000
```

Web tooling deps (not imported by `hdu/`): `fastapi`, `uvicorn[standard]`, `httpx`, `websockets`. API lives under `/api/*`; the SPA (slice 4) mounts at `/` from `server/static/` when present. (Update this block if the toolchain changes — e.g. if you adopt `uv` or add a lint/format step.)

## Project phase

The engine (M0–M5) is feature-complete, so the project has moved into the **front-end / transport phase**: a self-hosted web app for user testing, designed to carry into the eventual websocket multiplayer. This relaxes the old "CLI only" rule — but only *outside* `hdu/`. The web layer lives in **`server/`** (a consumer that imports `hdu` and never modifies it): `server/serialize.py` (PlayerView/Action/Event ↔ JSON, pure) and `server/session.py` (authoritative `SessionManager`/`GameSession` that holds `GameState`, drives AI seats, re-validates every action against `legal_actions`). Done: `server/app.py` (FastAPI REST + WebSocket; API under `/api/*`, errors mapped to HTTP codes, broadcaster pushes per-seat snapshots) and the **vanilla-JS SPA** in `server/static/` (index.html/style.css/app.js — renders entirely off `legal_actions`, WebSocket-driven, validated live in a browser). Features layered on: an optional **passcode gate** (`HDU_PASSCODE` via `.env`/compose; gates game creation only), an **end-of-hand pause** (`continue_hand` + `hand_result` preview so players read the scoring before the next deal; all-AI games auto-settle), and **multi-human seats** — create with `num_humans`, players claim a seat via `POST /join` and get a secret **player token** (`seat_tokens`); the token authorizes actions and gates the redacted view (`X-HDU-Player` header, `?token=` on the WS), so you only see/play your own hand. Reconnect reuses the stored token; game-full → 409; join broadcasts so the lobby fills live. SPA shows a lobby (seat roles + invite link) and per-seat turn gating. **Card help**: `server/catalog.py` (per-CardId description/category/value/defense, curated from the wiki + house rules) served at `GET /api/cards` powers both a **Rules modal** (how-to-play primer + categorized card reference) and **in-game tooltips** (hover + a "?" badge). Tooltips show each card's *live* held value — the snapshot annotates every hand card with `card_held_value` (so Penn State/Mystery Draw/Spreader/Magic 5 read their real current worth, never a static guess). Run with `.venv/bin/uvicorn server.app:app`; preview config in `.claude/launch.json`. **Deploy artifacts ready** (slice 5): `Dockerfile` (python:3.12-slim, non-root, healthcheck, single worker), `requirements.txt` (prod = `fastapi` + `uvicorn[standard]` only — verified sufficient in a clean venv), `docker-compose.yml` (binds `127.0.0.1:8126`), `deploy/nginx/hdu.ospdy.com.conf` (reverse proxy + `wss` upgrade map + TLS), and `deploy/README.md` (DNS → compose up → nginx → certbot). Couldn't build the image locally (Docker daemon not running on this Mac); it builds/runs on the Ubuntu box. v1 = single uvicorn worker, in-memory sessions.

## Do not (still standing)

- **The `hdu/` engine stays pure**: stdlib only, no I/O, no networking, no un-seeded randomness, no rules logic. All of that lives in consumers (`server/`, `cli.py`, AI). This rule is permanent.
- No "smart" AI — random-legal baseline behind the `Player` protocol. Strategy is out of scope until the engine is proven.
- Don't implement all the special cards at once (engine work is done, but the discipline holds for any future card tweaks).
