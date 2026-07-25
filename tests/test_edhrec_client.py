"""EdhrecClient — build-id scraping, deck-table/decklist parsing, runbook retry.

All deterministic via httpx.MockTransport; no live network. Rate limiting is
zeroed so the suite stays fast.
"""

import httpx
import pytest

from manaless.edhrec_client import (
    CardPopularity,
    EdhrecBlocked,
    EdhrecBuildIdError,
    EdhrecClient,
    EdhrecDeckNotFound,
    EdhrecError,
    PopularityIndex,
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


# --- commander card popularity -------------------------------------------

def _commander_page() -> dict:
    return {
        "container": {
            "json_dict": {
                "cardlists": [
                    # "New Cards" uses a smaller recent-decks denominator (100)...
                    {"header": "New Cards", "cardviews": [
                        {"name": "Sol Ring", "num_decks": 90, "potential_decks": 100, "synergy": 0.1},
                    ]},
                    # ...the main list uses the real denominator (1000) -> 85%.
                    {"header": "Mana Artifacts", "cardviews": [
                        {"name": "Sol Ring", "num_decks": 850, "potential_decks": 1000, "synergy": -0.02},
                    ]},
                    {"header": "Instants", "cardviews": [
                        {"name": "Counterspell", "num_decks": 370, "potential_decks": 1000},
                        {"name": "", "num_decks": 5, "potential_decks": 1000},  # skipped: no name
                    ]},
                ]
            }
        }
    }


def test_commander_stats_inclusion_percent_and_denominator(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json=_commander_page()))
    stats = client.fetch_commander_card_stats("Atraxa, Praetors' Voice")
    sol = stats.get("Sol Ring")
    assert sol.percent == 85.0  # picks potential_decks=1000, not the New-Cards 100
    assert sol.num_decks == 850
    assert round(stats.get("counterspell").percent) == 37  # case-insensitive lookup
    assert len(stats) == 2  # the unnamed cardview is dropped


def test_commander_stats_dfc_front_face_lookup(tmp_path):
    page = {"container": {"json_dict": {"cardlists": [
        {"header": "Top", "cardviews": [{"name": "Valki, God of Lies", "num_decks": 10, "potential_decks": 100}]},
    ]}}}
    client = _client(tmp_path, lambda r: httpx.Response(200, json=page))
    stats = client.fetch_commander_card_stats("X")
    assert stats.get("Valki, God of Lies // Tibalt, Cosmic Impostor") is not None


def test_commander_stats_empty_when_page_missing_404(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(404))
    stats = client.fetch_commander_card_stats("Obscure Commander")
    assert not stats and len(stats) == 0


def test_commander_stats_403_raises_blocked(tmp_path):
    # A 403 here is a WAF/rate ban, not an empty commander — it must surface.
    client = _client(tmp_path, lambda r: httpx.Response(403))
    with pytest.raises(EdhrecBlocked):
        client.fetch_commander_card_stats("Atraxa, Praetors' Voice")


# --- top commanders (popular browse ranking) -----------------------------

def _top_commanders_page() -> dict:
    return {"container": {"json_dict": {"cardlists": [
        {"header": "Past 2 Years", "cardviews": [
            {"name": "The Ur-Dragon", "num_decks": 48385},
            {"name": "Edgar Markov", "num_decks": 47842},
            {"name": "The Ur-Dragon", "num_decks": 48385},  # dupe: kept once
            {"name": "", "num_decks": 9},                    # skipped: no name
        ]},
    ]}}}


def test_fetch_top_commanders_ranked_and_deduped(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(200, json=_top_commanders_page()))
    top = client.fetch_top_commanders()
    assert [c.name for c in top] == ["The Ur-Dragon", "Edgar Markov"]  # order preserved, deduped
    assert top[0].num_decks == 48385


def test_fetch_top_commanders_empty_when_no_page_404(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(404))
    assert client.fetch_top_commanders() == []


def test_fetch_top_commanders_403_raises_blocked(tmp_path):
    client = _client(tmp_path, lambda r: httpx.Response(403))
    with pytest.raises(EdhrecBlocked):
        client.fetch_top_commanders()


def test_popularity_excluding_filters_deck_and_sorts_by_usage():
    idx = PopularityIndex({
        "sol ring": CardPopularity("Sol Ring", 900, 1000),
        "smothering tithe": CardPopularity("Smothering Tithe", 600, 1000),
        "counterspell": CardPopularity("Counterspell", 370, 1000),
    })
    out = idx.excluding(["counterspell"])  # case-insensitive exclusion
    assert [c.name for c in out] == ["Sol Ring", "Smothering Tithe"]  # most-played first


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


def test_fetch_deck_refreshes_build_id_on_html_body(tmp_path):
    """A stale _next/data URL 200-redirects to HTML: parse failure -> refresh once."""
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
        return httpx.Response(200, text="<!doctype html><html>login wall</html>")  # not JSON

    client = _client(tmp_path, handler)
    assert client.fetch_deck("xyz") == ["1 Sol Ring"]
    assert state["scrapes"] == 2  # refreshed exactly once


