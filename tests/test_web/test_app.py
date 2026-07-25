"""web.app — route smoke tests via FastAPI TestClient, deps overridden by fakes.

No live network: EDHREC + enrichment are fakes (mirroring test_deck_builder), and
the Spellbook calls inside web.readout are monkeypatched. Engines run for real.
"""

import pytest
from fastapi.testclient import TestClient

import manaless.web.readout as readout_mod
from manaless.collection import Collection
from manaless.edhrec_client import CardPopularity, PopularityIndex, TopCommander
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
            # Enriched but carries no USD price — keeps the "no price tag" path covered
            # on both the palette and the swap suggestions.
            "unpriced relic": CardPopularity("Unpriced Relic", 40, 100, 0.0),
        })

    def fetch_top_commanders(self):
        # EDHREC deck-count ranking (most-played first) + padding past one page.
        ranked = [
            ("The Ur-Dragon", 48385),
            ("Edgar Markov", 47842),
            ("Atraxa, Praetors' Voice", 42263),
        ]
        ranked += [(f"Cmdr {i}", 1000 - i) for i in range(4, 71)]  # 70 total -> page 2
        return [TopCommander(name=n, num_decks=d) for n, d in ranked]


# TCGplayer estimates for the fake pool. "Unpriced Relic" is deliberately absent, so
# the no-price fallback path stays covered.
_PRICES = {
    "Atraxa, Praetors' Voice": 32.50,
    "Sol Ring": 1.50,
    "Counterspell": 0.50,
    "Smothering Tithe": 25.00,   # pricier than Sol Ring -> "+$23.50" in the swap modal
    "Rhystic Study": 0.75,       # cheaper than Sol Ring -> "-$0.75"
}


def _meta(name):
    tl = "Legendary Creature" if "Atraxa" in name else "Artifact"
    return ScryfallCard(
        name=name, type_line=tl, oracle_text=f"text of {name}", mana_value=1.0,
        color_identity=(), image_url=f"http://img/{name}.png", scryfall_uri=None, has_faces=False,
        price_usd=_PRICES.get(name),
    )


def _enrich(names):
    return {n: _meta(n) for n in names if n != "Bogus Card"}


# A fake commander pool that emulates Scryfall's real page size (175/page): the
# app sub-paginates each Scryfall page into UI pages of 60, so the fake must hand
# back a big page, not pre-slice it. Named commanders for the filter/autocomplete
# tests, plus enough 'a'-containing fillers to give the "a" search a real 2nd UI page.
_SCRYFALL_PAGE = 175
_COMMANDERS = (
    ["Atraxa, Praetors' Voice", "Edgar Markov", "The Ur-Dragon", "Yuriko"]
    + [f"Arcades Variant {i}" for i in range(70)]  # all contain 'a'
)


def _fake_search(query, page):
    pool = [c for c in _COMMANDERS if query.casefold() in c.casefold()] if query else _COMMANDERS
    start = (page - 1) * _SCRYFALL_PAGE
    window = pool[start : start + _SCRYFALL_PAGE]
    return CommanderSearch(
        names=tuple(window), has_more=start + _SCRYFALL_PAGE < len(pool), total=len(pool)
    )


def _fake_autocomplete(query):
    return [c for c in ["Counterspell", "Counterflux", "Sol Ring"] if query.casefold() in c.casefold()]


@pytest.fixture
def owned():
    """The owned-cards Collection the app sees; tests may mutate it before building."""
    return Collection()


@pytest.fixture
def client(monkeypatch, tmp_path, owned):
    # NOTE: this mutates the module-global ``app.dependency_overrides`` and clears
    # it on teardown, so it is correct only under a serial run. It would race under
    # pytest-xdist; move to an app-factory pattern before adopting parallel runs.
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


def test_build_creates_session_and_lazy_loads_readouts(client):
    r = _build(client)
    assert r.status_code == 200
    assert "Sol Ring" in r.text
    assert 'hx-get="/build/readouts"' in r.text  # readouts fetched lazily, off the critical path
    assert client.cookies.get("manaless_sid")  # session cookie set


