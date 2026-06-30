"""Authoritative game sessions.

A ``GameSession`` owns one ``GameState`` and is the *only* thing that calls
``apply`` / ``settle_hand``. Human seats wait for submitted actions; AI seats are
driven automatically between human turns, and finished hands are auto-settled. A
submitted action is always re-validated against ``legal_actions`` — the client
is never trusted.

Hidden information stays server-side: clients receive a per-seat ``view_for``
(other hands redacted). Events are public (they never reveal a hidden hand), so
the event log is shared across seats and backs catch-up/resync via a cursor.

Seat identity is first-class from day one: single-player is just "seat 0 is
human, the rest are AI." Adding human seats later (real multiplayer) is only a
matter of which seats are in ``human_seats``.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from hdu.actions import Action
from hdu.engine import apply, card_count, legal_actions, new_hand, settle_hand
from hdu.events import Event
from hdu.players.random_ai import RandomAI
from hdu.scoring import score_hand
from hdu.state import GameState, Phase
from hdu.view import PlayerView, view_for

_TERMINAL = (Phase.HAND_OVER, Phase.GAME_OVER)
_MAX_ADVANCE = 100_000  # safety valve against a runaway drive loop


class SessionError(Exception):
    """Base class for session-level errors (map to 4xx at the API boundary)."""


class GameNotFound(SessionError):
    pass


class NotYourTurn(SessionError):
    pass


class IllegalAction(SessionError):
    pass


class SeatError(SessionError):
    pass


@dataclass
class GameSession:
    game_id: str
    state: GameState
    human_seats: frozenset[int]
    ai: dict[int, RandomAI]
    seed: int  # engine seed, kept so a game can be replayed for debugging
    event_log: list[Event] = field(default_factory=list)

    @property
    def num_players(self) -> int:
        return len(self.state.players)

    @property
    def is_over(self) -> bool:
        return self.state.phase is Phase.GAME_OVER

    # -- reads -------------------------------------------------------------- #

    def view_for_seat(self, seat: int) -> PlayerView:
        self._check_seat(seat)
        return view_for(self.state, seat)

    def legal_for_seat(self, seat: int) -> list[Action]:
        """Legal actions for ``seat`` — empty unless it is that seat's turn."""
        self._check_seat(seat)
        if self.state.phase in _TERMINAL or self.state.to_act != seat:
            return []
        return legal_actions(self.state)

    def events_since(self, cursor: int) -> tuple[list[Event], int]:
        """Public events appended since ``cursor``, plus the new cursor."""
        cursor = max(0, min(cursor, len(self.event_log)))
        return self.event_log[cursor:], len(self.event_log)

    def hand_result(self) -> dict | None:
        """At a hand-over pause, a preview of this hand's scoring (winner + the
        points each player gains) for display before the next deal. None unless
        we're paused between hands."""
        if self.state.phase is not Phase.HAND_OVER:
            return None
        gains = score_hand(self.state)
        return {"winner": self.state.winner, "gains": {i: gains[i] for i in gains}}

    def public_status(self) -> dict:
        s = self.state
        return {
            "game_id": self.game_id,
            "phase": s.phase.value,
            "to_act": s.to_act if s.phase not in _TERMINAL else None,
            "direction": s.direction,
            "dealer": s.dealer,
            "winner": s.winner,
            "scores": {p.id: p.score for p in s.players},
            "hand_counts": {p.id: len(p.hand) for p in s.players},
            "eliminated": [p.id for p in s.players if p.eliminated],
            "human_seats": sorted(self.human_seats),
            "event_cursor": len(self.event_log),
            "card_count": card_count(s),
        }

    # -- writes ------------------------------------------------------------- #

    def submit(self, seat: int, action: Action) -> list[Event]:
        """Apply a human action, then drive AI seats / settle until the next
        human turn or game end. Returns the events produced by this submission."""
        self._check_seat(seat)
        if seat not in self.human_seats:
            raise SeatError(f"seat {seat} is not a human seat")
        if self.state.phase in _TERMINAL:
            raise NotYourTurn("the game is between hands or over")
        if self.state.to_act != seat:
            raise NotYourTurn(f"it is seat {self.state.to_act}'s turn, not {seat}")
        if action not in legal_actions(self.state):
            raise IllegalAction(f"{action!r} is not legal right now")

        start = len(self.event_log)
        self.state, events = apply(self.state, action)
        self.event_log.extend(events)
        self._advance()
        return self.event_log[start:]

    def continue_hand(self, seat: int) -> list[Event]:
        """Acknowledge a finished hand and deal the next one (or end the game).
        Any human seat may trigger it. Returns the events produced."""
        self._check_seat(seat)
        if seat not in self.human_seats:
            raise SeatError(f"seat {seat} is not a human seat")
        if self.state.phase is not Phase.HAND_OVER:
            raise NotYourTurn("there is no finished hand to continue")
        start = len(self.event_log)
        self.state, events = settle_hand(self.state)
        self.event_log.extend(events)
        self._advance()
        return self.event_log[start:]

    def _advance(self) -> None:
        """Run AI seats until a human must act, the game ends, or a hand ends.

        With human seats, a finished hand *pauses* here so players can read the
        scoring; an explicit :meth:`continue_hand` settles it and deals the next.
        An all-AI game (no human seats) auto-settles straight through."""
        for _ in range(_MAX_ADVANCE):
            phase = self.state.phase
            if phase is Phase.GAME_OVER:
                return
            if phase is Phase.HAND_OVER:
                if self.human_seats:
                    return  # pause for humans; continue_hand() resumes
                self.state, events = settle_hand(self.state)
                self.event_log.extend(events)
                continue
            seat = self.state.to_act
            if seat in self.human_seats:
                return  # wait for a human submission
            action = self.ai[seat].decide(view_for(self.state, seat), legal_actions(self.state))
            self.state, events = apply(self.state, action)
            self.event_log.extend(events)
        raise RuntimeError("session drive loop exceeded its ceiling — likely a bug")

    def _check_seat(self, seat: int) -> None:
        if not (0 <= seat < self.num_players):
            raise SeatError(f"seat {seat} out of range for {self.num_players} players")


class SessionManager:
    """In-memory registry of live games. Single-process; fine for user testing.
    (Behind one interface so a shared store could replace it for scale-out.)"""

    def __init__(self) -> None:
        self._games: dict[str, GameSession] = {}

    def create_game(
        self,
        num_players: int = 4,
        hand_size: int = 7,
        human_seats: frozenset[int] | set[int] | None = None,
        seed: int | None = None,
    ) -> GameSession:
        if human_seats is None:
            human_seats = frozenset({0})
        human_seats = frozenset(human_seats)
        if any(not (0 <= s < num_players) for s in human_seats):
            raise SeatError("human seat out of range")
        if seed is None:
            seed = secrets.randbelow(2**31)

        state = new_hand(seed=seed, num_players=num_players, hand_size=hand_size)
        ai = {
            seat: RandomAI(seed=1000 + seat)
            for seat in range(num_players)
            if seat not in human_seats
        }
        game_id = secrets.token_urlsafe(8)
        session = GameSession(
            game_id=game_id, state=state, human_seats=human_seats, ai=ai, seed=seed
        )
        # Drive any AI seats that act before the first human turn.
        session._advance()
        self._games[game_id] = session
        return session

    def get(self, game_id: str) -> GameSession:
        try:
            return self._games[game_id]
        except KeyError:
            raise GameNotFound(game_id) from None

    def remove(self, game_id: str) -> None:
        self._games.pop(game_id, None)

    def __len__(self) -> int:
        return len(self._games)
