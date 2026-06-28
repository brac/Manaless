"""buy — TCGplayer Mass Entry URL construction + deck-diff (build steps 5/6)."""

from urllib.parse import parse_qs, urlsplit

from manaless.buy import deck_diff, deck_diff_url, is_basic_land, mass_entry_url, single_card_url
from manaless.collection import Collection
from manaless.deck_model import Card, DeckModel


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _deck():
    return DeckModel(
        commanders=(Card("Atraxa, Praetors' Voice", 1),),
        cards=(
            Card("Sol Ring", 1),
            Card("Counterspell", 1),
            Card("Lightning Bolt", 2),
            Card("Forest", 10),
        ),
    )


def test_single_card_url_points_at_mass_entry():
    url = single_card_url("Sol Ring")
    assert url.startswith("https://www.tcgplayer.com/massentry?")
    q = _query(url)
    assert q["c"] == ["1 Sol Ring"]
    assert q["productline"] == ["Magic"]


def test_single_card_url_quantity():
    q = _query(single_card_url("Lightning Bolt", quantity=4))
    assert q["c"] == ["4 Lightning Bolt"]


def test_single_card_url_encodes_special_names():
    # apostrophes, commas and the // in DFC names must survive the round-trip
    name = "Atraxa, Praetors' Voice"
    assert _query(single_card_url(name))["c"] == [f"1 {name}"]
    assert _query(single_card_url("Fire // Ice"))["c"] == ["1 Fire // Ice"]


def test_mass_entry_url_joins_entries_with_double_pipe():
    url = mass_entry_url([(1, "Sol Ring"), (2, "Counterspell")])
    assert _query(url)["c"] == ["1 Sol Ring||2 Counterspell"]


def test_mass_entry_clamps_quantity_to_at_least_one():
    assert _query(single_card_url("Sol Ring", quantity=0))["c"] == ["1 Sol Ring"]


# --- step 6: deck diff ---------------------------------------------------

def test_is_basic_land():
    assert is_basic_land("Forest") and is_basic_land("snow-covered island")
    assert is_basic_land("Wastes")
    assert not is_basic_land("Sol Ring") and not is_basic_land("Bojuka Bog")


def test_deck_diff_empty_collection_buys_all_nonbasics():
    missing = dict((name, qty) for qty, name in deck_diff(_deck(), Collection()))
    assert "Forest" not in missing  # basics excluded
    assert missing == {
        "Atraxa, Praetors' Voice": 1,  # commander included
        "Sol Ring": 1,
        "Counterspell": 1,
        "Lightning Bolt": 2,
    }


def test_deck_diff_subtracts_owned_quantity():
    owned = Collection.from_csv("Name,Quantity\nSol Ring,1\nLightning Bolt,1\n")
    missing = dict((name, qty) for qty, name in deck_diff(_deck(), owned))
    assert "Sol Ring" not in missing  # own the 1 we need
    assert missing["Lightning Bolt"] == 1  # need 2, own 1 -> buy 1


def test_deck_diff_include_basics_flag():
    missing = dict((name, qty) for qty, name in deck_diff(_deck(), Collection(), include_basics=True))
    assert missing["Forest"] == 10


def test_deck_diff_dfc_matches_front_face():
    deck = DeckModel(
        commanders=(Card("Atraxa, Praetors' Voice", 1),),
        cards=(Card("Valki, God of Lies // Tibalt, Cosmic Impostor", 1),),
    )
    owned = Collection.from_csv('Name,Quantity\n"Valki, God of Lies",1\n')  # Collectr stores front face
    names = [name for _, name in deck_diff(deck, owned)]
    assert "Valki, God of Lies // Tibalt, Cosmic Impostor" not in names  # counted as owned


def test_deck_diff_url_contains_missing_cards():
    q = _query(deck_diff_url(_deck(), Collection()))
    assert "1 Sol Ring" in q["c"][0] and "2 Lightning Bolt" in q["c"][0]
    assert "Forest" not in q["c"][0]


def test_deck_diff_owning_everything_is_empty():
    owned = Collection()
    for name, qty in [("Atraxa, Praetors' Voice", 1), ("Sol Ring", 1), ("Counterspell", 1), ("Lightning Bolt", 2)]:
        owned.add(name, qty)
    assert deck_diff(_deck(), owned) == []
