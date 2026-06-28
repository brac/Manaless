"""Commander Spellbook client — combos + bracket baseline (build steps 2/3).

POST a decklist to ``find-my-combos`` (combos present + "Add 1" near-complete
lines) and ``estimate-bracket`` (bracket-relevant combo classification). Cache
by decklist hash — results are stable for a fixed list.

VERIFY the exact request/response schemas and the current bucket->1-5 mapping
against the live Swagger before wiring (CLAUDE.md §12; Phase 0.4).
"""

from __future__ import annotations

from manaless.http.client import HttpClient

BASE_URL = "https://backend.commanderspellbook.com"
CACHE_NAMESPACE = "spellbook"


def find_my_combos(http: HttpClient, decklist: list[str]) -> dict:
    """POST decklist -> {present: [...], add_one: [...]}. Build step 2."""
    raise NotImplementedError("build step 2 — win conditions")


def estimate_bracket(http: HttpClient, decklist: list[str]) -> dict:
    """POST decklist -> bracket-relevant info (buckets to map to 1-5). Build step 3."""
    raise NotImplementedError("build step 3 — bracket")