def test_fetch_deck_soft_404_is_evicted_and_recovers(tmp_path):
    """An HTTP-200 soft-404 must raise AND drop its cache entry (no stale replay)."""
    state = {"good": False}
    good_deck = {"pageProps": {"data": {"deck": ["1 Sol Ring"]}}}

    def handler(request):
        url = str(request.url)
        if _is_homepage(url):
            return httpx.Response(200, text=_manifest_html("BUILD"))
        if state["good"]:
            return httpx.Response(200, json=good_deck)
        return httpx.Response(200, json={"pageProps": {}})  # soft-404 shape

    client = _client(tmp_path, handler)
    with pytest.raises(EdhrecError):
        client.fetch_deck("xyz")
    # the poisoned entry was evicted, not left to shadow later good fetches
    assert client._http.cache.get("edhrec-decklist", "xyz") is None
    state["good"] = True
    assert client.fetch_deck("xyz") == ["1 Sol Ring"]


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


def test_filter_deck_hashes_treats_missing_price_as_unknown():
    # A row without a numeric price is unknown, not $0: it survives BOTH bounds (D14).
    table = [
        {"urlhash": "priced", "savedate": "2026-06-01", "price": 100},
        {"urlhash": "nopriced", "savedate": "2026-05-01"},  # no price field
    ]
    assert "nopriced" in filter_deck_hashes(table, min_price=50)   # not excluded as $0
    assert "nopriced" in filter_deck_hashes(table, max_price=50)   # still included
    assert "priced" not in filter_deck_hashes(table, max_price=50)  # real price filtered


def test_filter_deck_hashes_handles_null_savedate():
    # A stored ``"savedate": null`` must not crash the sort (None < str); nulls last.
    table = [
        {"urlhash": "dated", "savedate": "2026-01-01"},
        {"urlhash": "nulldate", "savedate": None},
    ]
    assert filter_deck_hashes(table) == ["dated", "nulldate"]


# --- average composition (commander page scalars + curve) -----------------
# Same page as fetch_commander_card_stats, so a commander costs one fetch.


def _page(**over):
    """A commander page carrying the composition scalars, shaped like the real one."""
    data = {
        "creature": 24, "instant": 10, "sorcery": 8, "artifact": 9,
        "enchantment": 7, "battle": 0, "planeswalker": 6, "land": 35,
        "basic": 12, "nonbasic": 23,
        "panels": {"mana_curve": {"0": 1, "1": 8, "2": 18, "7": 1}},
        "container": {"json_dict": {"cardlists": []}},
    }
    data.update(over)
    return data


def test_fetch_commander_average_parses_types_and_curve(tmp_path):
    c = _client(tmp_path, lambda r: httpx.Response(200, json=_page()))
    avg = c.fetch_commander_average("Atraxa, Praetors' Voice")
    assert avg.types == {
        "Creature": 24, "Planeswalker": 6, "Battle": 0, "Instant": 10,
        "Sorcery": 8, "Artifact": 9, "Enchantment": 7, "Land": 35,
    }
    assert avg.curve == {0: 1, 1: 8, 2: 18, 7: 1}  # keys coerced to int
    assert (avg.basics, avg.nonbasics) == (12, 23)


def test_average_and_popularity_share_one_fetch(tmp_path):
    """The second reader must hit the disk cache, not the network."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=_page())

    c = _client(tmp_path, handler)
    c.fetch_commander_card_stats("Atraxa, Praetors' Voice")
    c.fetch_commander_average("Atraxa, Praetors' Voice")
    assert calls["n"] == 1


def test_fetch_commander_average_returns_none_when_no_page(tmp_path):
    c = _client(tmp_path, lambda r: httpx.Response(404, json={}))
    assert c.fetch_commander_average("Nobody") is None


def test_fetch_commander_average_returns_none_without_scalars(tmp_path):
    """A page shaped unexpectedly reads as "no baseline", not a bogus all-zero one."""
    page = {"container": {"json_dict": {"cardlists": []}}}
    c = _client(tmp_path, lambda r: httpx.Response(200, json=page))
    assert c.fetch_commander_average("Weird") is None


def test_fetch_commander_average_survives_a_junk_curve(tmp_path):
    c = _client(tmp_path, lambda r: httpx.Response(
        200, json=_page(panels={"mana_curve": {"2": 18, "x": 3, "4": "n/a"}})))
    avg = c.fetch_commander_average("Atraxa, Praetors' Voice")
    assert avg.curve == {2: 18}  # unparseable buckets skipped, types still returned
    assert avg.types["Land"] == 35


def test_fetch_commander_average_403_still_raises_blocked(tmp_path):
    c = _client(tmp_path, lambda r: httpx.Response(403, json={}))
    with pytest.raises(EdhrecBlocked):
        c.fetch_commander_average("Atraxa, Praetors' Voice")
