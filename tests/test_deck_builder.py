"""deck_builder — wiring EDHREC + Scryfall into a DeckModel (mocked, no network)."""

import pytest

from manaless.deck_builder import NoDecksAvailable, build_deck
from manaless.scryfall_client import ScryfallCard, ScryfallCardNotFound


class FakeEdhrec:
    def __init__(self, table, deck):
        self._table = table
        self._deck = deck
        self.table_calls = 0

    def fetch_deck_table(self, commander):
        self.table_calls += 1
        return self._table

    def fetch_deck(self, deck_id):
        return self._deck


def _meta(name, type_line="Artifact"):
    return ScryfallCard(
        name=name, type_line=type_line, oracle_text=f"text of {name}",
        mana_value=1.0, color_identity=(), image_url=None, scryfall_uri=None, is_dfc=False,
    )


def _enricher(missing=()):
    def enrich(name):
        if name in missing:
            raise ScryfallCardNotFound(name)
        tl = "Legendary Creature" if "Atraxa" in name else "Artifact"
        return _meta(name, tl)
    return enrich


TABLE = [{"urlhash": "newest", "savedate": "2026-06-27"}, {"urlhash": "older", "savedate": "2025-01-01"}]
DECK = ["1 Atraxa, Praetors' Voice", "1 Sol Ring", "3 Forest"]


def test_builds_deck_and_splits_commander():
    edhrec = FakeEdhrec(TABLE, DECK)
    deck = build_deck(edhrec, _enricher(), "Atraxa, Praetors' Voice")

    assert deck.deck_id == "newest"  # most recent picked
    assert [c.name for c in deck.commanders] == ["Atraxa, Praetors' Voice"]
    assert [c.name for c in deck.cards] == ["Sol Ring", "Forest"]
    assert deck.total_cards == 5  # 1 + 1 + 3
    assert deck.cards[1].quantity == 3


def test_enrichment_applied_to_cards():
    edhrec = FakeEdhrec(TABLE, DECK)
    deck = build_deck(edhrec, _enricher(), "Atraxa, Praetors' Voice")
    sol = next(c for c in deck.cards if c.name == "Sol Ring")
    assert sol.oracle_text == "text of Sol Ring"
    assert sol.category == "Artifact"


def test_explicit_deck_id_skips_table_lookup():
    edhrec = FakeEdhrec(TABLE, DECK)
    build_deck(edhrec, _enricher(), "Atraxa, Praetors' Voice", deck_id="chosen")
    assert edhrec.table_calls == 0


def test_no_decks_raises():
    edhrec = FakeEdhrec([], DECK)
    with pytest.raises(NoDecksAvailable):
        build_deck(edhrec, _enricher(), "Obscure Commander")


def test_unresolved_card_kept_not_dropped():
    edhrec = FakeEdhrec(TABLE, DECK)
    deck = build_deck(edhrec, _enricher(missing={"Sol Ring"}), "Atraxa, Praetors' Voice")
    # Sol Ring stays in the deck, flagged unresolved — not silently dropped.
    assert "Sol Ring" in [c.name for c in deck.cards]
    assert deck.unresolved == ("Sol Ring",)
    assert deck.total_cards == 5
