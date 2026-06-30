"""FastAPI app: REST + WebSocket over the authoritative session manager.

Thin glue. Every request resolves to a `GameSession` call; serialization is the
`serialize` module; no rules logic here. The WebSocket channel is the
multiplayer-ready path — actions submitted on any channel are broadcast (as
per-seat redacted snapshots) to all connected seats of that game.

Run locally:  uvicorn server.app:app --reload
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .serialize import decode_action, encode_actions, encode_events, encode_view
from .session import (
    GameFull,
    GameNotFound,
    GameSession,
    IllegalAction,
    NotYourTurn,
    SeatError,
    SessionError,
    SessionManager,
)

app = FastAPI(title="Hot Death Uno", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for self-hosted user testing
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SessionManager()


# --------------------------------------------------------------------------- #
# Passcode gate (optional). Set HDU_PASSCODE to require a shared code to *create*
# games; existing games are reached via their unguessable id, so only creation
# is gated. Unset/empty => no gate (open, e.g. for local dev and tests).
# --------------------------------------------------------------------------- #

def _passcode_ok(provided: str | None) -> bool:
    required = os.environ.get("HDU_PASSCODE", "")
    return (not required) or provided == required


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return {"passcode_required": bool(os.environ.get("HDU_PASSCODE", ""))}


# --------------------------------------------------------------------------- #
# Error handling: SessionError subclasses -> HTTP status codes.
# --------------------------------------------------------------------------- #

_STATUS = {
    GameNotFound: 404,
    GameFull: 409,
    NotYourTurn: 409,
    IllegalAction: 422,
    SeatError: 401,  # missing/invalid player token
}


@app.exception_handler(SessionError)
async def _session_error(_: Request, exc: SessionError) -> JSONResponse:
    code = next((c for cls, c in _STATUS.items() if isinstance(exc, cls)), 400)
    return JSONResponse(status_code=code, content={"error": type(exc).__name__, "detail": str(exc)})


# --------------------------------------------------------------------------- #
# Snapshot helper — what a seat needs to render.
# --------------------------------------------------------------------------- #

def snapshot(session: GameSession, seat: int) -> dict[str, Any]:
    return {
        "status": session.public_status(),
        "view": encode_view(session.view_for_seat(seat)),
        "legal_actions": encode_actions(session.legal_for_seat(seat)),
        "your_turn": (not session.is_over) and session.state.to_act == seat,
        "hand_result": session.hand_result(),  # set only at an end-of-hand pause
    }


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #

def _seat_of(session: GameSession, token: str | None) -> int:
    """Resolve the caller's seat from their player token (raises SeatError)."""
    return session.seat_for_token(token)


class CreateGameRequest(BaseModel):
    num_players: int = Field(default=4, ge=2, le=10)
    num_humans: int = Field(default=1, ge=1, le=10)
    hand_size: int = Field(default=7, ge=2, le=15)
    seed: int | None = None


@app.post("/api/games")
async def create_game(
    req: CreateGameRequest,
    x_hdu_passcode: str | None = Header(default=None),
) -> dict[str, Any]:
    if not _passcode_ok(x_hdu_passcode):
        raise HTTPException(status_code=401, detail="bad or missing passcode")
    if req.num_humans > req.num_players:
        raise HTTPException(status_code=422, detail="num_humans exceeds num_players")
    # Humans take the low seats (0..num_humans-1); the rest are AI.
    session = manager.create_game(
        num_players=req.num_players,
        hand_size=req.hand_size,
        human_seats=set(range(req.num_humans)),
        seed=req.seed,
    )
    seat, token = session.claim_seat()  # the creator is seated first (seat 0)
    return {
        "game_id": session.game_id,
        "seat": seat,
        "player_token": token,
        "status": session.public_status(),
    }


class JoinRequest(BaseModel):
    player_token: str | None = None  # present on reconnect


@app.post("/api/games/{game_id}/join")
async def join_game(game_id: str, req: JoinRequest) -> dict[str, Any]:
    session = manager.get(game_id)
    seat, token = session.claim_seat(req.player_token)
    await hub.broadcast(game_id, session, [])  # let seated players see the lobby fill
    return {"seat": seat, "player_token": token, "status": session.public_status()}


