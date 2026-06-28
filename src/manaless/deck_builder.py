"""Deck-fetch + enrich pipeline — the spine (build step 1; architecture.md).

Wires the 0.3 `EdhrecClient` to Scryfall enrichment, producing the `DeckModel`
the engines and UI consume:

    commander -> deck table -> pick deck -> decklist -> enrich each card -> DeckModel

`enrich` is injected (a `name -> ScryfallCard` callable) so the pipeline is
testable headless and the real Scryfall client is just one binding of it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from manaless.deck_model import Card, DeckModel
from manaless.edhrec_client import EdhrecClient, filter_deck_hashes
from manaless.scryfall_client import ScryfallCard, ScryfallCardNotFound, get_card_metadata

Enricher = Callable[[str], ScryfallCard]

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
    if deck_id is None:
        deck_id = _pick_most_recent(edhrec, commander)

    entries = [_parse_line(line) for line in edhrec.fetch_deck(deck_id)]
    metadata = _enrich_unique(enrich, entries)

    commander_key = commander.casefold()
    commanders: list[Card] = []
    mainboard: list[Card] = []
    for quantity, name in entries:
        card = _to_card(quantity, name, metadata[name])
        target = commanders if name.casefold() == commander_key else mainboard
        target.append(card)

    return DeckModel(
        commanders=tuple(commanders),
        cards=tuple(mainboard),
        deck_id=deck_id,
    )


def _pick_most_recent(edhrec: EdhrecClient, commander: str) -> str:
    table = edhrec.fetch_deck_table(commander)
    hashes = filter_deck_hashes(table)
    if not hashes:
        raise NoDecksAvailable(
            f"No indexed EDHREC decks for {commander!r}; "
            "the §5 average-deck fallback is not built yet."
        )
    return hashes[0]


def _parse_line(line: str) -> tuple[int, str]:
    match = _LINE.match(line.strip())
    if not match:
        return (1, line.strip())
    return (int(match.group(1)), match.group(2).strip())


def _enrich_unique(enrich: Enricher, entries: list[tuple[int, str]]) -> dict[str, ScryfallCard | None]:
    metadata: dict[str, ScryfallCard | None] = {}
    for _, name in entries:
        if name in metadata:
            continue
        try:
            metadata[name] = enrich(name)
        except ScryfallCardNotFound:
            metadata[name] = None
    return metadata


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
    from functools import partial

    from manaless.http.cache import DiskCache
    from manaless.http.client import HttpClient
    from manaless.paths import CACHE_DIR

    parser = argparse.ArgumentParser(description="Build + enrich a real EDHREC deck (step 1).")
    parser.add_argument("commander", nargs="?", default="Atraxa, Praetors' Voice")
    args = parser.parse_args()

    with HttpClient(DiskCache(CACHE_DIR)) as http:
        edhrec = EdhrecClient(http)
        try:
            deck = build_deck(edhrec, partial(get_card_metadata, http), args.commander)
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
