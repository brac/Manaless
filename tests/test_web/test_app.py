"""web.app — route smoke tests via FastAPI TestClient, deps overridden by fakes.

No live network: EDHREC + enrichment are fakes (mirroring test_deck_builder), and
the Spellbook calls inside web.readout are monkeypatched. Engines run for real.
"""

import pytest
from fastapi.testclient import TestClient

import manaless.web.readout as readout_mod
from manaless.collection import Collection
from manaless.edhrec_client import CardPopularity, PopularityIndex
from manaless.scryfall_client import ScryfallCard
from manaless.spellbook_client import BracketEstimate, Combo, ComboResults
from manaless.scryfall_client import CommanderSearch
from manaless.web.app import (
    app,
    get_autocomplete,
    get_collection_path,
    get_edhrec,
    get_enrich,
    get_http,
    get_owned,
    get_search,
)


class FakeEdhrec:
    def fetch_deck_table(self, commander):
        return [
            {"urlhash": "newest", "savedate": "2026-06-27", "price": 420, "bracket": 3, "salt": 20.0},
            {"urlhash": "cheap", "savedate": "2025-01-01", "price": 50, "bracket": 2, "salt": 5.0},
            {"urlhash": "pricey", "savedate": "2025-06-01", "price": 900, "bracket": 4, "salt": 80.0},
        ]

    def fetch_deck(self, deck_id):
        return ["1 Atraxa, Praetors' Voice", "1 Sol Ring", "1 Counterspell"]

    def fetch_commander_card_stats(self, commander):
        return PopularityIndex({
            "sol ring": CardPopularity("Sol Ring", 85, 100, -0.02),  # in the deck (85%)
            "smothering tithe": CardPopularity("Smothering Tithe", 60, 100, -0.1),  # not in deck
            "rhystic study": CardPopularity("Rhystic Study", 55, 100, 0.2),  # not in deck
        })


def _meta(name):
    tl = "Legendary Creature" if "Atraxa" in name else "Artifact"
    return ScryfallCard(
        name=name, type_line=tl, oracle_text=f"text of {name}", mana_value=1.0,
        color_identity=(), image_url=f"http://img/{name}.png", scryfall_uri=None, is_dfc=False,
    )


def _enrich(names):
    return {n: _meta(n) for n in names if n != "Bogus Card"}


# A tiny fake commander pool, EDHREC-ranked, paged 2-per-page so tests can walk
# pagination without needing 60+ names.
_COMMANDERS = ["Atraxa, Praetors' Voice", "Edgar Markov", "The Ur-Dragon", "Yuriko"]


def _fake_search(query, page):
    pool = [c for c in _COMMANDERS if query.casefold() in c.casefold()] if query else _COMMANDERS
    start = (page - 1) * 2
    window = pool[start : start + 2]
    return CommanderSearch(names=tuple(window), has_more=start + 2 < len(pool), total=len(pool))


def _fake_autocomplete(query):
    return [c for c in ["Counterspell", "Counterflux", "Sol Ring"] if query.casefold() in c.casefold()]


@pytest.fixture
def owned():
    """The owned-cards Collection the app sees; tests may mutate it before building."""
    return Collection()


@pytest.fixture
def client(monkeypatch, tmp_path, owned):
    monkeypatch.setattr(readout_mod, "find_my_combos", lambda http, deck: ComboResults("WUBRG", (), ()))
    monkeypatch.setattr(
        readout_mod, "estimate_bracket", lambda http, deck: BracketEstimate(tag="C", cards=(), combos=())
    )
    app.dependency_overrides[get_http] = lambda: None
    app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()
    app.dependency_overrides[get_enrich] = lambda: _enrich
    app.dependency_overrides[get_owned] = lambda: owned
    app.dependency_overrides[get_collection_path] = lambda: tmp_path / "collection.json"
    app.dependency_overrides[get_search] = lambda: _fake_search
    app.dependency_overrides[get_autocomplete] = lambda: _fake_autocomplete
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _build(client):
    return client.post("/build", data={"commander": "Atraxa, Praetors' Voice", "deck_id": "newest"})


def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Manaless" in r.text


def test_decks_picker_lists_rows(client):
    r = client.get("/decks", params={"commander": "Atraxa, Praetors' Voice"})
    assert r.status_code == 200
    assert "newest" in r.text  # the deck_id is in the Build form
    assert "Build" in r.text


def _order(text, *needles):
    return [text.index(n) for n in needles]


def test_decks_default_sort_is_newest(client):
    r = client.get("/decks", params={"commander": "X"})
    a, b, c = _order(r.text, "newest", "pricey", "cheap")  # 2026, 2025-06, 2025-01
    assert a < b < c


def test_decks_sort_by_price_low_to_high(client):
    r = client.get("/decks", params={"commander": "X", "sort": "price_low"})
    cheap, newest, pricey = _order(r.text, "cheap", "newest", "pricey")  # 50, 420, 900
    assert cheap < newest < pricey


