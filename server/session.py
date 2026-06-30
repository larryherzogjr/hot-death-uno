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


class GameFull(SessionError):
    pass


def _clean_name(name: str | None) -> str | None:
    if not name:
        return None
    return name.strip()[:24] or None


@dataclass
class GameSession:
    game_id: str
    state: GameState
    human_seats: frozenset[int]
    ai: dict[int, RandomAI]
    seed: int  # engine seed, kept so a game can be replayed for debugging
    event_log: list[Event] = field(default_factory=list)
    seat_tokens: dict[int, str] = field(default_factory=dict)  # claimed human seat -> token
    seat_names: dict[int, str] = field(default_factory=dict)   # claimed human seat -> display name
    chat_log: list[dict] = field(default_factory=list)         # recent chat (capped)

    @property
    def num_players(self) -> int:
        return len(self.state.players)

    # -- seats -------------------------------------------------------------- #

    def claim_seat(self, token: str | None = None, name: str | None = None) -> tuple[int, str]:
        """Claim a human seat. A matching ``token`` resumes its seat (reconnect);
        otherwise the lowest unclaimed human seat is assigned a fresh token.
        Raises :class:`GameFull` when every human seat is taken."""
        name = _clean_name(name)
        if token is not None:
            for seat, t in self.seat_tokens.items():
                if t == token:
                    if name:
                        self.seat_names[seat] = name
                    return seat, token
        for seat in sorted(self.human_seats):
            if seat not in self.seat_tokens:
                new = secrets.token_urlsafe(8)
                self.seat_tokens[seat] = new
                self.seat_names[seat] = name or f"Player {seat}"
                return seat, new
        raise GameFull("all human seats are taken")

    def add_chat(self, seat: int, text: str) -> dict:
        """Record a chat message from a seated player and return it for broadcast."""
        self._check_seat(seat)
        if seat not in self.seat_tokens:
            raise SeatError("only seated players can chat")
        text = (text or "").strip()[:500]
        if not text:
            raise IllegalAction("empty message")
        msg = {"seat": seat, "name": self.seat_names.get(seat, f"Player {seat}"), "text": text}
        self.chat_log.append(msg)
        if len(self.chat_log) > 50:
            del self.chat_log[:-50]
        return msg

    def seat_for_token(self, token: str | None) -> int:
        """The seat a token owns, or raise. Authorizes per-seat reads/actions."""
        if token is not None:
            for seat, t in self.seat_tokens.items():
                if t == token:
                    return seat
        raise SeatError("unknown or missing player token")

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
            "claimed_seats": sorted(self.seat_tokens),
            "names": dict(self.seat_names),
            "event_cursor": len(self.event_log),
            "card_count": card_count(s),
        }

    # -- writes ------------------------------------------------------------- #

    def apply_human(self, seat: int, action: Action) -> list[Event]:
        """Apply exactly one human action — no AI advance. Lets the app layer
        pace the AI cascade afterwards via :meth:`advance_one`."""
        self._check_seat(seat)
        if seat not in self.human_seats:
            raise SeatError(f"seat {seat} is not a human seat")
        if self.state.phase in _TERMINAL:
            raise NotYourTurn("the game is between hands or over")
        if self.state.to_act != seat:
            raise NotYourTurn(f"it is seat {self.state.to_act}'s turn, not {seat}")
        if action not in legal_actions(self.state):
            raise IllegalAction(f"{action!r} is not legal right now")
        self.state, events = apply(self.state, action)
        self.event_log.extend(events)
        return list(events)

    def settle_pending(self, seat: int) -> list[Event]:
        """Settle a finished hand (one step) — no AI advance. The next hand's AI
        cascade is then paced via :meth:`advance_one`."""
        self._check_seat(seat)
        if seat not in self.human_seats:
            raise SeatError(f"seat {seat} is not a human seat")
        if self.state.phase is not Phase.HAND_OVER:
            raise NotYourTurn("there is no finished hand to continue")
        self.state, events = settle_hand(self.state)
        self.event_log.extend(events)
        return list(events)

    def advance_one(self) -> list[Event] | None:
        """Perform the *next single* AI move or auto-settle, returning its events.
        Returns None when a human must act, the game is over, or a hand-over is
        paused for human review. Driving these one at a time (with a delay
        between) is what lets clients watch each AI play its card."""
        phase = self.state.phase
        if phase is Phase.GAME_OVER:
            return None
        if phase is Phase.HAND_OVER:
            if self.human_seats:
                return None  # pause for humans; settle_pending() resumes
            self.state, events = settle_hand(self.state)
            self.event_log.extend(events)
            return list(events)
        seat = self.state.to_act
        if seat in self.human_seats:
            return None  # wait for a human action
        action = self.ai[seat].decide(view_for(self.state, seat), legal_actions(self.state))
        self.state, events = apply(self.state, action)
        self.event_log.extend(events)
        return list(events)

    # Synchronous convenience (tests / non-paced callers): apply + drain the AI.

    def submit(self, seat: int, action: Action) -> list[Event]:
        start = len(self.event_log)
        self.apply_human(seat, action)
        self._advance()
        return self.event_log[start:]

    def continue_hand(self, seat: int) -> list[Event]:
        start = len(self.event_log)
        self.settle_pending(seat)
        self._advance()
        return self.event_log[start:]

    def _advance(self) -> None:
        for _ in range(_MAX_ADVANCE):
            if self.advance_one() is None:
                return
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
