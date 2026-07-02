"""win_conditions — three-source merge: add-1 filter, alt-win scan, non-combo heuristic."""

from manaless.deck_model import Card, DeckModel
from manaless.spellbook_client import Combo, ComboResults
from manaless.win_conditions import evaluate_win_conditions


def _combo(cards, produces=("Infinite mana",), pop=100):
    return Combo(id="x", cards=tuple(cards), produces=tuple(produces), popularity=pop, bracket_tag="S")


def _deck(cards, commander="Cmd"):
    return DeckModel(
        commanders=(Card(name=commander, quantity=1),),
        cards=tuple(cards),
    )


def test_present_combo_drives_primary_combo():
    deck = _deck([Card("Sol Ring", 1), Card("Basalt Monolith", 1)])
    combos = ComboResults(identity="C", included=(_combo(["Sol Ring", "Basalt Monolith"]),), almost_included=())
    wc = evaluate_win_conditions(deck, combos)
    assert wc.primary == "combo"
    assert wc.combos[0].cards == ("Sol Ring", "Basalt Monolith")


def test_add_one_keeps_only_exactly_one_missing():
    deck = _deck([Card("Sol Ring", 1)])
    combos = ComboResults(
        identity="C",
        included=(),
        almost_included=(
            _combo(["Sol Ring", "Basalt Monolith"]),          # missing 1 -> add-1
            _combo(["Sol Ring", "Mana Vault", "Kiki-Jiki"]),  # missing 2 -> dropped
        ),
    )
    wc = evaluate_win_conditions(deck, combos)
    assert wc.primary == "combo (one card away)"
    assert len(wc.add_one) == 1
    line = wc.add_one[0]
    assert line.add == "Basalt Monolith"
    assert line.completes == 1
    assert line.example_with == ("Sol Ring",)


def test_add_one_groups_and_ranks_by_card_to_add():
    # Adding "Kiki-Jiki" completes two different lines already started in the deck.
    deck = _deck([Card("Sol Ring", 1), Card("Pestermite", 1), Card("Deceiver Exarch", 1)])
    combos = ComboResults(
        identity="C",
        included=(),
        almost_included=(
            _combo(["Kiki-Jiki", "Pestermite"], pop=500),
            _combo(["Kiki-Jiki", "Deceiver Exarch"], pop=900),
            _combo(["Sol Ring", "Basalt Monolith"], pop=10),  # different card, one line
        ),
    )
    wc = evaluate_win_conditions(deck, combos)
    assert [a.add for a in wc.add_one] == ["Kiki-Jiki", "Basalt Monolith"]  # 2 lines beats 1
    kiki = wc.add_one[0]
    assert kiki.completes == 2
    assert kiki.popularity == 900
    assert kiki.example_with == ("Deceiver Exarch",)  # pieces of the most-played line


def test_alt_win_scan_flags_win_the_game_text():
    deck = _deck([
        Card("Thassa's Oracle", 1, oracle_text="...you win the game."),
        Card("Sol Ring", 1, oracle_text="{T}: Add {C}{C}."),
    ])
    wc = evaluate_win_conditions(deck, ComboResults("C", (), ()))
    assert wc.alt_wins == ("Thassa's Oracle",)
    assert wc.primary == "alternate win"


def test_alt_win_scan_excludes_cant_win_the_game():
    # Platinum Angel says "you can't win the game" — a liability, not a wincon.
    deck = _deck([
        Card("Platinum Angel", 1, oracle_text="You can't lose the game and your opponents can't win the game."),
        Card("Thassa's Oracle", 1, oracle_text="...you win the game."),
    ])
    wc = evaluate_win_conditions(deck, ComboResults("C", (), ()))
    assert wc.alt_wins == ("Thassa's Oracle",)  # Platinum Angel excluded


