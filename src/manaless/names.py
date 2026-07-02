"""Canonical card-name comparison key — the one definition of "same card".

Magic card names collide across three axes the codebase kept re-solving ad hoc:

* **DFC / split / adventure** names — Scryfall returns ``"Front // Back"`` while
  EDHREC decklists carry just ``"Front"``. Front faces are unique across every
  Magic card, so keying on the front face is collision-safe and reconciles both.
* **Apostrophes** — EDHREC serves curly ``’`` (U+2019); user input and Scryfall
  use straight ``'``. ``"Gaea's Cradle"`` must match ``"Gaea’s Cradle"``.
* **Case / surrounding whitespace** — cosmetic only.

Every "is this the same card?" comparison (owned-matching, commander detection,
deck mutation, combo piece matching, Game-Changer matching) routes through
``norm_name`` so the notion of identity is defined exactly once.
"""

from __future__ import annotations


def norm_name(name: str) -> str:
    """Canonical comparison key: front face, straight apostrophe, casefolded."""
    front = name.split("//", 1)[0]
    return front.replace("’", "'").strip().casefold()
