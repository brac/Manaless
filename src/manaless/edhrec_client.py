"""EDHREC client — the spine (build step 1; CLAUDE.md §4, architecture.md).

The single hard-break dependency lives here: the Next.js **build id**. RUNBOOK —
if deck fetches start returning 404s, the build id rotated; refresh it FIRST.
That recovery is automated in :meth:`EdhrecClient.fetch_deck` (one forced
refresh + retry on a 404) and isolated to :meth:`EdhrecClient._scrape_build_id`,
so the fix — if it ever needs a human — is in exactly one place.

``format_commander_name`` is pure and has no network dependency. The networked
operations live on :class:`EdhrecClient`, which owns the rate-limited
``HttpClient`` and caches the build id for the session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from manaless.http.client import HttpClient

EDHREC_HOME = "https://edhrec.com/"
DECK_TABLE_URL = "https://json.edhrec.com/pages/decks/{slug}.json"
COMMANDER_PAGE_URL = "https://json.edhrec.com/pages/commanders/{slug}.json"
DECK_PREVIEW_URL = (
    "https://edhrec.com/_next/data/{build_id}/deckpreview/{deck_id}.json"
    "?deckId={deck_id}"
)

# EDHREC refreshes deck data ~daily; the per-deck list is immutable by hash.
DECK_TABLE_TTL_SECONDS = 24 * 60 * 60

_NON_SLUG = re.compile(r"[^a-z0-9]+")
_APOSTROPHES = ("'", "’")

# Primary: the build id is the directory in the *Manifest.js asset path.
# Fallback: Next.js also embeds it as "buildId":"..." in __NEXT_DATA__.
_BUILD_ID_PATTERNS = (
    re.compile(r"/_next/static/([^/\"]+)/_(?:buildManifest|ssgManifest)\.js"),
    re.compile(r'"buildId"\s*:\s*"([^"]+)"'),
)

# The one status that means "the build id rotated" (CLAUDE.md §4 runbook).
_BUILD_ID_ROTATED_STATUS = 404

# json.edhrec.com returns 403 (not 404) for a commander slug with no deck page;
# both mean "no indexed decks" -> the §5 fallback to an average deck. Scoped to
# the deck-table call so a systemic block still surfaces via other endpoints.
_NO_DECK_TABLE_STATUS = {403, 404}


class EdhrecError(RuntimeError):
    """Base class for EDHREC adapter failures."""


class EdhrecBuildIdError(EdhrecError):
    """The Next.js build id could not be extracted from the homepage."""


class EdhrecDeckNotFound(EdhrecError):
    """A decklist could not be fetched for a deck id, even after a build-id refresh."""


@dataclass(frozen=True, slots=True)
class CardPopularity:
    """How often a card appears in EDHREC decks for a given commander.

    ``num_decks`` of ``potential_decks`` run it; ``percent`` is the inclusion
    rate. ``synergy`` is EDHREC's synergy score (how much *more* this commander
    runs it vs. the colour-identity baseline).
    """

    name: str
    num_decks: int
    potential_decks: int
    synergy: float = 0.0

    @property
    def percent(self) -> float:
        return 100.0 * self.num_decks / self.potential_decks if self.potential_decks else 0.0


def _popularity_key(name: str) -> str:
    """Front-face, case-folded — so a card matches regardless of DFC spelling/case."""
    return name.split("//", 1)[0].strip().casefold()


@dataclass(frozen=True, slots=True)
class PopularityIndex:
    """Per-commander card-popularity lookup, keyed by `_popularity_key(name)`."""

    cards: dict

    def get(self, name: str) -> CardPopularity | None:
        return self.cards.get(_popularity_key(name))

    def excluding(self, names) -> list[CardPopularity]:
        """Popular cards minus ``names`` (a deck), most-played first.

        Ranked by ``num_decks`` (raw usage), not ``percent`` — so a niche card
        with a small recent-decks denominator can't masquerade near the top.
        """
        skip = {_popularity_key(n) for n in names}
        out = [cp for key, cp in self.cards.items() if key not in skip]
        out.sort(key=lambda cp: cp.num_decks, reverse=True)
        return out

    def __bool__(self) -> bool:
        return bool(self.cards)

    def __len__(self) -> int:
        return len(self.cards)


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


class EdhrecClient:
    """Rate-limited, cached access to EDHREC's deck data, fragile point isolated."""

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._build_id: str | None = None

    def build_id(self, *, force_refresh: bool = False) -> str:
        """Return the current Next.js build id, scraping once per session.

        Pass ``force_refresh=True`` to re-scrape after a suspected rotation.
        """
        if self._build_id is None or force_refresh:
            self._build_id = self._scrape_build_id()
        return self._build_id

    def fetch_deck_table(self, commander: str) -> list[dict]:
        """Curated deck table for a commander.

        Each row (verified against a live response, CLAUDE.md §12) carries:
        ``urlhash`` (deck id), ``savedate`` ("YYYY-MM-DD"), ``price`` (number),
        ``salt`` (float saltiness), ``bracket`` (1-5), ``budget_label`` (int),
        ``tags`` (theme strings), and per-type counts (``creature``, ``instant``,
        ``sorcery``, ``artifact``, ``enchantment``, ``battle``, ``planeswalker``,
        ``land``). There is **no per-deck popularity/views field** — these are
        individual published lists, so recency is the only "what's hot" proxy.

        Returns an empty list when EDHREC has no indexed decks (the §5 fallback
        to an average deck would trigger on this signal).
        """
        slug = format_commander_name(commander)
        try:
            data = self._http.get_json(
                DECK_TABLE_URL.format(slug=slug),
                cache_namespace="edhrec-deck-table",
                cache_key=slug,
                ttl_seconds=DECK_TABLE_TTL_SECONDS,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _NO_DECK_TABLE_STATUS:
                return []  # no deck page for this slug -> §5 fallback signal
            raise
        if not isinstance(data, dict):
            return []
        return data.get("table") or []

    def fetch_commander_card_stats(self, commander: str) -> PopularityIndex:
        """Aggregate card popularity for a commander: ``{card -> CardPopularity}``.

        From the EDHREC commander page (``cardlists`` grouped by category). A card
        can appear in several lists (e.g. "New Cards" uses a smaller recent-decks
        denominator); we keep the entry with the **largest** ``potential_decks`` so
        the percentage is the headline inclusion rate, not a recent-only slice.

        Returns an empty index when EDHREC has no page for the commander.
        """
        slug = format_commander_name(commander)
        try:
            data = self._http.get_json(
                COMMANDER_PAGE_URL.format(slug=slug),
                cache_namespace="edhrec-commander",
                cache_key=slug,
                ttl_seconds=DECK_TABLE_TTL_SECONDS,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _NO_DECK_TABLE_STATUS:
                return PopularityIndex({})
            raise

        container = data.get("container") if isinstance(data, dict) else None
        json_dict = container.get("json_dict") if isinstance(container, dict) else None
        cardlists = json_dict.get("cardlists") if isinstance(json_dict, dict) else None

        cards: dict[str, CardPopularity] = {}
        for cardlist in cardlists or []:
            for cv in cardlist.get("cardviews") or []:
                name = cv.get("name")
                if not name:
                    continue
                potential = int(cv.get("potential_decks") or 0)
                key = _popularity_key(name)
                prev = cards.get(key)
                if prev is None or potential > prev.potential_decks:
                    cards[key] = CardPopularity(
                        name=name,
                        num_decks=int(cv.get("num_decks") or 0),
                        potential_decks=potential,
                        synergy=float(cv.get("synergy") or 0.0),
                    )
        return PopularityIndex(cards)

    def fetch_deck(self, deck_id: str) -> list[str]:
        """Full decklist for a deck id as a flat ``["1 Card Name", ...]`` array.

        Implements the runbook: a 404 means the build id rotated, so refresh it
        once and retry before giving up.
        """
        try:
            return self._fetch_deck_raw(self.build_id(), deck_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != _BUILD_ID_ROTATED_STATUS:
                raise
            try:
                return self._fetch_deck_raw(self.build_id(force_refresh=True), deck_id)
            except httpx.HTTPStatusError as retry_exc:
                raise EdhrecDeckNotFound(
                    f"Deck {deck_id!r} not found even after refreshing the build id "
                    f"(HTTP {retry_exc.response.status_code})."
                ) from retry_exc

    def _scrape_build_id(self) -> str:
        html = self._http.get_text(EDHREC_HOME)
        for pattern in _BUILD_ID_PATTERNS:
            match = pattern.search(html)
            if match:
                return match.group(1)
        raise EdhrecBuildIdError(
            "Could not find the EDHREC build id on the homepage. EDHREC likely "
            "changed its markup — inspect the homepage HTML and update "
            "_BUILD_ID_PATTERNS in edhrec_client.py."
        )

    def _fetch_deck_raw(self, build_id: str, deck_id: str) -> list[str]:
        # Cached by deck id (not the build-id-bearing URL): deck content is
        # immutable by hash, so a rotated build id must not invalidate it.
        data = self._http.get_json(
            DECK_PREVIEW_URL.format(build_id=build_id, deck_id=deck_id),
            cache_namespace="edhrec-decklist",
            cache_key=deck_id,
        )
        try:
            return data["pageProps"]["data"]["deck"]
        except (KeyError, TypeError) as exc:
            raise EdhrecError(
                f"Unexpected deck-preview shape for {deck_id!r}; EDHREC may have "
                "changed its response structure."
            ) from exc


def filter_deck_hashes(
    table: list[dict],
    *,
    min_price: float | None = None,
    max_price: float | None = None,
) -> list[str]:
    """Deck ids from a deck table, most-recent-first, optionally price-banded.

    Price is a crude bracket pre-filter (cEDH skews expensive — §7), not the
    estimate itself.
    """
    rows = list(table)
    if min_price is not None:
        rows = [row for row in rows if _price(row) >= min_price]
    if max_price is not None:
        rows = [row for row in rows if _price(row) <= max_price]
    rows.sort(key=lambda row: row.get("savedate", ""), reverse=True)
    return [row["urlhash"] for row in rows if row.get("urlhash")]


def _price(row: dict) -> float:
    try:
        return float(row.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0
