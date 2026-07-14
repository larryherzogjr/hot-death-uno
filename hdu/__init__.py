"""Hot Death Uno — deterministic rules plus colocated consumers.

The rules kernel is framework-free: no I/O, no printing, no networking, no
global mutable state, and no un-seeded randomness. The CLI and AI consumers are
colocated in this package; the WebSocket server sits on top of it. See AGENTS.md
and HANDOFF.md for the exact boundary.
"""
