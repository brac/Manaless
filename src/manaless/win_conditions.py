"""Win-condition engine — three-source merge (build step 2; win-conditions.md).

Merges, into one readout recomputed on every substitution:

1. **Combo wins** — Commander Spellbook ``find-my-combos`` (`spellbook_client`):
   combos present in the deck, plus the standout **"Add 1"** lines (a combo one
   card away from completion).
2. **Explicit alt-wins** — cards whose oracle text literally says "win the game"
   (Thassa's Oracle, Approach of the Second Sun, …). Scanned locally off the
   already-enriched oracle text — no extra Scryfall call needed.
3. **Non-combo plan** — the custom oracle heuristic (one of only two genuinely
   custom pieces, CLAUDE.md §2): a ranked aggro / burn / mill / go-wide profile,
   the plan a combo engine won't see.

The combo source is injected (fetched via ``spellbook_client.find_my_combos``)
so this module is pure over the ``DeckModel`` + ``ComboResults`` and runs in the
test suite with no network — same pattern as ``deck_builder``.
"""

from __future__ import annotations

from dataclasses import dataclass

from manaless.deck_model import DeckModel
from manaless.spellbook_client import Combo, ComboResults

# --- non-combo heuristic signal sets (lowercased oracle-text substrings) -------
# Intentionally simple and explainable (win-conditions.md): tune as real play
# shows what reads correctly; don't over-fit.
_EVASION = (
    "flying", "trample", "menace", "can't be blocked", "unblockable",
    "shadow", "fear", "intimidate", "skulk", "horsemanship",
)
_ANTHEM = ("creatures you control get +", "other creatures you control get +")
_EXTRA_COMBAT = ("additional combat phase", "additional combat step", "additional combat")
_BURN = (
    "deals damage to each opponent",
    "damage to each of your opponents",
    "deals damage to each of your opponents",
)
_MILL = ("mill", "into their graveyard from their library")

# Human labels for the heuristic's internal plan keys.
_PLAN_LABELS = {
    "aggro": "aggro / combat",
    "burn": "burn",
    "mill": "mill",
    "tokens": "go-wide tokens",
}
# A plan needs at least this many supporting cards to count as the fallback plan.
_PLAN_FLOOR = 4


@dataclass(frozen=True, slots=True)
class AddOneLine:
    """A single card that, if added, completes one or more combos already started.

    Aggregated by the card to ``add`` (the standout "you're one swap from a
    wincon" feature): ``completes`` lines, unlocking ``produces`` effects, where
    ``example_with`` shows the in-deck pieces of the most-played such combo.
    """

    add: str
    completes: int
    produces: tuple[str, ...]
    example_with: tuple[str, ...]
    popularity: int


@dataclass(frozen=True, slots=True)
class WinConditions:
    """The merged win-condition readout for a deck (recomputed on every edit)."""

    primary: str
    combos: tuple[Combo, ...]
    add_one: tuple[AddOneLine, ...]
    alt_wins: tuple[str, ...]
    noncombo_profile: tuple[tuple[str, int], ...]  # (label, score), ranked desc
    fallback_plan: str | None
    combo_completeness: str | None

    def to_dict(self) -> dict:
        """The win-conditions.md output object (UI / JSON surface)."""
        return {
            "primary": self.primary,
            "combos": [
                {"cards": list(c.cards), "produces": list(c.produces), "popularity": c.popularity}
                for c in self.combos
            ],
            "add_one": [
                {
                    "add": a.add,
                    "completes": a.completes,
                    "produces": list(a.produces),
                    "example_with": list(a.example_with),
                    "popularity": a.popularity,
                }
                for a in self.add_one
            ],
            "alt_wins": list(self.alt_wins),
            "fallback_plan": self.fallback_plan,
            "combo_completeness": self.combo_completeness,
        }


def evaluate_win_conditions(deck: DeckModel, combos: ComboResults) -> WinConditions:
    """Merge the three sources into one readout. Pure; no network."""
    deck_names = {name.casefold() for name in deck.card_names()}

    add_one = _add_one_lines(combos, deck_names)
    alt_wins = _scan_alt_wins(deck)
    profile = _infer_noncombo_plan(deck)
    fallback = _PLAN_LABELS[profile[0][0]] if profile and profile[0][1] >= _PLAN_FLOOR else None

    return WinConditions(
        primary=_primary_route(combos, add_one, alt_wins, fallback),
        combos=combos.included,
        add_one=add_one,
        alt_wins=alt_wins,
        noncombo_profile=tuple((_PLAN_LABELS[k], v) for k, v in profile),
        fallback_plan=fallback,
        combo_completeness=_combo_completeness(combos, deck_names),
    )


