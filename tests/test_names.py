"""names — the single canonical card-name comparison key (norm_name)."""

import pytest

from manaless.names import norm_name


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # DFC full name vs its front face
        ("Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Fable of the Mirror-Breaker"),
        ("Valki, God of Lies // Tibalt, Cosmic Impostor", "Valki, God of Lies"),
        # curly vs straight apostrophe
        ("Gaea’s Cradle", "Gaea's Cradle"),
        ("Urza’s Bauble", "Urza's Bauble"),
        # case and surrounding whitespace
        ("SOL RING", "sol ring"),
        ("  Sol Ring  ", "Sol Ring"),
        # all three at once
        ("  GAEA’S CRADLE // whatever  ", "gaea's cradle"),
    ],
)
def test_equivalent_names_normalize_equal(a, b):
    assert norm_name(a) == norm_name(b)


def test_distinct_cards_stay_distinct():
    assert norm_name("Sol Ring") != norm_name("Sol Ringer")
    assert norm_name("Fire // Ice") != norm_name("Ice")  # keyed on the FRONT face


def test_no_separator_is_unchanged_apart_from_folding():
    assert norm_name("Lightning Bolt") == "lightning bolt"
