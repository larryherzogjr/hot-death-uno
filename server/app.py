"""FastAPI app: REST + WebSocket over the authoritative session manager.

Thin glue. Every request resolves to a `GameSession` call; serialization is the
`serialize` module; no rules logic here. The WebSocket channel is the
multiplayer-ready path — actions submitted on any channel are broadcast (as
per-seat redacted snapshots) to all connected seats of that game.

Run locally:  uvicorn server.app:app --reload
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .serialize import decode_action, encode_actions, encode_events, encode_view
from .session import (
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
# Error handling: SessionError subclasses -> HTTP status codes.
# --------------------------------------------------------------------------- #

_STATUS = {
    GameNotFound: 404,
    NotYourTurn: 409,
    IllegalAction: 422,
    SeatError: 400,
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
    }


# --------------------------------------------------------------------------- #
# REST
# --------------------------------------------------------------------------- #

class CreateGameRequest(BaseModel):
    num_players: int = Field(default=4, ge=2, le=10)
    hand_size: int = Field(default=7, ge=2, le=15)
    human_seats: list[int] = Field(default_factory=lambda: [0])
    seed: int | None = None


@app.post("/api/games")
async def create_game(req: CreateGameRequest) -> dict[str, Any]:
    session = manager.create_game(
        num_players=req.num_players,
        hand_size=req.hand_size,
        human_seats=set(req.human_seats),
        seed=req.seed,
    )
    return {
        "game_id": session.game_id,
        "human_seats": sorted(session.human_seats),
        "status": session.public_status(),
    }


@app.get("/api/games/{game_id}/state")
async def get_state(game_id: str, seat: int = Query(...)) -> dict[str, Any]:
    return snapshot(manager.get(game_id), seat)


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
async def post_action(game_id: str, seat: int, action: ActionRequest) -> dict[str, Any]:
    session = manager.get(game_id)
    events = session.submit(seat, decode_action(action.model_dump(exclude_none=True)))
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
async def game_ws(websocket: WebSocket, game_id: str, seat: int = Query(...)) -> None:
    await websocket.accept()
    try:
        session = manager.get(game_id)
    except GameNotFound:
        await websocket.close(code=4404)
        return

    hub.add(game_id, seat, websocket)
    try:
        await websocket.send_json({"type": "snapshot", "snapshot": snapshot(session, seat)})
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "action":
                try:
                    events = session.submit(seat, decode_action(msg["action"]))
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