def _add_one_lines(combos: ComboResults, deck_names: set[str]) -> tuple[AddOneLine, ...]:
    """One swap from a wincon: combos missing EXACTLY one card, grouped by that card.

    Returned ranked by how many lines the card completes, then by the best line's
    EDHREC popularity — so the highest-impact single addition is first.
    """
    grouped: dict[str, dict] = {}
    for combo in combos.almost_included:
        missing = [c for c in combo.cards if c.casefold() not in deck_names]
        if len(missing) != 1:
            continue
        entry = grouped.setdefault(
            missing[0], {"completes": 0, "produces": [], "example_with": (), "popularity": -1}
        )
        entry["completes"] += 1
        for effect in combo.produces:
            if effect not in entry["produces"]:
                entry["produces"].append(effect)
        if combo.popularity > entry["popularity"]:  # keep the most-played line's pieces
            entry["popularity"] = combo.popularity
            entry["example_with"] = tuple(c for c in combo.cards if c.casefold() in deck_names)

    lines = [
        AddOneLine(
            add=card,
            completes=e["completes"],
            produces=tuple(e["produces"]),
            example_with=e["example_with"],
            popularity=max(e["popularity"], 0),
        )
        for card, e in grouped.items()
    ]
    lines.sort(key=lambda a: (a.completes, a.popularity), reverse=True)
    return tuple(lines)


def _scan_alt_wins(deck: DeckModel) -> tuple[str, ...]:
    """Cards whose oracle text literally wins the game (Scryfall oracle:"win the game")."""
    return tuple(
        card.name
        for card in deck.all_cards()
        if "win the game" in card.oracle_text.casefold()
    )


def _infer_noncombo_plan(deck: DeckModel) -> tuple[tuple[str, int], ...]:
    """Ranked (plan_key, score) profile from oracle-text + type density."""
    counts = {"aggro": 0, "burn": 0, "mill": 0, "tokens": 0}
    creatures = 0
    for card in deck.all_cards():
        text = card.oracle_text.casefold()
        if "Creature" in card.type_line:
            creatures += 1
        if any(kw in text for kw in _EVASION):
            counts["aggro"] += 1
        if any(kw in text for kw in _ANTHEM):
            counts["aggro"] += 1
        if any(kw in text for kw in _EXTRA_COMBAT):
            counts["aggro"] += 1
        if any(kw in text for kw in _BURN):
            counts["burn"] += 1
        if "double" in text and "damage" in text:  # damage doublers (Torbran-style)
            counts["burn"] += 1
        if any(kw in text for kw in _MILL):
            counts["mill"] += 1
        if "token" in text and "create" in text:
            counts["tokens"] += 1

    # Creature density is the backbone of an aggro plan.
    counts["aggro"] += 3 if creatures >= 25 else 1 if creatures >= 18 else 0

    ranked = sorted(
        ((plan, score) for plan, score in counts.items() if score > 0),
        key=lambda item: item[1],
        reverse=True,
    )
    return tuple(ranked)


def _combo_completeness(combos: ComboResults, deck_names: set[str]) -> str | None:
    """"X of Y pieces" for the closest-to-complete almost-included combo."""
    best: tuple[int, int] | None = None  # (present, total) of the fewest-missing combo
    for combo in combos.almost_included:
        total = len(combo.cards)
        if not total:
            continue
        present = sum(1 for c in combo.cards if c.casefold() in deck_names)
        if best is None or (total - present) < (best[1] - best[0]):
            best = (present, total)
    return f"{best[0]} of {best[1]} pieces" if best else None


def _primary_route(
    combos: ComboResults,
    add_one: tuple[AddOneLine, ...],
    alt_wins: tuple[str, ...],
    fallback: str | None,
) -> str:
    if combos.included:
        return "combo"
    if add_one:
        return "combo (one card away)"
    if alt_wins:
        return "alternate win"
    return fallback or "unclear"


def main() -> None:
    import argparse
    import json
    import sys

    from manaless.deck_builder import NoDecksAvailable, build_deck
    from manaless.edhrec_client import EdhrecClient
    from manaless.http.cache import DiskCache
    from manaless.http.client import HttpClient
    from manaless.paths import CACHE_DIR
    from manaless.scryfall_client import get_collection
    from manaless.spellbook_client import find_my_combos

    parser = argparse.ArgumentParser(description="Win-condition readout for an EDHREC deck (step 2).")
    parser.add_argument("commander", nargs="?", default="Atraxa, Praetors' Voice")
    args = parser.parse_args()

    with HttpClient(DiskCache(CACHE_DIR)) as http:
        edhrec = EdhrecClient(http)
        try:
            deck = build_deck(edhrec, lambda names: get_collection(http, names)[0], args.commander)
        except NoDecksAvailable as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        combos = find_my_combos(http, deck)

    wc = evaluate_win_conditions(deck, combos)
    print(f"commander(s): {', '.join(c.name for c in deck.commanders)}")
    print(f"primary     : {wc.primary}")
    print(f"combos      : {len(wc.combos)} present | add-1 lines: {len(wc.add_one)}")
    for combo in wc.combos[:5]:
        print(f"  - {' + '.join(combo.cards)}  => {', '.join(combo.produces)}  (pop {combo.popularity})")
    if wc.add_one:
        print("add 1 to win (top, by lines completed):")
        for line in wc.add_one[:5]:
            print(f"  + {line.add}  completes {line.completes} line(s)  => {', '.join(line.produces[:3])}")
    print(f"alt wins    : {', '.join(wc.alt_wins) or '(none)'}")
    print(f"profile     : {', '.join(f'{lbl}:{n}' for lbl, n in wc.noncombo_profile)}")
    print(f"fallback    : {wc.fallback_plan or '(no clear non-combo plan)'}")
    print(f"completeness: {wc.combo_completeness or '(n/a)'}")
    print("\njson:")
    print(json.dumps(wc.to_dict(), indent=2)[:600])


if __name__ == "__main__":
    main()
