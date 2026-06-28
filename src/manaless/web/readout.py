"""Recompute glue — run both engines over a deck and bundle their readouts.

The one place the win-condition (step 2) and bracket (step 3) engines are driven
together. Called once when a deck is first built and again on every substitution;
both Spellbook POSTs cache by `decklist_hash`, so an unchanged list never re-hits
the network. Kept thin and pure-ish (the only I/O is the injected ``http``) so it
unit-tests with fakes — same injection pattern as `deck_builder`/`win_conditions`.
"""

from __future__ import annotations

from dataclasses import dataclass

from manaless.bracket import BracketReadout, evaluate_bracket
from manaless.deck_model import DeckModel
from manaless.http.client import HttpClient
from manaless.spellbook_client import estimate_bracket, find_my_combos
from manaless.win_conditions import WinConditions, evaluate_win_conditions


@dataclass(frozen=True, slots=True)
class Readouts:
    """The live feedback panel for the current build: win conditions + bracket."""

    win_conditions: WinConditions
    bracket: BracketReadout


def compute_readouts(http: HttpClient, deck: DeckModel) -> Readouts:
    """Evaluate win conditions + bracket for ``deck`` (one network-cached pass).

    ``deck.edhrec_bracket`` is the source deck's EDHREC label for the *unmodified*
    deck and ``None`` after any substitution (cleared by ``DeckModel.substitute``),
    so passing it straight through gives the right behaviour automatically: trust
    the label until the user edits, then re-infer from ``estimate-bracket``.
    """
    combos = find_my_combos(http, deck)
    win_conditions = evaluate_win_conditions(deck, combos)

    estimate = estimate_bracket(http, deck)
    bracket = evaluate_bracket(deck, estimate, edhrec_bracket=deck.edhrec_bracket)

    return Readouts(win_conditions=win_conditions, bracket=bracket)
