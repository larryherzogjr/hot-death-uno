"""Authoritative session manager: AI drive loop, turn enforcement, validation."""

from __future__ import annotations

import random

import pytest

from hdu.engine import card_count
from hdu.state import Phase
from server.session import (
    GameFull,
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
    # The drive loop ran AI seats and parked on the human, the game ended, or a
    # hand ended during setup (an end-of-hand pause) — all valid.
    if g.is_over or g.state.phase is Phase.HAND_OVER:
        return
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
        assert guard < 20_000
        if g.state.phase is Phase.HAND_OVER:
            g.continue_hand(0)  # acknowledge the pause and deal the next hand
        else:
            assert g.state.to_act == 0  # drive loop only parks on the human
            g.submit(0, rng.choice(g.legal_for_seat(0)))
        assert card_count(g.state) == 113  # conserved across every step
    assert g.state.phase is Phase.GAME_OVER


def test_hand_over_pauses_for_humans_then_continues():
    g = SessionManager().create_game(num_players=4, human_seats={0}, seed=9)
    rng = random.Random(1)
    saw_pause = False
    guard = 0
    while not g.is_over:
        guard += 1
        assert guard < 20_000
        if g.state.phase is Phase.HAND_OVER:
            saw_pause = True
            assert g.hand_result() is not None  # scoring preview available
            assert g.legal_for_seat(0) == []    # no card actions during the pause
            g.continue_hand(0)
        else:
            g.submit(0, rng.choice(g.legal_for_seat(0)))
    assert saw_pause  # a hand ended and paused rather than auto-dealing


def test_continue_requires_a_finished_hand():
    g = SessionManager().create_game(num_players=4, human_seats={0}, seed=9)
    if g.state.phase is Phase.HAND_OVER:
        pytest.skip("paused at setup")
    with pytest.raises(NotYourTurn):
        g.continue_hand(0)


def test_all_ai_game_does_not_pause():
    # No human seats -> hands auto-settle straight through to game over.
    g = SessionManager().create_game(num_players=4, human_seats=set(), seed=3)
    assert g.is_over and g.hand_result() is None


def test_claim_seats_lowest_first_then_full():
    g = SessionManager().create_game(num_players=4, human_seats={0, 1}, seed=1)
    s0, t0 = g.claim_seat()
    s1, t1 = g.claim_seat()
    assert [s0, s1] == [0, 1]  # lowest unclaimed first
    assert t0 != t1
    with pytest.raises(GameFull):
        g.claim_seat()


def test_reconnect_token_returns_same_seat():
    g = SessionManager().create_game(num_players=4, human_seats={0, 1}, seed=1)
    s0, t0 = g.claim_seat()
    g.claim_seat()  # someone takes seat 1
    assert g.claim_seat(t0) == (s0, t0)  # reconnect keeps the seat


def test_advance_one_steps_the_ai_then_stops_at_the_human():
    g = SessionManager().create_game(num_players=4, human_seats={0}, seed=9)
    if g.is_over or g.state.phase is Phase.HAND_OVER:
        pytest.skip("game ended/paused during setup")
    g.apply_human(0, g.legal_for_seat(0)[0])  # human acts, no AI advance yet
    steps = 0
    while g.advance_one() is not None:  # drive AI one move at a time
        steps += 1
        assert steps < 5_000
        assert card_count(g.state) == 113
    # Parked again on the human (or terminal / paused) — never mid-AI-turn.
    assert g.is_over or g.state.phase is Phase.HAND_OVER or g.state.to_act == 0


def test_seat_for_token_authorizes():
    g = SessionManager().create_game(num_players=4, human_seats={0}, seed=1)
    seat, token = g.claim_seat()
    assert g.seat_for_token(token) == seat
    with pytest.raises(SeatError):
        g.seat_for_token("bogus")
    with pytest.raises(SeatError):
        g.seat_for_token(None)


def test_names_and_chat():
    from server.session import IllegalAction

    g = SessionManager().create_game(num_players=4, human_seats={0, 1}, seed=1)
    g.claim_seat(name="Alice")
    g.claim_seat(name="  Bob  ")
    assert g.public_status()["names"] == {0: "Alice", 1: "Bob"}  # trimmed

    msg = g.add_chat(0, "  hi there  ")
    assert msg == {"seat": 0, "name": "Alice", "text": "hi there"}
    assert g.chat_log[-1] == msg
    with pytest.raises(IllegalAction):
        g.add_chat(0, "   ")           # empty rejected
    with pytest.raises(SeatError):
        g.add_chat(2, "I'm an AI")     # only seated players can chat


def test_reconnect_updates_name():
    g = SessionManager().create_game(num_players=2, human_seats={0, 1}, seed=1)
    seat, token = g.claim_seat(name="Al")
    g.claim_seat(token, name="Alice")  # same token, new name
    assert g.public_status()["names"][seat] == "Alice"


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
