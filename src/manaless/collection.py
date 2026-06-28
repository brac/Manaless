"""Owned-cards store — thin local file (build step 6; CLAUDE.md §9).

Hand-maintained or exported from Deckstats. JSON or CSV of (name, qty). Keep it
dumb. Only needed for the deck-diff buy (step 6).
"""

from __future__ import annotations

from pathlib import Path


class Collection:
    """Owned cards as {name: qty}. Build step 6."""

    def __init__(self) -> None:
        raise NotImplementedError("build step 6 — collection")

    @classmethod
    def load(cls, path: Path) -> "Collection":
        raise NotImplementedError("build step 6 — collection")
