"""The engine: the only place rules live.

The full contract is ``apply(state, action) -> (new_state, events)`` and
``legal_actions(state)``. Those arrive in M1 (the vanilla turn loop). M0 ships
the deterministic deal and the card-conservation helper that the whole test
suite leans on.
"""

from __future__ import annotations

from dataclasses import replace

from .actions import (
    Action,
    ChooseColor,
    ChooseVictim,
    Decline,
    DrawCard,
    Pass,
    PlayCard,
    Reveal,
)
from .cards import DECK_SIZE, Card, CardId, Color, build_deck
from .effects import EffectKind, effect_kind, matches
from .events import (
    BastardHand,
    CardPlayed,
    ColorChosen,
    DeckReshuffled,
    DirectionReversed,
    Event,
    GameOver,
    GlasnostStarted,
    HandRevealed,
    HandScored,
    LuckRevealed,
    PennStateRevealed,
    PlayerDrew,
    PlayerEliminated,
    PlayerSkipped,
    PlayerWonHand,
    QuitterStarted,
    SpreaderStarted,
    TurnPassed,
    UnoCalled,
)
from .rng import RngState, new_rng, rng_from_state, state_of
from .scoring import new_aids_counts, score_hand
from .state import DiscardEntry, GameState, Pending, Phase, PlayerState

DEFAULT_HAND_SIZE = 7

# The four choosable colors, in canonical order.
COLORS: tuple[Color, ...] = (Color.RED, Color.YELLOW, Color.GREEN, Color.BLUE)


def card_count(state: GameState) -> int:
    """Total cards visible across hands, draw pile, and discard. Must always
    equal :data:`DECK_SIZE` — cards are never created or destroyed."""
    return (
        sum(len(p.hand) for p in state.players)
        + len(state.draw_pile)
        + len(state.discard)
    )


WIN_THRESHOLD = 1000  # game ends when any running total reaches this (low wins)


def new_hand(
    seed: int,
    num_players: int = 4,
    hand_size: int = DEFAULT_HAND_SIZE,
    dealer: int = 0,
) -> GameState:
    """Start a fresh *game*: a brand-new seeded RNG and zeroed running scores.
    Subsequent hands are dealt by :func:`settle_hand`, which carries scores and
    continues the same RNG stream."""
    if num_players < 2:
        raise ValueError("need at least 2 players")
    if hand_size * num_players + 1 > DECK_SIZE:
        raise ValueError("hand_size too large for the deck")

    rng = new_rng(seed)
    return _deal_hand(
        rng,
        num_players=num_players,
        hand_size=hand_size,
        dealer=dealer,
        scores=[0] * num_players,
        aids=[0] * num_players,
    )


def _deal_hand(
    rng,
    *,
    num_players: int,
    hand_size: int,
    dealer: int,
    scores: list[int],
    aids: list[int],
) -> GameState:
    """Shuffle a fresh deck with ``rng``, deal, and flip the starter. Pure given
    the RNG state; carries running ``scores`` / ``aids`` into the new hand.

    The implemented v1 deal behavior handles a Draw Two against the dealer and
    opens color choice for wild starters. Remaining directed/draw starter rules
    are tracked explicitly in RULES_DECISIONS.md.
    """
    deck = list(build_deck())
    rng.shuffle(deck)

    hands: list[list[Card]] = [[] for _ in range(num_players)]
    idx = 0
    first = (dealer + 1) % num_players  # deal starts to the dealer's left
    for _ in range(hand_size):
        for offset in range(num_players):
            hands[(first + offset) % num_players].append(deck[idx])
            idx += 1

    starter = deck[idx]
    idx += 1
    discard = (DiscardEntry(starter, starter.color, starter.number),)
    draw_pile = tuple(deck[idx:])

    players = tuple(
        PlayerState(id=i, hand=tuple(hands[i]), score=scores[i], aids_count=aids[i])
        for i in range(num_players)
    )
    phase = Phase.CHOOSE_COLOR if starter.is_wild else Phase.PLAY

    state = GameState(
        players=players,
        draw_pile=draw_pile,
        discard=discard,
        to_act=first,
        direction=1,
        dealer=dealer,
        rng_state=state_of(rng),
        phase=phase,
        pending=None,
        hand_size=hand_size,
    )

    # Deal special condition (§8): a Draw Two starter affects the dealer, who
    # draws 2; play then proceeds clockwise from the dealer's left as usual.
    # (Wild draw-four starters open the color choice; directed-card starters seat
    # without firing — both deferred simplifications. AIDS-on-deal naturally
    # penalises nobody since a Share starter has no effect.)
    if effect_kind(starter) is EffectKind.DRAW_TWO:
        state = _draw(state, dealer, 2).state

    assert card_count(state) == DECK_SIZE  # conservation holds from birth
    return state


