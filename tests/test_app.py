"""FastAPI layer: REST + WebSocket, token-based seat auth, multi-human seats."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.app import app, manager


@pytest.fixture(autouse=True)
def _clean_manager(monkeypatch):
    monkeypatch.delenv("HDU_PASSCODE", raising=False)  # gate off unless a test sets it
    monkeypatch.delenv("HDU_TOKENS_FILE", raising=False)
    monkeypatch.setattr("server.app._AI_DELAY", 0)  # no pacing delay in tests
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
    return r.json()  # {game_id, seat, player_token, status}


def _hdr(token):
    return {"X-HDU-Player": token}


def _state(client, gid, token):
    return client.get(f"/api/games/{gid}/state", headers=_hdr(token)).json()


def _start(client, gid, host_token):
    return client.post(f"/api/games/{gid}/start", headers=_hdr(host_token))


# --------------------------------------------------------------------------- #
# Single-player basics.
# --------------------------------------------------------------------------- #

def test_create_returns_seat_and_token(client):
    data = _new_game(client)
    assert data["game_id"]
    assert data["seat"] == 0  # the creator is seated first
    assert data["player_token"]
    assert data["status"]["card_count"] == 113


def test_state_requires_a_token_and_is_redacted(client):
    g = _new_game(client)
    snap = _state(client, g["game_id"], g["player_token"])
    assert len(snap["view"]["hand"]) >= 1
    for opp in snap["view"]["opponents"]:
        assert "hand" not in opp and "hand_count" in opp
    # No / wrong token is rejected.
    assert client.get(f"/api/games/{g['game_id']}/state").status_code == 401
    assert client.get(
        f"/api/games/{g['game_id']}/state", headers=_hdr("nope")
    ).status_code == 401


def test_play_a_full_game_over_rest(client):
    g = _new_game(client)
    gid, tok = g["game_id"], g["player_token"]
    guard, saw_pause = 0, False
    while True:
        guard += 1
        assert guard < 20_000
        snap = _state(client, gid, tok)
        phase = snap["status"]["phase"]
        if phase == "game_over":
            break
        if phase == "hand_over":
            saw_pause = True
            assert client.post(f"/api/games/{gid}/continue", headers=_hdr(tok)).status_code == 200
            continue
        assert snap["your_turn"] is True
        r = client.post(f"/api/games/{gid}/action", headers=_hdr(tok), json=snap["legal_actions"][0])
        assert r.status_code == 200
    final = _state(client, gid, tok)
    assert final["status"]["winner"] is not None
    assert final["status"]["card_count"] == 113
    assert saw_pause


def test_unknown_game_is_404(client):
    r = client.get("/api/games/nope/state", headers=_hdr("x"))
    assert r.status_code == 404
    assert r.json()["error"] == "GameNotFound"


def test_illegal_action_is_422(client):
    g = _new_game(client)
    r = client.post(
        f"/api/games/{g['game_id']}/action",
        headers=_hdr(g["player_token"]),
        json={"type": "choose_victim", "player": 3},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "IllegalAction"


# --------------------------------------------------------------------------- #
# Multi-human seats.
# --------------------------------------------------------------------------- #

def test_join_assigns_seats_and_reports_full(client):
    g = _new_game(client, num_players=2, num_humans=2)  # host = seat 0
    gid = g["game_id"]
    j = client.post(f"/api/games/{gid}/join", json={}).json()
    assert j["seat"] == 1
    # Both human seats taken -> a third joiner is refused.
    full = client.post(f"/api/games/{gid}/join", json={})
    assert full.status_code == 409
    assert full.json()["error"] == "GameFull"


def test_reconnect_with_token_keeps_seat(client):
    g = _new_game(client, num_players=2, num_humans=2)
    gid = g["game_id"]
    j = client.post(f"/api/games/{gid}/join", json={}).json()
    again = client.post(f"/api/games/{gid}/join", json={"player_token": j["player_token"]}).json()
    assert again["seat"] == j["seat"]
    assert again["player_token"] == j["player_token"]


def test_two_humans_only_the_active_seat_can_act(client):
    g = _new_game(client, num_players=2, num_humans=2)
    gid, host_tok = g["game_id"], g["player_token"]
    other_tok = client.post(f"/api/games/{gid}/join", json={}).json()["player_token"]
    tokens = {0: host_tok, 1: other_tok}
    assert _start(client, gid, host_tok).status_code == 200

    # Whoever's turn it is can act; the other is rejected (NotYourTurn).
    snap = _state(client, gid, host_tok)
    to_act = snap["status"]["to_act"]
    wrong = tokens[1 - to_act]
    legal = _state(client, gid, tokens[to_act])["legal_actions"][0]
    assert client.post(f"/api/games/{gid}/action", headers=_hdr(wrong), json=legal).status_code == 409
    assert client.post(f"/api/games/{gid}/action", headers=_hdr(tokens[to_act]), json=legal).status_code == 200


def test_two_humans_play_a_full_game(client):
    g = _new_game(client, num_players=2, num_humans=2, seed=7)
    gid, host_tok = g["game_id"], g["player_token"]
    other_tok = client.post(f"/api/games/{gid}/join", json={}).json()["player_token"]
    tokens = {0: host_tok, 1: other_tok}
    assert _start(client, gid, host_tok).status_code == 200
    guard = 0
    while True:
        guard += 1
        assert guard < 40_000
        snap = _state(client, gid, host_tok)
        st = snap["status"]
        if st["phase"] == "game_over":
            break
        if st["phase"] == "hand_over":
            client.post(f"/api/games/{gid}/continue", headers=_hdr(host_tok))
            continue
        seat = st["to_act"]
        me = _state(client, gid, tokens[seat])
        client.post(f"/api/games/{gid}/action", headers=_hdr(tokens[seat]), json=me["legal_actions"][0])
    assert _state(client, gid, host_tok)["status"]["card_count"] == 113


# --------------------------------------------------------------------------- #
# Passcode + WebSocket.
# --------------------------------------------------------------------------- #

def test_passcode_gate(client, monkeypatch):
    monkeypatch.setenv("HDU_PASSCODE", "letmein")
    assert client.get("/api/config").json()["passcode_required"] is True
    assert client.post("/api/games", json={"seed": 1}).status_code == 401
    assert client.post(
        "/api/games", json={"seed": 1}, headers={"X-HDU-Passcode": "nope"}
    ).status_code == 401
    assert client.post(
        "/api/games", json={"seed": 1}, headers={"X-HDU-Passcode": "letmein"}
    ).status_code == 200


def test_no_passcode_required_when_unset(client):
    assert client.get("/api/config").json()["passcode_required"] is False
    assert client.post("/api/games", json={"seed": 1}).status_code == 200


def _create(client, code):
    return client.post("/api/games", json={"seed": 1}, headers={"X-HDU-Passcode": code})


def test_token_file_codes_work_and_revoke_live(client, monkeypatch, tmp_path):
    f = tmp_path / "tokens.txt"
    f.write_text("alpha\nbravo: Bob's code\n# a comment line\n")
    monkeypatch.setenv("HDU_TOKENS_FILE", str(f))

    assert client.get("/api/config").json()["passcode_required"] is True
    assert _create(client, "alpha").status_code == 200
    assert _create(client, "bravo").status_code == 200  # label after ':' ignored
    assert _create(client, "nope").status_code == 401

    # Revoke just 'alpha' by editing the file — takes effect immediately.
    f.write_text("bravo: Bob's code\n")
    assert _create(client, "alpha").status_code == 401
    assert _create(client, "bravo").status_code == 200  # others unaffected


def test_shared_passcode_and_token_file_combine(client, monkeypatch, tmp_path):
    f = tmp_path / "tokens.txt"
    f.write_text("filecode\n")
    monkeypatch.setenv("HDU_PASSCODE", "sharedcode")
    monkeypatch.setenv("HDU_TOKENS_FILE", str(f))
    assert _create(client, "sharedcode").status_code == 200
    assert _create(client, "filecode").status_code == 200
    assert _create(client, "other").status_code == 401


def test_modal_hidden_override_present(client):
    # Regression: `.modal { display: flex }` defeats the HTML `hidden` attribute
    # (author CSS beats the UA [hidden] rule), which left the rules modal stuck
    # open, empty, and unclosable. `.modal[hidden] { display: none }` re-hides it.
    css = client.get("/style.css").text
    assert ".modal[hidden]" in css and "display: none" in css


def test_me_overlay_hidden_override_present(client):
    # Same trap as the modal: `.me-overlay { display: flex }` overrode the `hidden`
    # attribute, so the "Eliminated" overlay showed over EVERY player's hand at all
    # times (not just eliminated ones). `.me-overlay[hidden] { display: none }` fixes it.
    css = client.get("/style.css").text
    assert ".me-overlay[hidden]" in css


def test_spa_index_is_no_cache_with_versioned_assets(client):
    # The SPA index must revalidate (no-cache) and reference versioned asset URLs
    # so a deploy busts even an aggressive browser/proxy cache.
    r = client.get("/")
    assert r.headers.get("cache-control") == "no-cache"
    body = r.text
    assert "app.js?v=" in body and "style.css?v=" in body


def test_websocket_pushes_snapshot_and_updates(client):
    g = _new_game(client)
    gid, tok = g["game_id"], g["player_token"]
    with client.websocket_connect(f"/api/games/{gid}/ws?token={tok}") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        snap = first["snapshot"]
        assert snap["view"]["me"] == 0
        if not snap["your_turn"]:
            return
        ws.send_json({"type": "action", "action": snap["legal_actions"][0]})
        update = ws.receive_json()
        assert update["type"] == "update"
        assert "events" in update and "snapshot" in update


def test_name_recorded_and_chat_broadcasts(client):
    g = _new_game(client, name="Alice")
    gid, tok = g["game_id"], g["player_token"]
    # The name is in the public status.
    assert _state(client, gid, tok)["status"]["names"]["0"] == "Alice"
    # Chat over the WS echoes back to the sender (and everyone).
    with client.websocket_connect(f"/api/games/{gid}/ws?token={tok}") as ws:
        ws.receive_json()  # snapshot
        ws.send_json({"type": "chat", "text": "hello table"})
        m = ws.receive_json()
        assert m["type"] == "chat"
        assert m["message"] == {"seat": 0, "name": "Alice", "text": "hello table"}


def test_single_player_starts_immediately(client):
    g = _new_game(client)  # num_humans defaults to 1
    assert g["status"]["started"] is True
    assert g["status"]["host_seat"] == 0


def test_multi_human_waits_in_lobby_until_host_starts(client):
    g = _new_game(client, num_players=3, num_humans=2)
    gid, host_tok = g["game_id"], g["player_token"]
    assert g["status"]["started"] is False  # sits in the lobby
    # No one can act before start.
    snap = _state(client, gid, host_tok)
    assert snap["your_turn"] is False and snap["legal_actions"] == []
    assert client.post(
        f"/api/games/{gid}/action", headers=_hdr(host_tok),
        json={"type": "draw_card"},
    ).status_code == 409  # NotYourTurn: not started

    # Only the host can start.
    other_tok = client.post(f"/api/games/{gid}/join", json={}).json()["player_token"]
    assert _start(client, gid, other_tok).status_code == 403
    assert _start(client, gid, host_tok).status_code == 200
    assert _state(client, gid, host_tok)["status"]["started"] is True


def test_start_converts_unfilled_human_seats_to_bots(client):
    # A 2-human game the host starts solo: seat 1 (nobody joined) becomes a bot.
    g = _new_game(client, num_players=2, num_humans=2)
    gid, host_tok = g["game_id"], g["player_token"]
    assert _start(client, gid, host_tok).status_code == 200
    st = _state(client, gid, host_tok)["status"]
    assert st["human_seats"] == [0]          # only the seat that was claimed
    assert st["names"]["1"] == "Bot 1"       # the no-show seat is now a bot
    # And the game is playable through to the end with just the one human.
    guard = 0
    while st["phase"] != "game_over":
        guard += 1
        assert guard < 20_000
        if st["phase"] == "hand_over":
            client.post(f"/api/games/{gid}/continue", headers=_hdr(host_tok))
        else:
            snap = _state(client, gid, host_tok)
            client.post(f"/api/games/{gid}/action", headers=_hdr(host_tok), json=snap["legal_actions"][0])
        st = _state(client, gid, host_tok)["status"]
    assert st["card_count"] == 113


def test_humans_watching_drives_pacing(client):
    # Pacing is skipped once no human is left in the hand, so an all-AI tail
    # plays out instantly instead of a beat per move.
    import dataclasses

    from server.app import _humans_watching

    g = manager.create_game(num_players=4, human_seats={0}, seed=3)
    assert _humans_watching(g) is True
    players = list(g.state.players)
    players[0] = dataclasses.replace(players[0], eliminated=True)  # human knocked out
    g.state = dataclasses.replace(g.state, players=tuple(players))
    assert _humans_watching(g) is False


def test_websocket_rejects_bad_token(client):
    g = _new_game(client)
    with pytest.raises(Exception):  # connection closed (4401) before any message
        with client.websocket_connect(f"/api/games/{g['game_id']}/ws?token=bogus") as ws:
            ws.receive_json()