def test_decks_sort_by_bracket_high(client):
    r = client.get("/decks", params={"commander": "X", "sort": "bracket_high"})
    pricey, newest, cheap = _order(r.text, "pricey", "newest", "cheap")  # 4, 3, 2
    assert pricey < newest < cheap


def test_decks_sort_dropdown_offers_options(client):
    r = client.get("/decks", params={"commander": "X", "sort": "salt_high"})
    assert 'name="sort"' in r.text
    assert "Saltiest" in r.text and "Price: low" in r.text
    assert 'value="salt_high" selected' in r.text  # current sort preserved


def test_decks_unknown_sort_falls_back_to_recent(client):
    r = client.get("/decks", params={"commander": "X", "sort": "bogus"})
    assert r.status_code == 200
    a, b, c = _order(r.text, "newest", "pricey", "cheap")
    assert a < b < c


def test_build_creates_session_and_renders_readouts(client):
    r = _build(client)
    assert r.status_code == 200
    assert "Sol Ring" in r.text
    assert "Bracket" in r.text and "Win conditions" in r.text
    assert client.cookies.get("manaless_sid")  # session cookie set


def test_build_shows_card_popularity(client):
    r = _build(client)
    assert "85%" in r.text  # Sol Ring inclusion from the commander page
    assert "EDHREC decks for this commander" in r.text  # the popularity bar tooltip


def test_build_shows_substitution_palette(client):
    r = _build(client)
    assert "Popular cards to add" in r.text
    assert "Smothering Tithe" in r.text  # popular + not in deck -> offered


def test_palette_drops_card_once_added(client):
    _build(client)
    r = client.post("/build/add", data={"name": "Smothering Tithe"})
    assert "Smothering Tithe" in r.text  # now in the card list
    # palette is OOB-swapped and recomputed; the added card no longer appears as an
    # add suggestion (its only other mention would be the palette button).
    assert "Popular cards to add" in r.text
    assert r.text.count("+ Smothering Tithe") == 0


def test_substitute_returns_updated_fragment(client):
    _build(client)
    r = client.post("/build/substitute", data={"old_name": "Sol Ring", "new_name": "Arcane Signet"})
    assert r.status_code == 200
    assert "Arcane Signet" in r.text
    # Sol Ring is gone from the card list (its swap form carried value="Sol Ring");
    # it may still appear as a palette suggestion now that it's no longer in the deck.
    assert 'value="Sol Ring"' not in r.text
    assert 'id="readouts"' in r.text and 'hx-swap-oob' in r.text  # OOB readouts update


def test_substitute_unresolvable_card_flashes_but_keeps_it(client):
    _build(client)
    r = client.post("/build/substitute", data={"old_name": "Sol Ring", "new_name": "Bogus Card"})
    assert r.status_code == 200
    assert "Bogus Card" in r.text
    assert "resolve on Scryfall" in r.text  # flash banner (apostrophes are HTML-escaped)


def test_add_card_from_suggestion(client):
    _build(client)
    r = client.post("/build/add", data={"name": "Thassa's Oracle"})
    assert r.status_code == 200
    assert "Thassa" in r.text and "Oracle" in r.text  # apostrophe HTML-escaped in markup


def test_remove_card(client):
    _build(client)
    r = client.post("/build/remove", data={"name": "Counterspell"})
    assert r.status_code == 200
    assert "Counterspell" not in r.text


def test_export_dck_is_attachment(client):
    _build(client)
    r = client.get("/build/export.dck")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert ".dck" in r.headers["content-disposition"]
    assert "[XXX:0] Sol Ring" in r.text
    assert "SB: 1 [XXX:0] Atraxa, Praetors' Voice" in r.text


