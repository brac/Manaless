"""HttpClient: cache short-circuit, host->limiter selection, and HTTP error raise.

Uses httpx.MockTransport so no real network is touched.
"""

import httpx
import pytest

from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient, _retry_after_seconds


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


def test_retries_on_429_then_succeeds(tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"ok": True})

    client = _client(tmp_path, handler)
    assert client.get_json("https://api.scryfall.com/cards/named?exact=Sol+Ring") == {"ok": True}
    assert calls["n"] == 2  # one 429, one success


def test_gives_up_after_max_429_retries(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={})

    client = _client(tmp_path, handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://api.scryfall.com/x")


def test_post_json_sends_body_and_parses_response(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["method"] = request.method
        return httpx.Response(200, json={"data": []})

    client = _client(tmp_path, handler)
    result = client.post_json("https://api.scryfall.com/cards/collection", {"identifiers": []})

    assert seen["method"] == "POST"
    assert b"identifiers" in seen["body"]
    assert result == {"data": []}


def test_known_hosts_get_their_configured_limiter(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json={}))

    edhrec = client._limiter_for("https://json.edhrec.com/pages/decks/x.json")
    scryfall = client._limiter_for("https://api.scryfall.com/cards/named")
    unknown = client._limiter_for("https://example.com/x")

    assert edhrec is not scryfall
    assert unknown is client._default_limiter


def test_both_edhrec_hosts_share_one_limiter(tmp_path):
    # json.edhrec.com and edhrec.com are one service: interleaved traffic must
    # share a single limiter so the combined cadence honours the 0.80s promise.
    client = _client(tmp_path, lambda r: httpx.Response(200, json={}))
    a = client._limiter_for("https://json.edhrec.com/pages/decks/x.json")
    b = client._limiter_for("https://edhrec.com/_next/data/B/deckpreview/x.json")
    assert a is b
    assert a is not client._limiter_for("https://api.scryfall.com/cards/named")


def test_injected_client_is_not_closed_on_exit(tmp_path):
    inner = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with HttpClient(DiskCache(tmp_path), client=inner):
        pass
    assert not inner.is_closed  # we don't own it, so we don't close it


def test_retry_after_delta_seconds_is_clamped():
    def resp(value):
        return httpx.Response(429, headers={"Retry-After": value})

    assert _retry_after_seconds(resp("5")) == 5.0
    assert _retry_after_seconds(resp("86400")) == 30.0  # clamped to the ceiling


def test_retry_after_http_date_form_is_parsed_and_clamped():
    def resp(value):
        return httpx.Response(429, headers={"Retry-After": value})

    assert _retry_after_seconds(resp("Wed, 21 Oct 2099 07:28:00 GMT")) == 30.0  # far future -> ceiling
    assert _retry_after_seconds(resp("Wed, 21 Oct 2000 07:28:00 GMT")) == 0.0   # past -> floor


def test_retry_after_missing_or_garbage_uses_fallback():
    assert _retry_after_seconds(httpx.Response(429)) == 1.0
    assert _retry_after_seconds(httpx.Response(429, headers={"Retry-After": "soon"})) == 1.0
