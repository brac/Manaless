"""web.app — route smoke tests via FastAPI TestClient, deps overridden by fakes.

No live network: EDHREC + enrichment are fakes (mirroring test_deck_builder), and
the Spellbook calls inside web.readout are monkeypatched. Engines run for real.
"""

import pytest
from fastapi.testclient import TestClient

import manaless.web.readout as readout_mod
from manaless.scryfall_client import ScryfallCard
from manaless.spellbook_client import BracketEstimate, Combo, ComboResults
from manaless.web.app import app, get_edhrec, get_enrich, get_http


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
def client(monkeypatch):
    monkeypatch.setattr(readout_mod, "find_my_combos", lambda http, deck: ComboResults("WUBRG", (), ()))
    monkeypatch.setattr(
        readout_mod, "estimate_bracket", lambda http, deck: BracketEstimate(tag="C", cards=(), combos=())
    )
    app.dependency_overrides[get_http] = lambda: None
    app.dependency_overrides[get_edhrec] = lambda: FakeEdhrec()
    app.dependency_overrides[get_enrich] = lambda: _enrich
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
