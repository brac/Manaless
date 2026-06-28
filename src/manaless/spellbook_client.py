"""Commander Spellbook client — combos + bracket baseline (build steps 2/3).

POST a decklist to ``find-my-combos`` (combos present + the "almost included"
pool that powers the "Add 1" feature) and, later, ``estimate-bracket``. Results
are cached by a decklist hash — stable for a fixed list, so a substitution is the
only thing that triggers a fresh call.

Schemas live-verified 2026-06-27 (see docs/verified.md §1): the top-level
``{count, next, previous, results}`` wrapper is **not** actually paginated
(``next``/``previous`` come back null), so we read ``results`` directly. Each
combo is a ``Variant`` with ``uses[].card.name``, ``produces[].feature.name``,
``popularity`` and ``bracketTag``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from manaless.deck_model import DeckModel
from manaless.http.client import HttpClient

BASE_URL = "https://backend.commanderspellbook.com"
FIND_MY_COMBOS_URL = f"{BASE_URL}/find-my-combos"
ESTIMATE_BRACKET_URL = f"{BASE_URL}/estimate-bracket"
CACHE_NAMESPACE = "spellbook-combos"


@dataclass(frozen=True, slots=True)
class Combo:
    """One Spellbook combo (``Variant``), flattened to what the UI needs."""

    id: str
    cards: tuple[str, ...]       # every card the combo uses, by name
    produces: tuple[str, ...]    # produced effects, e.g. "Infinite mana"
    popularity: int              # EDHREC decks running it
    bracket_tag: str | None      # E/C/O/P/S/R/B (per-combo bracket floor)


@dataclass(frozen=True, slots=True)
class ComboResults:
    """The slice of ``find-my-combos`` we use: combos in the deck + near-misses.

    ``almost_included`` is "missing ≥1 card but within color identity" — the raw
    pool the win-condition engine filters down to genuine one-card-away lines.
    """

    identity: str
    included: tuple[Combo, ...]
    almost_included: tuple[Combo, ...]


def decklist_hash(deck: DeckModel) -> str:
    """Order-independent hash of the deck's cards, keyed by role + qty + name.

    Two builds with the same cards hash the same (so caching is substitution-
    driven); moving a card between commander and mainboard changes the hash
    because the commander defines color identity, which Spellbook keys on.
    """
    lines = [f"C {c.quantity} {c.name}" for c in deck.commanders]
    lines += [f"M {c.quantity} {c.name}" for c in deck.cards]
    canonical = "\n".join(sorted(lines))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def find_my_combos(http: HttpClient, deck: DeckModel) -> ComboResults:
    """POST the deck to ``find-my-combos`` and return the parsed results (cached)."""
    key = decklist_hash(deck)
    cached = http.cache.get(CACHE_NAMESPACE, key)
    if cached is None:
        cached = http.post_json(FIND_MY_COMBOS_URL, _deck_request(deck))
        http.cache.set(CACHE_NAMESPACE, key, cached)
    return _parse_results(cached)


def _deck_request(deck: DeckModel) -> dict:
    """Build the Spellbook ``DeckRequest`` body from a deck model."""
    return {
        "commanders": [{"card": c.name, "quantity": c.quantity} for c in deck.commanders],
        "main": [{"card": c.name, "quantity": c.quantity} for c in deck.cards],
    }


def _parse_results(payload: dict) -> ComboResults:
    results = payload.get("results") or {}
    return ComboResults(
        identity=results.get("identity", ""),
        included=tuple(_parse_combo(v) for v in results.get("included", [])),
        almost_included=tuple(_parse_combo(v) for v in results.get("almostIncluded", [])),
    )


def _parse_combo(variant: dict) -> Combo:
    cards = tuple(
        (use.get("card") or {}).get("name", "")
        for use in variant.get("uses", [])
    )
    produces = tuple(
        (prod.get("feature") or {}).get("name", "")
        for prod in variant.get("produces", [])
    )
    return Combo(
        id=str(variant.get("id", "")),
        cards=tuple(name for name in cards if name),
        produces=tuple(name for name in produces if name),
        popularity=int(variant.get("popularity") or 0),
        bracket_tag=variant.get("bracketTag"),
    )


def estimate_bracket(http: HttpClient, deck: DeckModel) -> dict:
    """POST decklist -> bracket-relevant info (buckets to map to 1-5). Build step 3."""
    raise NotImplementedError("build step 3 — bracket")
