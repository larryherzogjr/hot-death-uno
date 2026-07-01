"""FastAPI app: REST + WebSocket over the authoritative session manager.

Thin glue. Every request resolves to a `GameSession` call; serialization is the
`serialize` module; no rules logic here. The WebSocket channel is the
multiplayer-ready path — actions submitted on any channel are broadcast (as
per-seat redacted snapshots) to all connected seats of that game.

Run locally:  uvicorn server.app:app --reload
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from . import auth

from .catalog import catalog_payload
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
# Signs the session cookie used for OAuth. Set HDU_SESSION_SECRET for logins to
# survive restarts; otherwise a random per-process secret is used.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("HDU_SESSION_SECRET") or secrets.token_urlsafe(32),
    same_site="lax",
)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    """Make browsers revalidate the SPA assets every load, so a deploy is picked
    up immediately instead of running a stale mix of cached old/new files."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response

manager = SessionManager()


# --------------------------------------------------------------------------- #
# Access gate (optional). Valid codes come from HDU_PASSCODE (a single shared
# code) and/or HDU_TOKENS_FILE (a file with one code per line — `code` or
# `code: label`, `#` comments allowed). The file is read live on each check, so
# codes can be handed out or revoked by editing it — no restart, and removing
# one code doesn't affect the others. Only game *creation* is gated; existing
# games are reached via their unguessable id. No codes => open server.
# --------------------------------------------------------------------------- #

def _valid_codes() -> set[str]:
    codes: set[str] = set()
    shared = os.environ.get("HDU_PASSCODE", "").strip()
    if shared:
        codes.add(shared)
    path = os.environ.get("HDU_TOKENS_FILE", "").strip()
    if path:
        try:
            for line in Path(path).read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                code = line.split(":", 1)[0].strip()  # allow "code: label"
                if code:
                    codes.add(code)
        except OSError:
            pass  # missing/unreadable file -> just those codes absent
    return codes


def _passcode_ok(provided: str | None) -> bool:
    codes = _valid_codes()
    return (not codes) or (provided in codes)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe — cheap, unauthenticated, no session work. Used by the
    Docker HEALTHCHECK / autoheal and any external uptime monitor."""
    return {"status": "ok"}


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return {"passcode_required": bool(_valid_codes())}


@app.get("/api/cards")
async def get_cards() -> dict[str, Any]:
    """Static card catalog + rules primer for the rules page and tooltips."""
    return catalog_payload()


# --------------------------------------------------------------------------- #
# Google OAuth (optional). Identity only: a verified first name. Access is still
# gated by the passcode/token list unless HDU_REQUIRE_LOGIN makes sign-in
# mandatory. All endpoints no-op gracefully when OAuth isn't configured.
# --------------------------------------------------------------------------- #

@app.get("/api/me")
async def api_me(request: Request) -> dict[str, Any]:
    user = auth.current_user(request)
    return {
        "authenticated": bool(user),
        "name": auth.session_name(user),
        "email": (user or {}).get("email"),
        "oauth_enabled": auth.oauth_enabled(),
        "require_login": auth.require_login(),
    }


@app.get("/auth/login")
async def auth_login(request: Request):
    if not auth.oauth_enabled():
        raise HTTPException(status_code=404, detail="OAuth is not configured")
    return await auth.google().authorize_redirect(request, auth.callback_url(request))


@app.get("/auth/callback")
async def auth_callback(request: Request):
    if not auth.oauth_enabled():
        raise HTTPException(status_code=404, detail="OAuth is not configured")
    try:
        token = await auth.google().authorize_access_token(request)
    except Exception:  # noqa: BLE001 — bad/expired code, user cancelled, etc.
        return RedirectResponse("/?login=failed")
    info = token.get("userinfo") or {}
    if not auth.email_allowed(info.get("email")):
        request.session.pop("user", None)
        return RedirectResponse("/?login=denied")
    request.session["user"] = {
        "name": info.get("name"),
        "given_name": info.get("given_name"),
        "email": info.get("email"),
        "sub": info.get("sub"),
    }
    return RedirectResponse("/")


@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse("/")


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
        "your_turn": session.started and (not session.is_over) and session.state.to_act == seat,
        "hand_result": session.hand_result(),  # set only at an end-of-hand pause
    }


# Pace AI turns: one move per broadcast, a beat apart, so players watch each AI
# play its card. Tunable via HDU_AI_DELAY (seconds); tests set it to 0. A per-game
# lock keeps two drivers from interleaving (only one runs — a human can't act
# mid-cascade).
_AI_DELAY = float(os.environ.get("HDU_AI_DELAY", "1.2"))
_drive_locks: dict[str, asyncio.Lock] = {}


def _humans_watching(session: GameSession) -> bool:
    """Whether any human seat is still active in the current hand. When every
    human is eliminated there's no one to watch, so the rest of the hand plays
    out instantly instead of a beat per AI move."""
    players = session.state.players
    return any(not players[s].eliminated for s in session.human_seats)


async def _drive_ai(game_id: str) -> None:
    session = manager.get(game_id)
    async with _drive_locks.setdefault(game_id, asyncio.Lock()):
        while True:
            events = session.advance_one()
            if events is None:
                break
            await hub.broadcast(game_id, session, events)
            if _AI_DELAY and _humans_watching(session):
                await asyncio.sleep(_AI_DELAY)


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
    name: str | None = None


@app.post("/api/games")
async def create_game(
    request: Request,
    req: CreateGameRequest,
    x_hdu_passcode: str | None = Header(default=None),
) -> dict[str, Any]:
    user = auth.current_user(request)
    if auth.require_login() and user is None:
        raise HTTPException(status_code=401, detail="sign-in required")
    if not _passcode_ok(x_hdu_passcode):
        raise HTTPException(status_code=401, detail="bad or missing passcode")
    if req.num_humans > req.num_players:
        raise HTTPException(status_code=422, detail="num_humans exceeds num_players")
    # Humans take the low seats (0..num_humans-1); the rest are AI. Multi-human
    # games wait in a lobby until the host starts; single-player begins at once.
    multi_human = req.num_humans > 1
    session = manager.create_game(
        num_players=req.num_players,
        hand_size=req.hand_size,
        human_seats=set(range(req.num_humans)),
        seed=req.seed,
        start=not multi_human,
    )
    name = auth.session_name(user) or req.name  # verified name wins
    seat, token = session.claim_seat(name=name)  # the creator is seated first (seat 0)
    return {
        "game_id": session.game_id,
        "seat": seat,
        "player_token": token,
        "status": session.public_status(),
    }


class JoinRequest(BaseModel):
    player_token: str | None = None  # present on reconnect
    name: str | None = None


@app.post("/api/games/{game_id}/join")
async def join_game(request: Request, game_id: str, req: JoinRequest) -> dict[str, Any]:
    user = auth.current_user(request)
    if auth.require_login() and user is None:
        raise HTTPException(status_code=401, detail="sign-in required")
    session = manager.get(game_id)
    name = auth.session_name(user) or req.name
    seat, token = session.claim_seat(req.player_token, name=name)
    await hub.broadcast(game_id, session, [])  # let seated players see the lobby fill
    return {"seat": seat, "player_token": token, "status": session.public_status()}


@app.post("/api/games/{game_id}/start")
async def start_game(
    game_id: str, x_hdu_player: str | None = Header(default=None)
) -> dict[str, Any]:
    """Host-only: begin a lobbied multi-human game. Unfilled human seats become
    bots so a no-show can't wedge the game."""
    session = manager.get(game_id)
    seat = _seat_of(session, x_hdu_player)
    if seat != session.host_seat:
        raise HTTPException(status_code=403, detail="only the host can start the game")
    session.start(convert_unclaimed=True)
    await hub.broadcast(game_id, session, [])  # flip every client from lobby to table
    await _drive_ai(game_id)                    # paced opening AI cascade
    return {"ok": True, "status": session.public_status()}


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
    events = session.apply_human(seat, decode_action(action.model_dump(exclude_none=True)))
    await hub.broadcast(game_id, session, events)  # show the human's move at once
    await _drive_ai(game_id)  # then pace the AI cascade
    return {"events": encode_events(events), "snapshot": snapshot(session, seat)}


