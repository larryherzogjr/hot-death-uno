"""Wire serialization: engine types <-> JSON-able dicts.

Pure and stdlib-only. Views and events are *encode-only* (server -> client);
actions round-trip (client picks a legal action dict and posts it back, so
``decode_action(encode_action(a)) == a`` must hold). Cards carry their display
name so the client needs no card table.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from hdu.actions import (
    Action,
    ChooseColor,
    ChooseVictim,
    Decline,
    DrawCard,
    Pass,
    PlayCard,
    Reveal,
)
from hdu.cards import Card, CardId, Color, display_name
from hdu.events import CardPlayed, ColorChosen, Event, GameOver, HandScored
from hdu.state import DiscardEntry, Pending
from hdu.view import OpponentView, PlayerView

# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #

def encode_card(card: Card) -> dict[str, Any]:
    return {
        "id": card.id.name,
        "color": card.color.name,
        "number": card.number,
        "name": display_name(card),
        "wild": card.is_wild,
    }


def encode_discard(entry: DiscardEntry) -> dict[str, Any]:
    return {
        "card": encode_card(entry.card),
        "eff_color": entry.eff_color.name,
        "eff_number": entry.eff_number,
    }


def encode_opponent(o: OpponentView) -> dict[str, Any]:
    return {
        "id": o.id,
        "hand_count": o.hand_count,
        "score": o.score,
        "eliminated": o.eliminated,
        "called_uno": o.called_uno,
        "revealed_hand": (
            [encode_card(c) for c in o.revealed_hand] if o.revealed_hand is not None else None
        ),
    }


def encode_pending(p: Pending | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "kind": p.kind,
        "target": p.target,
        "origin": p.origin,
        "draw_total": p.draw_total,
        "chain": [cid.name for cid in p.chain],
        "undefendable": p.undefendable,
        "queue": list(p.queue),
        "penn_revealer": p.penn_revealer,
    }


def encode_view(v: PlayerView) -> dict[str, Any]:
    return {
        "me": v.me,
        "hand": [encode_card(c) for c in v.hand],
        "opponents": [encode_opponent(o) for o in v.opponents],
        "top": encode_discard(v.top),
        "to_act": v.to_act,
        "direction": v.direction,
        "phase": v.phase.value,
        "pending": encode_pending(v.pending),
        "draw_count": v.draw_count,
    }


# --------------------------------------------------------------------------- #
# Actions (round-trip)
# --------------------------------------------------------------------------- #

def encode_action(a: Action) -> dict[str, Any]:
    if isinstance(a, PlayCard):
        return {"type": "play_card", "hand_index": a.hand_index}
    if isinstance(a, DrawCard):
        return {"type": "draw_card"}
    if isinstance(a, ChooseColor):
        return {"type": "choose_color", "color": a.color.name}
    if isinstance(a, Pass):
        return {"type": "pass"}
    if isinstance(a, Reveal):
        return {"type": "reveal", "hand_index": a.hand_index}
    if isinstance(a, Decline):
        return {"type": "decline"}
    if isinstance(a, ChooseVictim):
        return {"type": "choose_victim", "player": a.player}
    raise TypeError(f"cannot encode action {a!r}")


def decode_action(d: dict[str, Any]) -> Action:
    t = d["type"]
    if t == "play_card":
        return PlayCard(int(d["hand_index"]))
    if t == "draw_card":
        return DrawCard()
    if t == "choose_color":
        return ChooseColor(Color[d["color"]])
    if t == "pass":
        return Pass()
    if t == "reveal":
        return Reveal(int(d["hand_index"]))
    if t == "decline":
        return Decline()
    if t == "choose_victim":
        return ChooseVictim(int(d["player"]))
    raise ValueError(f"unknown action type {t!r}")


def encode_actions(actions: list[Action]) -> list[dict[str, Any]]:
    return [encode_action(a) for a in actions]


# --------------------------------------------------------------------------- #
# Events (encode-only)
# --------------------------------------------------------------------------- #

def encode_event(e: Event) -> dict[str, Any]:
    name = type(e).__name__
    if isinstance(e, CardPlayed):
        return {"type": name, "player": e.player, "card": encode_card(e.card)}
    if isinstance(e, ColorChosen):
        return {"type": name, "player": e.player, "color": e.color.name}
    if isinstance(e, HandScored):
        return {"type": name, "hand_winner": e.hand_winner, "gains": [list(g) for g in e.gains]}
    if isinstance(e, GameOver):
        return {"type": name, "winner": e.winner, "scores": [list(s) for s in e.scores]}
    # Everything else has only int fields — asdict is JSON-safe.
    return {"type": name, **asdict(e)}


def encode_events(events: list[Event]) -> list[dict[str, Any]]:
    return [encode_event(e) for e in events]