def test_build_readouts_endpoint_renders_panel(client):
    _build(client)
    r = client.get("/build/readouts")
    assert r.status_code == 200
    assert "Bracket" in r.text and "Win conditions" in r.text
    assert 'id="readouts"' in r.text  # replaces the placeholder in place


def test_build_readouts_without_session_redirects_home(client):
    client.cookies.clear()
    r = client.get("/build/readouts", follow_redirects=False)
    assert r.status_code == 303


# --- combo outline indicators -------------------------------------------

def test_cardlist_cards_carry_data_name(client):
    # ui.js keys combo outlines off data-name; every mainboard + commander tile has it.
    r = _build(client)
    assert 'data-name="Sol Ring"' in r.text
    assert 'data-name="Atraxa, Praetors' in r.text  # commander tile too (apostrophe HTML-escaped)


def test_readouts_emit_combo_data_for_present_combo(client, monkeypatch):
    # A combo whose cards are all in the deck -> shows in the panel with a colour dot
    # and a #combo-data payload ui.js uses to outline those cards.
    combo = Combo(
        id="1", cards=("Sol Ring", "Counterspell"), produces=("Infinite mana",),
        popularity=100, bracket_tag="S",
    )
    monkeypatch.setattr(
        readout_mod, "find_my_combos",
        lambda http, deck: ComboResults("WUBRG", (combo,), ()),
    )
    _build(client)
    r = client.get("/build/readouts")
    assert r.status_code == 200
    assert 'id="combo-data"' in r.text and 'class="combo-dot"' in r.text
    assert 'data-combo-index="0"' in r.text
    assert "Sol Ring + Counterspell" in r.text  # panel line
    assert '"cards"' in r.text and "Infinite mana" in r.text  # JSON payload for ui.js


def test_readouts_without_combos_emit_no_combo_data(client):
    # The client fixture's fake returns no combos -> no outline payload.
    _build(client)
    r = client.get("/build/readouts")
    assert 'id="combo-data"' not in r.text


def test_build_shows_card_popularity(client):
    r = _build(client)
    assert "85%" in r.text  # Sol Ring inclusion from the commander page
    assert "EDHREC decks for this commander" in r.text  # the popularity bar tooltip


def test_build_shows_substitution_palette(client):
    r = _build(client)
    assert "Popular cards to add" in r.text
    assert "Smothering Tithe" in r.text  # popular + not in deck -> offered


def test_palette_shows_type_tag_and_hover_image(client):
    r = _build(client)
    assert 'class="type-tag"' in r.text  # card-type abbreviation shown
    assert ">ART<" in r.text  # fake meta type_line "Artifact" -> ART tag
    assert 'data-img="http://img/Smothering Tithe.png"' in r.text  # hover-preview source


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
    # Counts derive from deck_diff now: needed = 3 non-basics (commander included),
    # owned = 1, so the header reads "1 of 3" and agrees with the buy count.
    assert "You own" in r.text and "1</strong> of 3" in r.text


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


# --- E6 / swap modal: category-matched replacement suggestions ----------

def test_cardlist_swap_button_targets_suggest_modal(client):
    r = _build(client)
    # The inline "swap to…" input is gone; each card now has a swap button that
    # lazily loads the modal body from /build/suggest.
    assert 'placeholder="swap to…"' not in r.text
    assert 'hx-get="/build/suggest?old_name=' in r.text
    assert 'id="swapmodal"' in r.text  # the modal shell is on the page


def test_suggest_returns_same_category_suggestions(client):
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    assert r.status_code == 200
    # Smothering Tithe + Rhystic Study share Sol Ring's fallback category (all the
    # fake cards enrich as "Artifact"), so both are offered as replacements.
    assert "Smothering Tithe" in r.text and "Rhystic Study" in r.text
    assert "Counterspell" not in r.text  # a deck card -> excluded from suggestions


