"""Hot Death Uno — pure rules engine.

The engine (this package) is framework-free: no I/O, no printing, no
networking, no global mutable state, and no un-seeded randomness. Consumers
(the CLI, the AI, a future websocket server) sit on top of it. See CLAUDE.md
and HANDOFF.md for the full contract.
"""
