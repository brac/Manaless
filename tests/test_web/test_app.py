"""web.app — route smoke tests via FastAPI TestClient, deps overridden by fakes.

No live network: EDHREC + enrichment are fakes (mirroring test_deck_builder), and
the Spellbook calls inside web.readout are monkeypatched. Engines run for real.
"""

import pytest
from fastapi.testclient import TestClient

import manaless.web.readout as readout_mod
from manaless.collection import Collection
from manaless.scryfall_client import ScryfallCard
from manaless.spellbook_client import BracketEstimate, Combo, ComboResults
from manaless.web.app import (
    app,
    get_collection_path,
    get_edhrec,
    get_enrich,
    get_http,
    get_owned,
)


class FakeEdhrec:
    def fetch_deck_table(self, commander):
        return [{"urlhash": "newest", "savedate": "2026-06-27", "price": 420, "bracket": 3}]

    def fetch_deck(self, deck_id):
        return ["1 Atraxa, Praetors' Voice", "1 Sol Ring", "1 Counterspell"]


def _meta(name):
    tl = "Legendary Creature" if "Atraxa" in name else "Artifact"
    return ScryfallCard(
        name=name, type_line=tl, oracle_text=f"text of {name}", mana_value=1.0,
        color_identity=(), image_url=f"http://img/{name}.png", scryfall_uri=None, is_dfc=False,
    )


def _enrich(names):
    return {n: _meta(n) for n in names if n != "Bogus Card"}


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


def test_build_creates_session_and_renders_readouts(client):
    r = _build(client)
    assert r.status_code == 200
    assert "Sol Ring" in r.text
    assert "Bracket" in r.text and "Win conditions" in r.text
    assert client.cookies.get("manaless_sid")  # session cookie set


def test_substitute_returns_updated_fragment(client):
    _build(client)
    r = client.post("/build/substitute", data={"old_name": "Sol Ring", "new_name": "Arcane Signet"})
    assert r.status_code == 200
    assert "Arcane Signet" in r.text
    assert "Sol Ring" not in r.text
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
