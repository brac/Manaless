"""Bracket estimator — inferred power level 1-5 (build step 3; bracket-evaluator.md).

Spellbook ``estimate-bracket`` baseline + a small explainable non-combo signal
(Game Changers count, fast mana, tutors, cheap/free interaction) over Scryfall
data. Calibrated so the precon dataset clusters at ~2 before trusting it on
EDHREC decks. VERIFY current brackets definitions + Game Changers list first
(CLAUDE.md §12; Phase 0.4).
"""

from __future__ import annotations


def estimate_bracket(deck) -> int:  # deck: DeckModel (build step 4)
    """Return an inferred 1-5 bracket for the deck. Build step 3."""
    raise NotImplementedError("build step 3 — bracket")
