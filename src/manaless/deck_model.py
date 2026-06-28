"""Deck model — the in-memory deck the UI mutates (build step 4; architecture.md).

Single source of truth for the current build. Substitutions produce a new deck
state (immutable updates, not in-place mutation per coding-style); the
win-condition and bracket engines recompute off it. Kept UI-agnostic so the
pipeline is callable headless for batch practice-ladder generation.
"""

from __future__ import annotations


class DeckModel:
    """Enriched, categorised deck the substitution UI and engines read. Build step 4."""

    def __init__(self) -> None:
        raise NotImplementedError("build step 4 — substitution")