def test_suggest_fragment_posts_substitute_with_old_name(client):
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    assert 'hx-post="/build/substitute"' in r.text
    assert 'name="old_name" value="Sol Ring"' in r.text  # swap keeps the removed card
    assert 'data-autocomplete="card"' in r.text  # fuzzy search input carried into the modal


def test_suggest_without_session_redirects_home(client):
    client.cookies.clear()
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"}, follow_redirects=False)
    assert r.status_code == 303


# --- E2/E5: paginated commander browse + fuzzy search -------------------

def test_commanders_popular_uses_edhrec_ranking(client):
    # The empty "popular" browse ranks by EDHREC deck count, not Scryfall's
    # card-inclusion rank — so #1 is The Ur-Dragon, above Edgar Markov.
    r = client.get("/commanders")
    assert r.status_code == 200
    assert r.text.index("The Ur-Dragon") < r.text.index("Edgar Markov")
    assert "48,385 decks" in r.text  # deck count surfaced on the popular list
    assert "/decks?commander=" in r.text  # each links to its deck picker


def test_commanders_popular_paginates(client):
    r1 = client.get("/commanders", params={"page": 1})
    assert "The Ur-Dragon" in r1.text
    assert "page=2" in r1.text  # a live "next" link (70 commanders > one page)
    r2 = client.get("/commanders", params={"page": 2})
    assert "Cmdr 61" in r2.text  # 61st commander lands on page 2
    assert "page=1" in r2.text  # a live "prev" link back


def test_commanders_popular_falls_back_when_edhrec_unavailable(client):
    # EDHREC's ranking momentarily returns nothing (403/network) -> the browse
    # must still list commanders via Scryfall, not dead-end on "not found".
    class DownEdhrec(FakeEdhrec):
        def fetch_top_commanders(self):
            return []

    app.dependency_overrides[get_edhrec] = lambda: DownEdhrec()
    try:
        r = client.get("/commanders")
        assert r.status_code == 200
        assert "No commanders found" not in r.text
        assert "Atraxa" in r.text  # Scryfall fallback populated the list
    finally:
        app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()


def test_commanders_search_filters(client):
    r = client.get("/commanders", params={"q": "dragon"})
    assert "The Ur-Dragon" in r.text
    assert "Edgar Markov" not in r.text  # filtered out by the query


def test_commanders_search_paginates(client):
    r1 = client.get("/commanders", params={"q": "a", "page": 1})
    assert "page=2" in r1.text  # more matches than the fake's 2-per-page
    r2 = client.get("/commanders", params={"q": "a", "page": 2})
    assert "page=1" in r2.text  # prev link back to page 1


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


# --- W1: commander search sub-paginates one Scryfall page ----------------

def test_commander_search_subpaginates_one_scryfall_page(client):
    # One Scryfall page (175 names) fills 3 UI pages of 60; the Scryfall page only
    # advances every 3 UI pages, and no names are silently dropped.
    seen_pages = []
    page1 = [f"Cmd {i:03d}" for i in range(175)]
    tail = [f"Tail {i}" for i in range(55)]

    def spy_search(query, page):
        seen_pages.append(page)
        return CommanderSearch(
            names=tuple(page1 if page == 1 else tail),
            has_more=(page == 1),
            total=230,
        )

    app.dependency_overrides[get_search] = lambda: spy_search
    try:
        r2 = client.get("/commanders", params={"q": "x", "page": 2})
        assert "Cmd 060" in r2.text and "Cmd 119" in r2.text  # names 61–120
        assert "Cmd 059" not in r2.text and "Cmd 120" not in r2.text
        assert seen_pages == [1]  # UI page 2 is still Scryfall page 1
        seen_pages.clear()
        r4 = client.get("/commanders", params={"q": "x", "page": 4})
        assert seen_pages == [2]  # UI page 4 -> Scryfall page 2
        assert "Tail 0" in r4.text
    finally:
        app.dependency_overrides[get_search] = lambda: _fake_search