def test_noncombo_aggro_profile_and_fallback():
    creatures = [
        Card(f"Beater {i}", 1, type_line="Creature — Beast", oracle_text="Flying")
        for i in range(20)
    ]
    deck = _deck(creatures)
    wc = evaluate_win_conditions(deck, ComboResults("C", (), ()))
    top_label, top_score = wc.noncombo_profile[0]
    assert top_label == "aggro / combat"
    assert wc.fallback_plan == "aggro / combat"
    assert wc.primary == "aggro / combat"  # no combos, no alt-wins -> falls back
    assert top_score >= 4


def test_mill_and_tokens_signals():
    deck = _deck([
        Card("Miller", 1, oracle_text="Each opponent mills four cards."),
        Card("Maker", 1, oracle_text="Create three 1/1 green Saproling creature tokens."),
    ])
    profile = dict(evaluate_win_conditions(deck, ComboResults("C", (), ())).noncombo_profile)
    assert profile.get("mill", 0) >= 1
    assert profile.get("go-wide tokens", 0) >= 1


def test_self_mill_and_nontoken_do_not_score():
    # Self-mill dorks and Treasure/Clue makers must NOT read as mill / go-wide plans.
    deck = _deck([
        Card("Stitcher's Supplier", 1, oracle_text="When this enters, mill three cards."),
        Card("Smothering Tithe", 1, oracle_text="Whenever an opponent draws, create a Treasure token unless they pay."),
    ])
    profile = dict(evaluate_win_conditions(deck, ComboResults("C", (), ())).noncombo_profile)
    assert profile.get("mill", 0) == 0        # self-mill, not opponent-facing
    assert profile.get("go-wide tokens", 0) == 0  # Treasure, not creature tokens


def test_combo_completeness_reports_assembled_first():
    # An assembled combo plus an unrelated near-miss must report the assembled state.
    deck = _deck([Card("Sol Ring", 1), Card("Basalt Monolith", 1), Card("Kiki-Jiki", 1)])
    combos = ComboResults(
        identity="C",
        included=(_combo(["Sol Ring", "Basalt Monolith"]),),   # complete
        almost_included=(_combo(["Kiki-Jiki", "Pestermite"]),),  # 1 of 2
    )
    wc = evaluate_win_conditions(deck, combos)
    assert wc.combo_completeness == "1 combo complete"


def test_combo_completeness_reports_closest_line():
    deck = _deck([Card("Sol Ring", 1)])
    combos = ComboResults(
        identity="C",
        included=(),
        almost_included=(
            _combo(["Sol Ring", "A", "B"]),  # 1 of 3
            _combo(["Sol Ring", "C"]),       # 1 of 2  <- closest (fewest missing)
        ),
    )
    wc = evaluate_win_conditions(deck, combos)
    assert wc.combo_completeness == "1 of 2 pieces"


def test_add_one_matches_dfc_present_piece_against_front_face():
    # Spellbook names the in-deck piece with its full DFC spelling; the deck holds
    # the front face. The combo is genuinely one card away and must not be dropped.
    deck = _deck([Card("Fable of the Mirror-Breaker", 1)])
    combos = ComboResults(
        identity="C",
        included=(),
        almost_included=(
            _combo(["Fable of the Mirror-Breaker // Reflection of Kiki-Jiki", "Twinflame"]),
        ),
    )
    wc = evaluate_win_conditions(deck, combos)
    assert [a.add for a in wc.add_one] == ["Twinflame"]  # the only missing piece
    assert wc.combo_completeness == "1 of 2 pieces"       # present piece counted


def test_to_dict_shape_matches_spec():
    deck = _deck([Card("Sol Ring", 1), Card("Basalt Monolith", 1)])
    combos = ComboResults("C", (_combo(["Sol Ring", "Basalt Monolith"]),), ())
    out = evaluate_win_conditions(deck, combos).to_dict()
    assert set(out) == {"primary", "combos", "add_one", "alt_wins", "fallback_plan", "combo_completeness"}
    assert out["combos"][0]["popularity"] == 100
