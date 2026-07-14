"""Text harness. A *consumer* of the engine — printing lives here, never in the
engine.

    python -m hdu.cli                 # play a full hand, 4 AI players, narrated
    python -m hdu.cli --deal-only     # M0-style: just print the dealt state
    python -m hdu.cli --seed N --players N --hand-size N
"""

from __future__ import annotations

import argparse

from .cards import Color, display_name
from .engine import DEFAULT_HAND_SIZE, card_count, new_hand
from .events import (
    CardPlayed,
    ColorChosen,
    DeckReshuffled,
    DirectionReversed,
    Event,
    GameOver,
    HandScored,
    PlayerDrew,
    PlayerSkipped,
    PlayerWonHand,
    TurnPassed,
    UnoCalled,
)
from .play import play_game, play_hand
from .players.random_ai import RandomAI
from .state import GameState


def _color_label(color: Color) -> str:
    return color.name.title() if color is not Color.WILD else "(no color yet)"


def _render_deal(state: GameState) -> str:
    lines: list[str] = []
    top = state.top
    lines.append(
        f"Top of discard: {display_name(top.card)}  [effective color: {_color_label(top.eff_color)}]"
    )
    lines.append(
        f"Draw pile: {len(state.draw_pile)} cards   Dealer: P{state.dealer}   To act: P{state.to_act}"
    )
    lines.append("")
    for p in state.players:
        tag = " (dealer)" if p.id == state.dealer else ""
        lines.append(f"Player {p.id}{tag} — {len(p.hand)} cards:")
        for card in p.hand:
            lines.append(f"    {display_name(card)}")
        lines.append("")
    lines.append(f"Card conservation: {card_count(state)} cards total.")
    return "\n".join(lines)


def _describe(state: GameState, events: tuple[Event, ...]) -> None:
    for e in events:
        if isinstance(e, CardPlayed):
            print(f"  P{e.player} plays {display_name(e.card)}")
        elif isinstance(e, ColorChosen):
            print(f"  P{e.player} chooses {e.color.name.title()}")
        elif isinstance(e, PlayerDrew):
            print(f"  P{e.player} draws {e.count}")
        elif isinstance(e, PlayerSkipped):
            print(f"  P{e.player} is skipped")
        elif isinstance(e, DirectionReversed):
            arrow = "clockwise" if e.direction == 1 else "counter-clockwise"
            print(f"  direction reversed -> {arrow}")
        elif isinstance(e, DeckReshuffled):
            print(f"   * discard reshuffled into draw pile ({e.new_draw_count} cards)")
        elif isinstance(e, UnoCalled):
            print(f"  P{e.player} — UNO!")
        elif isinstance(e, TurnPassed):
            print(f"  P{e.player} passes")
        elif isinstance(e, PlayerWonHand):
            print(f"  *** P{e.player} goes out and wins the hand! ***")
        elif isinstance(e, HandScored):
            gained = ", ".join(f"P{pid} +{pts}" for pid, pts in e.gains)
            print(f"  hand scored: {gained}")
        elif isinstance(e, GameOver):
            standings = ", ".join(f"P{pid}={pts}" for pid, pts in e.scores)
            print(f"  === GAME OVER — P{e.winner} wins (lowest). Totals: {standings} ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hot Death Uno (M1 vanilla loop)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--players", type=int, default=4)
    parser.add_argument("--hand-size", type=int, default=DEFAULT_HAND_SIZE)
    parser.add_argument("--deal-only", action="store_true", help="just print the deal")
    parser.add_argument("--game", action="store_true", help="play a full game to 1000")
    args = parser.parse_args()

    # Each seat gets its own seeded AI so the whole game replays deterministically.
    players = [RandomAI(seed=1000 + i) for i in range(args.players)]

    if args.deal_only:
        state = new_hand(seed=args.seed, num_players=args.players, hand_size=args.hand_size)
        print(_render_deal(state))
        return

    if args.game:
        print(f"Full game to {1000} points — low wins.  ({args.players} AIs, seed {args.seed})\n")
        final = play_game(
            args.seed, players, num_players=args.players, hand_size=args.hand_size,
            observer=_describe_game,
        )
        print()
        print("Final standings (low wins):")
        for p in sorted(final.players, key=lambda p: p.score):
            crown = "  <- winner" if p.id == final.winner else ""
            print(f"  P{p.id}: {p.score}{crown}")
        return

    state = new_hand(seed=args.seed, num_players=args.players, hand_size=args.hand_size)
    print(
        f"Starter: {display_name(state.top.card)}  "
        f"[{_color_label(state.top.eff_color)}]   ({args.players} AI players, seed {args.seed})\n"
    )
    final = play_hand(state, players, observer=_describe)
    print()
    print(f"Hand over. Winner: P{final.winner}.")
    print(f"Card conservation: {card_count(final)} cards total.")
    for p in final.players:
        print(f"  P{p.id}: {len(p.hand)} cards left")


# Only narrate hand-level milestones in a full game (per-card would be huge).
def _describe_game(state: GameState, events: tuple[Event, ...]) -> None:
    for e in events:
        if isinstance(e, PlayerWonHand):
            print(f"P{e.player} wins the hand.")
        elif isinstance(e, HandScored):
            gained = ", ".join(f"P{pid}+{pts}" for pid, pts in e.gains)
            print(f"  scored: {gained}")
        elif isinstance(e, GameOver):
            standings = ", ".join(f"P{pid}={pts}" for pid, pts in e.scores)
            print(f"\n=== GAME OVER — P{e.winner} wins (lowest). Totals: {standings} ===")


if __name__ == "__main__":
    main()