# --- W2: per-tab sid stops a second tab hijacking the first --------------

def test_page_sid_targets_the_right_session(client):
    _build(client)
    sid_a = client.cookies.get("manaless_sid")
    _build(client)  # a "second tab": mints sid B, cookie now points at B
    sid_b = client.cookies.get("manaless_sid")
    assert sid_a and sid_b and sid_a != sid_b
    # Remove from A via its page-carried sid (cookie is B's now).
    ra = client.post("/build/remove", data={"name": "Counterspell", "sid": sid_a})
    assert "2 cards" in ra.text
    # B is untouched: it still has Counterspell to remove (would 404-ish otherwise).
    rb = client.post("/build/remove", data={"name": "Counterspell", "sid": sid_b})
    assert "2 cards" in rb.text and "is not in the deck" not in rb.text


# --- W3: htmx lost-session signals a client redirect, not a doc swap ------

def test_lost_session_htmx_returns_204_hx_redirect(client):
    client.cookies.clear()
    r = client.post(
        "/build/remove", data={"name": "X"},
        headers={"HX-Request": "true"}, follow_redirects=False,
    )
    assert r.status_code == 204
    assert r.headers.get("HX-Redirect") == "/"


def test_lost_session_non_htmx_still_303(client):
    client.cookies.clear()
    r = client.post("/build/remove", data={"name": "X"}, follow_redirects=False)
    assert r.status_code == 303


# --- W4: cross-origin POSTs are rejected ---------------------------------

