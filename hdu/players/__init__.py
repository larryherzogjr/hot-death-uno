"""Opponent strategies. Strategy is a *consumer* concern: a player receives a
``PlayerView`` plus ``legal_actions`` and returns one action. Swapping a player
must never touch the engine."""