def settle_hand(state: GameState) -> tuple[GameState, tuple[Event, ...]]:
    """Tally a finished hand, fold the points into running scores, and either
    deal the next hand (carrying scores, rotating the dealer, continuing the RNG)
    or end the game when someone reaches :data:`WIN_THRESHOLD` — lowest total
    wins. ``legal_actions`` returns ``[]`` at HAND_OVER to signal "call this".
    """
    if state.phase is not Phase.HAND_OVER:
        raise ValueError(f"settle_hand requires HAND_OVER, got {state.phase!r}")

    n = len(state.players)
    gains = score_hand(state)
    new_scores = [state.players[i].score + gains[i] for i in range(n)]
    events: list[Event] = [
        HandScored(state.winner, tuple((i, gains[i]) for i in range(n)))
    ]

    if max(new_scores) >= WIN_THRESHOLD:
        winner = min(range(n), key=lambda i: (new_scores[i], i))  # ties -> low id
        players = tuple(
            replace(p, score=new_scores[i]) for i, p in enumerate(state.players)
        )
        over = replace(state, players=players, phase=Phase.GAME_OVER, winner=winner)
        events.append(GameOver(winner, tuple((i, new_scores[i]) for i in range(n))))
        return over, tuple(events)

    rng = rng_from_state(state.rng_state)
    aids = new_aids_counts(state)
    # Normally the deal rotates +1; but an all-eliminated hand (no winner) is
    # dealt by the lowest hand-total, ties to low id as a stand-in for a deck cut
    # (HANDOFF §8).
    if state.winner is None:
        next_dealer = min(range(n), key=lambda i: (gains[i], i))
    else:
        next_dealer = (state.dealer + 1) % n
    nxt = _deal_hand(
        rng,
        num_players=n,
        hand_size=state.hand_size,
        dealer=next_dealer,
        scores=new_scores,
        aids=[aids[i] for i in range(n)],
    )
    return nxt, tuple(events)


# --------------------------------------------------------------------------- #
# legal_actions — the single source of truth for what may happen next.
# --------------------------------------------------------------------------- #

def _can_draw(state: GameState) -> bool:
    return len(state.draw_pile) > 0 or len(state.discard) > 1


def legal_actions(state: GameState) -> list[Action]:
    if state.phase in (Phase.HAND_OVER, Phase.GAME_OVER):
        return []
    if state.phase is Phase.CHOOSE_COLOR:
        return [ChooseColor(c) for c in COLORS]
    if state.phase is Phase.CHOOSE_VICTIM:
        return [
            ChooseVictim(p.id)
            for p in state.players
            if not p.eliminated and p.id != state.to_act
        ]
    if state.phase is Phase.RESPOND:
        return _respond_actions(state)
    if state.phase is Phase.PLAY:
        player = state.players[state.to_act]
        only = len(player.hand) == 1
        actions: list[Action] = [
            PlayCard(i)
            for i, card in enumerate(player.hand)
            if matches(card, state.top, is_only_card=only)
        ]
        if _can_draw(state):
            actions.append(DrawCard())
        if not actions:  # can neither play nor draw — pass (rare corner)
            actions.append(Pass())
        return actions
    raise AssertionError(f"unhandled phase {state.phase!r}")


def _respond_actions(state: GameState) -> list[Action]:
    pending = state.pending
    assert pending is not None
    if pending.kind == "spreader":
        # The victim may reveal a Penn State (exempt) or take the draw.
        hand = state.players[pending.target].hand
        actions: list[Action] = [Decline()]
        actions += [Reveal(i) for i, c in enumerate(hand) if c.id is CardId.PENN_STATE]
        return actions
    if pending.kind == "quitter" and _two_player(state):
        # §7: only AIDS answers (both die); otherwise the Quitter player wins.
        hand = state.players[pending.target].hand
        quitter_actions: list[Action] = [Decline()]
        quitter_actions += [
            PlayCard(i) for i, c in enumerate(hand) if c.id is CardId.SHARE
        ]
        return quitter_actions
    if pending.kind in ("quitter", "glasnost"):
        # The threatened player may decline (take it) or play a defense.
        hand = state.players[pending.target].hand
        actions = [Decline()]
        actions += [PlayCard(i) for i, c in enumerate(hand) if c.id in _BASIC_DEFENSES]
        return actions
    if pending.kind == "draw_stack":
        # Decline (eat the stack), stack another Draw-Four-type, or defend.
        hand = state.players[pending.target].hand
        on_hot_death = bool(pending.chain) and pending.chain[-1] is CardId.HOT_DEATH
        actions = [Decline()]
        for i, c in enumerate(hand):
            if c.id in _DRAW_FOUR_TYPES or c.id in _BASIC_DEFENSES:
                actions.append(PlayCard(i))
            elif c.id is CardId.MAGIC_5 and on_hot_death:
                actions.append(PlayCard(i))  # Magic 5 only nullifies Hot Death
        return actions
    raise AssertionError(f"unhandled pending kind {pending.kind!r}")


# Cards that defend against a Quitter or Glasnost (HANDOFF §6): Fuck You, AIDS,
# Holy Defender.
_BASIC_DEFENSES = frozenset({CardId.BOUNCE, CardId.SHARE, CardId.HOLY_DEFENDER})

# Draw-Four-type attacks and the cards each adds to the draw stack (HANDOFF §4).
_DRAW_FOUR_TYPES: dict[CardId, int] = {
    CardId.DRAW_FOUR: 4,
    CardId.HOT_DEATH: 8,
    CardId.DELAYED_BLAST: 4,
    CardId.HARVESTER: 4,
}


# --------------------------------------------------------------------------- #
# apply — the only place rules mutate state. Returns (new_state, events).
# --------------------------------------------------------------------------- #

