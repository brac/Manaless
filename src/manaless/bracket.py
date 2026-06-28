"""Bracket estimator — inferred power level 1-5 (build step 3; bracket-evaluator.md).

Two paths, in priority order:

1. **EDHREC's own label.** The deck-table row carries a `bracket` (1-5) for the
   *source* deck (verified.md §6). For an UNMODIFIED deck, trust it — it's a human
   signal, not an inference. `DeckModel.edhrec_bracket` carries it through.
2. **Spellbook `estimate-bracket` + a small custom layer.** Once the user
   substitutes, the label is stale, so re-infer: map the API's `bracketTag`
   (E/C/O/P/S/R/B) onto 1-5, resolving the ambiguous tags (O, S, R) with the
   rubric flags the API already provides (Game Changers, mass land denial, fast
   two-card combos) plus a small local fast-mana / free-interaction density.

Mirrors Spellbook's own rubric (`brackets.ts` `computeBracketInfo`): the tag is
authoritative, and a banned card (`B`) means "not legal in any bracket". Tutors
are **off the official rubric** since 2025-10-21 (verified.md §3) — surfaced for
information only, never fed into the number.

`evaluate_bracket` is pure over the `DeckModel` + an injected `BracketEstimate`
(same test-without-network pattern as `win_conditions`/`deck_builder`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from manaless.deck_model import DeckModel
from manaless.paths import DATA_DIR
from manaless.spellbook_client import BracketEstimate

# bracketTag -> (range string, floor bracket). Floors/ranges per Spellbook's
# brackets.ts BRACKET_RANGE_MAP (verified.md §2). "B" = a banned card is present.
_TAG_RANGE = {
    "E": "1+",
    "C": "2+",
    "O": "2-3+",
    "P": "3+",
    "S": "3-4+",
    "R": "4+",
    "B": "N/A",
}
_TAG_LABEL = {
    "E": "Exhibition", "C": "Core", "O": "Oddball", "P": "Powerful",
    "S": "Spicy", "R": "Ruthless", "B": "Not Legal",
}

# A fast two-card combo: definite, game-winning, and fast (speed >= 4). This is
# the "no early-game 2-card infinite combos below bracket 4" rubric line.
_FAST_COMBO_SPEED = 4

# Curated, explainable signal sets (names compared case-insensitively). Kept
# small and obvious rather than exhaustive — tune as calibration shows drift.
_FAST_MANA = frozenset(n.casefold() for n in (
    "Sol Ring", "Mana Crypt", "Mana Vault", "Grim Monolith", "Basalt Monolith",
    "Chrome Mox", "Mox Diamond", "Mox Opal", "Mox Amber", "Lotus Petal",
    "Jeweled Lotus", "Lion's Eye Diamond", "Dark Ritual", "Cabal Ritual",
    "Rite of Flame", "Jeska's Will", "Culling the Weak", "Simian Spirit Guide",
    "Elvish Spirit Guide", "Mana Geyser",
))
_FREE_INTERACTION = frozenset(n.casefold() for n in (
    "Force of Will", "Force of Negation", "Fierce Guardianship", "Deflecting Swat",
    "Deadly Rollick", "Misdirection", "Pact of Negation", "Mindbreak Trap",
    "Mental Misstep", "Swan Song", "An Offer You Can't Refuse", "Flusterstorm",
    "Veil of Summer", "Dispel", "Solitude", "Subtlety", "Fury", "Grief",
))
# Tutor detection (off-rubric, informational): non-land "search your library".
_TUTOR_TEXT = "search your library"


@dataclass(frozen=True, slots=True)
class BracketReadout:
    """The inferred bracket readout for a deck (recomputed on every edit)."""

    bracket: int | None          # 1-5; None if not legal (banned card present)
    legal: bool
    source: str                  # "edhrec-label" | "spellbook" | "heuristic"
    tag: str | None              # Spellbook bracketTag, when that path ran
    tag_label: str | None        # human name for the tag
    bracket_range: str | None    # e.g. "3-4+"
    game_changers: tuple[str, ...]
    fast_mana: tuple[str, ...]
    free_interaction: tuple[str, ...]
    tutors: tuple[str, ...]      # off-rubric, informational only
    mass_land_denial: int
    extra_turns: int
    fast_combo: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "bracket": self.bracket,
            "legal": self.legal,
            "source": self.source,
            "tag": self.tag,
            "bracket_range": self.bracket_range,
            "game_changers": list(self.game_changers),
            "fast_mana": list(self.fast_mana),
            "free_interaction": list(self.free_interaction),
            "tutors": list(self.tutors),
            "mass_land_denial": self.mass_land_denial,
            "extra_turns": self.extra_turns,
            "fast_combo": self.fast_combo,
            "reasons": list(self.reasons),
        }


@lru_cache(maxsize=1)
def _game_changer_set() -> frozenset[str]:
    """The official Game Changers list (case-folded names), from the data snapshot.

    Used only when there's no Spellbook estimate to flag Game Changers per card;
    `estimate-bracket` flags them authoritatively, so this is a fallback.
    """
    try:
        data = json.loads((DATA_DIR / "game-changers.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    return frozenset(n.casefold() for n in data.get("cards", []))


def evaluate_bracket(
    deck: DeckModel,
    estimate: BracketEstimate | None = None,
    *,
    edhrec_bracket: int | None = None,
) -> BracketReadout:
    """Infer a 1-5 bracket. Pure; no network (``estimate`` is fetched by the caller).

    ``edhrec_bracket`` overrides inference for an unmodified deck (pass
    ``deck.edhrec_bracket``; the caller is responsible for not passing it once the
    deck has been substituted).
    """
    gc_names, fast_mana, free_int, tutors = _custom_signals(deck, estimate)
    mld = sum(1 for c in (estimate.cards if estimate else ()) if c.mass_land_denial)
    extra_turns = sum(1 for c in (estimate.cards if estimate else ()) if c.extra_turn)
    fast_combo = bool(estimate) and any(
        c.relevant and c.definitely_two_card and c.speed >= _FAST_COMBO_SPEED
        for c in estimate.combos
    )

    def readout(bracket, legal, source, tag, reasons):
        return BracketReadout(
            bracket=bracket, legal=legal, source=source,
            tag=tag, tag_label=_TAG_LABEL.get(tag) if tag else None,
            bracket_range=_TAG_RANGE.get(tag) if tag else None,
            game_changers=gc_names, fast_mana=fast_mana, free_interaction=free_int,
            tutors=tutors, mass_land_denial=mld, extra_turns=extra_turns,
            fast_combo=fast_combo, reasons=tuple(reasons),
        )

    # A banned card overrides everything: not legal in any bracket.
    if estimate and estimate.tag == "B":
        banned = [c.name for c in estimate.cards if c.banned]
        return readout(None, False, "spellbook", "B", [f"Banned card(s): {', '.join(banned)}"])

    # Path 1: trust EDHREC's own label for an unmodified deck.
    if edhrec_bracket is not None:
        reasons = [f"EDHREC deck-table label (bracket {edhrec_bracket})"]
        tag = estimate.tag if estimate else None
        if tag:
            reasons.append(f"Spellbook cross-check: {tag} ({_TAG_RANGE.get(tag)})")
        return readout(int(edhrec_bracket), True, "edhrec-label", tag, reasons)

    # Path 2: infer from the Spellbook tag, resolving ambiguous ranges.
    if estimate:
        bracket, reasons = _resolve_tag(
            estimate.tag, len(gc_names), mld, fast_combo, len(fast_mana)
        )
        return readout(bracket, True, "spellbook", estimate.tag, reasons)

    # Path 3 (no label, no estimate): rough local guess from density alone.
    bracket, reasons = _heuristic_only(len(gc_names), len(fast_mana))
    return readout(bracket, True, "heuristic", None, reasons)


def _resolve_tag(
    tag: str, gc: int, mld: int, fast_combo: bool, fast_mana: int
) -> tuple[int, list[str]]:
    """Map a bracketTag to a single 1-5, resolving O/S/R with rubric signals."""
    high_power = gc >= 4 or mld > 0 or fast_combo
    reasons = [f"Spellbook tag {tag} ({_TAG_RANGE.get(tag, '?')})"]
    if gc:
        reasons.append(f"{gc} Game Changer(s)")
    if mld:
        reasons.append("mass land denial present")
    if fast_combo:
        reasons.append("fast two-card combo present")

    # The tag is a *floor* from combo content, not the deck's actual bracket: "E"
    # means "nothing forces this above bracket 1". But WotC positions a clean,
    # comboless deck (every precon) as bracket 2 (Core), and bracket 1
    # (Exhibition) is a player-intent / theme choice that isn't reliably inferable
    # from the cards. So E and C both resolve to 2 — this is what makes the precon
    # calibration set cluster at 2 (see docs/bracket-evaluator.md). Inference does
    # not emit bracket 1; that's a deliberate self-declared casual bracket.
    if tag in ("E", "C"):
        return 2, reasons
    if tag == "O":  # 2-3+: nudge to 3 if any real power signal, else 2
        return (3 if (gc or fast_combo or mld) else 2), reasons
    if tag == "P":  # 3+: 4 if Game-Changer-dense
        return (4 if gc >= 4 else 3), reasons
    if tag == "S":  # 3-4+
        return (4 if high_power else 3), reasons
    if tag == "R":  # 4+: bump to cEDH (5) only on strong combined signals
        is_cedh = gc >= 5 and fast_mana >= 4
        if is_cedh:
            reasons.append("cEDH-level density (Game Changers + fast mana)")
        return (5 if is_cedh else 4), reasons
    return 2, [*reasons, "unknown tag — defaulted to 2"]


def _heuristic_only(gc: int, fast_mana: int) -> tuple[int, list[str]]:
    reasons = [f"No Spellbook estimate or EDHREC label; {gc} Game Changers, {fast_mana} fast mana"]
    if gc >= 5 and fast_mana >= 4:
        return 5, reasons
    if gc >= 4:
        return 4, reasons
    if gc >= 1 or fast_mana >= 2:
        return 3, reasons
    return 2, reasons


def _custom_signals(
    deck: DeckModel, estimate: BracketEstimate | None
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """(game_changers, fast_mana, free_interaction, tutors) over the deck."""
    if estimate:
        gc = tuple(c.name for c in estimate.cards if c.game_changer)
    else:
        gc_set = _game_changer_set()
        gc = tuple(c.name for c in deck.all_cards() if c.name.casefold() in gc_set)

    fast_mana, free_int, tutors = [], [], []
    for card in deck.all_cards():
        folded = card.name.casefold()
        if folded in _FAST_MANA:
            fast_mana.append(card.name)
        if folded in _FREE_INTERACTION:
            free_int.append(card.name)
        if _TUTOR_TEXT in card.oracle_text.casefold() and "Land" not in card.type_line:
            tutors.append(card.name)
    return gc, tuple(fast_mana), tuple(free_int), tuple(tutors)


def main() -> None:
    import argparse
    import sys

    from manaless.deck_builder import NoDecksAvailable, build_deck
    from manaless.edhrec_client import EdhrecClient
    from manaless.http.cache import DiskCache
    from manaless.http.client import HttpClient
    from manaless.paths import CACHE_DIR
    from manaless.scryfall_client import get_collection
    from manaless.spellbook_client import estimate_bracket

    parser = argparse.ArgumentParser(description="Inferred bracket (1-5) for an EDHREC deck (step 3).")
    parser.add_argument("commander", nargs="?", default="Atraxa, Praetors' Voice")
    parser.add_argument("--infer", action="store_true", help="ignore the EDHREC label; force Spellbook inference")
    args = parser.parse_args()

    with HttpClient(DiskCache(CACHE_DIR)) as http:
        edhrec = EdhrecClient(http)
        try:
            deck = build_deck(edhrec, lambda names: get_collection(http, names)[0], args.commander)
        except NoDecksAvailable as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        estimate = estimate_bracket(http, deck)

    label = None if args.infer else deck.edhrec_bracket
    readout = evaluate_bracket(deck, estimate, edhrec_bracket=label)
    verdict = "NOT LEGAL" if readout.bracket is None else f"bracket {readout.bracket}"
    print(f"commander(s): {', '.join(c.name for c in deck.commanders)}")
    print(f"verdict     : {verdict}   (source: {readout.source})")
    if readout.tag:
        print(f"spellbook   : {readout.tag} {readout.tag_label} ({readout.bracket_range})")
    print(f"edhrec label: {deck.edhrec_bracket}")
    print(f"game chngrs : {len(readout.game_changers)} -> {', '.join(readout.game_changers) or '(none)'}")
    print(f"fast mana   : {len(readout.fast_mana)} -> {', '.join(readout.fast_mana) or '(none)'}")
    print(f"free interax: {len(readout.free_interaction)} -> {', '.join(readout.free_interaction) or '(none)'}")
    print(f"mld/xturn   : {readout.mass_land_denial} / {readout.extra_turns}   fast combo: {readout.fast_combo}")
    print(f"tutors(info): {len(readout.tutors)}")
    print(f"reasons     : {'; '.join(readout.reasons)}")


if __name__ == "__main__":
    main()
