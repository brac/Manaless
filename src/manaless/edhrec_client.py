"""EDHREC client — the spine (build step 1; CLAUDE.md §4, architecture.md).

The single hard-break dependency lives here: ``fetch_edhrec_build_id``. RUNBOOK —
if deck fetches start returning 404/HTTP errors, refresh the build id FIRST;
EDHREC redeployed and rotated it. Keep that fix isolated to one function.

Only the pure ``format_commander_name`` helper is implemented now. The network
functions are wired in Phase 0.3 (the fragile-point spike) against live data.
"""

from __future__ import annotations

import re

from manaless.http.client import HttpClient

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_APOSTROPHES = ("'", "’")


def format_commander_name(name: str) -> str:
    """Slugify a commander name for EDHREC URLs.

    Rule (CLAUDE.md §4): lowercase, drop apostrophes, map every other run of
    non-alphanumerics to a single hyphen, trim hyphens from the ends.

    >>> format_commander_name("Atraxa, Praetors' Voice")
    'atraxa-praetors-voice'
    """
    lowered = name.lower()
    for mark in _APOSTROPHES:
        lowered = lowered.replace(mark, "")
    return _NON_SLUG.sub("-", lowered).strip("-")


def fetch_edhrec_build_id(http: HttpClient) -> str:
    """Scrape the EDHREC homepage and extract the Next.js ``<BUILD_ID>``.

    THE fragile point. Implemented in Phase 0.3.
    """
    raise NotImplementedError("Phase 0.3 — fragile-point spike")


def fetch_deck_table(http: HttpClient, slug: str) -> list[dict]:
    """GET json.edhrec.com/pages/decks/{slug}.json -> list of deck-table entries
    ({urlhash, savedate, price, ...}). Implemented in Phase 0.3 / build step 1."""
    raise NotImplementedError("build step 1 — spine")


def fetch_deck_by_hash(http: HttpClient, build_id: str, deck_id: str) -> list[str]:
    """GET the full decklist for a deck id -> flat ['1 Card Name', ...] array.
    Needs the build id. Implemented in Phase 0.3 / build step 1."""
    raise NotImplementedError("build step 1 — spine")
