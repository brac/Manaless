"""Deck-fetch + enrich pipeline — the spine (build step 1; architecture.md).

Wires the 0.3 `EdhrecClient` to Scryfall enrichment, producing the `DeckModel`
the engines and UI consume:

    commander -> deck table -> pick deck -> decklist -> enrich each card -> DeckModel

`enrich` is injected (a `name -> ScryfallCard` callable) so the pipeline is
testable headless and the real Scryfall client is just one binding of it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from manaless.deck_model import Card, DeckModel
from manaless.edhrec_client import EdhrecClient, filter_deck_hashes
from manaless.scryfall_client import ScryfallCard, get_collection

# Enrich a batch of card names at once. Returns metadata only for names that
# resolved; an absent name is treated as unresolved (kept, flagged — not dropped).
Enricher = Callable[[Sequence[str]], Mapping[str, ScryfallCard]]

_LINE = re.compile(r"^(\d+)\s+(.*)$")


class NoDecksAvailable(RuntimeError):
    """EDHREC has no indexed decks for this commander (§5 fallback not yet built)."""


def build_deck(
    edhrec: EdhrecClient,
    enrich: Enricher,
    commander: str,
    *,
    deck_id: str | None = None,
) -> DeckModel:
    """Build an enriched `DeckModel` for a commander (most-recent deck by default).

    Pass `deck_id` to build a specific deck and skip the table lookup. A card
    Scryfall can't resolve becomes an unenriched `Card(resolved=False)` rather
    than dropping out — inspect `DeckModel.unresolved`.
    """
    edhrec_bracket: int | None = None
    if deck_id is None:
        deck_id, edhrec_bracket = _pick_most_recent(edhrec, commander)

    entries = [_parse_line(line) for line in edhrec.fetch_deck(deck_id)]
    names = list(dict.fromkeys(name for _, name in entries))
    metadata = enrich(names)

    commander_key = commander.casefold()
    commanders: list[Card] = []
    mainboard: list[Card] = []
    for quantity, name in entries:
        card = _to_card(quantity, name, metadata.get(name))
        target = commanders if name.casefold() == commander_key else mainboard
        target.append(card)

    return DeckModel(
        commanders=tuple(commanders),
        cards=tuple(mainboard),
        deck_id=deck_id,
        edhrec_bracket=edhrec_bracket,
    )


def substitute_card(
    enrich: Enricher,
    deck: DeckModel,
    old_name: str,
    new_name: str,
    *,
    quantity: int = 1,
) -> DeckModel:
    """Swap ``old_name`` out for ``new_name``, enriching the new card (build step 4).

    Returns a NEW `DeckModel` (the source provenance is cleared by `.substitute`,
    so the caller re-runs `find_my_combos` / `estimate_bracket` on the result for
    the live win-condition + bracket readout). The new card is enriched through
    the same injected `enrich` callable as `build_deck`; an unresolvable name is
    kept as `Card(resolved=False)` rather than rejected.
    """
    meta = enrich([new_name]).get(new_name)
    return deck.substitute(old_name, _to_card(quantity, new_name, meta))


def add_card(
    enrich: Enricher,
    deck: DeckModel,
    name: str,
    *,
    quantity: int = 1,
) -> DeckModel:
    """Add ``name`` to the mainboard, enriching it first (build step 4).

    Symmetric with `substitute_card` — used by the "Add 1 → completes a combo"
    one-click action. Returns a new `DeckModel` (provenance cleared by `.add`).
    """
    meta = enrich([name]).get(name)
    return deck.add(_to_card(quantity, name, meta))


def _pick_most_recent(edhrec: EdhrecClient, commander: str) -> tuple[str, int | None]:
    """Return the most-recent deck id + its EDHREC bracket label (1-5, if present)."""
    table = edhrec.fetch_deck_table(commander)
    hashes = filter_deck_hashes(table)
    if not hashes:
        raise NoDecksAvailable(
            f"No indexed EDHREC decks for {commander!r}; "
            "the §5 average-deck fallback is not built yet."
        )
    deck_id = hashes[0]
    row = next((r for r in table if r.get("urlhash") == deck_id), {})
    bracket = row.get("bracket")
    return deck_id, int(bracket) if isinstance(bracket, (int, float)) else None


def _parse_line(line: str) -> tuple[int, str]:
    match = _LINE.match(line.strip())
    if not match:
        return (1, line.strip())
    return (int(match.group(1)), match.group(2).strip())


def _to_card(quantity: int, name: str, meta: ScryfallCard | None) -> Card:
    # Keep the EDHREC line name as the card name (front-face, source-faithful);
    # meta supplies enrichment only.
    if meta is None:
        return Card(name=name, quantity=quantity, resolved=False)
    return Card(
        name=name,
        quantity=quantity,
        type_line=meta.type_line,
        oracle_text=meta.oracle_text,
        mana_value=meta.mana_value,
        color_identity=meta.color_identity,
        image_url=meta.image_url,
        scryfall_uri=meta.scryfall_uri,
        is_dfc=meta.is_dfc,
    )


def main() -> None:
    import argparse
    import sys

    from manaless.http.cache import DiskCache
    from manaless.http.client import HttpClient
    from manaless.paths import CACHE_DIR

    parser = argparse.ArgumentParser(description="Build + enrich a real EDHREC deck (step 1).")
    parser.add_argument("commander", nargs="?", default="Atraxa, Praetors' Voice")
    args = parser.parse_args()

    with HttpClient(DiskCache(CACHE_DIR)) as http:
        edhrec = EdhrecClient(http)
        enrich = lambda names: get_collection(http, names)[0]  # noqa: E731
        try:
            deck = build_deck(edhrec, enrich, args.commander)
        except NoDecksAvailable as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    print(f"commander(s): {', '.join(c.name for c in deck.commanders)}")
    print(f"deck_id     : {deck.deck_id}   total cards: {deck.total_cards}")
    print("by type:")
    for category, cards in deck.categorized().items():
        count = sum(c.quantity for c in cards)
        print(f"  {category:13s} {count}")
    if deck.unresolved:
        print(f"unresolved  : {len(deck.unresolved)} -> {', '.join(deck.unresolved)}")
    sample = next((c for c in deck.cards if c.resolved), None)
    if sample:
        oracle = sample.oracle_text.replace("\n", " ")
        print(f"\nsample card : {sample.name}  [{sample.category}]  MV {sample.mana_value:g}")
        print(f"  {sample.type_line}")
        print(f"  {oracle[:140]}{'…' if len(oracle) > 140 else ''}")


if __name__ == "__main__":
    main()
