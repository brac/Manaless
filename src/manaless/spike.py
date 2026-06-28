"""Phase 0.3 fragile-point spike — prove the EDHREC spine end to end, live.

    python -m manaless.spike "Atraxa, Praetors' Voice"

commander -> slug -> deck table -> most-recent deck -> full decklist, all
through the shared rate-limited + cached HTTP layer. This exercises the one
hard-break dependency (the Next.js build id) against the *current* live EDHREC,
so a rotation shows up here first. Throwaway driver, not a product surface.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from manaless.edhrec_client import (
    EdhrecClient,
    EdhrecError,
    filter_deck_hashes,
    format_commander_name,
)
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.paths import CACHE_DIR

DEFAULT_COMMANDER = "Atraxa, Praetors' Voice"
_PREVIEW_LINES = 15


def run(commander: str) -> int:
    with HttpClient(DiskCache(CACHE_DIR)) as http:
        client = EdhrecClient(http)

        slug = format_commander_name(commander)
        print(f"commander : {commander}")
        print(f"slug      : {slug}")
        print(f"build id  : {client.build_id()}")

        table = client.fetch_deck_table(commander)
        print(f"deck table: {len(table)} decks")
        if not table:
            print("  (no indexed decks — §5 fallback to the average deck would fire)")
            return 1

        deck_ids = filter_deck_hashes(table)
        deck_id = deck_ids[0]
        selected = next((row for row in table if row.get("urlhash") == deck_id), {})
        print(
            f"selected  : {deck_id}  "
            f"(most recent of {len(deck_ids)}; "
            f"savedate={selected.get('savedate')} price={selected.get('price')})"
        )

        cards = client.fetch_deck(deck_id)
        print(f"decklist  : {len(cards)} lines")
        for line in cards[:_PREVIEW_LINES]:
            print(f"  {line}")
        if len(cards) > _PREVIEW_LINES:
            print(f"  ... (+{len(cards) - _PREVIEW_LINES} more)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="EDHREC spine spike (Phase 0.3).")
    parser.add_argument("commander", nargs="?", default=DEFAULT_COMMANDER)
    args = parser.parse_args()
    try:
        sys.exit(run(args.commander))
    except EdhrecError as exc:
        print(f"ERROR (edhrec adapter): {exc}", file=sys.stderr)
        sys.exit(2)
    except httpx.HTTPError as exc:
        print(f"ERROR (http): {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
