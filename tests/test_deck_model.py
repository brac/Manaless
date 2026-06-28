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


# --- substitution (build step 4) -----------------------------------------

def _src_deck():
    return DeckModel(
        commanders=(_c("Atraxa, Praetors' Voice", "Legendary Creature"),),
        cards=(_c("Sol Ring", "Artifact"), _c("Counterspell", "Instant")),
        deck_id="abc",
        edhrec_bracket=3,
    )


def test_substitute_swaps_card_and_clears_provenance():
    deck = _src_deck().substitute("Sol Ring", _c("Arcane Signet", "Artifact"))
    names = [c.name for c in deck.cards]
    assert "Sol Ring" not in names and "Arcane Signet" in names
    # source provenance is stale after an edit -> cleared so engines re-infer
    assert deck.edhrec_bracket is None
    assert deck.deck_id is None


def test_substitute_is_case_insensitive_on_old_name():
    deck = _src_deck().substitute("sol ring", _c("Arcane Signet", "Artifact"))
    assert "Arcane Signet" in [c.name for c in deck.cards]


def test_remove_unknown_card_raises():
    with pytest.raises(KeyError):
        _src_deck().remove("Not In Deck")


def test_add_merges_quantity_for_existing_name():
    deck = _src_deck().add(Card(name="Sol Ring", quantity=1, type_line="Artifact"))
    sol = [c for c in deck.cards if c.name == "Sol Ring"]
    assert len(sol) == 1 and sol[0].quantity == 2


def test_substitution_returns_new_model_leaving_original_unchanged():
    original = _src_deck()
    original.substitute("Sol Ring", _c("Arcane Signet", "Artifact"))
    assert "Sol Ring" in [c.name for c in original.cards]  # frozen: untouched
    assert original.edhrec_bracket == 3


def test_commanders_untouched_by_substitution():
    deck = _src_deck().substitute("Sol Ring", _c("Arcane Signet", "Artifact"))
    assert [c.name for c in deck.commanders] == ["Atraxa, Praetors' Voice"]