# The four "bastard cards" (the four 0s). Holding all four ends the hand (§8).
_BASTARD_CARDS = frozenset(
    {CardId.QUITTER, CardId.DUMP, CardId.BOUNCE, CardId.HOLY_DEFENDER}
)


def _bastard_holder(state: GameState) -> int | None:
    for p in state.players:
        if _BASTARD_CARDS <= {c.id for c in p.hand}:
            return p.id
    return None


def apply(state: GameState, action: Action) -> tuple[GameState, tuple[Event, ...]]:
    # Keep this public boundary authoritative for every consumer, not only the
    # network session wrapper. In particular, Python accepts negative sequence
    # indexes; dispatching an unchecked PlayCard(-1) would make the slicing in
    # _apply_play_card duplicate cards instead of removing one.
    if action not in legal_actions(state):
        raise ValueError(f"{action!r} is not legal in the current state")
    new_state, events = _apply_dispatch(state, action)
    # Terminal check during play: holding all four bastard cards ends the hand
    # immediately; that holder scores 0 (HANDOFF §8).
    if new_state.phase not in (Phase.HAND_OVER, Phase.GAME_OVER):
        holder = _bastard_holder(new_state)
        if holder is not None:
            new_state = replace(
                new_state, phase=Phase.HAND_OVER, winner=holder, pending=None
            )
            events = events + (BastardHand(holder),)
    return new_state, events


