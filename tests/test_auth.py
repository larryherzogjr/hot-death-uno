"""Google OAuth sign-in plumbing (server/auth.py) and the login gate in app.py.

The live Google round-trip can't run here; these cover the pure helpers, the
/api/me surface, the require-login gate, and the AI bot naming.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import auth
from server.app import app, manager


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for var in (
        "HDU_PASSCODE", "HDU_TOKENS_FILE", "HDU_REQUIRE_LOGIN",
        "HDU_ALLOWED_EMAILS", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("server.app._AI_DELAY", 0)
    manager._games.clear()
    yield
    manager._games.clear()


@pytest.fixture
def client():
    return TestClient(app)


# -- session_name: prefer the verified given name -------------------------- #

def test_session_name_prefers_given_name():
    assert auth.session_name({"given_name": "Larry", "name": "Larry Herzog"}) == "Larry"


def test_session_name_falls_back_to_first_word_then_email():
    assert auth.session_name({"name": "Larry Herzog"}) == "Larry"
    assert auth.session_name({"email": "larry@example.com"}) == "larry"
    assert auth.session_name(None) is None
    assert auth.session_name({}) is None


# -- email allow-list ------------------------------------------------------ #

def test_email_allowed_open_when_unset():
    assert auth.email_allowed("anyone@example.com") is True


def test_email_allowed_respects_list(monkeypatch):
    monkeypatch.setenv("HDU_ALLOWED_EMAILS", "a@x.com, B@X.com")
    assert auth.email_allowed("a@x.com") is True
    assert auth.email_allowed("b@x.com") is True   # case-insensitive
    assert auth.email_allowed("c@x.com") is False
    assert auth.email_allowed(None) is False


# -- require_login flag ---------------------------------------------------- #

def test_require_login_flag(monkeypatch):
    assert auth.require_login() is False
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "1")
    assert auth.require_login() is True
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "yes")
    assert auth.require_login() is True
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "0")
    assert auth.require_login() is False


# -- /api/me --------------------------------------------------------------- #

def test_api_me_unauthenticated(client):
    me = client.get("/api/me").json()
    assert me["authenticated"] is False
    assert me["name"] is None
    assert me["oauth_enabled"] is False   # no client creds in the test env
    assert me["require_login"] is False


# -- login gate ------------------------------------------------------------ #

def test_require_login_blocks_create_and_join(client, monkeypatch):
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "1")
    # Create is refused without a signed-in session.
    assert client.post("/api/games", json={"seed": 1}).status_code == 401
    # And so is join (set up a game with the gate off, then turn it on).
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "0")
    gid = client.post("/api/games", json={"seed": 1, "num_players": 2, "num_humans": 2}).json()["game_id"]
    monkeypatch.setenv("HDU_REQUIRE_LOGIN", "1")
    assert client.post(f"/api/games/{gid}/join", json={}).status_code == 401


def test_login_optional_by_default(client):
    assert client.post("/api/games", json={"seed": 1}).status_code == 200


def test_auth_login_404_when_oauth_disabled(client):
    assert client.get("/auth/login", follow_redirects=False).status_code == 404


# -- AI seats are named so the table reads names throughout ---------------- #

def test_ai_seats_are_named(client):
    g = client.post("/api/games", json={"seed": 1, "num_players": 4, "num_humans": 1}).json()
    names = g["status"]["names"]
    # Seat 0 is the human (default "Player 0"); seats 1..3 are named bots.
    assert names["1"] == "Bot 1"
    assert names["2"] == "Bot 2"
    assert names["3"] == "Bot 3"
