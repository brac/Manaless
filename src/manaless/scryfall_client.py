"""Scryfall client — card enrichment (build step 1; CLAUDE.md §4).

GET api.scryfall.com/cards/named?exact={name}; pull type_line, oracle_text,
image, scryfall_uri, mana value. DFC/split/transform: fall back to
card_faces[0] when there is no top-level image, and concatenate face oracle
text. Cache by exact card name forever — card data is near-static.
"""

from __future__ import annotations

from manaless.http.client import HttpClient

CACHE_NAMESPACE = "scryfall-card"


def get_card_metadata(http: HttpClient, name: str) -> dict:
    """Return enriched metadata for one card by exact name. Build step 1."""
    raise NotImplementedError("build step 1 — enrichment")
