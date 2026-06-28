"""dck_export — XMage .dck text shape (commanders in SB, DFC front face, file name)."""

from manaless.dck_export import dck_filename, to_dck, write_dck
from manaless.deck_model import Card, DeckModel


def _deck(cards, commanders=("Atraxa, Praetors' Voice",)):
    return DeckModel(
        commanders=tuple(Card(name=n, quantity=1) for n in commanders),
        cards=tuple(cards),
    )


def test_mainboard_lines_use_placeholder_printing():
    out = to_dck(_deck([Card("Sol Ring", 1), Card("Forest", 10)]))
    lines = out.splitlines()
    assert "1 [XXX:0] Sol Ring" in lines
    assert "10 [XXX:0] Forest" in lines


def test_commander_goes_to_sideboard():
    out = to_dck(_deck([Card("Sol Ring", 1)]))
    assert "SB: 1 [XXX:0] Atraxa, Praetors' Voice" in out.splitlines()
    # the commander is NOT also emitted as a mainboard line
    assert "1 [XXX:0] Atraxa, Praetors' Voice" not in out.splitlines()


def test_dfc_split_emits_front_face_only():
    out = to_dck(_deck([Card("Fire // Ice", 1), Card("Valki, God of Lies // Tibalt", 1)]))
    assert "1 [XXX:0] Fire" in out.splitlines()
    assert "1 [XXX:0] Valki, God of Lies" in out.splitlines()


def test_trailing_newline_and_every_line_has_bracket():
    out = to_dck(_deck([Card("Sol Ring", 1)]))
    assert out.endswith("\n")
    for line in out.splitlines():
        assert "[XXX:0]" in line  # XMage importer regex requires the bracket


def test_filename_keeps_legal_chars_and_strips_illegal():
    # commas/apostrophes are legal in filenames -> preserved
    assert dck_filename(_deck([], commanders=("Atraxa, Praetors' Voice",))) == "Atraxa, Praetors' Voice.dck"
    partners = _deck([], commanders=("Tymna the Weaver", "Thrasios, Triton Hero"))
    assert dck_filename(partners) == "Tymna the Weaver & Thrasios, Triton Hero.dck"
    # an illegal char (':') is replaced
    assert dck_filename(_deck([], commanders=("Urza: Lord",))) == "Urza_ Lord.dck"


def test_write_dck_round_trips(tmp_path):
    deck = _deck([Card("Sol Ring", 1)])
    path = write_dck(deck, tmp_path)
    assert path.name == "Atraxa, Praetors' Voice.dck"
    assert path.read_text(encoding="utf-8") == to_dck(deck)
