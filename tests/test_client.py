"""HttpClient: cache short-circuit, host->limiter selection, and HTTP error raise.

Uses httpx.MockTransport so no real network is touched.
"""

import httpx
import pytest

from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient


def _client(tmp_path, handler) -> HttpClient:
    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport)
    return HttpClient(DiskCache(tmp_path), client=inner)


def test_get_json_fetches_then_caches(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    client = _client(tmp_path, handler)
    url = "https://api.scryfall.com/cards/named?exact=Sol+Ring"

    first = client.get_json(url, cache_namespace="scryfall-card", cache_key="Sol Ring")
    second = client.get_json(url, cache_namespace="scryfall-card", cache_key="Sol Ring")

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert calls["n"] == 1  # second call served from cache, no second request


def test_get_json_without_key_does_not_cache(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    client = _client(tmp_path, handler)
    url = "https://api.scryfall.com/x"
    client.get_json(url)
    client.get_json(url)

    assert calls["n"] == 2


def test_http_error_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = _client(tmp_path, handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://edhrec.com/_next/data/BUILD/deckpreview/x.json")


def test_known_hosts_get_their_configured_limiter(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json={}))

    edhrec = client._limiter_for("https://json.edhrec.com/pages/decks/x.json")
    scryfall = client._limiter_for("https://api.scryfall.com/cards/named")
    unknown = client._limiter_for("https://example.com/x")

    assert edhrec is not scryfall
    assert unknown is client._default_limiter
