"""End-of-hand scoring. Golf scoring: low is good.

The held value of each card plus the ordered end-of-hand resolution from
HANDOFF §8. The winner (empty hand) scores 0; every other player tallies their
hand through the pipeline:

  1. raw total — face values + each card's held value (Penn State = highest-point
     card; Mystery Draw = 10× highest number card; Quitter 100; etc.)
  2. Sixty Nine override — 69 regardless, where held
  3. Shitter — if the holder is not the top scorer, bump them up to it
  4. Holy Defender halves / Fucker (Bounce) doubles the holder's total
  5. AIDS — cumulative −10 per acquired Share, applied to every lost hand

M5 owns the *locking* of this order against edge cases; M3 implements each
modifier here. A held Magic 5 = −5 (and its knock-on to Mystery Draw) lands with
Magic 5 itself in M4.
"""

from __future__ import annotations

from .cards import Card, CardId
from .effects import EffectKind, effect_kind
from .state import GameState, PlayerState

# Per-card held-value overrides (HANDOFF §6), checked before the by-kind table.
_HELD_OVERRIDE: dict[CardId, int] = {
    CardId.MUTUAL_DESTRUCT: 75,
    CardId.QUITTER: 100,  # M5: 1000 when paired with Fucker
    CardId.GLASNOST: 75,
    CardId.LUCK: 75,
    CardId.DRAW_FOUR: 50,
    CardId.HOT_DEATH: 100,
    CardId.DELAYED_BLAST: 100,
    CardId.HARVESTER: 0,  # nastiest card, worth nothing to hold
    CardId.MAGIC_5: -5,  # negative: usually held unless needed to defend
}

# Held-value by what a card does, for cards with a static value.
_POINTS: dict[EffectKind, int] = {
    EffectKind.SKIP: 20,
    EffectKind.DOUBLE_SKIP: 40,
    EffectKind.REVERSE: 20,
    EffectKind.REVERSE_SKIP: 40,
    EffectKind.DRAW_TWO: 20,
    EffectKind.WILD: 40,  # plain Wild + every wild-type until its milestone
}


def _base_value(card: Card) -> int:
    """Static (hand-independent) held value — also used to rank 'highest card'."""
    if card.id in _HELD_OVERRIDE:
        return _HELD_OVERRIDE[card.id]
    kind = effect_kind(card)
    if kind is EffectKind.NONE:  # number card (incl. number-overlay specials)
        return card.number if card.number is not None else 0
    return _POINTS[kind]


def _penn_state_value(hand: tuple[Card, ...]) -> int:
    """Penn State is worth the value of the highest-point *other* card held."""
    return max((_base_value(c) for c in hand if c.id is not CardId.PENN_STATE), default=0)


def _mystery_draw_value(hand: tuple[Card, ...]) -> int:
    """10× your highest number card (10 if you hold no number card). Uses held
    value, so a Magic 5 counts as −5 — e.g. Magic 5 alone makes this −50 (§6)."""
    vals = [_base_value(c) for c in hand if c.number is not None]
    return 10 * (max(vals) if vals else 1)


def card_held_value(card: Card, hand: tuple[Card, ...], num_opponents: int = 0) -> int:
    """Held value of a card in context: Penn State and Mystery Draw depend on the
    hand; Spreader is worth 20 × the number of opponents (phoneboy.com/hdu)."""
    if card.id is CardId.PENN_STATE:
        return _penn_state_value(hand)
    if card.id is CardId.MYSTERY_DRAW:
        return _mystery_draw_value(hand)
    if card.id is CardId.SPREADER:
        return 20 * num_opponents
    return _base_value(card)


def card_points(card: Card) -> int:
    """Static held value of a card (hand-independent). Penn State / Mystery Draw
    fall back to their printed base here; use :func:`card_held_value` in context."""
    return _base_value(card)


def hand_points(player: PlayerState, num_opponents: int = 0) -> int:
    """Step-1 raw total for a player's hand."""
    return sum(card_held_value(c, player.hand, num_opponents) for c in player.hand)


def _holds(player: PlayerState, cid: CardId) -> int:
    return sum(1 for c in player.hand if c.id is cid)


def score_hand(state: GameState) -> dict[int, int]:
    """Points each player gains this hand, via the ordered §8 pipeline. The hand
    winner (empty hand) gains 0; everyone else is a 'loser' and tallies."""
    players = state.players
    winner = state.winner
    num_opponents = len(players) - 1  # for Spreader's held value

    # 1. Raw totals.
    totals = {p.id: hand_points(p, num_opponents) for p in players}

    # 2. Sixty Nine override.
    for p in players:
        if _holds(p, CardId.SIXTY_NINE):
            totals[p.id] = 69

    # 3. Shitter: a non-top-scoring holder is bumped up to the top score.
    highest = max(totals.values(), default=0)
    for p in players:
        if _holds(p, CardId.DUMP) and totals[p.id] < highest:
            totals[p.id] = highest

    # 4. Holy Defender halves (toward zero); Fucker/Bounce doubles.
    for p in players:
        t = totals[p.id]
        for _ in range(_holds(p, CardId.HOLY_DEFENDER)):
            t = int(t / 2)  # truncate toward zero so negatives move toward zero
        for _ in range(_holds(p, CardId.BOUNCE)):
            t *= 2
        totals[p.id] = t

    # 5. AIDS: −10 per acquired Share, for every lost hand (not the winner).
    for p in players:
        if p.id == winner:
            continue
        new_count = p.aids_count + _holds(p, CardId.SHARE)
        totals[p.id] -= 10 * new_count

    # Terminal: caught with Quitter + Fucker together is worth 1000 (§8). The
    # bastard-four terminal (which contains both) ends the hand during play, so a
    # player tallied here with both never also holds the other two.
    for p in players:
        if p.id != winner and _holds(p, CardId.QUITTER) and _holds(p, CardId.BOUNCE):
            totals[p.id] = 1000

    if winner is not None:
        totals[winner] = 0
    return totals


def new_aids_counts(state: GameState) -> dict[int, int]:
    """Each player's AIDS count after this hand (cumulative; carried forward)."""
    return {
        p.id: p.aids_count + _holds(p, CardId.SHARE) for p in state.players
    }
