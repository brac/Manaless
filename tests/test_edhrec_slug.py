"""format_commander_name — the one pure utility implemented in Phase 0."""

import pytest

from manaless.edhrec_client import format_commander_name


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Atraxa, Praetors' Voice", "atraxa-praetors-voice"),
        ("Krenko, Mob Boss", "krenko-mob-boss"),
        ("Niv-Mizzet, Parun", "niv-mizzet-parun"),
        ("The Ur-Dragon", "the-ur-dragon"),
        ("Slimefoot, the Stowaway", "slimefoot-the-stowaway"),
        ("  Edgar Markov  ", "edgar-markov"),
        ("Jolene, the Plunder Queen", "jolene-the-plunder-queen"),
    ],
)
def test_slugifies_commander_names(name, slug):
    assert format_commander_name(name) == slug


def test_curly_apostrophe_is_dropped_not_hyphenated():
    # Real-world data uses U+2019; must match the straight-quote behaviour.
    assert format_commander_name("Praetors’ Voice") == "praetors-voice"
