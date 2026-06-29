"""Card identity and deck construction for Hot Death Uno.

Card identity is stable; display names are not. Every card carries an internal
``CardId`` (and its printed ``Color`` / ``number``); human-facing labels are
resolved separately through :data:`DISPLAY_NAMES` / :func:`display_name`, so a
rename never touches rules logic. Several source names in the original game are
crude; the rename layer is how we swap them.

Deck composition (v1, confirmed) — a single standard 108-card Uno deck with the
HDU specials hand-modified onto specific real cards, exactly as the physical
game does it. Singleton specials map cleanly onto the singleton slots that
already exist (the four 0s, specific colored numbers, the wild slots).

Per color (RED, YELLOW, GREEN, BLUE):
  * one 0, two each of 1..9                         -> 19 number cards  (x4 = 76)
  * two Skip, two Reverse, two Draw Two             ->  6 action cards  (x4 = 24)
Wilds:
  * 4 plain Wild, 4 Draw Four                       ->  8
  * Hot Death, Delayed Blast, Harvester,
    Mystery Draw, Spreader (singleton wild adds)    ->  5
                                                       ----
                                          DECK_SIZE  = 113

Specials are *overlays*: they replace one instance of an existing slot (identity
changes, count does not) except the five singleton wild-types, which are added.

  Blue 0    -> Bounce            Green 0  -> Quitter
  Red 0     -> Holy Defender     Yellow 0 -> Dump (Shitter)
  Green 3   -> Share (AIDS)      Red 5    -> Magic 5
  Blue 2    -> Penn State        Yellow 1 -> M.A.D.
  Red 2     -> Glasnost          Yellow 9 -> Sixty Nine
  Green 4   -> Luck o' the Irish
  Red Skip  -> Double Skip       Red Reverse -> Reverse Skip

NEEDS CONFIRMATION (placeholders chosen so the deck is fixed for M0; changing
them later only touches this module + the conservation count):
  * Double Skip / Reverse Skip have no slot in HANDOFF §6. Modelled here as
    hand-modified RED action cards (so they retain a color and match on red or
    on their symbol). Color choice is arbitrary-but-fixed.
  * Spreader has no slot in §6, so it is modelled as a singleton WILD-type card
    (playable anytime, choose color). Its mechanics now follow the phoneboy.com/
    hdu ruleset: every opponent draws 2 unless they reveal a Penn State; with no
    Penn State shown the Spreader player acts again, otherwise the Spreader
    player draws 2 and the Penn State holder takes the turn; held value is
    20 × the number of opponents. (Card identity/color remains an open choice.)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Color(Enum):
    RED = "R"
    YELLOW = "Y"
    GREEN = "G"
    BLUE = "B"
    WILD = "W"


class CardId(Enum):
    # Generic (distinguished further by color/number, not by id)
    NUMBER = auto()
    SKIP = auto()
    REVERSE = auto()
    DRAW_TWO = auto()
    WILD = auto()
    DRAW_FOUR = auto()
    # Tame specials
    DOUBLE_SKIP = auto()
    REVERSE_SKIP = auto()
    # Stack attacks (wild-type)
    HOT_DEATH = auto()
    DELAYED_BLAST = auto()
    HARVESTER = auto()
    # Protective / defensive
    BOUNCE = auto()
    HOLY_DEFENDER = auto()
    SHARE = auto()
    MAGIC_5 = auto()
    PENN_STATE = auto()
    # Eliminators
    QUITTER = auto()
    MUTUAL_DESTRUCT = auto()
    # Reveal / scoring specials
    GLASNOST = auto()
    DUMP = auto()
    SIXTY_NINE = auto()
    MYSTERY_DRAW = auto()
    LUCK = auto()
    SPREADER = auto()


@dataclass(frozen=True)
class Card:
    """A card's stable identity. ``number`` is 0..9 for number cards else None.

    ``color`` is the printed color (``Color.WILD`` for wild-type cards). A
    special overlay keeps the printed identity of the slot it modified — e.g.
    Bounce is ``Card(CardId.BOUNCE, Color.BLUE, 0)`` and therefore matches as a
    blue 0 — while its id drives the special behaviour.
    """

    id: CardId
    color: Color
    number: int | None = None

    @property
    def is_wild(self) -> bool:
        return self.color is Color.WILD


# Neutral, renamed display labels for the specials (originals are crude).
DISPLAY_NAMES: dict[CardId, str] = {
    CardId.SKIP: "Skip",
    CardId.REVERSE: "Reverse",
    CardId.DRAW_TWO: "Draw Two",
    CardId.WILD: "Wild",
    CardId.DRAW_FOUR: "Draw Four",
    CardId.DOUBLE_SKIP: "Double Skip",
    CardId.REVERSE_SKIP: "Reverse Skip",
    CardId.HOT_DEATH: "Hot Death",
    CardId.DELAYED_BLAST: "Delayed Blast",
    CardId.HARVESTER: "Harvester of Sorrows",
    CardId.BOUNCE: "Bounce",
    CardId.HOLY_DEFENDER: "Holy Defender",
    CardId.SHARE: "Share",
    CardId.MAGIC_5: "Magic 5",
    CardId.PENN_STATE: "Penn State",
    CardId.QUITTER: "Quitter",
    CardId.MUTUAL_DESTRUCT: "M.A.D.",
    CardId.GLASNOST: "Glasnost",
    CardId.DUMP: "Dump",
    CardId.SIXTY_NINE: "Sixty Nine",
    CardId.MYSTERY_DRAW: "Mystery Draw",
    CardId.LUCK: "Luck o' the Irish",
    CardId.SPREADER: "Spreader",
}


def display_name(card: Card) -> str:
    """Human-facing label for a card. Rules logic must never depend on this."""
    if card.id is CardId.NUMBER:
        return f"{card.color.name.title()} {card.number}"
    label = DISPLAY_NAMES[card.id]
    if card.is_wild:
        return label
    return f"{card.color.name.title()} {label}"


_COLORS: tuple[Color, ...] = (Color.RED, Color.YELLOW, Color.GREEN, Color.BLUE)

# (color, number) slots that one special overlays. The 0s are singletons, so
# the overlay fully replaces them; for 1..9 one of the two instances is special
# and the other stays vanilla.
_NUMBER_OVERLAYS: dict[tuple[Color, int], CardId] = {
    (Color.BLUE, 0): CardId.BOUNCE,
    (Color.RED, 0): CardId.HOLY_DEFENDER,
    (Color.GREEN, 0): CardId.QUITTER,
    (Color.YELLOW, 0): CardId.DUMP,
    (Color.GREEN, 3): CardId.SHARE,
    (Color.RED, 5): CardId.MAGIC_5,
    (Color.BLUE, 2): CardId.PENN_STATE,
    (Color.YELLOW, 1): CardId.MUTUAL_DESTRUCT,
    (Color.RED, 2): CardId.GLASNOST,
    (Color.YELLOW, 9): CardId.SIXTY_NINE,
    (Color.GREEN, 4): CardId.LUCK,
}

# Singleton wild-type cards added on top of the standard wild slots.
_WILD_SINGLETONS: tuple[CardId, ...] = (
    CardId.HOT_DEATH,
    CardId.DELAYED_BLAST,
    CardId.HARVESTER,
    CardId.MYSTERY_DRAW,
    CardId.SPREADER,
)


def build_deck() -> tuple[Card, ...]:
    """Construct the fixed v1 deck. Pure and deterministic (order is canonical;
    shuffling happens later via the seeded RNG)."""
    cards: list[Card] = []

    for color in _COLORS:
        # One 0 per color (always a special overlay in this deck).
        cards.append(Card(_NUMBER_OVERLAYS[(color, 0)], color, 0))
        # Two each of 1..9; overlay one instance where a special claims the slot.
        for n in range(1, 10):
            overlay = _NUMBER_OVERLAYS.get((color, n))
            if overlay is not None:
                cards.append(Card(overlay, color, n))
                cards.append(Card(CardId.NUMBER, color, n))
            else:
                cards.append(Card(CardId.NUMBER, color, n))
                cards.append(Card(CardId.NUMBER, color, n))

    for color in _COLORS:
        skips = [CardId.DOUBLE_SKIP, CardId.SKIP] if color is Color.RED else [CardId.SKIP, CardId.SKIP]
        revs = [CardId.REVERSE_SKIP, CardId.REVERSE] if color is Color.RED else [CardId.REVERSE, CardId.REVERSE]
        for cid in skips:
            cards.append(Card(cid, color))
        for cid in revs:
            cards.append(Card(cid, color))
        cards.append(Card(CardId.DRAW_TWO, color))
        cards.append(Card(CardId.DRAW_TWO, color))

    for _ in range(4):
        cards.append(Card(CardId.WILD, Color.WILD))
    for _ in range(4):
        cards.append(Card(CardId.DRAW_FOUR, Color.WILD))
    for cid in _WILD_SINGLETONS:
        cards.append(Card(cid, Color.WILD))

    return tuple(cards)


DECK_SIZE: int = len(build_deck())