def _apply_dispatch(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    if state.phase is Phase.CHOOSE_COLOR:
        if isinstance(action, ChooseColor):
            return _apply_choose_color(state, action)
        raise ValueError(f"expected ChooseColor in choose_color phase, got {action!r}")

    if state.phase is Phase.CHOOSE_VICTIM:
        if isinstance(action, ChooseVictim):
            return _apply_choose_victim(state, action)
        raise ValueError(f"expected ChooseVictim, got {action!r}")

    if state.phase is Phase.RESPOND:
        return _apply_response(state, action)

    if state.phase is Phase.PLAY:
        if isinstance(action, PlayCard):
            return _apply_play_card(state, action)
        if isinstance(action, DrawCard):
            return _apply_draw(state)
        if isinstance(action, Pass):
            nxt = _advance(state, state.to_act, 1, state.direction)
            return replace(state, to_act=nxt), (TurnPassed(state.to_act),)
        raise ValueError(f"illegal action {action!r} in play phase")

    raise ValueError(f"no actions are legal in phase {state.phase!r}")


def _apply_play_card(
    state: GameState, action: PlayCard
) -> tuple[GameState, tuple[Event, ...]]:
    pid = state.to_act
    player = state.players[pid]
    card = player.hand[action.hand_index]
    if not matches(card, state.top, is_only_card=len(player.hand) == 1):
        raise ValueError(f"{card!r} does not match top {state.top!r}")

    new_hand = player.hand[: action.hand_index] + player.hand[action.hand_index + 1 :]
    events: list[Event] = [CardPlayed(pid, card)]

    if card.is_wild:
        entry = DiscardEntry(card=card, eff_color=Color.WILD, eff_number=None)
    else:
        entry = DiscardEntry(card=card, eff_color=card.color, eff_number=card.number)
    discard = state.discard + (entry,)

    # M.A.D. eliminates the player (and a chosen victim) rather than racing to go
    # out — so it resolves before the win/uno bookkeeping.
    if effect_kind(card) is EffectKind.MUTUAL_DESTRUCT:
        return _begin_mad(state, pid, new_hand, discard, events)

    # Win check: emptying your hand ends the hand. A last-card *draw* effect
    # still lands on the next player (it changes their score); skip/reverse/wild/
    # directed effects are moot once the hand is over and are not applied.
    if not new_hand:
        players = _set_player(state.players, pid, hand=new_hand, called_uno=False)
        won = replace(
            state, players=players, discard=discard, phase=Phase.HAND_OVER, winner=pid
        )
        last_kind = effect_kind(card)
        amount = 2 if last_kind is EffectKind.DRAW_TWO else _DRAW_FOUR_TYPES.get(card.id, 0)
        if amount:
            target = _advance(won, pid, 1, won.direction)
            k, luck = _luck_reduce(won, target, amount)
            events.extend(luck)
            drawn = _draw(won, target, k)
            events.extend(drawn.events)
            events.append(PlayerDrew(target, drawn.count))
            won = drawn.state
        events.append(PlayerWonHand(pid))
        return won, tuple(events)

    called = len(new_hand) == 1
    if called:
        events.append(UnoCalled(pid))
    players = _set_player(state.players, pid, hand=new_hand, called_uno=called)
    base = replace(state, players=players, discard=discard)

    if card.is_wild:
        # Plain-wild behaviour in M1: choose color, then advance one.
        return replace(base, phase=Phase.CHOOSE_COLOR), tuple(events)

    kind = effect_kind(card)
    if kind is EffectKind.NONE:
        nxt = _advance(base, pid, 1, base.direction)
        return replace(base, to_act=nxt), tuple(events)

    # 2-player (§7): every reverse/skip variant collapses to "skip the opponent,
    # you play again."
    if _two_player(base) and kind in (
        EffectKind.SKIP,
        EffectKind.DOUBLE_SKIP,
        EffectKind.REVERSE,
        EffectKind.REVERSE_SKIP,
    ):
        events.append(PlayerSkipped(_advance(base, pid, 1, base.direction)))
        return replace(base, to_act=pid), tuple(events)

    if kind is EffectKind.SKIP:
        nxt = _advance(base, pid, 2, base.direction)
        skipped = _advance(base, pid, 1, base.direction)
        events.append(PlayerSkipped(skipped))
        return replace(base, to_act=nxt), tuple(events)

    if kind is EffectKind.DOUBLE_SKIP:
        # Skip the next two players. §7 reduces this to a single skip; that case
        # was handled above.
        for step in (1, 2):
            events.append(PlayerSkipped(_advance(base, pid, step, base.direction)))
        nxt = _advance(base, pid, 3, base.direction)
        return replace(base, to_act=nxt), tuple(events)

    if kind is EffectKind.REVERSE:
        new_dir = -base.direction
        nxt = _advance(base, pid, 1, new_dir)
        events.append(DirectionReversed(new_dir))
        return replace(base, direction=new_dir, to_act=nxt), tuple(events)

    if kind is EffectKind.REVERSE_SKIP:
        # Reverse direction, then skip one player in the new direction.
        new_dir = -base.direction
        events.append(DirectionReversed(new_dir))
        events.append(PlayerSkipped(_advance(base, pid, 1, new_dir)))
        nxt = _advance(base, pid, 2, new_dir)
        return replace(base, direction=new_dir, to_act=nxt), tuple(events)

    if kind is EffectKind.DRAW_TWO:
        target = _advance(base, pid, 1, base.direction)
        k, luck = _luck_reduce(base, target, 2)
        events.extend(luck)
        drawn = _draw(base, target, k)
        events.extend(drawn.events)
        events.append(PlayerDrew(target, drawn.count))
        events.append(PlayerSkipped(target))
        nxt = _advance(drawn.state, pid, 2, base.direction)
        return replace(drawn.state, to_act=nxt), tuple(events)

    if kind is EffectKind.QUITTER:
        return _begin_quitter(base, origin=pid, events=events)

    if kind is EffectKind.GLASNOST:
        return _begin_glasnost_choose(base, origin=pid, events=events)

    raise AssertionError(f"unhandled effect kind {kind!r}")


def _apply_choose_color(
    state: GameState, action: ChooseColor
) -> tuple[GameState, tuple[Event, ...]]:
    if action.color is Color.WILD:
        raise ValueError("must choose a real color")
    top = state.top
    new_top = replace(top, eff_color=action.color)
    discard = state.discard[:-1] + (new_top,)
    base = replace(state, discard=discard)
    events: list[Event] = [ColorChosen(state.to_act, action.color)]

    # A discard of length 1 means this is the opening starter-wild choice: the
    # same player then plays. Opening Spreader currently starts as a plain wild;
    # full starter behavior is tracked in RULES_DECISIONS.md.
    if len(discard) == 1:
        return replace(base, phase=Phase.PLAY), tuple(events)

    # Spreader resolves its table-wide draw after the color is chosen.
    if top.card.id is CardId.SPREADER:
        spread_state, spread_events = _begin_spreader(base, origin=state.to_act)
        return spread_state, tuple(events) + spread_events

    # Mystery Draw: the next player draws the number on the card it was played on
    # (the entry beneath it). 0 or absent → it was just a plain wild.
    if top.card.id is CardId.MYSTERY_DRAW:
        underlying = base.discard[-2].eff_number if len(base.discard) >= 2 else None
        if underlying:
            pid = state.to_act
            target = _advance(base, pid, 1, base.direction)
            k, luck = _luck_reduce(base, target, underlying)
            events.extend(luck)
            drawn = _draw(base, target, k)
            events.extend(drawn.events)
            events.append(PlayerDrew(target, drawn.count))
            events.append(PlayerSkipped(target))
            nxt = _advance(drawn.state, pid, 2, base.direction)
            return replace(drawn.state, phase=Phase.PLAY, to_act=nxt), tuple(events)

    # A Draw-Four-type opens (or, when one is already pending, extends) the stack.
    if top.card.id in _DRAW_FOUR_TYPES:
        return _extend_or_open_draw_stack(base, top.card, player=state.to_act, events=events)

    nxt = _advance(base, state.to_act, 1, state.direction)
    return replace(base, phase=Phase.PLAY, to_act=nxt), tuple(events)


def _active_victims(state: GameState, origin: int) -> list[int]:
    """Active players other than ``origin``, in turn order from the next seat."""
    n = len(state.players)
    victims: list[int] = []
    idx = origin
    for _ in range(n - 1):
        idx = (idx + state.direction) % n
        if not state.players[idx].eliminated:
            victims.append(idx)
    return victims


def _begin_spreader(
    state: GameState, origin: int
) -> tuple[GameState, tuple[Event, ...]]:
    """Open a ``spreader`` pending: each other active player draws 2 unless they
    reveal a Penn State. (Inferred-spec house rule — see cards.py / HANDOFF §6.)"""
    victims = _active_victims(state, origin)
    events: tuple[Event, ...] = (SpreaderStarted(origin),)
    if not victims:  # everyone else is eliminated — nothing to spread
        nxt = _advance(state, origin, 1, state.direction)
        return replace(state, phase=Phase.PLAY, to_act=nxt), events
    pending = Pending(
        kind="spreader",
        target=victims[0],
        origin=origin,
        draw_total=2,
        queue=tuple(victims[1:]),
    )
    return replace(state, phase=Phase.RESPOND, pending=pending, to_act=victims[0]), events


def _apply_response(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    pending = state.pending
    assert pending is not None
    if pending.kind == "spreader":
        return _apply_spreader_response(state, action)
    if pending.kind == "quitter":
        return _apply_quitter_response(state, action)
    if pending.kind == "glasnost":
        return _apply_glasnost_response(state, action)
    if pending.kind == "draw_stack":
        return _apply_draw_stack_response(state, action)
    raise ValueError(f"no response handler for pending kind {pending.kind!r}")


def _apply_spreader_response(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    pending = state.pending
    assert pending is not None
    target = pending.target
    events: list[Event] = []
    revealer = pending.penn_revealer  # carried across victims; first one sticks

    if isinstance(action, Reveal):
        card = state.players[target].hand[action.hand_index]
        if card.id is not CardId.PENN_STATE:
            raise ValueError("only a Penn State protects against Spreader")
        events.append(PennStateRevealed(target))
        if revealer is None:
            revealer = target
        resolved = state  # exempt; Penn State stays in hand, no draw
    elif isinstance(action, Decline):
        k, luck = _luck_reduce(state, target, pending.draw_total)
        events.extend(luck)
        drawn = _draw(state, target, k)
        events.extend(drawn.events)
        events.append(PlayerDrew(target, drawn.count))
        resolved = drawn.state
    else:
        raise ValueError(f"illegal spreader response {action!r}")

    # Move to the next victim...
    if pending.queue:
        nxt_pending = replace(
            pending, target=pending.queue[0], queue=pending.queue[1:], penn_revealer=revealer
        )
        return replace(resolved, pending=nxt_pending, to_act=pending.queue[0]), tuple(events)

    # ...or finish. Per phoneboy.com/hdu: with no Penn State shown, the Spreader
    # player acts again; if it was shown, the Spreader player draws 2 and the
    # (first) Penn State holder takes the turn.
    origin = pending.origin
    if revealer is not None:
        k, luck = _luck_reduce(resolved, origin, pending.draw_total)
        events.extend(luck)
        drawn = _draw(resolved, origin, k)
        events.extend(drawn.events)
        events.append(PlayerDrew(origin, drawn.count))
        return replace(drawn.state, pending=None, phase=Phase.PLAY, to_act=revealer), tuple(events)
    return replace(resolved, pending=None, phase=Phase.PLAY, to_act=origin), tuple(events)


def _begin_mad(
    state: GameState,
    pid: int,
    new_hand: tuple[Card, ...],
    discard: tuple[DiscardEntry, ...],
    events: list[Event],
) -> tuple[GameState, tuple[Event, ...]]:
    """M.A.D.: the player is eliminated (hand frozen) and then chooses a victim
    to be eliminated alongside them."""
    players = _set_player(
        state.players, pid, hand=new_hand, eliminated=True, called_uno=False
    )
    base = replace(state, players=players, discard=discard)
    events.append(PlayerEliminated(pid))

    victims = [p.id for p in players if not p.eliminated]
    if not victims:  # no one left to take down
        return _after_elimination(base, origin=pid, events=events)
    if _two_player(state):  # §7: both players die, no choice
        other = victims[0]
        base = replace(base, players=_set_player(base.players, other, eliminated=True))
        events.append(PlayerEliminated(other))
        return _after_elimination(base, origin=pid, events=events)
    return replace(base, phase=Phase.CHOOSE_VICTIM, to_act=pid), tuple(events)


def _apply_choose_victim(
    state: GameState, action: ChooseVictim
) -> tuple[GameState, tuple[Event, ...]]:
    victim = action.player
    if state.players[victim].eliminated:
        raise ValueError(f"P{victim} is already eliminated")

    # Glasnost uses choose-victim to pick whose hand is exposed (origin survives).
    if state.pending is not None and state.pending.kind == "glasnost_choose":
        return _begin_glasnost(state, origin=state.pending.origin, victim=victim)

    # Otherwise it's M.A.D.: the chooser (already eliminated) takes the victim down.
    players = _set_player(state.players, victim, eliminated=True)
    base = replace(state, players=players)
    return _after_elimination(base, origin=state.to_act, events=[PlayerEliminated(victim)])


def _after_elimination(
    state: GameState, origin: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    """Resolve play flow after one or more eliminations. A hand ends only when
    *all* active players are eliminated (no winner — HANDOFF §5/§8); otherwise
    play continues from the seat after ``origin``. The lone-survivor case is not
    special-cased: that player simply keeps playing until they go out."""
    active = [p for p in state.players if not p.eliminated]
    if not active:
        # All eliminated: no hand-winner; settle_hand scores every frozen hand.
        return replace(state, phase=Phase.HAND_OVER, winner=None, pending=None), tuple(events)
    nxt = _advance(state, origin, 1, state.direction)
    return replace(state, phase=Phase.PLAY, to_act=nxt, pending=None), tuple(events)


def _begin_quitter(
    state: GameState, origin: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    """Open a ``quitter`` pending threatening the next active player."""
    target = _advance(state, origin, 1, state.direction)
    if target == origin:  # no one else active to threaten
        nxt = _advance(state, origin, 1, state.direction)
        return replace(state, phase=Phase.PLAY, to_act=nxt), tuple(events)
    pending = Pending(kind="quitter", target=target, origin=origin)
    events.append(QuitterStarted(origin, target))
    return replace(state, phase=Phase.RESPOND, pending=pending, to_act=target), tuple(events)


def _play_defense(
    state: GameState, defender: int, hand_index: int
) -> tuple[GameState, Card, list[Event]]:
    """Play a defense card from ``defender``'s hand: it goes to the discard and
    sets the effective color to its own (HANDOFF §4). Returns the new state, the
    card, and the emitted events."""
    hand = state.players[defender].hand
    card = hand[hand_index]
    new_hand = hand[:hand_index] + hand[hand_index + 1 :]
    players = _set_player(state.players, defender, hand=new_hand)
    entry = DiscardEntry(card=card, eff_color=card.color, eff_number=card.number)
    new_state = replace(state, players=players, discard=state.discard + (entry,))
    return new_state, card, [CardPlayed(defender, card)]


def _apply_quitter_response(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    pending = state.pending
    assert pending is not None
    target, origin = pending.target, pending.origin

    # 2-player (§7): the Quitter player wins by default unless AIDS is played, in
    # which case both die. Bounce/Holy Defender don't apply.
    if _two_player(state):
        if isinstance(action, Decline):
            won = replace(state, phase=Phase.HAND_OVER, winner=origin, pending=None)
            return won, (PlayerWonHand(origin),)
        if isinstance(action, PlayCard):
            card = state.players[target].hand[action.hand_index]
            if card.id is not CardId.SHARE:
                raise ValueError("only AIDS answers a 2-player Quitter")
            base, _c, events = _play_defense(state, target, action.hand_index)
            players = _set_player(base.players, target, eliminated=True)
            players = _set_player(players, origin, eliminated=True)
            events.append(PlayerEliminated(target))
            events.append(PlayerEliminated(origin))
            return _after_elimination(replace(base, players=players), origin=origin, events=events)
        raise ValueError(f"illegal 2-player quitter response {action!r}")

    if isinstance(action, Decline):
        players = _set_player(state.players, target, eliminated=True)
        base = replace(state, players=players)
        return _after_elimination(
            base, origin=origin, events=[PlayerEliminated(target)]
        )

    if isinstance(action, PlayCard):
        card = state.players[target].hand[action.hand_index]
        if card.id not in _BASIC_DEFENSES:
            raise ValueError(f"{card!r} cannot defend a Quitter")
        base, _card, events = _play_defense(state, target, action.hand_index)

        if card.id is CardId.BOUNCE:
            # Fuck You: the Quitter player is eliminated instead, and (like every
            # defensive Fuck You, per phoneboy.com/hdu) the direction reverses.
            new_dir = -base.direction
            players = _set_player(base.players, origin, eliminated=True)
            events.append(PlayerEliminated(origin))
            events.append(DirectionReversed(new_dir))
            return _after_elimination(
                replace(base, players=players, direction=new_dir), origin=origin, events=events
            )

        if card.id is CardId.SHARE:
            # AIDS: both the target and the Quitter player are eliminated.
            players = _set_player(base.players, target, eliminated=True)
            players = _set_player(players, origin, eliminated=True)
            events.append(PlayerEliminated(target))
            events.append(PlayerEliminated(origin))
            return _after_elimination(replace(base, players=players), origin=origin, events=events)

        if card.id is CardId.HOLY_DEFENDER:
            # The elimination points to the following player, who may respond.
            following = _advance(base, target, 1, base.direction)
            if following == origin or following == target:
                # No further player to pass to — the threat fizzles.
                nxt = _advance(base, origin, 1, base.direction)
                return replace(base, phase=Phase.PLAY, pending=None, to_act=nxt), tuple(events)
            nxt_pending = replace(pending, target=following)
            return replace(base, pending=nxt_pending, to_act=following), tuple(events)

    raise ValueError(f"illegal quitter response {action!r}")


def _begin_glasnost_choose(
    state: GameState, origin: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    """Glasnost: the player chooses whose hand to expose (they survive). Opens a
    choose-victim step marked so it routes to Glasnost, not M.A.D."""
    victims = [p.id for p in state.players if not p.eliminated and p.id != origin]
    if not victims:
        nxt = _advance(state, origin, 1, state.direction)
        return replace(state, phase=Phase.PLAY, to_act=nxt), tuple(events)
    pending = Pending(kind="glasnost_choose", target=origin, origin=origin)
    return replace(state, phase=Phase.CHOOSE_VICTIM, pending=pending, to_act=origin), tuple(events)


def _begin_glasnost(
    state: GameState, origin: int, victim: int
) -> tuple[GameState, tuple[Event, ...]]:
    pending = Pending(kind="glasnost", target=victim, origin=origin)
    return (
        replace(state, phase=Phase.RESPOND, pending=pending, to_act=victim),
        (GlasnostStarted(origin, victim),),
    )


def _reveal(state: GameState, pid: int) -> GameState:
    return replace(state, players=_set_player(state.players, pid, revealed=True))


def _finish_glasnost(
    state: GameState, origin: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    nxt = _advance(state, origin, 1, state.direction)
    return replace(state, phase=Phase.PLAY, pending=None, to_act=nxt), tuple(events)


def _apply_glasnost_response(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    pending = state.pending
    assert pending is not None
    target, origin = pending.target, pending.origin

    if isinstance(action, Decline):
        revealed = _reveal(state, target)
        return _finish_glasnost(revealed, origin, [HandRevealed(target)])

    if isinstance(action, PlayCard):
        card = state.players[target].hand[action.hand_index]
        if card.id not in _BASIC_DEFENSES:
            raise ValueError(f"{card!r} cannot defend a Glasnost")
        base, _card, events = _play_defense(state, target, action.hand_index)

        if card.id is CardId.BOUNCE:
            # Fuck You: the Glasnost player reveals instead, and direction flips.
            revealed = _reveal(base, origin)
            new_dir = -base.direction
            events.append(HandRevealed(origin))
            events.append(DirectionReversed(new_dir))
            return _finish_glasnost(replace(revealed, direction=new_dir), origin, events)

        if card.id is CardId.SHARE:
            # AIDS: both reveal.
            revealed = _reveal(_reveal(base, target), origin)
            events.append(HandRevealed(target))
            events.append(HandRevealed(origin))
            return _finish_glasnost(revealed, origin, events)

        if card.id is CardId.HOLY_DEFENDER:
            following = _advance(base, target, 1, base.direction)
            if following == origin or following == target:
                nxt = _advance(base, origin, 1, base.direction)
                return replace(base, phase=Phase.PLAY, pending=None, to_act=nxt), tuple(events)
            nxt_pending = replace(pending, target=following)
            return replace(base, pending=nxt_pending, to_act=following), tuple(events)

    raise ValueError(f"illegal glasnost response {action!r}")


# --------------------------------------------------------------------------- #
# The draw stack (HANDOFF §4) — the load-bearing mechanic.
# --------------------------------------------------------------------------- #

def _extend_or_open_draw_stack(
    state: GameState, card: Card, player: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    """A Draw-Four-type was played (color already chosen). Open a fresh stack or
    extend the pending one, then either resolve immediately (Harvester makes the
    whole thing undefendable) or open the response window on the next player."""
    amount = _DRAW_FOUR_TYPES[card.id]
    is_harvester = card.id is CardId.HARVESTER
    prev = state.pending
    if prev is not None and prev.kind == "draw_stack":
        draw_total = prev.draw_total + amount
        chain = prev.chain + (card.id,)
        undefendable = prev.undefendable or is_harvester
    else:
        draw_total = amount
        chain = (card.id,)
        undefendable = is_harvester

    target = _advance(state, player, 1, state.direction)
    pending = Pending(
        kind="draw_stack",
        target=target,
        origin=player,  # last attacker — bounce sends the stack back here
        draw_total=draw_total,
        chain=chain,
        undefendable=undefendable,
    )
    staged = replace(state, pending=pending)
    if undefendable:
        return _resolve_draw_stack_eat(staged, list(events))
    return replace(staged, phase=Phase.RESPOND, to_act=target), tuple(events)


def _resolve_draw_stack_eat(
    state: GameState, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    """The target eats the whole stack and is skipped; each Delayed Blast in the
    chain skips one extra player on the way out."""
    pending = state.pending
    assert pending is not None
    target = pending.target
    k, luck = _luck_reduce(state, target, pending.draw_total)
    events.extend(luck)
    drawn = _draw(state, target, k)
    events.extend(drawn.events)
    events.append(PlayerDrew(target, drawn.count))
    events.append(PlayerSkipped(target))

    # In 2-player a Delayed Blast is just a normal Draw Four — no extra skip (§7).
    extra = 0 if _two_player(state) else pending.chain.count(CardId.DELAYED_BLAST)
    for step in range(1, extra + 1):
        events.append(PlayerSkipped(_advance(drawn.state, target, step, state.direction)))
    nxt = _advance(drawn.state, target, 1 + extra, state.direction)
    return replace(drawn.state, pending=None, phase=Phase.PLAY, to_act=nxt), tuple(events)


def _apply_draw_stack_response(
    state: GameState, action: Action
) -> tuple[GameState, tuple[Event, ...]]:
    pending = state.pending
    assert pending is not None
    target, origin = pending.target, pending.origin

    if isinstance(action, Decline):
        return _resolve_draw_stack_eat(state, [])

    if isinstance(action, PlayCard):
        card = state.players[target].hand[action.hand_index]

        # Stack another Draw-Four-type: play it as a wild (choose color), keeping
        # the pending stack; _apply_choose_color then extends it.
        if card.id in _DRAW_FOUR_TYPES:
            hand = state.players[target].hand
            new_hand = hand[: action.hand_index] + hand[action.hand_index + 1 :]
            players = _set_player(state.players, target, hand=new_hand)
            entry = DiscardEntry(card=card, eff_color=Color.WILD, eff_number=None)
            base = replace(
                state,
                players=players,
                discard=state.discard + (entry,),
                phase=Phase.CHOOSE_COLOR,
                to_act=target,
            )
            return base, (CardPlayed(target, card),)

        if card.id is CardId.BOUNCE:
            # Fuck You: the stack flies back to the last attacker; reverse; blue.
            base, _c, events = _play_defense(state, target, action.hand_index)
            new_dir = -base.direction
            events.append(DirectionReversed(new_dir))
            swapped = replace(pending, target=origin, origin=target)
            return replace(base, direction=new_dir, pending=swapped, to_act=origin), tuple(events)

        if card.id is CardId.HOLY_DEFENDER:
            # Pass the stack over the target to the next player.
            base, _c, events = _play_defense(state, target, action.hand_index)
            following = _advance(base, target, 1, base.direction)
            if following in (target, origin):
                # Nowhere meaningful to pass — the threat fizzles onto the origin.
                return _resolve_pass_fizzle(base, origin, events)
            return replace(base, pending=replace(pending, target=following), to_act=following), tuple(events)

        if card.id is CardId.SHARE:
            # AIDS: split the draw evenly between target and the last attacker.
            base, _c, events = _play_defense(state, target, action.hand_index)
            attacker_half = pending.draw_total // 2
            target_half = pending.draw_total - attacker_half
            kt, luck_t = _luck_reduce(base, target, target_half)
            d1 = _draw(base, target, kt)
            ka, luck_a = _luck_reduce(d1.state, origin, attacker_half)
            d2 = _draw(d1.state, origin, ka)
            events.extend(luck_t)
            events.extend(d1.events)
            events.append(PlayerDrew(target, d1.count))
            events.extend(luck_a)
            events.extend(d2.events)
            events.append(PlayerDrew(origin, d2.count))
            nxt = _advance(d2.state, target, 1, base.direction)
            return replace(d2.state, pending=None, phase=Phase.PLAY, to_act=nxt), tuple(events)

        if card.id is CardId.MAGIC_5:
            # Magic 5 nullifies a Hot Death (and everything stacked beneath it).
            base, _c, events = _play_defense(state, target, action.hand_index)
            nxt = _advance(base, target, 1, base.direction)
            return replace(base, pending=None, phase=Phase.PLAY, to_act=nxt), tuple(events)

    raise ValueError(f"illegal draw-stack response {action!r}")


def _resolve_pass_fizzle(
    state: GameState, origin: int, events: list[Event]
) -> tuple[GameState, tuple[Event, ...]]:
    nxt = _advance(state, origin, 1, state.direction)
    return replace(state, pending=None, phase=Phase.PLAY, to_act=nxt), tuple(events)


def _apply_draw(state: GameState) -> tuple[GameState, tuple[Event, ...]]:
    pid = state.to_act
    drawn = _draw(state, pid, 1)
    events: list[Event] = list(drawn.events)
    events.append(PlayerDrew(pid, drawn.count))
    called = len(drawn.state.players[pid].hand) == 1
    players = _set_player(drawn.state.players, pid, called_uno=called)
    nxt = _advance(drawn.state, pid, 1, state.direction)
    return replace(drawn.state, players=players, to_act=nxt), tuple(events)


# --------------------------------------------------------------------------- #
# Private helpers — pure, no I/O.
# --------------------------------------------------------------------------- #

def _set_player(
    players: tuple[PlayerState, ...], pid: int, **changes
) -> tuple[PlayerState, ...]:
    return tuple(replace(p, **changes) if p.id == pid else p for p in players)


def _two_player(state: GameState) -> bool:
    """True when exactly two players are still active (§7 rule modifications)."""
    return sum(1 for p in state.players if not p.eliminated) == 2


def _advance(state: GameState, start: int, steps: int, direction: int) -> int:
    """Index of the player ``steps`` active seats from ``start`` in ``direction``
    (eliminated players are skipped over)."""
    n = len(state.players)
    idx = start
    moved = 0
    while moved < steps:
        idx = (idx + direction) % n
        if not state.players[idx].eliminated:
            moved += 1
    return idx


class _DrawResult:
    __slots__ = ("state", "count", "events")

    def __init__(self, state: GameState, count: int, events: list[Event]):
        self.state = state
        self.count = count
        self.events = events


def _luck_reduce(state: GameState, pid: int, k: int) -> tuple[int, list[Event]]:
    """Luck o' the Irish shaves 1 off any *punishment* draw (not the can't-play
    draw). v1 auto-reveals it whenever beneficial; an opt-in reveal is a future
    refinement. Returns the reduced count and any LuckRevealed event."""
    if k > 0 and any(c.id is CardId.LUCK for c in state.players[pid].hand):
        return k - 1, [LuckRevealed(pid)]
    return k, []


def _draw(state: GameState, pid: int, k: int) -> _DrawResult:
    """Draw up to ``k`` cards for ``pid``, reshuffling the discard (minus its
    top) into the draw pile when it empties. Threads the seeded RNG state so the
    whole thing replays deterministically."""
    draw = list(state.draw_pile)
    discard = list(state.discard)
    rng_state: RngState = state.rng_state
    hand = list(state.players[pid].hand)
    events: list[Event] = []
    drawn = 0

    for _ in range(k):
        if not draw:
            if len(discard) <= 1:
                break  # nothing left to draw, even after a reshuffle
            rng = rng_from_state(rng_state)
            top = discard[-1]
            rest = [d.card for d in discard[:-1]]
            rng.shuffle(rest)
            draw = rest
            discard = [top]
            rng_state = state_of(rng)
            events.append(DeckReshuffled(len(draw)))
        if not draw:
            break
        hand.append(draw.pop())
        drawn += 1

    players = _set_player(state.players, pid, hand=tuple(hand))
    new_state = replace(
        state,
        players=players,
        draw_pile=tuple(draw),
        discard=tuple(discard),
        rng_state=rng_state,
    )
    return _DrawResult(new_state, drawn, events)
