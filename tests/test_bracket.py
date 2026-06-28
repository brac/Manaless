"""bracket — bracketTag->1-5 resolution, EDHREC-label preference, custom signals."""

from manaless.bracket import evaluate_bracket
from manaless.deck_model import Card, DeckModel
from manaless.spellbook_client import BracketEstimate, ClassifiedCard, ClassifiedCombo


def _deck(cards, commander="Cmd", edhrec_bracket=None):
    return DeckModel(
        commanders=(Card(name=commander, quantity=1),),
        cards=tuple(cards),
        edhrec_bracket=edhrec_bracket,
    )


def _estimate(tag, cards=(), combos=()):
    return BracketEstimate(tag=tag, cards=tuple(cards), combos=tuple(combos))


def _gc(name):
    return ClassifiedCard(name=name, game_changer=True, banned=False, mass_land_denial=False, extra_turn=False)


def _mld(name):
    return ClassifiedCard(name=name, game_changer=False, banned=False, mass_land_denial=True, extra_turn=False)


def _fast_combo():
    return ClassifiedCombo(
        relevant=True, arguably_two_card=True, definitely_two_card=True, speed=4,
        lock=False, extra_turn=False, mass_land_denial=False, skip_turns=False,
        control_all_opponents=False, control_some_opponents=False,
    )


def test_core_tag_maps_to_two():
    out = evaluate_bracket(_deck([Card("Llanowar Elves", 1)]), _estimate("C"))
    assert out.bracket == 2
    assert out.source == "spellbook"
    assert out.legal is True


def test_exhibition_tag_defaults_to_core_two():
    # "E" is a floor (nothing forces it up), but a clean comboless deck reads as
    # bracket 2 (Core) — inference never emits the self-declared bracket 1.
    assert evaluate_bracket(_deck([]), _estimate("E")).bracket == 2


def test_banned_card_is_not_legal():
    est = _estimate("B", cards=[ClassifiedCard("Channel", False, True, False, False)])
    out = evaluate_bracket(_deck([Card("Channel", 1)]), est)
    assert out.bracket is None
    assert out.legal is False
    assert "Channel" in out.reasons[0]


def test_oddball_nudges_to_three_with_a_game_changer():
    plain = evaluate_bracket(_deck([Card("Forest", 1)]), _estimate("O"))
    powered = evaluate_bracket(_deck([Card("Rhystic Study", 1)]), _estimate("O", cards=[_gc("Rhystic Study")]))
    assert plain.bracket == 2          # no power signal -> low end of 2-3
    assert powered.bracket == 3        # a Game Changer -> high end


def test_spicy_resolves_to_four_on_high_power():
    low = evaluate_bracket(_deck([Card("X", 1)]), _estimate("S"))
    high = evaluate_bracket(_deck([Card("Armageddon", 1)]), _estimate("S", cards=[_mld("Armageddon")]))
    assert low.bracket == 3
    assert high.bracket == 4           # mass land denial pushes Spicy to 4
    assert high.mass_land_denial == 1


def test_powerful_tag_goes_to_four_when_gamechanger_dense():
    cards = [_gc(f"GC{i}") for i in range(4)]
    out = evaluate_bracket(_deck([Card(f"GC{i}", 1) for i in range(4)]), _estimate("P", cards=cards))
    assert out.bracket == 4
    assert len(out.game_changers) == 4


def test_ruthless_bumps_to_five_only_at_cedh_density():
    gcs = [_gc(f"GC{i}") for i in range(5)]
    fast = [Card(n, 1) for n in ("Sol Ring", "Mana Crypt", "Mana Vault", "Chrome Mox")]
    deck = _deck([Card(f"GC{i}", 1) for i in range(5)] + fast)
    cedh = evaluate_bracket(deck, _estimate("R", cards=gcs, combos=[_fast_combo()]))
    assert cedh.bracket == 5
    # Same tag, but without the fast-mana density, stays at 4.
    lean = evaluate_bracket(_deck([Card("GC0", 1)]), _estimate("R", cards=[_gc("GC0")]))
    assert lean.bracket == 4


def test_edhrec_label_preferred_for_unmodified_deck():
    # Even though the Spellbook tag says S (3-4), an unmodified deck trusts the label.
    out = evaluate_bracket(_deck([Card("X", 1)], edhrec_bracket=3), _estimate("S"), edhrec_bracket=3)
    assert out.bracket == 3
    assert out.source == "edhrec-label"
    assert out.tag == "S"  # still surfaced as a cross-check


def test_custom_signals_detected():
    deck = _deck([
        Card("Sol Ring", 1),
        Card("Force of Will", 1),
        Card("Demonic Tutor", 1, type_line="Sorcery", oracle_text="Search your library for a card..."),
        Card("Evolving Wilds", 1, type_line="Land", oracle_text="Search your library for a basic land card..."),
    ])
    out = evaluate_bracket(deck, _estimate("C"))
    assert out.fast_mana == ("Sol Ring",)
    assert out.free_interaction == ("Force of Will",)
    assert out.tutors == ("Demonic Tutor",)  # land tutor excluded (off-rubric anyway)


def test_heuristic_path_without_estimate_or_label():
    # No Spellbook estimate, no EDHREC label -> rough local guess from density.
    out = evaluate_bracket(_deck([Card("Sol Ring", 1), Card("Mana Crypt", 1)]), None)
    assert out.source == "heuristic"
    assert out.bracket == 3  # >=2 fast mana -> 3
    assert out.tag is None
