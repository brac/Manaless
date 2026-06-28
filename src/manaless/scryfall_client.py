"""Scryfall client — card enrichment (build step 1; CLAUDE.md §4).

`GET cards/named?exact={name}` → the fields the win-condition heuristic and
bracket evaluator need. DFC / split / transform cards have no top-level
`image_uris` / `oracle_text`; fall back to `card_faces` (image from face 0,
oracle text concatenated). Cached by exact card name forever — card data is
near-static.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from manaless.http.client import HttpClient

CACHE_NAMESPACE = "scryfall-card"
NAMED_URL = "https://api.scryfall.com/cards/named?exact={query}"
COLLECTION_URL = "https://api.scryfall.com/cards/collection"

# Scryfall's batch endpoint caps each request at 75 identifiers.
_COLLECTION_BATCH = 75
_DFC_NAME_SEP = " // "

# Scryfall asks clients to send an explicit Accept header (and a User-Agent,
# which HttpClient already sets).
_ACCEPT = {"Accept": "application/json;q=0.9,*/*;q=0.8"}

_FACE_ORACLE_JOIN = "\n//\n"


@dataclass(frozen=True, slots=True)
class ScryfallCard:
    """Enriched metadata for one card (DFC-flattened)."""

    name: str
    type_line: str
    oracle_text: str
    mana_value: float
    color_identity: tuple[str, ...]
    image_url: str | None
    scryfall_uri: str | None
    is_dfc: bool


class ScryfallError(RuntimeError):
    """Base class for Scryfall adapter failures."""


class ScryfallCardNotFound(ScryfallError):
    """Scryfall has no exact match for the given card name."""


def get_card_metadata(http: HttpClient, name: str) -> ScryfallCard:
    """Fetch + parse enrichment for one card by exact name (disk-cached)."""
    url = NAMED_URL.format(query=quote(name))
    try:
        data = http.get_json(
            url, cache_namespace=CACHE_NAMESPACE, cache_key=name, headers=_ACCEPT
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ScryfallCardNotFound(name) from exc
        raise
    return _parse_card(data)


def get_collection(
    http: HttpClient, names: Iterable[str]
) -> tuple[dict[str, ScryfallCard], list[str]]:
    """Enrich many cards in one shot via the batch ``cards/collection`` endpoint.

    Returns ``(by_name, not_found)`` keyed by the *requested* name. Per-name disk
    cache is read first (sharing the ``get_card_metadata`` cache), so only the
    misses hit the network — in chunks of 75. Cold cost drops from ~1 request per
    card to ~2 per deck, which is why a fresh build is fast.

    The endpoint returns cards whose ``name`` may differ from the request (a DFC
    comes back as ``"Front // Back"``) and order is not guaranteed, so each
    returned card is matched back to its requested name by exact or front-face
    compare. Unresolved names land in ``not_found``.
    """
    by_name: dict[str, ScryfallCard] = {}
    misses: list[str] = []
    for name in dict.fromkeys(names):  # de-dupe, preserve order
        cached = http.cache.get(CACHE_NAMESPACE, name)
        if cached is not None:
            by_name[name] = _parse_card(cached)
        else:
            misses.append(name)

    not_found: list[str] = []
    for start in range(0, len(misses), _COLLECTION_BATCH):
        batch = misses[start : start + _COLLECTION_BATCH]
        not_found.extend(_fetch_collection_batch(http, batch, by_name))
    return by_name, not_found


def _fetch_collection_batch(
    http: HttpClient, batch: Sequence[str], by_name: dict[str, ScryfallCard]
) -> list[str]:
    """Fetch one ≤75-name batch, populate ``by_name``, return the names not found."""
    body = {"identifiers": [{"name": name} for name in batch]}
    data = http.post_json(COLLECTION_URL, body, headers=_ACCEPT)

    wanted = {name.casefold(): name for name in batch}
    for raw in data.get("data", []):
        full = raw.get("name", "")
        front = full.split(_DFC_NAME_SEP, 1)[0]
        requested = wanted.get(full.casefold()) or wanted.get(front.casefold())
        if requested is None:
            continue  # unexpected extra card; ignore rather than mis-key it
        http.cache.set(CACHE_NAMESPACE, requested, raw)
        by_name[requested] = _parse_card(raw)

    # Scryfall echoes each unmatched identifier back verbatim ({"name": "..."}).
    return [nf.get("name", "") for nf in data.get("not_found", [])]


def _parse_card(data: dict) -> ScryfallCard:
    faces = data.get("card_faces") or []

    image = (data.get("image_uris") or {}).get("normal")
    if image is None and faces:
        image = (faces[0].get("image_uris") or {}).get("normal")

    oracle = data.get("oracle_text")
    if oracle is None and faces:
        oracle = _FACE_ORACLE_JOIN.join(f.get("oracle_text", "") for f in faces)

    type_line = data.get("type_line")
    if type_line is None and faces:
        type_line = faces[0].get("type_line", "")

    return ScryfallCard(
        name=data.get("name", ""),
        type_line=type_line or "",
        oracle_text=oracle or "",
        mana_value=float(data.get("cmc") or 0),
        color_identity=tuple(data.get("color_identity") or ()),
        image_url=image,
        scryfall_uri=data.get("scryfall_uri"),
        is_dfc=bool(faces),
    )
