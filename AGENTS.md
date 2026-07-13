# Hot Death Uno repository guide

## Purpose

Hot Death Uno is a deterministic Python rules engine with a FastAPI/WebSocket
server and a dependency-free browser client. The long-term architecture is an
authoritative multiplayer server over the same pure engine used by the CLI and
AI players.

Read `HANDOFF.md` for the complete game rules and card behavior. When it
conflicts with this file, `HANDOFF.md` controls game behavior and this file
controls repository practices.

## Architectural boundaries

- `hdu/` is a pure, framework-free engine. Keep it free of I/O, networking,
  wall-clock behavior, global mutable state, and unseeded randomness.
- `hdu.engine.apply(state, action)` and `hdu.engine.legal_actions(state)` are
  the authoritative rules boundary. Do not duplicate legality or card effects
  in the client, server, CLI, or AI.
- All state transitions return new state plus structured events.
- Preserve perspective filtering: clients and AI receive `view_for(...)`, not
  another player's hidden hand.
- `server/` is a consumer of the engine. It owns sessions, authentication,
  serialization, transport, and static assets, but not game rules.
- Display names are resolved from stable `CardId` values. Renaming a card must
  not change rules logic.

## Working conventions

- Python 3.12+, full type hints, frozen dataclasses where practical.
- The engine uses only the standard library. Web and test dependencies remain
  outside `hdu/`.
- Make focused rule changes one card or mechanic at a time.
- Treat `legal_actions` as the only accepted-action source; the server must
  revalidate every client submission.
- Preserve deterministic golden games unless a rule change intentionally
  changes their expected result.
- Never commit `.env`, access-code files, OAuth credentials, session secrets,
  or player tokens.

## Verification

Run before considering a change complete:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

The test suite must preserve these invariants:

1. The 113-card deck is conserved after every action.
2. `legal_actions(state)` is non-empty outside terminal phases.
3. Other players' hands remain redacted at the transport boundary.
4. A submitted action is rejected unless it is currently legal for that seat.

Useful local commands:

```bash
.venv/bin/python -m hdu.cli
.venv/bin/python -m hdu.cli --game
.venv/bin/uvicorn server.app:app --reload
```

## Deployment model

Production is intentionally a single Uvicorn worker because sessions are held
in memory. The app is bound to localhost in Docker and reached through nginx
with TLS and WebSocket upgrades. Moving to multiple workers requires a shared
session store; do not simply increase the worker count.
