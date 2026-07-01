"""card_category — functional-first classifier with primary-type fallback."""

import pytest

from manaless.card_category import (
    BOARD_WIPE,
    CARD_DRAW,
    COUNTERSPELL,
    RAMP,
    REMOVAL,
    category_of,
    functional_category,
)
from manaless.deck_model import Card

# (type_line, oracle_text, expected) — one row per branch, real-ish oracle text.
_CASES = [
    # --- Ramp: mana rocks, dorks, land-fetch; guarded off actual lands ---------
    ("Artifact", "{T}: Add {C}{C}.", RAMP),  # Sol Ring
    ("Creature — Elf Druid", "{T}: Add {G}.", RAMP),  # Llanowar Elves
    (
        "Sorcery",
        "Search your library for up to two basic land cards, reveal them, put one "
        "onto the battlefield tapped and the other into your hand, then shuffle.",
        RAMP,
    ),  # Cultivate
    ("Artifact", "{T}, Sacrifice: Create a Treasure token.", RAMP),
    # --- Land: "adds mana" but the Ramp check is land-guarded ------------------
    ("Basic Land — Swamp", "{T}: Add {B}.", "Land"),
    ("Land", "{T}: Add one mana of any color in your commander's color identity.", "Land"),  # Command Tower
    # --- Board wipe outranks single-target removal -----------------------------
    ("Sorcery", "Destroy all creatures.", BOARD_WIPE),  # Wrath of God
    ("Sorcery", "Blasphemous Act deals 13 damage to each creature.", BOARD_WIPE),
    ("Sorcery", "Destroy all creatures. Then destroy target land.", BOARD_WIPE),  # precedence
    # --- Removal: single-target destroy/exile/bounce/burn ----------------------
    ("Instant", "Exile target creature.", REMOVAL),  # Swords to Plowshares
    ("Instant", "Lightning Bolt deals 3 damage to any target.", REMOVAL),
    ("Sorcery", "Return target creature to its owner's hand.", REMOVAL),
    # --- Counterspell ----------------------------------------------------------
    ("Instant", "Counter target spell.", COUNTERSPELL),
    # --- Card draw: explicit and incidental ------------------------------------
    ("Sorcery", "Draw two cards.", CARD_DRAW),  # Divination
    (
        "Enchantment",
        "Whenever an opponent casts a spell, you may draw a card unless that "
        "player pays {1}.",
        CARD_DRAW,
    ),  # Rhystic Study
    # --- primary-type fallback -------------------------------------------------
    ("Creature — Bear", "", "Creature"),  # Grizzly Bears (vanilla)
    ("Legendary Planeswalker — Teferi", "+1: Something happens.", "Planeswalker"),
    ("", "", "Other"),
]


@pytest.mark.parametrize("type_line, oracle, expected", _CASES)
def test_functional_category(type_line, oracle, expected):
    assert functional_category(type_line, oracle) == expected


def test_category_of_reads_card_fields():
    card = Card(name="Sol Ring", quantity=1, type_line="Artifact", oracle_text="{T}: Add {C}{C}.")
    assert category_of(card) == RAMP


def test_ramp_beats_card_draw_for_dual_purpose():
    # Mind Stone: adds mana AND can sac to draw — Ramp is checked first.
    text = "{T}: Add {C}. {1}, {T}, Sacrifice Mind Stone: Draw a card."
    assert functional_category("Artifact", text) == RAMP
