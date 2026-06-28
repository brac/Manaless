"""buy — TCGplayer Mass Entry URL construction (build step 5)."""

from urllib.parse import parse_qs, urlsplit

import pytest

from manaless.buy import deck_diff_url, mass_entry_url, single_card_url


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


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


def test_deck_diff_still_unbuilt():
    with pytest.raises(NotImplementedError):
        deck_diff_url(None, None)
