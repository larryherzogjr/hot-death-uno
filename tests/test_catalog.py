"""Card catalog: completeness, fields, and the /api/cards endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from hdu.cards import CardId
from server.app import app
from server.catalog import CATALOG, RULES_SECTIONS


def test_catalog_covers_every_card_id():
    ids = {c["id"] for c in CATALOG}
    for cid in CardId:
        assert cid.name in ids, f"no catalog entry for {cid.name} — tooltips would miss it"


def test_catalog_entries_have_required_fields():
    for c in CATALOG:
        assert c["name"] and c["category"] and c["effect"]
        assert "value" in c and "defense" in c  # defense may be None


def test_cards_endpoint_returns_catalog_and_rules():
    client = TestClient(app)
    data = client.get("/api/cards").json()
    assert len(data["cards"]) == len(CATALOG) >= 20
    assert len(data["sections"]) == len(RULES_SECTIONS) >= 3
