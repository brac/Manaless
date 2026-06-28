"""Buy steps — the rare, deliberate funnel exit (build steps 5/6; buy-pipeline.md).

Single-card buy (step 5): name -> TCGplayer Mass Entry URL. Deck-diff buy
(step 6, build ONLY after first wanting a paper deck): .dck minus collection ->
Mass Entry URL of missing cards. Lean on the vendor for pricing / cheapest-seller
/ shipping; the only custom value is "buy what I don't own".

Mass Entry is the public web form (no API key). Format confirmed against several
real implementations (zwipe, cardmystic, manavault, …):

    https://www.tcgplayer.com/massentry?c=<entries>&productline=Magic

where ``c`` is the card list, entries joined by ``||``, each entry ``qty name``,
and the whole query string URL-encoded. Less specificity = "any printing", which
is exactly what we want (printing is irrelevant for a vs-AI proxy).
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlencode

from manaless.collection import Collection

MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry"
PRODUCTLINE = "Magic"
_ENTRY_SEP = "||"


def _entry(quantity: int, name: str) -> str:
    return f"{quantity} {name}"


def mass_entry_url(entries: Iterable[tuple[int, str]]) -> str:
    """``[(qty, name), ...]`` -> a TCGplayer Mass Entry deep link.

    Quantities below 1 are clamped to 1 (a buy is at least one copy). The result
    pre-populates the Mass Entry form; the user reviews printings/condition and
    adds to cart there — we never touch the cart or pricing.
    """
    c = _ENTRY_SEP.join(_entry(max(1, qty), name.strip()) for qty, name in entries)
    query = urlencode({"c": c, "productline": PRODUCTLINE})
    return f"{MASS_ENTRY_BASE}?{query}"


def single_card_url(name: str, *, quantity: int = 1) -> str:
    """Card name -> TCGplayer Mass Entry URL for that one card. Build step 5."""
    return mass_entry_url([(quantity, name)])


# Basic lands are excluded from the buy list by default: nobody mass-orders
# basics (free at any game store), and ~35 of them per deck just pad the cart.
_BASIC_LANDS = frozenset({"plains", "island", "swamp", "mountain", "forest", "wastes"})
_SNOW = "snow-covered "


def is_basic_land(name: str) -> bool:
    n = name.casefold()
    if n.startswith(_SNOW):
        n = n[len(_SNOW):]
    return n in _BASIC_LANDS


def deck_diff(deck, collection: Collection, *, include_basics: bool = False) -> list[tuple[int, str]]:
    """``deck`` minus what you own -> ``[(qty_to_buy, name), ...]``. Build step 6.

    Quantity-aware (buy ``need - owned``, never negative); commanders included;
    basic lands skipped unless ``include_basics``. ``deck`` is any object with
    ``all_cards()`` yielding cards that have ``name`` and ``quantity``.
    """
    missing: list[tuple[int, str]] = []
    for card in deck.all_cards():
        if not include_basics and is_basic_land(card.name):
            continue
        short = card.quantity - collection.quantity(card.name)
        if short > 0:
            missing.append((short, card.name))
    return missing


def deck_diff_url(deck, collection: Collection) -> str:  # deck: DeckModel
    """Missing cards (deck minus collection) -> TCGplayer Mass Entry URL. Step 6."""
    return mass_entry_url(deck_diff(deck, collection))
