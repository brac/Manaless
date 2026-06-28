"""Buy steps — the rare, deliberate funnel exit (build steps 5/6; buy-pipeline.md).

Single-card buy (step 5, build when first wanted): name -> TCGplayer Mass Entry
URL. Deck-diff buy (step 6, build ONLY after first wanting a paper deck): .dck
minus collection -> Mass Entry URL of missing cards. Lean on the vendor for
pricing/cheapest-seller/shipping; the only custom value is "buy what I don't own".
"""

from __future__ import annotations

from manaless.collection import Collection


def single_card_url(name: str) -> str:
    """Card name -> TCGplayer Mass Entry URL. Build step 5 (build when wanted)."""
    raise NotImplementedError("build step 5 — single-card buy")


def deck_diff_url(deck, collection: Collection) -> str:  # deck: DeckModel
    """Missing cards (deck minus collection) -> Mass Entry URL. Build step 6."""
    raise NotImplementedError("build step 6 — deck-diff buy")
