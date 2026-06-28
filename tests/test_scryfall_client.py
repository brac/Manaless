"""scryfall_client — enrichment parsing (normal, DFC fallback, split), 404, cache."""

import httpx
import pytest

from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.scryfall_client import (
    ScryfallCardNotFound,
    get_card_metadata,
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
