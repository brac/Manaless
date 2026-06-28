# Win Conditions

> How the tool answers "how does this deck win?" live, as you build.

## The problem

There is no API field for "this deck's win condition" — it's a semantic,
interpretive property. But three sources together cover most of it, and the gap
is small. The output updates on every substitution, so the user sees their win
plan change as they edit.

## Source 1 — Combo wins (Commander Spellbook `find-my-combos`)

The highest-signal source. For a large fraction of Commander decks, "how do you
win" = "assemble combo X". POST the current decklist; receive:
- **Combos present** — required cards + produced effect (infinite mana, infinite
  damage, infinite mill, infinite tokens, etc.).
- **EDHREC popularity** per combo (number of decks running it) — texture for
  "is this a known line or a fringe one".
- **"Add 1" combos** — combos completable by adding exactly ONE card.

### Why "Add 1" is the standout feature
While substituting, the tool can say: *"Adding [Card] completes an infinite-mana
line with two cards already in your deck."* No existing try-before-you-buy flow
surfaces this. It directly serves the "build toward a wincon" experience.

Spellbook is the same data that powers EDHREC's combo feature — go to the source.

## Source 2 — Explicit alt-wins (Scryfall, trivial)

One query catches cards that literally end the game:
```
oracle:"win the game"
```
Flags Thassa's Oracle, Approach of the Second Sun, Laboratory Maniac,
Felidar Sovereign, etc. Scan the deck's cards against this; any hit is a labeled
alternate win condition. Near-zero effort.

## Source 3 — Non-combo plan (Scryfall oracle heuristic — CUSTOM ~50 lines)

The plan a combo engine won't see: the deck that just attacks, burns, or mills.
Pattern-match density over enriched oracle text + type data:

| Plan | Signals |
|---|---|
| Aggro / combat | high creature count, total power, anthems, extra-combat steps, evasion keywords (flying, trample, menace, unblockable) |
| Burn / direct damage | "deals damage to each opponent", damage doublers (e.g. Torbran-style) |
| Mill | "mill", "into their graveyard from their library" |
| Go-wide tokens | token generators + mass pump / overrun effects |

Output is a *ranked profile*, not a single label. A deck can be "primarily combo,
secondary go-wide aggro."

## Merged output object

Recomputed on every edit to the deck model:

```json
{
  "primary": "combo",
  "combos": [
    {"cards": ["Card A", "Card B"], "produces": "infinite mana", "popularity": 12000}
  ],
  "alt_wins": ["Thassa's Oracle"],
  "fallback_plan": "go-wide tokens",
  "combo_completeness": "2 of 3 pieces"
}
```

- `primary` — best-supported win route.
- `combos` — from Spellbook, present in deck.
- `alt_wins` — from Scryfall explicit scan.
- `fallback_plan` — from the non-combo heuristic; the deck's "plan B" or its
  actual plan if it isn't a combo deck.
- `combo_completeness` — derived from "Add 1" data; surfaces near-complete lines.

## Build notes
- Cache Spellbook results by decklist hash; only re-call when the list changes.
- The heuristic is intentionally simple and explainable. Tune thresholds as you
  learn what reads correctly in play. Don't over-fit.
- Verify the exact `find-my-combos` request/response schema against the Swagger
  before wiring (`backend.commanderspellbook.com/schema/swagger/`).

## Prior art
**jamese.dev "Combinator"** already does Spellbook combo-surfacing with an
"Add 1" tab, pulling decks from Moxfield/Archidekt/MTGGoldfish. Read it for the
API request/response handling before writing the client.
