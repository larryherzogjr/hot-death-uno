"""Card catalog: human-facing help for the rules page and in-game tooltips.

Curated from the authoritative ruleset (phoneboy.com/hdu) and HANDOFF §6,
including this build's documented house-rule calls. This is flavor/help text, so
it lives in the server layer, not the pure ``hdu/`` engine; the *live* held value
of a card in a hand comes from the engine via the snapshot, so tooltips show the
real number, not a guess.
"""

from __future__ import annotations

from hdu.cards import DISPLAY_NAMES, CardId

# (CardId, category, held-value description, effect, defense/when-playable)
_CARDS: list[tuple[CardId, str, str, str, str | None]] = [
    (CardId.NUMBER, "Number", "Face value (0–9)",
     "A plain number card. Play it on a matching color or number.", None),
    (CardId.SKIP, "Action", "20", "Skips the next player.", None),
    (CardId.DOUBLE_SKIP, "Action", "40",
     "Skips the next two players (just one in a 2-player game).", None),
    (CardId.REVERSE, "Action", "20", "Reverses the direction of play.", None),
    (CardId.REVERSE_SKIP, "Action", "40",
     "Reverses direction, then skips the next player in the new direction.", None),
    (CardId.DRAW_TWO, "Action", "20",
     "The next player draws 2 and is skipped. Doesn't stack with Draw Fours.", None),
    (CardId.WILD, "Action", "40", "Play on anything; choose the next color.", None),
    (CardId.DRAW_FOUR, "Stack attack", "50",
     "+4 to the draw stack, and you choose the color.",
     "Stack another draw card, or play Fuck You, Holy Defender, or AIDS."),
    (CardId.HOT_DEATH, "Stack attack", "100",
     "A Draw 8 wild that stacks like a Draw Four.", "Only a Magic 5 can nullify it."),
    (CardId.DELAYED_BLAST, "Stack attack", "100",
     "Draw 4 that also skips an extra player when it resolves (a plain Draw Four in 2-player).",
     "Defended like any draw card; a bounced Fuck You can return it to you."),
    (CardId.HARVESTER, "Stack attack", "0",
     "Adds 4 and is undefendable — the next player eats the whole stack no matter what.",
     "No defense exists."),
    (CardId.BOUNCE, "Defense", "Doubles your hand (1000 with a Quitter)",
     "Fuck You: send a punishment back to the last attacker and reverse direction.",
     "Also playable as a blue 0."),
    (CardId.HOLY_DEFENDER, "Defense", "Halves your hand",
     "Pass most punishments to the next player.", "Also playable as a red 0."),
    (CardId.SHARE, "Defense", "3, then −10 every lost hand",
     "AIDS: split a defendable punishment evenly with the attacker.",
     "Also playable as a green 3."),
    (CardId.MAGIC_5, "Defense", "−5",
     "Play on any card. Nullifies a Hot Death and everything stacked beneath it.", None),
    (CardId.PENN_STATE, "Defense", "Your highest other card",
     "Reveal it to dodge a Spreader.", "Also playable as a blue 2."),
    (CardId.QUITTER, "Eliminator", "100",
     "Eliminates the next player (their hand freezes) unless they answer.",
     "Fuck You sends it back to you; AIDS kills both; Holy Defender passes it on. "
     "In 2-player you win unless they play AIDS."),
    (CardId.MUTUAL_DESTRUCT, "Eliminator", "75",
     "M.A.D.: you're eliminated and you drag a chosen player down with you "
     "(both players, in 2-player).", None),
    (CardId.GLASNOST, "Scoring special", "75",
     "Pick a player to reveal their hand to everyone.",
     "AIDS makes both reveal; Fuck You turns it on you and reverses; Holy Defender passes it on."),
    (CardId.DUMP, "Scoring special", "0 (or bumped to the top score)",
     "Shitter: only plays on a Holy Defender, a Magic 5, or as your last card. Scores 0 — "
     "unless you're not the top scorer, then you're bumped up to match them.", None),
    (CardId.SIXTY_NINE, "Scoring special", "69 if held",
     "Plays on a 6 or a 9. If caught holding it, your hand scores 69 regardless.", None),
    (CardId.MYSTERY_DRAW, "Scoring special", "10× your highest number card",
     "The next player draws the number shown on the card beneath it (0 or none = a plain wild).", None),
    (CardId.LUCK, "Scoring special", "75",
     "Luck o' the Irish: shaves 1 off any punishment draw (never the draw for being unable to "
     "play). Revealed automatically when it helps.", None),
    (CardId.SPREADER, "Scoring special", "20 × number of opponents",
     "Every opponent draws 2 unless they reveal a Penn State, then you play again. If a Penn "
     "State is shown, you draw 2 and that player takes the turn.", None),
]


def _name(cid: CardId) -> str:
    return "Number" if cid is CardId.NUMBER else DISPLAY_NAMES[cid]


CATALOG: list[dict] = [
    {"id": cid.name, "name": _name(cid), "category": cat, "value": val, "effect": eff, "defense": dfn}
    for (cid, cat, val, eff, dfn) in _CARDS
]

RULES_SECTIONS: list[dict] = [
    {"title": "Goal",
     "body": "Golf scoring — lowest total wins. A hand ends when someone empties their hand "
             "(they score 0); everyone else adds up the cards left in their hand. The game ends "
             "when a player reaches 1000; the lowest total wins."},
    {"title": "Your turn",
     "body": "Play a card that matches the top by color, number, or symbol — or a wild — "
             "otherwise draw one. The highlighted cards are the ones you can play right now."},
    {"title": "The draw stack",
     "body": "Draw Four, Hot Death, Delayed Blast, and Harvester pile up instead of resolving "
             "right away. The target can stack another, decline (and eat the whole pile), or "
             "defend with Fuck You (bounce + reverse), Holy Defender (pass it on), AIDS (split "
             "it), or — against Hot Death only — Magic 5 (nullify). Harvester can't be defended."},
    {"title": "Eliminations",
     "body": "Quitter and M.A.D. freeze players out of the hand. A hand can even end with "
             "everyone eliminated and no winner."},
    {"title": "Terminal conditions",
     "body": "Holding all four 'bastard' zeros — Quitter, Shitter, Fucker, Holy Defender — ends "
             "the hand and you score 0. Being caught with Quitter + Fucker together is worth 1000."},
    {"title": "Two players",
     "body": "Reverses and skips just skip the opponent (you go again); Delayed Blast is a plain "
             "Draw Four; M.A.D. eliminates both; a Quitter wins for you unless they play AIDS."},
]


def catalog_payload() -> dict:
    return {"cards": CATALOG, "sections": RULES_SECTIONS}
