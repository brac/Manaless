"""scryfall_client — enrichment parsing (normal, DFC fallback, split), 404, cache."""

import json

import httpx
import pytest

from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.scryfall_client import (
    ScryfallCardNotFound,
    autocomplete_names,
    get_card_metadata,
    get_collection,
    search_commanders,
)


def _http(tmp_path, handler) -> HttpClient:
    return HttpClient(
        DiskCache(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        host_delays={},
        default_delay=0.0,
    )


NORMAL = {
    "name": "Sol Ring",
    "type_line": "Artifact",
    "oracle_text": "{T}: Add {C}{C}.",
    "cmc": 1.0,
    "color_identity": [],
    "image_uris": {"normal": "https://img/solring.jpg"},
    "scryfall_uri": "https://scryfall.com/card/sol-ring",
}

# A transforming DFC: no top-level image_uris / oracle_text / type_line.
DFC = {
    "name": "Jace, Vryn's Prodigy // Jace, Telepath Unbound",
    "cmc": 2.0,
    "color_identity": ["U"],
    "scryfall_uri": "https://scryfall.com/card/jace",
    "card_faces": [
        {"type_line": "Legendary Creature — Human Wizard", "oracle_text": "FRONT", "image_uris": {"normal": "https://img/jace-front.jpg"}},
        {"type_line": "Legendary Planeswalker — Jace", "oracle_text": "BACK", "image_uris": {"normal": "https://img/jace-back.jpg"}},
    ],
}


def test_parses_normal_card(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json=NORMAL))
    card = get_card_metadata(http, "Sol Ring")
    assert card.name == "Sol Ring"
    assert card.type_line == "Artifact"
    assert card.mana_value == 1.0
    assert card.image_url == "https://img/solring.jpg"
    assert card.is_dfc is False
    assert card.color_identity == ()


def test_dfc_falls_back_to_front_face_image_and_concatenates_oracle(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json=DFC))
    card = get_card_metadata(http, "Jace, Vryn's Prodigy")
    assert card.is_dfc is True
    assert card.image_url == "https://img/jace-front.jpg"  # face 0
    assert "FRONT" in card.oracle_text and "BACK" in card.oracle_text
    assert card.type_line == "Legendary Creature — Human Wizard"
    assert card.color_identity == ("U",)


def test_missing_card_raises_not_found(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(404, json={"object": "error"}))
    with pytest.raises(ScryfallCardNotFound):
        get_card_metadata(http, "Definitely Not A Card")


def test_result_is_cached_by_name(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=NORMAL)

    http = _http(tmp_path, handler)
    get_card_metadata(http, "Sol Ring")
    get_card_metadata(http, "Sol Ring")
    assert calls["n"] == 1


# --- batch cards/collection enrichment ------------------------------------


def _collection_handler(by_name, not_found_names=()):
    """A MockTransport handler that answers a cards/collection POST."""

    def handler(request):
        identifiers = json.loads(request.content)["identifiers"]
        requested = [i["name"] for i in identifiers]
        data = [by_name[n] for n in requested if n in by_name]
        not_found = [{"name": n} for n in requested if n in not_found_names]
        return httpx.Response(200, json={"data": data, "not_found": not_found})

    return handler


def test_get_collection_batches_and_matches_by_name(tmp_path):
    http = _http(tmp_path, _collection_handler({"Sol Ring": NORMAL}))
    by_name, not_found = get_collection(http, ["Sol Ring"])
    assert not_found == []
    assert by_name["Sol Ring"].type_line == "Artifact"


def test_get_collection_matches_dfc_by_front_face(tmp_path):
    # Request the front-face name; Scryfall returns "Front // Back".
    http = _http(tmp_path, _collection_handler({"Jace, Vryn's Prodigy": DFC}))
    by_name, not_found = get_collection(http, ["Jace, Vryn's Prodigy"])
    card = by_name["Jace, Vryn's Prodigy"]  # keyed by REQUESTED name, not returned
    assert card.is_dfc is True
    assert "FRONT" in card.oracle_text


def test_get_collection_reports_not_found(tmp_path):
    handler = _collection_handler({"Sol Ring": NORMAL}, not_found_names={"Nope"})
    http = _http(tmp_path, handler)
    by_name, not_found = get_collection(http, ["Sol Ring", "Nope"])
    assert "Sol Ring" in by_name
    assert not_found == ["Nope"]


def test_get_collection_reuses_per_name_cache_and_skips_request(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _collection_handler({"Sol Ring": NORMAL})(request)

    http = _http(tmp_path, handler)
    get_collection(http, ["Sol Ring"])
    get_collection(http, ["Sol Ring"])  # served from the per-name cache
    assert calls["n"] == 1


def test_get_collection_cache_is_shared_with_get_card_metadata(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _collection_handler({"Sol Ring": NORMAL})(request)

    http = _http(tmp_path, handler)
    get_collection(http, ["Sol Ring"])
    card = get_card_metadata(http, "Sol Ring")  # no network: batch already cached it
    assert card.name == "Sol Ring"
    assert calls["n"] == 1


def test_get_collection_chunks_over_75(tmp_path):
    names = [f"Card {i}" for i in range(80)]
    catalog = {n: {**NORMAL, "name": n} for n in names}
    batch_sizes = []

    def handler(request):
        ids = json.loads(request.content)["identifiers"]
        batch_sizes.append(len(ids))
        return _collection_handler(catalog)(request)

    http = _http(tmp_path, handler)
    by_name, not_found = get_collection(http, names)
    assert len(by_name) == 80 and not_found == []
    assert batch_sizes == [75, 5]  # split into 75 + 5, never exceeding the cap


# --- autocomplete (E6) ----------------------------------------------------


def test_autocomplete_returns_names(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json={"data": ["Counterspell", "Counterflux"]}))
    assert autocomplete_names(http, "counter") == ["Counterspell", "Counterflux"]


def test_autocomplete_short_query_skips_request(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"data": []})

    http = _http(tmp_path, handler)
    assert autocomplete_names(http, "c") == []  # < 2 chars
    assert calls["n"] == 0  # never hit the network


def test_autocomplete_is_cached_by_query(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json={"data": ["Sol Ring"]})

    http = _http(tmp_path, handler)
    autocomplete_names(http, "sol")
    autocomplete_names(http, "SOL")  # same case-folded key -> served from cache
    assert calls["n"] == 1


# --- commander search (E2/E5) ---------------------------------------------


def _search_page(names, has_more=False, total=None):
    return {
        "data": [{"name": n} for n in names],
        "has_more": has_more,
        "total_cards": total if total is not None else len(names),
    }


def test_search_commanders_parses_names_and_paging(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json=_search_page(
        ["Atraxa, Praetors' Voice", "Edgar Markov"], has_more=True, total=42)))
    result = search_commanders(http, "atra", page=1)
    assert result.names == ("Atraxa, Praetors' Voice", "Edgar Markov")
    assert result.has_more is True
    assert result.total == 42


def test_search_commanders_sends_commander_filter_and_order(tmp_path):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_search_page(["X"]))

    http = _http(tmp_path, handler)
    search_commanders(http, "dragons", page=2)
    assert "is%3Acommander" in seen["url"] or "is:commander" in seen["url"]
    assert "order=edhrec" in seen["url"]
    assert "page=2" in seen["url"]


def test_search_commanders_404_is_empty_page(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(404, json={"object": "error"}))
    result = search_commanders(http, "zzzznotacommander")
    assert result.names == () and result.has_more is False and result.total == 0
