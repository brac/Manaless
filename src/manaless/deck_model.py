"""Deck model — the in-memory deck the UI mutates (build step 4; architecture.md).

Single source of truth for the current build. `Card` and `DeckModel` are
immutable (frozen) — substitutions (step 4) will produce a *new* `DeckModel`
rather than mutate in place, per coding-style. Kept UI-agnostic so the pipeline
runs headless for batch practice-ladder generation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Primary-type precedence for categorising a card (first match wins). A card with
# multiple types (e.g. "Artifact Creature", "Land Creature") lands in the more
# salient bucket — matching how deckbuilding sites group cards.
CATEGORY_ORDER = (
    "Creature",
    "Planeswalker",
    "Battle",
    "Instant",
    "Sorcery",
    "Artifact",
    "Enchantment",
    "Land",
)
_OTHER = "Other"


@dataclass(frozen=True, slots=True)
class Card:
    """A card in the deck: source quantity/name plus Scryfall enrichment.

    `resolved=False` marks a card whose enrichment failed (kept so a single bad
    name never drops a card from the deck silently — see `DeckModel.unresolved`).
    """

    name: str
    quantity: int
    type_line: str = ""
    oracle_text: str = ""
    mana_value: float = 0.0
    color_identity: tuple[str, ...] = ()
    image_url: str | None = None
    scryfall_uri: str | None = None
    is_dfc: bool = False
    resolved: bool = True

    @property
    def category(self) -> str:
        """Primary type bucket from the (front-face) type line."""
        front = self.type_line.split("//", 1)[0]
        for category in CATEGORY_ORDER:
            if category in front:
                return category
        return _OTHER


@dataclass(frozen=True, slots=True)
class DeckModel:
    """An enriched deck: commander(s) + mainboard, plus its EDHREC provenance."""

    commanders: tuple[Card, ...]
    cards: tuple[Card, ...]
    deck_id: str | None = None
    source_url: str | None = None
    # EDHREC's own power label (1-5) for the *source* deck, when picked from the
    # deck table. Prefer it for an unmodified deck; it goes stale once the user
    # substitutes (build step 3 re-infers via estimate-bracket). See verified.md §6.
    edhrec_bracket: int | None = None

    def all_cards(self) -> tuple[Card, ...]:
        return self.commanders + self.cards

    @property
    def total_cards(self) -> int:
        return sum(card.quantity for card in self.all_cards())

    @property
    def unresolved(self) -> tuple[str, ...]:
        """Names whose Scryfall enrichment failed."""
        return tuple(card.name for card in self.all_cards() if not card.resolved)

    def card_names(self) -> list[str]:
        return [card.name for card in self.all_cards()]

    def to_decklist(self) -> list[str]:
        """Flat ``["1 Card Name", ...]`` lines (commanders first)."""
        return [f"{card.quantity} {card.name}" for card in self.all_cards()]

    # --- substitution (build step 4) -------------------------------------
    # All mutators are pure: they return a NEW DeckModel (frozen). Substituting
    # invalidates the source provenance, so `edhrec_bracket`/`deck_id` are
    # cleared — bracket/win-conditions must re-infer from the new list. Cards are
    # matched by case-folded name. Commanders are never touched by these.

    def remove(self, name: str) -> "DeckModel":
        """Drop the mainboard card matching ``name`` (case-insensitive)."""
        folded = name.casefold()
        kept = tuple(c for c in self.cards if c.name.casefold() != folded)
        if len(kept) == len(self.cards):
            raise KeyError(f"{name!r} is not in the mainboard")
        return self._substituted(kept)

    def add(self, card: Card) -> "DeckModel":
        """Add ``card`` to the mainboard, merging quantities if it's already in."""
        folded = card.name.casefold()
        merged, found = [], False
        for existing in self.cards:
            if existing.name.casefold() == folded:
                merged.append(replace(card, quantity=existing.quantity + card.quantity))
                found = True
            else:
                merged.append(existing)
        if not found:
            merged.append(card)
        return self._substituted(tuple(merged))

    def substitute(self, old_name: str, new_card: Card) -> "DeckModel":
        """Swap ``old_name`` out for ``new_card`` (remove then add)."""
        return self.remove(old_name).add(new_card)

    def _substituted(self, cards: tuple[Card, ...]) -> "DeckModel":
        """New model with a changed mainboard; source provenance cleared."""
        return replace(self, cards=cards, edhrec_bracket=None, deck_id=None)

    def categorized(self) -> dict[str, list[Card]]:
        """Mainboard grouped by primary type, in `CATEGORY_ORDER` order.

        Commanders are excluded — they are surfaced separately by callers.
        """
        groups: dict[str, list[Card]] = {}
        for card in self.cards:
            groups.setdefault(card.category, []).append(card)
        ordered = {cat: groups[cat] for cat in CATEGORY_ORDER if cat in groups}
        if _OTHER in groups:
            ordered[_OTHER] = groups[_OTHER]
        return ordered
