"""Commander Spellbook client — combos + bracket baseline (build steps 2/3).

POST a decklist to ``find-my-combos`` (combos present + the "almost included"
pool that powers the "Add 1" feature) and, later, ``estimate-bracket``. Results
are cached by a decklist hash — stable for a fixed list, so a substitution is the
only thing that triggers a fresh call.

Schemas live-verified 2026-06-27 (see docs/verified.md §1): the top-level
``{count, next, previous, results}`` wrapper is **not** actually paginated
(``next``/``previous`` come back null), so we read ``results`` directly. Each
combo is a ``Variant`` with ``uses[].card.name``, ``produces[].feature.name``,
``popularity`` and ``bracketTag``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from manaless.deck_model import DeckModel
from manaless.http.client import HttpClient

BASE_URL = "https://backend.commanderspellbook.com"
FIND_MY_COMBOS_URL = f"{BASE_URL}/find-my-combos"
ESTIMATE_BRACKET_URL = f"{BASE_URL}/estimate-bracket"
CACHE_NAMESPACE = "spellbook-combos"
BRACKET_CACHE_NAMESPACE = "spellbook-bracket"


@dataclass(frozen=True, slots=True)
class Combo:
    """One Spellbook combo (``Variant``), flattened to what the UI needs."""

    id: str
    cards: tuple[str, ...]       # every card the combo uses, by name
    produces: tuple[str, ...]    # produced effects, e.g. "Infinite mana"
    popularity: int              # EDHREC decks running it
    bracket_tag: str | None      # E/C/O/P/S/R/B (per-combo bracket floor)


@dataclass(frozen=True, slots=True)
class ComboResults:
    """The slice of ``find-my-combos`` we use: combos in the deck + near-misses.

    ``almost_included`` is "missing ≥1 card but within color identity" — the raw
    pool the win-condition engine filters down to genuine one-card-away lines.
    """

    identity: str
    included: tuple[Combo, ...]
    almost_included: tuple[Combo, ...]


def decklist_hash(deck: DeckModel) -> str:
    """Order-independent hash of the deck's cards, keyed by role + qty + name.

    Two builds with the same cards hash the same (so caching is substitution-
    driven); moving a card between commander and mainboard changes the hash
    because the commander defines color identity, which Spellbook keys on.
    """
    lines = [f"C {c.quantity} {c.name}" for c in deck.commanders]
    lines += [f"M {c.quantity} {c.name}" for c in deck.cards]
    canonical = "\n".join(sorted(lines))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def find_my_combos(http: HttpClient, deck: DeckModel) -> ComboResults:
    """POST the deck to ``find-my-combos`` and return the parsed results (cached)."""
    key = decklist_hash(deck)
    cached = http.cache.get(CACHE_NAMESPACE, key)
    if cached is None:
        cached = http.post_json(FIND_MY_COMBOS_URL, _deck_request(deck))
        http.cache.set(CACHE_NAMESPACE, key, cached)
    return _parse_results(cached)


def _deck_request(deck: DeckModel) -> dict:
    """Build the Spellbook ``DeckRequest`` body from a deck model."""
    return {
        "commanders": [{"card": c.name, "quantity": c.quantity} for c in deck.commanders],
        "main": [{"card": c.name, "quantity": c.quantity} for c in deck.cards],
    }


def _parse_results(payload: dict) -> ComboResults:
    results = payload.get("results") or {}
    return ComboResults(
        identity=results.get("identity", ""),
        included=tuple(_parse_combo(v) for v in results.get("included", [])),
        almost_included=tuple(_parse_combo(v) for v in results.get("almostIncluded", [])),
    )


def _parse_combo(variant: dict) -> Combo:
    cards = tuple(
        (use.get("card") or {}).get("name", "")
        for use in variant.get("uses", [])
    )
    produces = tuple(
        (prod.get("feature") or {}).get("name", "")
        for prod in variant.get("produces", [])
    )
    return Combo(
        id=str(variant.get("id", "")),
        cards=tuple(name for name in cards if name),
        produces=tuple(name for name in produces if name),
        popularity=int(variant.get("popularity") or 0),
        bracket_tag=variant.get("bracketTag"),
    )


@dataclass(frozen=True, slots=True)
class ClassifiedCard:
    """A bracket-relevant card flagged by ``estimate-bracket`` against the rubric."""

    name: str
    game_changer: bool
    banned: bool
    mass_land_denial: bool
    extra_turn: bool


@dataclass(frozen=True, slots=True)
class ClassifiedCombo:
    """A combo classified by ``estimate-bracket`` (the bracket rubric's combo axis)."""

    relevant: bool
    arguably_two_card: bool
    definitely_two_card: bool
    speed: int
    lock: bool
    extra_turn: bool
    mass_land_denial: bool
    skip_turns: bool
    control_all_opponents: bool
    control_some_opponents: bool


@dataclass(frozen=True, slots=True)
class BracketEstimate:
    """Parsed ``estimate-bracket`` result: the headline tag + classified pieces.

    ``tag`` is one of E/C/O/P/S/R/B (Exhibition..Ruthless, or B = a banned card is
    present so the deck is not legal in any bracket). The flags on ``cards`` /
    ``combos`` are the official-rubric inputs (see docs/verified.md §2).
    """

    tag: str
    cards: tuple[ClassifiedCard, ...]
    combos: tuple[ClassifiedCombo, ...]


def estimate_bracket(http: HttpClient, deck: DeckModel) -> BracketEstimate:
    """POST the deck to ``estimate-bracket`` and return the parsed result (cached)."""
    key = decklist_hash(deck)
    cached = http.cache.get(BRACKET_CACHE_NAMESPACE, key)
    if cached is None:
        cached = http.post_json(ESTIMATE_BRACKET_URL, _deck_request(deck))
        http.cache.set(BRACKET_CACHE_NAMESPACE, key, cached)
    return _parse_bracket(cached)


def _parse_bracket(payload: dict) -> BracketEstimate:
    cards = tuple(
        ClassifiedCard(
            name=(c.get("card") or {}).get("name", ""),
            game_changer=bool(c.get("gameChanger")),
            banned=bool(c.get("banned")),
            mass_land_denial=bool(c.get("massLandDenial")),
            extra_turn=bool(c.get("extraTurn")),
        )
        for c in payload.get("cards", [])
    )
    combos = tuple(
        ClassifiedCombo(
            relevant=bool(c.get("relevant")),
            arguably_two_card=bool(c.get("arguablyTwoCard")),
            definitely_two_card=bool(c.get("definitelyTwoCard")),
            speed=int(c.get("speed") or 0),
            lock=bool(c.get("lock")),
            extra_turn=bool(c.get("extraTurn")),
            mass_land_denial=bool(c.get("massLandDenial")),
            skip_turns=bool(c.get("skipTurns")),
            control_all_opponents=bool(c.get("controlAllOpponents")),
            control_some_opponents=bool(c.get("controlSomeOpponents")),
        )
        for c in payload.get("combos", [])
    )
    return BracketEstimate(tag=payload.get("bracketTag", ""), cards=cards, combos=combos)
