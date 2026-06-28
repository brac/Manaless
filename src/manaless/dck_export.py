"""XMage .dck export (build step 4; CLAUDE.md §8).

Emit plain-text lines; XMage resolves by card name alone, so printing is
irrelevant for vs-AI play — emit names, don't fight set matching. Reference for
format + round-trip: thebear132/MTG-To-XMage.
"""

from __future__ import annotations


def to_dck(deck) -> str:  # deck: DeckModel (build step 4)
    """Serialise the deck to XMage .dck text. Build step 4."""
    raise NotImplementedError("build step 4 — export")
