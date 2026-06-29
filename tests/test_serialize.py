"""Wire serialization: round-trip actions, JSON-safe views and events."""

from __future__ import annotations

import json

from hdu.actions import (
    ChooseColor,
    ChooseVictim,
    Decline,
    DrawCard,
    Pass,
    PlayCard,
    Reveal,
)
from hdu.cards import Color
from hdu.engine import apply, legal_actions, new_hand
from hdu.players.random_ai import RandomAI
from hdu.view import view_for
from server.serialize import (
    decode_action,
    encode_action,
    encode_events,
    encode_view,
)

ALL_ACTIONS = [
    PlayCard(3),
    DrawCard(),
    ChooseColor(Color.RED),
    ChooseColor(Color.BLUE),
    Pass(),
    Reveal(1),
    Decline(),
    ChooseVictim(2),
]


def test_actions_round_trip_exactly():
    for a in ALL_ACTIONS:
        assert decode_action(encode_action(a)) == a


def test_action_encoding_is_json_safe():
    for a in ALL_ACTIONS:
        blob = json.dumps(encode_action(a))
        assert decode_action(json.loads(blob)) == a


def test_legal_actions_round_trip_in_a_real_state():
    state = new_hand(seed=4, num_players=4, hand_size=7)
    for a in legal_actions(state):
        assert decode_action(json.loads(json.dumps(encode_action(a)))) == a


def test_view_is_json_serializable_and_redacted():
    state = new_hand(seed=7, num_players=4, hand_size=7)
    encoded = encode_view(view_for(state, 0))
    json.dumps(encoded)  # must not raise
    assert len(encoded["hand"]) == 7
    assert len(encoded["opponents"]) == 3
    # Opponent entries expose a count, not their cards.
    for opp in encoded["opponents"]:
        assert "hand_count" in opp and "hand" not in opp
    assert encoded["hand"][0]["name"]  # cards carry a display name


def test_events_are_json_serializable_across_a_full_hand():
    state = new_hand(seed=11, num_players=4, hand_size=7)
    players = [RandomAI(seed=i) for i in range(4)]
    seen_types = set()
    from hdu.state import Phase

    while state.phase not in (Phase.HAND_OVER, Phase.GAME_OVER):
        actor = state.to_act
        action = players[actor].decide(view_for(state, actor), legal_actions(state))
        state, events = apply(state, action)
        blob = json.dumps(encode_events(list(events)))  # must not raise
        for e in json.loads(blob):
            seen_types.add(e["type"])
    assert "CardPlayed" in seen_types
