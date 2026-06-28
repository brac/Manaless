"""spellbook_client — find-my-combos parsing, DeckRequest body, hash-keyed cache."""

import json

import httpx

from manaless.deck_model import Card, DeckModel
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.spellbook_client import decklist_hash, estimate_bracket, find_my_combos


def _http(tmp_path, handler) -> HttpClient:
    return HttpClient(
        DiskCache(tmp_path),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        host_delays={},
        default_delay=0.0,
    )


def _deck() -> DeckModel:
    return DeckModel(
        commanders=(Card(name="Atraxa, Praetors' Voice", quantity=1),),
        cards=(Card(name="Sol Ring", quantity=1), Card(name="Forest", quantity=3)),
    )


RESPONSE = {
    "count": None, "next": None, "previous": None,
    "results": {
        "identity": "WUBG",
        "included": [
            {
                "id": 1,
                "uses": [{"card": {"name": "Sol Ring"}}, {"card": {"name": "Forest"}}],
                "produces": [{"feature": {"name": "Infinite mana"}}],
                "popularity": 26571,
                "bracketTag": "S",
            }
        ],
        "almostIncluded": [
            {
                "id": 2,
                "uses": [{"card": {"name": "Sol Ring"}}, {"card": {"name": "Basalt Monolith"}}],
                "produces": [{"feature": {"name": "Win the game"}}],
                "popularity": 50,
                "bracketTag": "P",
            }
        ],
    },
}


def test_parses_included_and_almost_included(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json=RESPONSE))
    results = find_my_combos(http, _deck())

    assert results.identity == "WUBG"
    assert len(results.included) == 1
    combo = results.included[0]
    assert combo.cards == ("Sol Ring", "Forest")
    assert combo.produces == ("Infinite mana",)
    assert combo.popularity == 26571
    assert combo.bracket_tag == "S"
    assert results.almost_included[0].cards == ("Sol Ring", "Basalt Monolith")


def test_posts_deck_request_body(tmp_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESPONSE)

    http = _http(tmp_path, handler)
    find_my_combos(http, _deck())

    assert seen["body"]["commanders"] == [{"card": "Atraxa, Praetors' Voice", "quantity": 1}]
    assert {"card": "Sol Ring", "quantity": 1} in seen["body"]["main"]


def test_result_cached_by_decklist_hash(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=RESPONSE)

    http = _http(tmp_path, handler)
    find_my_combos(http, _deck())
    find_my_combos(http, _deck())  # identical deck -> served from cache
    assert calls["n"] == 1


def test_decklist_hash_is_order_independent():
    a = DeckModel(commanders=(Card("Cmd", 1),), cards=(Card("A", 1), Card("B", 2)))
    b = DeckModel(commanders=(Card("Cmd", 1),), cards=(Card("B", 2), Card("A", 1)))
    c = DeckModel(commanders=(Card("Cmd", 1),), cards=(Card("A", 1), Card("C", 2)))
    assert decklist_hash(a) == decklist_hash(b)
    assert decklist_hash(a) != decklist_hash(c)


BRACKET_RESPONSE = {
    "bracketTag": "S",
    "cards": [
        {"card": {"name": "Cyclonic Rift"}, "quantity": 1, "gameChanger": True,
         "banned": False, "massLandDenial": False, "extraTurn": False},
        {"card": {"name": "Armageddon"}, "quantity": 1, "gameChanger": False,
         "banned": False, "massLandDenial": True, "extraTurn": False},
    ],
    "combos": [
        {"relevant": True, "arguablyTwoCard": True, "definitelyTwoCard": True,
         "speed": 4, "lock": False, "extraTurn": False, "massLandDenial": False,
         "skipTurns": False, "controlAllOpponents": False, "controlSomeOpponents": False},
    ],
    "templates": [],
}


def test_estimate_bracket_parses_tag_and_flags(tmp_path):
    http = _http(tmp_path, lambda r: httpx.Response(200, json=BRACKET_RESPONSE))
    est = estimate_bracket(http, _deck())
    assert est.tag == "S"
    assert {c.name for c in est.cards} == {"Cyclonic Rift", "Armageddon"}
    assert next(c for c in est.cards if c.name == "Cyclonic Rift").game_changer is True
    assert next(c for c in est.cards if c.name == "Armageddon").mass_land_denial is True
    combo = est.combos[0]
    assert combo.relevant and combo.definitely_two_card and combo.speed == 4


def test_estimate_bracket_cached_by_hash(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=BRACKET_RESPONSE)

    http = _http(tmp_path, handler)
    estimate_bracket(http, _deck())
    estimate_bracket(http, _deck())
    assert calls["n"] == 1