@app.get("/api/games/{game_id}/state")
async def get_state(
    game_id: str, x_hdu_player: str | None = Header(default=None)
) -> dict[str, Any]:
    session = manager.get(game_id)
    return snapshot(session, _seat_of(session, x_hdu_player))


@app.get("/api/games/{game_id}/events")
async def get_events(game_id: str, cursor: int = Query(0)) -> dict[str, Any]:
    session = manager.get(game_id)
    events, new_cursor = session.events_since(cursor)
    return {"events": encode_events(events), "cursor": new_cursor}


class ActionRequest(BaseModel):
    type: str
    hand_index: int | None = None
    color: str | None = None
    player: int | None = None


@app.post("/api/games/{game_id}/action")
async def post_action(
    game_id: str, action: ActionRequest, x_hdu_player: str | None = Header(default=None)
) -> dict[str, Any]:
    session = manager.get(game_id)
    seat = _seat_of(session, x_hdu_player)
    events = session.submit(seat, decode_action(action.model_dump(exclude_none=True)))
    await hub.broadcast(game_id, session, events)
    return {"events": encode_events(events), "snapshot": snapshot(session, seat)}


@app.post("/api/games/{game_id}/continue")
async def post_continue(
    game_id: str, x_hdu_player: str | None = Header(default=None)
) -> dict[str, Any]:
    """Acknowledge an end-of-hand pause and deal the next hand."""
    session = manager.get(game_id)
    seat = _seat_of(session, x_hdu_player)
    events = session.continue_hand(seat)
    await hub.broadcast(game_id, session, events)
    return {"events": encode_events(events), "snapshot": snapshot(session, seat)}


# --------------------------------------------------------------------------- #
# WebSocket push (the multiplayer-ready channel)
# --------------------------------------------------------------------------- #

class Hub:
    """Tracks live WebSocket connections per game so actions on any channel push
    a fresh per-seat snapshot to every connected seat."""

    def __init__(self) -> None:
        self._conns: dict[str, set[tuple[int, WebSocket]]] = {}

    def add(self, game_id: str, seat: int, ws: WebSocket) -> None:
        self._conns.setdefault(game_id, set()).add((seat, ws))

    def remove(self, game_id: str, seat: int, ws: WebSocket) -> None:
        conns = self._conns.get(game_id)
        if conns:
            conns.discard((seat, ws))
            if not conns:
                self._conns.pop(game_id, None)

    async def broadcast(self, game_id: str, session: GameSession, events: list) -> None:
        payload_events = encode_events(events)
        dead: list[tuple[int, WebSocket]] = []
        for seat, ws in self._conns.get(game_id, set()):
            try:
                await ws.send_json(
                    {"type": "update", "events": payload_events, "snapshot": snapshot(session, seat)}
                )
            except Exception:  # noqa: BLE001 — drop a broken connection
                dead.append((seat, ws))
        for seat, ws in dead:
            self.remove(game_id, seat, ws)


hub = Hub()


@app.websocket("/api/games/{game_id}/ws")
async def game_ws(websocket: WebSocket, game_id: str, token: str = Query(...)) -> None:
    await websocket.accept()
    try:
        session = manager.get(game_id)
        seat = session.seat_for_token(token)
    except GameNotFound:
        await websocket.close(code=4404)
        return
    except SeatError:
        await websocket.close(code=4401)  # bad/missing token
        return

    hub.add(game_id, seat, websocket)
    try:
        await websocket.send_json({"type": "snapshot", "snapshot": snapshot(session, seat)})
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")
            if kind in ("action", "continue"):
                try:
                    if kind == "action":
                        events = session.submit(seat, decode_action(msg["action"]))
                    else:
                        events = session.continue_hand(seat)
                except SessionError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                await hub.broadcast(game_id, session, events)
            # other message types (e.g. "ping") are ignored for now
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(game_id, seat, websocket)


# --------------------------------------------------------------------------- #
# Static frontend (slice 4). Mounted last so /api/* wins. Safe if absent.
# --------------------------------------------------------------------------- #

_STATIC = Path(__file__).parent / "static"
if _STATIC.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
else:
    @app.get("/")
    async def root() -> dict[str, str]:
        return {"app": "Hot Death Uno", "api": "/api", "frontend": "not built yet"}
