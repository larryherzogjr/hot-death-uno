"""FastAPI layer: REST endpoints, error mapping, and the WebSocket channel."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app, manager


@pytest.fixture(autouse=True)
def _clean_manager():
    manager._games.clear()
    yield
    manager._games.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _new_game(client, **body):
    body.setdefault("seed", 9)
    r = client.post("/api/games", json=body)
    assert r.status_code == 200
    return r.json()


def test_create_game_returns_id_and_status(client):
    data = _new_game(client)
    assert data["game_id"]
    assert data["human_seats"] == [0]
    assert data["status"]["card_count"] == 113


def test_state_is_redacted_for_the_seat(client):
    gid = _new_game(client)["game_id"]
    r = client.get(f"/api/games/{gid}/state", params={"seat": 0})
    assert r.status_code == 200
    snap = r.json()
    assert len(snap["view"]["hand"]) >= 1
    for opp in snap["view"]["opponents"]:
        assert "hand" not in opp and "hand_count" in opp


def test_play_a_full_game_over_rest(client):
    gid = _new_game(client)["game_id"]
    guard = 0
    while True:
        guard += 1
        assert guard < 10_000
        snap = client.get(f"/api/games/{gid}/state", params={"seat": 0}).json()
        if snap["status"]["phase"] == "game_over":
            break
        assert snap["your_turn"] is True
        action = snap["legal_actions"][0]
        r = client.post(f"/api/games/{gid}/action", params={"seat": 0}, json=action)
        assert r.status_code == 200
        assert "events" in r.json()
    final = client.get(f"/api/games/{gid}/state", params={"seat": 0}).json()
    assert final["status"]["winner"] is not None
    assert final["status"]["card_count"] == 113


def test_unknown_game_is_404(client):
    r = client.get("/api/games/nope/state", params={"seat": 0})
    assert r.status_code == 404
    assert r.json()["error"] == "GameNotFound"


def test_illegal_action_is_422(client):
    gid = _new_game(client)["game_id"]
    # choose_victim is not legal at the opening of this game.
    r = client.post(
        f"/api/games/{gid}/action", params={"seat": 0}, json={"type": "choose_victim", "player": 3}
    )
    assert r.status_code == 422
    assert r.json()["error"] == "IllegalAction"


def test_submitting_to_an_ai_seat_is_400(client):
    gid = _new_game(client)["game_id"]
    r = client.post(
        f"/api/games/{gid}/action", params={"seat": 1}, json={"type": "draw_card"}
    )
    assert r.status_code in (400, 409)  # SeatError (400) or NotYourTurn (409)


def test_events_endpoint_paginates_by_cursor(client):
    gid = _new_game(client)["game_id"]
    first = client.get(f"/api/games/{gid}/events", params={"cursor": 0}).json()
    cursor = first["cursor"]
    snap = client.get(f"/api/games/{gid}/state", params={"seat": 0}).json()
    if snap["status"]["phase"] != "game_over":
        client.post(f"/api/games/{gid}/action", params={"seat": 0}, json=snap["legal_actions"][0])
        nxt = client.get(f"/api/games/{gid}/events", params={"cursor": cursor}).json()
        assert nxt["cursor"] >= cursor


def test_websocket_pushes_snapshot_and_updates(client):
    gid = _new_game(client)["game_id"]
    with client.websocket_connect(f"/api/games/{gid}/ws?seat=0") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        snap = first["snapshot"]
        if not snap["your_turn"]:
            return
        ws.send_json({"type": "action", "action": snap["legal_actions"][0]})
        update = ws.receive_json()
        assert update["type"] == "update"
        assert "events" in update and "snapshot" in update
