# Hot Death Uno

Hot Death Uno is a deterministic Python 3.12 rules engine with an authoritative
FastAPI/WebSocket multiplayer server and a dependency-free browser client. The
same immutable engine drives automated games, the CLI harness, and web sessions.

## Quick start

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --constraint constraints.txt -e '.[dev]'
```

Run the complete validation suite:

```bash
.venv/bin/ruff check hdu server tests
.venv/bin/mypy hdu server
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
docker compose config --quiet
docker compose build
```

Run a deterministic all-AI hand or full game:

```bash
.venv/bin/python -m hdu.cli --seed 0
.venv/bin/python -m hdu.cli --seed 0 --game
```

Run the web app locally at <http://127.0.0.1:8000>:

```bash
.venv/bin/uvicorn server.app:app --reload
```

## Architecture

- `hdu/engine.py`, `cards.py`, `state.py`, `actions.py`, `effects.py`,
  `scoring.py`, `events.py`, `rng.py`, and `view.py` form the pure rules kernel.
  `legal_actions(state)` and `apply(state, action)` are the authoritative boundary.
- `hdu/cli.py`, `hdu/play.py`, and `hdu/players/` are colocated consumers of that
  kernel; they do not decide legality or card effects.
- `server/session.py` owns in-memory sessions, seats, tokens, AI advancement, and
  server-side action revalidation.
- `server/app.py` owns HTTP/WebSocket transport, optional access controls and
  OAuth, chat, static assets, and per-seat redacted snapshots.
- `server/static/` is plain HTML, CSS, and JavaScript with no frontend build step.

Production intentionally runs one Uvicorn worker because sessions are held in
memory. See [deploy/README.md](deploy/README.md) for Docker/nginx/TLS operations.

## Rules and project guidance

- [HANDOFF.md](HANDOFF.md) is the canonical card and game-behavior specification.
- [AGENTS.md](AGENTS.md) defines repository practices and validation invariants.
- [RULES_DECISIONS.md](RULES_DECISIONS.md) records implemented v1 choices that
  still need explicit product confirmation.

Do not commit `.env`, access-code files, OAuth credentials, session secrets, or
player tokens.