def test_edit_without_session_redirects_home(client):
    # fresh client state: no cookie -> substitute should bounce to /
    client.cookies.clear()
    r = client.post("/build/substitute", data={"old_name": "X", "new_name": "Y"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


# --- step 5: single-card buy button -------------------------------------

def test_build_shows_tcgplayer_buy_links(client):
    r = _build(client)
    assert "tcgplayer.com/massentry" in r.text  # per-card buy link present


# --- collection import + owned flagging ---------------------------------

def test_collection_page_renders(client):
    r = client.get("/collection")
    assert r.status_code == 200
    assert "collection" in r.text.lower()


def test_import_collection_csv_persists_and_reports(client, tmp_path):
    csv = b"Name,Quantity\nSol Ring,2\nCounterspell,1\n"
    r = client.post("/collection/import", files={"file": ("export.csv", csv, "text/csv")})
    assert r.status_code == 200
    assert "Imported 2 cards" in r.text  # distinct count
    assert (tmp_path / "collection.json").exists()  # persisted to the injected path


def test_import_bad_csv_shows_error_not_500(client):
    r = client.post("/collection/import", files={"file": ("bad.csv", b"Foo,Bar\n1,2\n", "text/csv")})
    assert r.status_code == 200
    assert "No card-name column" in r.text  # the error surfaces (apostrophes are HTML-escaped)


def test_owned_cards_flagged_in_builder(client, owned):
    owned.add("Sol Ring", 1)  # mutate the Collection the app sees
    r = _build(client)
    assert "✓ owned" in r.text
    assert "You own" in r.text and "1</strong> of 2" in r.text


# --- step 6: deck-diff buy ----------------------------------------------

def test_buy_missing_lists_unowned_and_links_to_tcgplayer(client, owned):
    owned.add("Sol Ring", 1)  # own one of the two mainboard cards
    _build(client)
    r = client.get("/build/buy-missing")
    assert r.status_code == 200
    assert "Counterspell" in r.text          # unowned -> listed
    assert "Sol Ring" not in r.text          # owned -> excluded
    assert "tcgplayer.com/massentry" in r.text  # buy-all link present


def test_buy_missing_when_owning_whole_deck(client, owned):
    for name in ("Atraxa, Praetors' Voice", "Sol Ring", "Counterspell"):
        owned.add(name, 1)
    _build(client)
    r = client.get("/build/buy-missing")
    assert "own the whole deck" in r.text.lower()
    assert "tcgplayer.com/massentry" not in r.text  # no link when nothing to buy


def test_buy_missing_without_session_redirects_home(client):
    client.cookies.clear()
    r = client.get("/build/buy-missing", follow_redirects=False)
    assert r.status_code == 303


# --- B1/B2: card count re-renders on every edit -------------------------

def test_build_shows_card_count(client):
    r = _build(client)
    assert 'id="cardcount"' in r.text
    assert "3 cards" in r.text  # commander + Sol Ring + Counterspell


def test_edit_oob_swaps_the_card_count(client):
    _build(client)
    r = client.post("/build/add", data={"name": "Smothering Tithe"})
    # count fragment is in the edit response, marked for OOB swap, and reflects +1
    assert 'id="cardcount"' in r.text and "hx-swap-oob" in r.text
    assert "4 cards" in r.text


def test_remove_decrements_card_count(client):
    _build(client)
    r = client.post("/build/remove", data={"name": "Counterspell"})
    assert "2 cards" in r.text


# --- B3: adds/subs are made obvious with a toast ------------------------

def test_add_shows_added_toast(client):
    _build(client)
    r = client.post("/build/add", data={"name": "Smothering Tithe"})
    assert "Added Smothering Tithe" in r.text
    assert 'class="flash ok"' in r.text  # success styling, not a warning


def test_substitute_shows_swapped_toast(client):
    _build(client)
    r = client.post("/build/substitute", data={"old_name": "Sol Ring", "new_name": "Arcane Signet"})
    assert "Swapped in Arcane Signet" in r.text


# --- E3: commander listed first in the builder --------------------------

def test_commander_listed_first_in_builder(client):
    r = _build(client)
    assert "★ commander" in r.text  # commander tile marker present
    # the commander appears before the mainboard cards in the list
    assert r.text.index("Atraxa") < r.text.index("Sol Ring")


# --- E6: swap box carries autocomplete hook -----------------------------

def test_swap_input_has_autocomplete_attr(client):
    r = _build(client)
    assert 'data-autocomplete="card"' in r.text


# --- E2/E5: paginated commander browse + fuzzy search -------------------

def test_commanders_lists_popular(client):
    r = client.get("/commanders")
    assert r.status_code == 200
    assert "Atraxa" in r.text and "Edgar Markov" in r.text
    assert "/decks?commander=" in r.text  # each links to its deck picker


def test_commanders_search_filters(client):
    r = client.get("/commanders", params={"q": "dragon"})
    assert "The Ur-Dragon" in r.text
    assert "Edgar Markov" not in r.text  # filtered out by the query


def test_commanders_paginates(client):
    r1 = client.get("/commanders", params={"page": 1})
    assert "Atraxa" in r1.text and "next →" in r1.text
    r2 = client.get("/commanders", params={"page": 2})
    assert "The Ur-Dragon" in r2.text  # third commander lands on page 2
    assert "prev" in r2.text


def test_commanders_empty_result_shows_message(client):
    r = client.get("/commanders", params={"q": "zzznope"})
    assert "No commanders found" in r.text


# --- E5/E6: autocomplete JSON endpoint ----------------------------------

def test_api_autocomplete_card(client):
    r = client.get("/api/autocomplete", params={"q": "counter", "kind": "card"})
    assert r.status_code == 200
    assert r.json() == ["Counterspell", "Counterflux"]


def test_api_autocomplete_commander(client):
    r = client.get("/api/autocomplete", params={"q": "dragon", "kind": "commander"})
    assert r.json() == ["The Ur-Dragon"]


def test_api_autocomplete_empty_query(client):
    r = client.get("/api/autocomplete", params={"q": "", "kind": "card"})
    assert r.json() == []
