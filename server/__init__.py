"""Web transport layer for Hot Death Uno.

A *consumer* of the `hdu` engine — it never modifies engine state except through
``apply`` / ``settle_hand`` and never decides legality itself (``legal_actions``
is the source of truth). The engine package stays pure stdlib; everything
network/JSON/framework lives here.

  serialize.py  PlayerView / Action / Event <-> JSON-able dicts (pure)
  session.py    authoritative game session manager (drives AI seats)
"""
