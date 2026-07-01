"""Functional-category classifier for swap suggestions (build step 4).

EDHREC's commander JSON carries only card *popularity*, no functional tags, so
"same-category" swap suggestions need the category inferred from Scryfall
``type_line`` + ``oracle_text``. This is a small, explainable oracle-text
heuristic in the same spirit as ``win_conditions._infer_noncombo_plan`` —
lowercased substrings plus a few regexes.

Functional categories (Ramp / Removal / Card Draw / Board Wipe / Counterspell)
are matched *first*; anything that matches none falls back to its primary card
type via ``deck_model.CATEGORY_ORDER`` (the single source of truth the deck list
already groups by). The point is match quality in the swap modal — this is
deliberately **not** wired into ``DeckModel.categorized()``.

Deliberate edge cases (all intentional for swap matching):
- Mana dorks / mana rocks (Llanowar Elves, Sol Ring) → **Ramp**, not Creature /
  Artifact — you swap a ramp piece for a ramp piece.
- Basic / utility lands (Swamp, Command Tower) → **Land**: the Ramp check is
  guarded to skip anything whose front face is a Land, so a land that "adds mana"
  isn't mislabelled Ramp.
- A board wipe (Wrath of God) outranks single-target Removal even though its text
  also matches removal verbs — Board Wipe is checked first.
- Incidental draw on a permanent (a creature that draws a card) → **Card Draw**.
"""

from __future__ import annotations

import re

from manaless.deck_model import CATEGORY_ORDER

_OTHER = "Other"  # matches deck_model's fallback label; used when nothing else fits

# --- functional categories, in precedence order (first match wins) ------------
BOARD_WIPE = "Board Wipe"
REMOVAL = "Removal"
COUNTERSPELL = "Counterspell"
RAMP = "Ramp"
CARD_DRAW = "Card Draw"

# Board wipe: mass destruction/exile/bounce/sacrifice. Checked before Removal so a
# wrath (which also matches "destroy target"-style verbs on tokens) lands here.
_BOARD_WIPE_SUBSTRINGS = (
    "destroy all",
    "exile all",
    "destroy each",
    "exile each",
    "all creatures get -",
    "each player sacrifices",
    "return all",
)
_BOARD_WIPE_RE = re.compile(r"damage to each (?:creature|other creature)")

# Single-target interaction: destroy/exile/bounce/burn one thing.
_REMOVAL_SUBSTRINGS = (
    "destroy target",
    "exile target",
    "target creature gets -",
)
_REMOVAL_RE = re.compile(
    r"damage to (?:target|any target)"
    r"|return target .*to (?:its|their) owner'?s hand"
)

_COUNTERSPELL_SUBSTRING = "counter target"

# Ramp: adds mana / makes treasure / ramps lands. Guarded so a Land (which also
# "adds mana") is never called Ramp — those stay in the Land bucket.
_RAMP_SUBSTRINGS = (
    "add one mana",
    "add two mana",
    "add that much",
    "treasure token",
    "additional land",
)
_RAMP_RE = re.compile(r"add \{|search your library for .*land")

# Card draw: "draw a/one/two/... cards" or the bare "draw cards".
_CARD_DRAW_RE = re.compile(
    r"draws?\s+(?:a|one|two|three|four|five|six|seven|x|that many|\d+)\s+cards?"
)


def _front(type_line: str) -> str:
    """Front-face type line (DFCs join with ``//``)."""
    return (type_line or "").split("//", 1)[0]


def functional_category(type_line: str, oracle_text: str) -> str:
    """Classify a card into a functional or primary-type category.

    Functional categories win over card type: e.g. a mana rock is ``"Ramp"``,
    not ``"Artifact"``. See the module docstring for the deliberate edge cases.
    """
    text = (oracle_text or "").casefold()
    front = _front(type_line)

    if any(s in text for s in _BOARD_WIPE_SUBSTRINGS) or _BOARD_WIPE_RE.search(text):
        return BOARD_WIPE
    if any(s in text for s in _REMOVAL_SUBSTRINGS) or _REMOVAL_RE.search(text):
        return REMOVAL
    if _COUNTERSPELL_SUBSTRING in text:
        return COUNTERSPELL
    if "Land" not in front and (
        any(s in text for s in _RAMP_SUBSTRINGS) or _RAMP_RE.search(text)
    ):
        return RAMP
    if _CARD_DRAW_RE.search(text) or "draw cards" in text:
        return CARD_DRAW

    # Fallback: primary card type (same precedence the deck list groups by).
    for category in CATEGORY_ORDER:
        if category in front:
            return category
    return _OTHER


def category_of(card) -> str:
    """``functional_category`` for a card object.

    Works for any object exposing ``.type_line`` / ``.oracle_text`` — both
    ``deck_model.Card`` and ``scryfall_client.ScryfallCard`` qualify.
    """
    return functional_category(card.type_line, card.oracle_text)
