"""Per-card effect classification and match legality.

Two distinct notions live here, and keeping them apart matters:

* **match symbol** — what a card matches *as* on the discard (its printed
  family). Double Skip carries the skip symbol, Reverse Skip the reverse symbol,
  so they remain interchangeable with plain Skip/Reverse for legality.
* **effect kind** — what a card *does* when resolved. This is where specials
  graduate out of their vanilla base, one milestone at a time.

Still on their vanilla base (not yet implemented): Reverse Skip resolves as a
plain Reverse; every wild-type (Draw Four and the HDU wild specials) resolves as
a plain Wild. The response-stack resolver will live here too (M4).
"""

from __future__ import annotations

from enum import Enum, auto

from .cards import Card, CardId
from .state import DiscardEntry


class EffectKind(Enum):
    NONE = auto()  # number cards (incl. number-overlay specials)
    SKIP = auto()
    DOUBLE_SKIP = auto()  # M3: skips the next two players
    REVERSE = auto()
    REVERSE_SKIP = auto()  # M3: reverse, then skip one in the new direction
    DRAW_TWO = auto()
    MUTUAL_DESTRUCT = auto()  # M3: eliminate self + a chosen victim
    QUITTER = auto()  # M3: eliminate the next player (with defenses)
    GLASNOST = auto()  # M3: a chosen victim reveals their hand (with defenses)
    WILD = auto()  # plain Wild + every wild-type special until its milestone


def effect_kind(card: Card) -> EffectKind:
    """What a card resolves to when played."""
    cid = card.id
    if cid is CardId.SKIP:
        return EffectKind.SKIP
    if cid is CardId.DOUBLE_SKIP:
        return EffectKind.DOUBLE_SKIP
    if cid is CardId.REVERSE:
        return EffectKind.REVERSE
    if cid is CardId.REVERSE_SKIP:
        return EffectKind.REVERSE_SKIP
    if cid is CardId.DRAW_TWO:
        return EffectKind.DRAW_TWO
    if cid is CardId.MUTUAL_DESTRUCT:
        return EffectKind.MUTUAL_DESTRUCT
    if cid is CardId.QUITTER:
        return EffectKind.QUITTER
    if cid is CardId.GLASNOST:
        return EffectKind.GLASNOST
    if card.is_wild:
        return EffectKind.WILD
    return EffectKind.NONE


# What a card matches *as* on the discard (printed family). Specials inherit the
# symbol of the slot they were modified onto, so they stay interchangeable.
_MATCH_SYMBOL: dict[CardId, str] = {
    CardId.SKIP: "skip",
    CardId.DOUBLE_SKIP: "skip",
    CardId.REVERSE: "reverse",
    CardId.REVERSE_SKIP: "reverse",
    CardId.DRAW_TWO: "draw_two",
}


def match_symbol(card: Card) -> str | None:
    """The action symbol a card matches by, or None for numbers/wilds."""
    return _MATCH_SYMBOL.get(card.id)


def is_action(card: Card) -> bool:
    """A colored non-number card (Skip/Reverse/Draw Two family)."""
    return card.number is None and not card.is_wild


def matches(card: Card, top: DiscardEntry, *, is_only_card: bool = False) -> bool:
    """Whether ``card`` may legally be played on the current discard top.

    Vanilla rule: wilds always match; otherwise match by effective color, by
    number, or by action symbol. Two specials override this:

    * **Shitter/Dump** plays *only* on Holy Defender, Magic 5, or as your last
      card — never by ordinary color/number.
    * **Sixty Nine** additionally plays on a 6 or a 9 (the 69 ability).
    """
    if card.id is CardId.DUMP:
        return is_only_card or top.card.id in (CardId.HOLY_DEFENDER, CardId.MAGIC_5)
    if card.id is CardId.MAGIC_5:
        return True  # wild placement: playable on any card (HANDOFF §6)
    if card.is_wild:
        return True
    if card.color is top.eff_color:
        return True
    if card.number is not None and top.eff_number is not None and card.number == top.eff_number:
        return True
    if card.id is CardId.SIXTY_NINE and top.eff_number in (6, 9):
        return True
    sym = match_symbol(card)
    return sym is not None and sym == match_symbol(top.card)
