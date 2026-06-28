"""XMage .dck export (build step 4; CLAUDE.md §8, prior-art.md).

XMage's `.dck` importer (`DckDeckImporter`) parses each line with the regex

    (SB:)?\\s*(\\d*)\\s*\\[([^]:]+):([^]:]+)\\]\\s*(.*)\\s*$

so the `[set:num]` bracket is **mandatory** (a bare ``qty name`` line won't
match and is silently dropped). Its lookup order is set/number -> name: when the
set+number don't resolve it falls back to ``findPreferredCoreExpansionCard(name,
set)``. We don't track printings, so we emit a placeholder set/number and let
that name fallback do the work -- exactly the "emit names, don't fight set
matching" intent in CLAUDE.md §8. Reference: thebear132/MTG-To-XMage.

Conventions (prior-art.md):
- Commanders go in the **sideboard** (``SB:`` prefix) -- XMage's command-zone
  convention.
- DFC / split / "//" cards: emit the **front-face name only**.
- File is ``<DeckName>.dck``, UTF-8.
"""

from __future__ import annotations

from pathlib import Path

from manaless.deck_model import Card, DeckModel

# Placeholder printing. Per the importer's regex, set and number must be
# non-empty and contain no ']' or ':'. Neither resolves to a real printing, so
# XMage falls back to resolving each card by name.
PLACEHOLDER_SET = "XXX"
PLACEHOLDER_NUM = "0"

# Characters illegal in a Windows filename (commas/apostrophes are fine, so a
# name like "Atraxa, Praetors' Voice.dck" survives intact).
_ILLEGAL_FILENAME = set('<>:"/\\|?*')


def _front_face(name: str) -> str:
    """Front-face name for a DFC/split/"//" card (XMage matches the front)."""
    return name.split("//", 1)[0].strip()


def _line(card: Card, *, sideboard: bool) -> str:
    prefix = "SB: " if sideboard else ""
    return f"{prefix}{card.quantity} [{PLACEHOLDER_SET}:{PLACEHOLDER_NUM}] {_front_face(card.name)}"


def to_dck(deck: DeckModel) -> str:
    """Serialise ``deck`` to XMage ``.dck`` text (mainboard + commanders in SB)."""
    lines = [_line(card, sideboard=False) for card in deck.cards]
    lines += [_line(card, sideboard=True) for card in deck.commanders]
    return "\n".join(lines) + "\n"


def dck_filename(deck: DeckModel) -> str:
    """A safe ``<DeckName>.dck`` filename derived from the commander(s)."""
    base = " & ".join(_front_face(c.name) for c in deck.commanders) or "deck"
    safe = "".join("_" if ch in _ILLEGAL_FILENAME or ord(ch) < 32 else ch for ch in base).strip()
    return f"{safe or 'deck'}.dck"


def write_dck(deck: DeckModel, directory: Path | str) -> Path:
    """Write ``deck`` as ``<DeckName>.dck`` into ``directory``; return the path."""
    path = Path(directory) / dck_filename(deck)
    path.write_text(to_dck(deck), encoding="utf-8")
    return path


def main() -> None:
    import argparse
    import sys

    from manaless.deck_builder import NoDecksAvailable, build_deck
    from manaless.edhrec_client import EdhrecClient
    from manaless.http.cache import DiskCache
    from manaless.http.client import HttpClient
    from manaless.paths import CACHE_DIR
    from manaless.scryfall_client import get_collection

    parser = argparse.ArgumentParser(description="Export a real EDHREC deck to an XMage .dck (step 4).")
    parser.add_argument("commander", nargs="?", default="Atraxa, Praetors' Voice")
    parser.add_argument("-o", "--out", help="directory to write <DeckName>.dck into (default: print to stdout)")
    args = parser.parse_args()

    with HttpClient(DiskCache(CACHE_DIR)) as http:
        edhrec = EdhrecClient(http)
        try:
            deck = build_deck(edhrec, lambda names: get_collection(http, names)[0], args.commander)
        except NoDecksAvailable as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.out:
        path = write_dck(deck, args.out)
        print(f"wrote {path}  ({deck.total_cards} cards)")
    else:
        sys.stdout.write(to_dck(deck))


if __name__ == "__main__":
    main()
