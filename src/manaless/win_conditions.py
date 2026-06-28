"""Win-condition engine — three-source merge (build step 2; win-conditions.md).

Merges Spellbook combos (+ "Add 1"), the Scryfall explicit alt-win scan
(oracle:"win the game"), and the custom ~50-line non-combo oracle heuristic
(aggro / burn / mill / go-wide) into one object, recomputed on every
substitution. Consumes the Scryfall + Spellbook clients; builds nothing new
that those already provide.
"""

from __future__ import annotations


def evaluate_win_conditions(deck) -> dict:  # deck: DeckModel (build step 4)
    """Return the merged win-condition object for the current deck. Build step 2."""
    raise NotImplementedError("build step 2 — win conditions")
