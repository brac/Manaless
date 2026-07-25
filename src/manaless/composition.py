"""Deck composition vs. the EDHREC per-commander average (build step 4 readout).

Answers "am I overloading on lands / short on creatures **for this commander**".
The baseline is deliberately per-commander rather than a global rule of thumb
(the usual "36-38 lands, 10 ramp, ..." template): the averages differ enough
between commanders that a global number is actively misleading — the average
Krenko deck runs 31 creatures and 29 basics, the average Thrasios deck runs 25
creatures and 15 instants.

Two things this module is careful about:

- **Types, not functions.** EDHREC's counts are primary *card types*, so they are
  compared against `DeckModel.categorized()`, which buckets the same way. They are
  NOT comparable to `card_category.functional_category` — EDHREC files Sol Ring
  under Artifact, that classifier calls it Ramp. Diffing those two would produce
  nonsense, so they stay separate readouts.
- **Mainboard only.** EDHREC's scalars exclude the commander (verified against its
  own average decklists), and `categorized()` excludes commanders too, so both
  sides agree without an off-by-one fudge.

Everything here is pure: no I/O, recomputed on every edit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from manaless.deck_model import CATEGORY_ORDER, DeckModel
from manaless.edhrec_client import CommanderAverage

# Curve buckets are exact mana values in EDHREC's data (a big-mana commander really
# does report a bucket at 13), but a per-MV column past this point is noise in a
# sidebar. Both sides fold everything >= this into one "7+" tail, so the comparison
# stays like-for-like.
CURVE_TAIL = 7

# How far from the average counts as worth flagging. Deliberately one flat number
# rather than per-category tuning: the line is genuinely fuzzy, and a hand-tuned
# threshold per category would dress a guess up as precision. Tune in one place.
NOTABLE_DELTA = 3

# The headline "furthest from average" line is a glance, not an inventory — past a
# few entries it reads as noise, and the full table sits directly below it anyway.
NOTABLE_LIMIT = 3


@dataclass(frozen=True, slots=True)
class CompositionRow:
    """One category (or curve bucket): the deck's count against the average."""

    label: str
    actual: int
    average: int | None

    @property
    def delta(self) -> int | None:
        """Deck minus average, or ``None`` when there's no baseline to compare to."""
        return None if self.average is None else self.actual - self.average

    @property
    def notable(self) -> bool:
        """True when the gap is big enough to be worth the user's attention."""
        delta = self.delta
        return delta is not None and abs(delta) >= NOTABLE_DELTA


@dataclass(frozen=True, slots=True)
class Composition:
    """The full readout: type rows, curve rows, and the land basic/nonbasic split.

    ``average is None`` when EDHREC has no page for the commander — the rows still
    carry the deck's own counts so the panel degrades to a plain breakdown rather
    than vanishing (the §5 "thin data" posture).
    """

    types: tuple[CompositionRow, ...]
    curve: tuple[CompositionRow, ...]
    has_average: bool

    @property
    def notable(self) -> tuple[CompositionRow, ...]:
        """The biggest gaps from average, worst first, capped at `NOTABLE_LIMIT`."""
        rows = [r for r in self.types if r.notable]
        rows.sort(key=lambda r: abs(r.delta or 0), reverse=True)
        return tuple(rows[:NOTABLE_LIMIT])


def deck_type_counts(deck: DeckModel) -> dict[str, int]:
    """Mainboard card count per primary type, quantity-aware.

    Commanders are excluded to match EDHREC's baseline. A stacked entry
    (``10 Forest``) contributes all ten, not one.
    """
    counts: dict[str, int] = {}
    for card in deck.cards:
        counts[card.category] = counts.get(card.category, 0) + card.quantity
    return counts


def deck_curve(deck: DeckModel) -> dict[int, int]:
    """Nonland mainboard count per mana value, quantity-aware.

    Lands are excluded because EDHREC's curve is a nonland curve; an unresolved
    card (no type line, mana value 0) would otherwise pile up a phantom 0-drop, so
    those are skipped too.
    """
    curve: dict[int, int] = {}
    for card in deck.cards:
        if not card.resolved or card.category == "Land":
            continue
        bucket = int(card.mana_value)
        curve[bucket] = curve.get(bucket, 0) + card.quantity
    return curve


def _fold_tail(counts: Mapping[int, int]) -> dict[int, int]:
    """Collapse every bucket at or past `CURVE_TAIL` into the tail bucket."""
    folded: dict[int, int] = {}
    for mv, count in counts.items():
        folded[min(mv, CURVE_TAIL)] = folded.get(min(mv, CURVE_TAIL), 0) + count
    return folded


def compare(deck: DeckModel, average: CommanderAverage | None) -> Composition:
    """Build the readout for ``deck`` against ``average`` (``None`` = no baseline)."""
    actual_types = deck_type_counts(deck)
    avg_types = average.types if average else {}

    # Show a type row when either side uses it, so an empty-but-expected category
    # (0 planeswalkers against an average of 6) still surfaces as a gap, while a
    # category both sides ignore (Battle, almost always) doesn't pad the panel.
    type_rows = [
        CompositionRow(
            label=label,
            actual=actual_types.get(label, 0),
            average=avg_types.get(label) if average else None,
        )
        for label in CATEGORY_ORDER
        if actual_types.get(label) or avg_types.get(label)
    ]
    # "Other" has no EDHREC counterpart; include it only when the deck has some, so
    # an unclassifiable card can't silently vanish from the breakdown.
    if actual_types.get("Other"):
        type_rows.append(CompositionRow("Other", actual_types["Other"], None))

    actual_curve = _fold_tail(deck_curve(deck))
    avg_curve = _fold_tail(average.curve) if average else {}
    buckets = sorted(set(actual_curve) | set(avg_curve))
    curve_rows = [
        CompositionRow(
            label=f"{mv}+" if mv >= CURVE_TAIL else str(mv),
            actual=actual_curve.get(mv, 0),
            average=avg_curve.get(mv) if average else None,
        )
        for mv in buckets
    ]

    return Composition(
        types=tuple(type_rows),
        curve=tuple(curve_rows),
        has_average=average is not None,
    )
