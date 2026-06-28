"""web.readout — engine wiring + the stale-label-clears-on-substitution behaviour."""

import manaless.web.readout as readout_mod
from manaless.deck_model import Card, DeckModel
from manaless.spellbook_client import BracketEstimate, Combo, ComboResults
from manaless.web.readout import compute_readouts


def _deck(edhrec_bracket=None, cards=(Card("Sol Ring", 1),)):
    return DeckModel(
        commanders=(Card(name="Atraxa, Praetors' Voice", quantity=1),),
        cards=tuple(cards),
        deck_id="abc" if edhrec_bracket is not None else None,
        edhrec_bracket=edhrec_bracket,
    )


def _patch(monkeypatch, *, tag="C", combos=ComboResults("WUBRG", (), ())):
    monkeypatch.setattr(readout_mod, "find_my_combos", lambda http, deck: combos)
    monkeypatch.setattr(
        readout_mod, "estimate_bracket", lambda http, deck: BracketEstimate(tag=tag, cards=(), combos=())
    )


def test_bundles_win_conditions_and_bracket(monkeypatch):
    combo = Combo(id="1", cards=("Sol Ring", "X"), produces=("Infinite mana",), popularity=100, bracket_tag="C")
    _patch(monkeypatch, combos=ComboResults("WUBRG", (combo,), ()))
    out = compute_readouts(http=None, deck=_deck(edhrec_bracket=3))

    assert out.win_conditions.primary == "combo"
    assert out.bracket.bracket == 3  # unmodified deck -> trusts the EDHREC label


def test_unmodified_deck_uses_edhrec_label(monkeypatch):
    _patch(monkeypatch, tag="R")  # Ruthless would infer to 4...
    out = compute_readouts(http=None, deck=_deck(edhrec_bracket=2))
    assert out.bracket.bracket == 2  # ...but the label wins for an unmodified deck
    assert out.bracket.source == "edhrec-label"


def test_substituted_deck_reinfers_from_tag(monkeypatch):
    _patch(monkeypatch, tag="R")
    # A substituted deck has its provenance cleared (edhrec_bracket=None) by
    # DeckModel.substitute, so the bracket must re-infer from the Spellbook tag.
    edited = _deck(edhrec_bracket=2).substitute("Sol Ring", Card("Mana Crypt", 1))
    assert edited.edhrec_bracket is None
    out = compute_readouts(http=None, deck=edited)
    assert out.bracket.source == "spellbook"
    assert out.bracket.bracket == 4  # R -> 4