def test_cross_origin_build_rejected(client):
    r = client.post(
        "/build", data={"commander": "Atraxa, Praetors' Voice", "deck_id": "newest"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_same_origin_build_allowed(client):
    r = client.post(
        "/build", data={"commander": "Atraxa, Praetors' Voice", "deck_id": "newest"},
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200


def test_cross_origin_collection_import_rejected(client):
    r = client.post(
        "/collection/import",
        files={"file": ("x.csv", b"Name\nSol Ring\n", "text/csv")},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403


# --- W5: EDHREC / Spellbook failures surface gracefully ------------------

def test_build_edhrec_error_shows_hint_not_500(client):
    from manaless.edhrec_client import EdhrecError

    class BoomEdhrec(FakeEdhrec):
        def fetch_deck(self, deck_id):
            raise EdhrecError("boom")

    app.dependency_overrides[get_edhrec] = lambda: BoomEdhrec()
    try:
        r = client.post(
            "/build", data={"commander": "Atraxa, Praetors' Voice", "deck_id": "newest"}
        )
        assert r.status_code == 200
        assert "EDHREC" in r.text  # friendly hint, not a bare 500
    finally:
        app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()


def test_commanders_survives_edhrec_connect_error(client):
    import httpx

    class DownEdhrec(FakeEdhrec):
        def fetch_top_commanders(self):
            raise httpx.ConnectError("no network")

    app.dependency_overrides[get_edhrec] = lambda: DownEdhrec()
    try:
        r = client.get("/commanders")
        assert r.status_code == 200
        assert "Atraxa" in r.text  # Scryfall fallback engaged, not a 500
    finally:
        app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()


def test_readouts_spellbook_unavailable_renders_retry(client, monkeypatch):
    from manaless.spellbook_client import SpellbookUnavailable

    def boom(http, deck):
        raise SpellbookUnavailable("down")

    monkeypatch.setattr(readout_mod, "find_my_combos", boom)
    _build(client)
    r = client.get("/build/readouts")
    assert r.status_code == 200
    assert 'id="readouts"' in r.text and "unavailable" in r.text.lower()


# --- W6: header owned/missing agree with the buy count -------------------

def test_header_missing_count_matches_buy(client, owned):
    owned.add("Sol Ring", 1)  # own one of the two buyable non-basics
    r = _build(client)
    assert "2 to buy" in r.text  # header buy link
    rb = client.get("/build/buy-missing")
    assert "Counterspell" in rb.text and "Sol Ring" not in rb.text  # same 2 missing


# --- W10: add validation + no silent singleton dupes ---------------------

def test_add_blank_name_rejected(client):
    _build(client)
    r = client.post("/build/add", data={"name": "   "})
    assert r.status_code == 200
    assert "Enter a card name" in r.text
    assert "3 cards" in r.text  # unchanged


def test_add_duplicate_nonbasic_warns_without_merging(client):
    _build(client)
    r = client.post("/build/add", data={"name": "Sol Ring"})  # already in the deck
    assert "already in the deck" in r.text
    assert "3 cards" in r.text  # no merge to 2× Sol Ring


# --- W15: paging past the last page never dead-ends ----------------------

def test_popular_page_past_end_is_clamped(client):
    r = client.get("/commanders", params={"page": 9})
    assert r.status_code == 200
    assert "The Ur-Dragon" in r.text or "Cmdr 61" in r.text  # a real page, not empty


def test_search_page_past_end_offers_prev(client):
    r = client.get("/commanders", params={"q": "a", "page": 3})
    assert r.status_code == 200
    assert "No more commanders on this page" in r.text
    assert "page=2" in r.text  # a live prev link back


# --- T6: over-100 warning fires above 100 and not at 100 -----------------

def test_over_100_warning(client):
    class BigEdhrec(FakeEdhrec):
        def fetch_deck(self, deck_id):
            return ["1 Atraxa, Praetors' Voice", "99 Forest"]  # 100 cards exactly

    app.dependency_overrides[get_edhrec] = lambda: BigEdhrec()
    try:
        r = _build(client)
        assert "over 100" not in r.text  # exactly 100 -> no warning
        r2 = client.post("/build/add", data={"name": "Sol Ring"})  # -> 101
        assert "over 100" in r2.text
    finally:
        app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()


# --- TCGplayer prices on palette + swap suggestions -----------------------
# Palette candidates ride the same batched Scryfall enrichment as the deck, so
# these numbers cost no extra requests.


def test_palette_shows_price_per_suggestion(client):
    r = _build(client)
    assert 'class="listprice"' in r.text
    assert "$25.00" in r.text  # Smothering Tithe, offered as an add


def test_palette_omits_price_when_scryfall_has_none(client):
    """An unpriced suggestion is still offered, just with no price tag."""
    r = _build(client)
    assert "Unpriced Relic" in r.text          # still a valid suggestion
    assert "$None" not in r.text and "$0.00" not in r.text

    # The row itself carries no price span: slice out just this <li>.
    row = r.text[r.text.index("Unpriced Relic"):]
    assert "listprice" not in row[: row.index("</li>")]


def test_swap_suggestion_without_price_shows_no_delta(client):
    """A delta needs both sides priced; an unpriced candidate shows nothing."""
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    row = r.text[r.text.index("Unpriced Relic"):]
    assert "listprice" not in row[: row.index("</li>")]


def test_swap_modal_shows_outgoing_card_price(client):
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    assert "$1.50" in r.text  # Sol Ring, the card being swapped out


def test_swap_suggestions_show_price_delta_not_bare_price(client):
    """With both sides priced the useful figure is the delta, signed and coloured."""
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    # Smothering Tithe ($25.00) for Sol Ring ($1.50) -> adds $23.50
    assert "+$23.50" in r.text
    assert 'listprice pricier' in r.text
    # Rhystic Study ($0.75) for Sol Ring ($1.50) -> saves $0.75
    assert "\u2212$0.75" in r.text
    assert 'listprice cheaper' in r.text


def test_swap_delta_tooltip_explains_both_sides(client):
    _build(client)
    r = client.get("/build/suggest", params={"old_name": "Sol Ring"})
    assert "$25.00 vs $1.50 — adds $23.50" in r.text
    assert "$0.75 vs $1.50 — saves $0.75" in r.text