@app.post("/api/games/{game_id}/continue")
async def post_continue(
    game_id: str, x_hdu_player: str | None = Header(default=None)
) -> dict[str, Any]:
    """Acknowledge an end-of-hand pause and deal the next hand."""
    session = manager.get(game_id)
    seat = _seat_of(session, x_hdu_player)
    events = session.settle_pending(seat)
    await hub.broadcast(game_id, session, events)
    await _drive_ai(game_id)
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

    async def send_all(self, game_id: str, payload: dict) -> None:
        """Send one identical payload to every connection (e.g. chat — no redaction)."""
        dead: list[tuple[int, WebSocket]] = []
        for seat, ws in list(self._conns.get(game_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
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
        if session.chat_log:
            await websocket.send_json({"type": "chat_history", "messages": session.chat_log})
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type")
            if kind in ("action", "continue"):
                try:
                    if kind == "action":
                        events = session.apply_human(seat, decode_action(msg["action"]))
                    else:
                        events = session.settle_pending(seat)
                except SessionError as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    continue
                await hub.broadcast(game_id, session, events)  # human's move
                await _drive_ai(game_id)  # paced AI cascade
            elif kind == "chat":
                try:
                    chat = session.add_chat(seat, msg.get("text", ""))
                except SessionError:
                    continue
                await hub.send_all(game_id, {"type": "chat", "message": chat})
            # other message types (e.g. "ping") are ignored for now
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(game_id, seat, websocket)


# --------------------------------------------------------------------------- #
# Static frontend. Index is served with versioned asset URLs (a content hash) so
# a deploy busts even an aggressive browser/proxy cache; assets come from the
# StaticFiles mount, which ignores the ?v= query. Mounted last so /api/* wins.
# --------------------------------------------------------------------------- #

_STATIC = Path(__file__).parent / "static"


def _build_version() -> str:
    h = hashlib.sha1()
    for name in ("index.html", "app.js", "style.css"):
        p = _STATIC / name
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:8]


if _STATIC.is_dir():
    _BUILD = _build_version()
    _INDEX_HTML = (
        (_STATIC / "index.html").read_text()
        .replace('href="style.css"', f'href="style.css?v={_BUILD}"')
        .replace('src="app.js"', f'src="app.js?v={_BUILD}"')
    )

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML, headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
else:
    @app.get("/")
    async def root() -> dict[str, str]:
        return {"app": "Hot Death Uno", "api": "/api", "frontend": "not built yet"}
