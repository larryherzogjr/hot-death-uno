"""Authoritative session manager: AI drive loop, turn enforcement, validation."""

from __future__ import annotations

import random

import pytest

from hdu.engine import card_count
from hdu.state import Phase
from server.session import (
    GameNotFound,
    IllegalAction,
    NotYourTurn,
    SeatError,
    SessionManager,
)


def test_all_ai_game_drives_to_completion():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats=set(), seed=3)
    assert g.is_over  # no human seats -> driven straight to GAME_OVER on create
    assert g.state.phase is Phase.GAME_OVER
    assert g.state.winner is not None
    assert card_count(g.state) == 113


def test_create_stops_at_the_human_turn():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats={0}, seed=5)
    # The drive loop ran AI seats and parked on the human (unless the game ended).
    if not g.is_over:
        assert g.state.to_act == 0
        assert g.legal_for_seat(0)  # non-empty on your turn
        assert g.legal_for_seat(1) == []  # not your turn


def test_human_plays_a_full_game_randomly():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats={0}, seed=9)
    rng = random.Random(0)
    guard = 0
    while not g.is_over:
        guard += 1
        assert guard < 10_000
        assert g.state.to_act == 0  # drive loop only ever parks on the human
        action = rng.choice(g.legal_for_seat(0))
        g.submit(0, action)
        assert card_count(g.state) == 113  # conserved across every submission
    assert g.state.phase is Phase.GAME_OVER


def test_submit_rejects_wrong_seat_and_illegal_action():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats={0}, seed=5)
    if g.is_over:
        pytest.skip("game ended during setup")
    # An AI seat cannot be submitted to.
    with pytest.raises(SeatError):
        g.submit(1, g.legal_for_seat(0)[0])
    # A made-up action that is not currently legal is refused.
    from hdu.actions import ChooseVictim

    legal = g.legal_for_seat(0)
    bogus = ChooseVictim(99)
    if bogus not in legal:
        with pytest.raises(IllegalAction):
            g.submit(0, bogus)


def test_out_of_turn_submit_raises():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats={0, 1}, seed=2)
    if g.is_over:
        pytest.skip("game ended during setup")
    acting = g.state.to_act
    other = 1 if acting == 0 else 0
    with pytest.raises(NotYourTurn):
        g.submit(other, g.legal_for_seat(acting)[0])


def test_event_cursor_advances():
    mgr = SessionManager()
    g = mgr.create_game(num_players=4, human_seats={0}, seed=9)
    if g.is_over:
        pytest.skip("game ended during setup")
    events, cursor = g.events_since(0)
    assert cursor == len(g.event_log)
    g.submit(0, g.legal_for_seat(0)[0])
    new_events, new_cursor = g.events_since(cursor)
    assert new_cursor >= cursor
    assert new_events == g.event_log[cursor:new_cursor]


def test_manager_lookup_and_missing():
    mgr = SessionManager()
    g = mgr.create_game(seed=1)
    assert mgr.get(g.game_id) is g
    with pytest.raises(GameNotFound):
        mgr.get("nope")


def test_seed_is_reproducible():
    a = SessionManager().create_game(num_players=4, human_seats=set(), seed=42)
    b = SessionManager().create_game(num_players=4, human_seats=set(), seed=42)
    assert [p.score for p in a.state.players] == [p.score for p in b.state.players]
    assert a.state.winner == b.state.winner
