"""composition — deck breakdown vs the EDHREC per-commander average."""

import pytest

from manaless.composition import (
    CURVE_TAIL,
    NOTABLE_DELTA,
    compare,
    deck_curve,
    deck_type_counts,
)
from manaless.deck_model import Card, DeckModel
from manaless.edhrec_client import CommanderAverage


def _card(name, type_line, quantity=1, mana_value=1.0, resolved=True):
    return Card(
        name=name, quantity=quantity, type_line=type_line,
        mana_value=mana_value, resolved=resolved,
    )


def _deck(*cards):
    return DeckModel(
        commanders=(_card("Atraxa, Praetors' Voice", "Legendary Creature — Phyrexian Angel"),),
        cards=tuple(cards),
    )


def _avg(types=None, curve=None, **kw):
    return CommanderAverage(types=types or {}, curve=curve or {}, **kw)


# --- deck-side counting ---------------------------------------------------


def test_type_counts_are_quantity_aware_and_exclude_commanders():
    deck = _deck(_card("Forest", "Basic Land — Forest", quantity=10), _card("Sol Ring", "Artifact"))
    counts = deck_type_counts(deck)
    assert counts == {"Land": 10, "Artifact": 1}
    # The commander is a Creature but must not appear: EDHREC's baseline excludes it.
    assert "Creature" not in counts


def test_curve_excludes_lands_and_is_quantity_aware():
    deck = _deck(
        _card("Forest", "Basic Land — Forest", quantity=10, mana_value=0.0),
        _card("Sol Ring", "Artifact", mana_value=1.0),
        _card("Signet", "Artifact", quantity=2, mana_value=2.0),
    )
    assert deck_curve(deck) == {1: 1, 2: 2}  # no 0-bucket from the ten Forests


def test_curve_skips_unresolved_cards():
    """An unenriched card has mana_value 0.0 and would fake a pile of 0-drops."""
    deck = _deck(
        _card("Mystery", "", mana_value=0.0, resolved=False),
        _card("Sol Ring", "Artifact", mana_value=1.0),
    )
    assert deck_curve(deck) == {1: 1}


# --- comparison -----------------------------------------------------------


def test_rows_carry_delta_against_the_average():
    deck = _deck(_card("Forest", "Basic Land — Forest", quantity=38))
    comp = compare(deck, _avg(types={"Land": 35}))
    land = next(r for r in comp.types if r.label == "Land")
    assert (land.actual, land.average, land.delta) == (38, 35, 3)


def test_category_the_deck_lacks_still_shows_as_a_gap():
    """0 planeswalkers against an average of 6 is exactly what the panel is for."""
    comp = compare(_deck(_card("Sol Ring", "Artifact")), _avg(types={"Planeswalker": 6}))
    pw = next(r for r in comp.types if r.label == "Planeswalker")
    assert (pw.actual, pw.delta) == (0, -6)


def test_category_neither_side_uses_is_omitted():
    comp = compare(_deck(_card("Sol Ring", "Artifact")), _avg(types={"Battle": 0, "Artifact": 1}))
    assert [r.label for r in comp.types] == ["Artifact"]


def test_other_category_is_shown_without_an_average():
    """An unclassifiable card must not silently vanish from the breakdown."""
    comp = compare(_deck(_card("Weird", "Conspiracy")), _avg(types={"Artifact": 9}))
    other = next(r for r in comp.types if r.label == "Other")
    assert other.actual == 1 and other.average is None and other.delta is None


@pytest.mark.parametrize(
    ("actual", "expected"),
    [(35, False), (35 + NOTABLE_DELTA - 1, False), (35 + NOTABLE_DELTA, True), (35 - NOTABLE_DELTA, True)],
)
def test_notable_threshold_is_symmetric(actual, expected):
    comp = compare(
        _deck(_card("Forest", "Basic Land — Forest", quantity=actual)), _avg(types={"Land": 35})
    )
    assert next(r for r in comp.types if r.label == "Land").notable is expected


def test_notable_rows_are_sorted_by_largest_gap():
    deck = _deck(
        _card("Forest", "Basic Land — Forest", quantity=30),   # -5
        _card("Bear", "Creature — Bear", quantity=30),         # +20
    )
    comp = compare(deck, _avg(types={"Land": 35, "Creature": 10}))
    assert [r.label for r in comp.notable] == ["Creature", "Land"]


# --- curve folding --------------------------------------------------------


def test_curve_tail_folds_both_sides_identically():
    """EDHREC reports exact mana values (up to 13); the 7+ tail is display-only."""
    deck = _deck(
        _card("Big", "Creature — Eldrazi", mana_value=9.0),
        _card("Bigger", "Creature — Eldrazi", mana_value=13.0),
    )
    comp = compare(deck, _avg(curve={7: 1, 8: 1, 12: 2}))
    tail = next(r for r in comp.curve if r.label == f"{CURVE_TAIL}+")
    assert tail.actual == 2  # 9 and 13 folded together
    assert tail.average == 4  # 1 + 1 + 2 folded together


def test_curve_buckets_below_the_tail_stay_separate():
    deck = _deck(_card("One", "Artifact", mana_value=1.0), _card("Two", "Artifact", mana_value=2.0))
    comp = compare(deck, _avg(curve={1: 8, 2: 18}))
    assert [(r.label, r.actual, r.average) for r in comp.curve] == [("1", 1, 8), ("2", 1, 18)]


def test_fractional_mana_value_floors_into_its_bucket():
    """Scryfall reports cmc as a float; 2.0 must not land in its own bucket."""
    comp = compare(_deck(_card("X", "Artifact", mana_value=2.0)), _avg(curve={2: 5}))
    assert [r.label for r in comp.curve] == ["2"]


# --- no baseline ----------------------------------------------------------


def test_without_an_average_rows_still_show_the_decks_own_counts():
    deck = _deck(_card("Forest", "Basic Land — Forest", quantity=38))
    comp = compare(deck, None)
    assert comp.has_average is False
    land = next(r for r in comp.types if r.label == "Land")
    assert land.actual == 38 and land.average is None and land.delta is None
    assert land.notable is False  # nothing to be notably off from
    assert comp.notable == ()


def test_notable_line_is_capped_but_the_table_keeps_everything():
    """The headline is a glance; the full breakdown stays in `types`."""
    from manaless.composition import NOTABLE_LIMIT

    deck = _deck(
        _card("A", "Creature — Bear", quantity=30),
        _card("B", "Instant", quantity=30),
        _card("C", "Sorcery", quantity=30),
        _card("D", "Enchantment", quantity=30),
    )
    avg = _avg(types={"Creature": 1, "Instant": 1, "Sorcery": 1, "Enchantment": 1})
    comp = compare(deck, avg)
    assert len(comp.notable) == NOTABLE_LIMIT
    assert len([r for r in comp.types if r.notable]) == 4  # nothing dropped from the table
