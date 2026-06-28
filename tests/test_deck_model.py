"""deck_model — card categorisation and DeckModel views."""

import pytest

from manaless.deck_model import Card, DeckModel


def _c(name, type_line="", quantity=1, resolved=True):
    return Card(name=name, quantity=quantity, type_line=type_line, resolved=resolved)


@pytest.mark.parametrize(
    ("type_line", "expected"),
    [
        ("Legendary Creature — Phyrexian Angel Horror", "Creature"),
        ("Artifact Creature — Golem", "Creature"),       # Creature wins over Artifact
        ("Land Creature — Dryad", "Creature"),           # Creature wins over Land
        ("Legendary Planeswalker — Teferi", "Planeswalker"),
        ("Instant", "Instant"),
        ("Sorcery", "Sorcery"),
        ("Artifact — Equipment", "Artifact"),
        ("Enchantment — Aura", "Enchantment"),
        ("Basic Land — Forest", "Land"),
        ("Legendary Creature — God // Legendary Enchantment", "Creature"),  # front face
        ("", "Other"),
    ],
)
def test_card_category(type_line, expected):
    assert _c("X", type_line).category == expected


def test_total_cards_sums_quantity():
    deck = DeckModel(
        commanders=(_c("Atraxa, Praetors' Voice", "Legendary Creature", quantity=1),),
        cards=(_c("Forest", "Basic Land", quantity=10), _c("Sol Ring", "Artifact", quantity=1)),
    )
    assert deck.total_cards == 12


def test_to_decklist_and_card_names_include_commander_first():
    deck = DeckModel(
        commanders=(_c("Atraxa, Praetors' Voice", "Legendary Creature"),),
        cards=(_c("Sol Ring", "Artifact"),),
    )
    assert deck.to_decklist() == ["1 Atraxa, Praetors' Voice", "1 Sol Ring"]
    assert deck.card_names() == ["Atraxa, Praetors' Voice", "Sol Ring"]


def test_categorized_excludes_commander_and_orders_by_type():
    deck = DeckModel(
        commanders=(_c("Atraxa, Praetors' Voice", "Legendary Creature"),),
        cards=(
            _c("Forest", "Basic Land"),
            _c("Birds of Paradise", "Creature — Bird"),
            _c("Counterspell", "Instant"),
        ),
    )
    cats = deck.categorized()
    assert list(cats.keys()) == ["Creature", "Instant", "Land"]  # CATEGORY_ORDER
    assert "Atraxa, Praetors' Voice" not in [c.name for group in cats.values() for c in group]


def test_unresolved_lists_unenriched_cards():
    deck = DeckModel(
        commanders=(_c("Atraxa, Praetors' Voice", "Legendary Creature"),),
        cards=(_c("Sol Ring", "Artifact"), _c("Weird Misspelled Card", resolved=False)),
    )
    assert deck.unresolved == ("Weird Misspelled Card",)
