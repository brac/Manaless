"""EdhrecClient — build-id scraping, deck-table/decklist parsing, runbook retry.

All deterministic via httpx.MockTransport; no live network. Rate limiting is
zeroed so the suite stays fast.
"""

import httpx
import pytest

from manaless.edhrec_client import (
    EdhrecBuildIdError,
    EdhrecClient,
    EdhrecDeckNotFound,
    filter_deck_hashes,
)
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient


def _client(tmp_path, handler) -> EdhrecClient:
    http = HttpClient(
        DiskCache(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        host_delays={},
        default_delay=0.0,
    )
    return EdhrecClient(http)


def _manifest_html(build_id: str) -> str:
    return f'<script src="/_next/static/{build_id}/_buildManifest.js"></script>'


def _is_homepage(url: str) -> bool:
    return "_next/data" not in url and url.startswith("https://edhrec.com")


# --- build id -------------------------------------------------------------

def test_build_id_from_manifest_path(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, text=_manifest_html("BUILD123")))
    assert client.build_id() == "BUILD123"


def test_build_id_from_next_data_fallback(tmp_path):
    html = '<script id="__NEXT_DATA__">{"buildId":"NEXT456","props":{}}</script>'
    client = _client(tmp_path, lambda r: httpx.Response(200, text=html))
    assert client.build_id() == "NEXT456"


def test_build_id_missing_raises(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, text="<html>no build id</html>"))
    with pytest.raises(EdhrecBuildIdError):
        client.build_id()


def test_build_id_scraped_once_per_session(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, text=_manifest_html("B"))

    client = _client(tmp_path, handler)
    client.build_id()
    client.build_id()
    assert calls["n"] == 1


# --- deck table -----------------------------------------------------------

def test_fetch_deck_table_returns_rows(tmp_path):
    table = {"table": [{"urlhash": "aaa", "savedate": "2026-06-01", "price": 250}]}
    client = _client(tmp_path, lambda r: httpx.Response(200, json=table))
    assert client.fetch_deck_table("Atraxa, Praetors' Voice") == table["table"]


def test_fetch_deck_table_empty_when_no_table_key(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json={}))
    assert client.fetch_deck_table("Obscure Commander") == []


@pytest.mark.parametrize("status", [403, 404])
def test_fetch_deck_table_treats_missing_page_as_no_decks(tmp_path, status):
    # json.edhrec.com 403s on a slug with no deck page; that is the §5 signal.
    client = _client(tmp_path, lambda r: httpx.Response(status))
    assert client.fetch_deck_table("Nonexistent Commander Xyz") == []


def test_fetch_deck_table_reraises_other_errors(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_deck_table("Atraxa, Praetors' Voice")


# --- decklist + runbook retry --------------------------------------------

def test_fetch_deck_parses_flat_list(tmp_path):
    deck = {"pageProps": {"data": {"deck": ["1 Sol Ring", "1 Atraxa, Praetors' Voice"]}}}

    def handler(request):
        url = str(request.url)
        if _is_homepage(url):
            return httpx.Response(200, text=_manifest_html("BUILD123"))
        return httpx.Response(200, json=deck)

    client = _client(tmp_path, handler)
    assert client.fetch_deck("xyz") == ["1 Sol Ring", "1 Atraxa, Praetors' Voice"]


def test_fetch_deck_refreshes_build_id_on_404(tmp_path):
    """A 404 means the build id rotated: refresh once, then succeed."""
    state = {"scrapes": 0}
    deck = {"pageProps": {"data": {"deck": ["1 Sol Ring"]}}}

    def handler(request):
        url = str(request.url)
        if _is_homepage(url):
            state["scrapes"] += 1
            build_id = "STALE" if state["scrapes"] == 1 else "FRESH"
            return httpx.Response(200, text=_manifest_html(build_id))
        if "/_next/data/FRESH/" in url:
            return httpx.Response(200, json=deck)
        return httpx.Response(404)

    client = _client(tmp_path, handler)
    assert client.fetch_deck("xyz") == ["1 Sol Ring"]
    assert state["scrapes"] == 2  # refreshed exactly once


def test_fetch_deck_gives_up_after_refresh(tmp_path):
    def handler(request):
        url = str(request.url)
        if _is_homepage(url):
            return httpx.Response(200, text=_manifest_html("B"))
        return httpx.Response(404)

    client = _client(tmp_path, handler)
    with pytest.raises(EdhrecDeckNotFound):
        client.fetch_deck("xyz")


# --- selection helper -----------------------------------------------------

def test_filter_deck_hashes_sorts_recent_first_and_bands_price():
    table = [
        {"urlhash": "old", "savedate": "2025-01-01", "price": 100},
        {"urlhash": "new", "savedate": "2026-06-01", "price": 500},
        {"urlhash": "mid", "savedate": "2026-01-01", "price": 1000},
    ]
    assert filter_deck_hashes(table) == ["new", "mid", "old"]
    assert filter_deck_hashes(table, max_price=600) == ["new", "old"]
    assert filter_deck_hashes(table, min_price=200) == ["new", "mid"]


def test_filter_deck_hashes_skips_rows_without_urlhash():
    table = [{"savedate": "2026-06-01"}, {"urlhash": "ok", "savedate": "2026-05-01"}]
    assert filter_deck_hashes(table) == ["ok"]
