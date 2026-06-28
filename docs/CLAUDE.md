# CLAUDE.md — MTG Commander Try-Before-You-Buy Tool

> Working name: **TBD** (placeholder: `gambit`). Single-developer personal project.
> This file is the handoff bible. Read it fully before writing code.

---

## 1. What this is

A **try-before-you-buy funnel for paper Magic: the Gathering Commander**.

The loop, in the owner's words:

> Try out decks, practice gameplay, learn the ruleset, and understand what
> different brackets feel like — without investing money. Then once I like a
> deck a lot, purchase the individual cards for my collection. Or otherwise
> just purchase a single card I see in play.

**XMage is the demo environment.** Purchase is the rare, deliberate exit —
NOT the main loop. This framing drives every priority decision below.

### The funnel
1. Pick a commander → browse **real, curated decklists** for it (from EDHREC).
2. Choose one deck as a starting point; **substitute** cards freely in a UI.
3. See, live as you build: **win conditions**, **combo completeness**, and an
   **inferred bracket** (1–5 power level).
4. Export to an XMage `.dck` file → play vs AI to learn rules + feel the bracket.
5. *(Rare)* Fell in love with the deck → diff against owned cards → buy the gaps.
6. *(Rare)* Saw one card in play → single-card buy link.

---

## 2. Core design principles

- **Play/learn loop is the center of gravity (~95% of usage).** The buy step
  fires occasionally. Build the buy tooling minimal and on-demand; do NOT
  over-engineer the part used least.
- **Curated real decks, not aggregates.** The user picks a real published deck
  and substitutes into it. Aggregate/average data is the *substitution palette*
  (the parts bin), never the starting skeleton — except as a fallback (§5).
- **Don't build what already exists. Pull it.** Win conditions, combos, and
  bracket estimation all have working APIs. The only genuinely custom code is
  (a) the non-combo win-condition heuristic and (b) the collection-diff buy step.
- **Isolate the fragile point.** The EDHREC build ID (§4) is the one hard-break
  dependency. One adapter, one runbook note. Everything else degrades gracefully.
- **Be a good API citizen.** Respect rate limits and cache aggressively. These
  are free community services (EDHREC, Scryfall, Commander Spellbook).

---

## 3. Build order (STRICT — do not jump ahead)

Build in this order. Later steps are speculative until earlier ones are used.

1. **Deck-fetch + enrich pipeline** — commander → real decklists → Scryfall
   enrich. (§4) This is the spine. Everything hangs off it.
2. **Win-condition module** — Commander Spellbook `find-my-combos` + Scryfall
   heuristic + alt-win scan. (§6)
3. **Inferred bracket** — Spellbook `estimate-bracket` baseline + non-combo
   layer, calibrated against precons. (§7)
4. **Substitution UI + `.dck` export** — pick deck, swap cards, export. (§8)
5. **Single-card buy** — name → Mass Entry URL. Trivial. Build when first wanted.
6. **Deck-diff buy** — `.dck` minus collection → Mass Entry URL. Build ONLY
   after actually falling for a deck and wanting it in paper.

Rule: build 1–4 now, 5 when you first want a card, 6 when you first want a deck.
Do not build 6 speculatively — real usage will tell you what it needs.

---

## 4. Data sources (exact endpoints — all confirmed)

### EDHREC — raw JSON endpoints (PRIMARY; do NOT use pyedhrec as primary)
> Decision: raw endpoints over the `pyedhrec` wrapper. pyedhrec last released
> early 2024 and may lag EDHREC's current structure. Raw is more code but
> durable and current. (pyedhrec is acceptable only as a convenience source for
> combo/synergy helper methods if ever wanted — not the spine.)

Reference implementation to mirror: **spicyFajitas/edhrec-deck-tools**
(`edhrec_backend.py`). MIT-spirited, actively maintained. Copy its patterns.

1. **Deck table for a commander** (the curated-deck picker)
   ```
   GET https://json.edhrec.com/pages/decks/{commander-slug}.json
   ```
   Returns `{"table": [ {urlhash, savedate, price, ...}, ... ]}`.
   - `urlhash` = the deck ID used to fetch the full list.
   - `savedate` = `"YYYY-MM-DD"` (use for recency sort).
   - `price` = numeric; use as a crude bracket pre-filter / price band.

2. **Full decklist by deck ID** (THE FRAGILE ONE — needs build ID)
   ```
   GET https://edhrec.com/_next/data/{BUILD_ID}/deckpreview/{deck_id}.json?deckId={deck_id}
   ```
   Card list at: `r.json()["pageProps"]["data"]["deck"]`
   Shape: a **flat array of strings** `"1 Card Name"` (qty space name).

3. **Build ID acquisition** (the maintenance liability)
   - Scrape `https://edhrec.com` homepage HTML.
   - Find `/_next/static/<BUILD_ID>/_buildManifest.js`; extract `<BUILD_ID>`.
   - Cache it for the session.
   - **RUNBOOK: if deck fetches start returning 404/HTTP errors, refresh the
     build ID first — EDHREC redeployed and rotated it.** This is the agreed
     failure response. Isolate behind one function (`fetch_edhrec_build_id`) so
     the fix is one place.

### Commander slug formatting
Lowercase, strip non-alphanumerics, spaces→hyphens, drop apostrophes.
(See `format_commander_name` in the reference repo.)

### Scryfall — card enrichment
```
GET https://api.scryfall.com/cards/named?exact={card_name}
```
- Pull `type_line`, `oracle_text`, `image_uris.normal`, `scryfall_uri`, mana value.
- **DFC/split/transform:** if no top-level `image_uris`, fall back to
  `card_faces[0].image_uris.normal`. Same for oracle text (concatenate faces).
- **Cache to disk by exact card name.** Card data is near-static.

### Commander Spellbook — combos + bracket (see §6, §7)
- Base: `https://backend.commanderspellbook.com`
- `find-my-combos` — POST decklist → combos present + "one card away".
- `estimate-bracket` — POST decklist → bracket-relevant combo classification.
- Swagger: `https://backend.commanderspellbook.com/schema/swagger/`
- MIT licensed; it's the source that powers EDHREC's own combo feature.

### Rate limits (from reference impl — respect these)
- EDHREC: **0.80s** min delay between requests.
- Scryfall: **0.12s** min delay (their docs ask 50–100ms).
- Spellbook: be polite; cache combo lookups per decklist hash.

---

## 5. Fallback behavior (agreed)

Deck availability varies wildly by commander. Popular commanders have dozens of
real indexed decks; fringe ones have few or none.

- **Many real decks:** show the curated picker. Normal path.
- **Few real decks:** show what exists; flag the thin selection in the UI.
- **Zero real decks:** fall back to the **average deck** (aggregate) as the
  starting skeleton, clearly labeled as synthetic/aggregate so the user knows
  it's a composite, not a playtested list. (The old donaldpminer EDHREC code
  literally returns a `NOT_ENOUGH_DATA` signal you can mirror as the trigger.)

---

## 6. Win conditions (three-source merge)

No API hands you "the win condition" as a field — it's interpretive. Merge three
sources into a structured readout that updates live as the user substitutes.

1. **Combo wins — Commander Spellbook `find-my-combos`.** POST the current
   decklist; get every combo present, with required cards + produced effect
   (infinite mana / damage / mill / tokens, etc.) and EDHREC popularity per
   combo. **Also returns "Add 1" combos** — completable by adding ONE card.
   That's the standout build-time feature: "you're one swap from a wincon."
2. **Explicit alt-wins — Scryfall.** One query flags cards that literally win:
   `oracle:"win the game"` (Thassa's Oracle, Approach of the Second Sun,
   Lab Maniac, etc.). Near-zero effort.
3. **Non-combo plan — Scryfall oracle-text heuristic (CUSTOM, ~50 lines).**
   The plan a combo engine won't see. Pattern-match density of:
   - aggro/combat: creature count, total power, anthems, extra-combat, evasion
   - burn: "deals damage to each opponent", damage doublers
   - mill: "mill" / "into their graveyard" text
   - go-wide tokens: token generators + overrun effects

### Output object (per deck, recomputed on edit)
```json
{
  "primary": "combo",
  "combos": [{"cards": [...], "produces": "infinite mana", "popularity": 12000}],
  "alt_wins": ["Thassa's Oracle"],
  "fallback_plan": "go-wide tokens",
  "combo_completeness": "2 of 3 pieces"
}
```
This is a better win-condition readout than most deckbuilding sites show, and
it's the core of the build-time experience. See `docs/win-conditions.md`.

---

## 7. Inferred bracket (1–5)

Goal: estimate where a deck sits so the user can feel each bracket and assemble a
practice ladder. The official framework is the **Commander Brackets** system
(1 exhibition → 5 cEDH) with a semi-official **Game Changers** card list.

### Approach (do NOT build from scratch)
- **Baseline: Commander Spellbook `estimate-bracket`.** POST decklist → returns
  bracket-relevant info, mainly two-card combos classified by requirements.
  - Caveat: API returns **thematic buckets**, not 1–5 directly. Maintainers'
    conversion (e.g. Ruthless→4, Spicy→3, …) — apply the mapping yourself.
    **Verify the current mapping before baking it in.**
- **Custom layer (small): non-combo power signal via Scryfall.** Count density
  of Game Changers + fast mana + tutors + cheap/free interaction. This covers
  what a combo-focused endpoint misses.
- **Calibration set: taw/magic-preconstructed-decks-data.** Every official
  precon as JSON (correct cards/commander/printing). Precons are Wizards'
  bracket-2 reference decks → run the evaluator against them, confirm they score
  ~2, validate before trusting on EDHREC decks.

**Verify before baking in:** current Commander Brackets definitions + current
Game Changers list (both updated periodically). See `docs/bracket-evaluator.md`.

---

## 8. XMage export + buy steps

### `.dck` export
- Format is plain text: lines of `1 [SET:NUM] Card Name`, but XMage will
  resolve by **card name alone** if set/number don't resolve — for vs-AI play,
  the printing is irrelevant. Emit names; don't fight precise set matching.
- Reference for format + round-trip: **thebear132/MTG-To-XMage**.
- Drop file in XMage `/decks`, or load via the client's Deck Editor.

### XMage AI game (manual, documented for the user — not automated)
Main Table → new table → format Commander/Freeform Commander → add computer
players → load `.dck` → start.

### Single-card buy (build when first wanted)
Card name → TCGplayer Mass Entry URL → open browser tab. Bookmark-tier effort.

### Deck-diff buy (build ONLY after first wanting a paper deck)
1. Parse `.dck` → `(qty, name)` list.
2. Diff against local collection file (§9).
3. Emit **TCGplayer Mass Entry** payload of ONLY missing cards → open tab.
   Mass Entry handles cheapest-seller + shipping optimization server-side.
- Mass Entry is the public web form (NOT the locked-down affiliate API). It
  accepts lines with or without set codes; gear icon sets printing/condition.
- Card Kingdom mass-entry = secondary source. Cardmarket = EU.

---

## 9. The collection file

A thin local file of owned cards. Hand-maintained, or exported from Deckstats'
collection tracker (which also does XMage import + multi-vendor pricing if you
want a zero-code cross-check). Only needed for the deck-diff buy (step 6).

Format: JSON or CSV, `name` + `qty`. Keep it dumb.

---

## 10. Prior art to read before writing (don't reinvent)

- **spicyFajitas/edhrec-deck-tools** — the EDHREC raw-endpoint pipeline. Spine
  reference. Copy build-ID logic, slug formatting, rate limiters, DFC handling.
- **jamese.dev "Combinator"** — Spellbook `find-my-combos` + "Add 1" UI done.
  Read for request/response handling.
- **thebear132/MTG-To-XMage** — `.dck` round-tripping + format handling.
- **taw/magic-preconstructed-decks-data** — precon calibration set.
- **SpaceCowMedia/commander-spellbook-backend** — Spellbook's own source (MIT)
  if you need to understand response schemas deeply.

---

## 11. Component status table

| Need | Source | Status |
|---|---|---|
| Curated deck list per commander | `json.edhrec.com/pages/decks/` | confirmed |
| Real decklist by ID | EDHREC `_next/data` + build ID | confirmed; fragile, isolated |
| Fallback when few/no decks | average deck | confirmed |
| Card enrichment | Scryfall `cards/named` | confirmed; cache |
| Substitution palette | EDHREC synergy/inclusion | confirmed |
| Win conditions (combo) | Spellbook `find-my-combos` | confirmed API |
| "One card from a wincon" | Spellbook "Add 1" | confirmed |
| Win conditions (non-combo) | Scryfall oracle heuristic | CUSTOM (~50 lines) |
| Explicit alt-wins | Scryfall `oracle:"win the game"` | trivial |
| Inferred bracket | Spellbook `estimate-bracket` | confirmed; map buckets→1–5 |
| Bracket calibration | taw precon dataset | confirmed |
| `.dck` export | format known + MTG-To-XMage ref | confirmed |
| Buy: deck diff | local collection + Mass Entry | CUSTOM glue |
| Buy: single card | Mass Entry URL | trivial |

---

## 12. Open items to verify at build time (don't trust memory)

- [ ] Commander Spellbook `find-my-combos` exact request/response schema (Swagger).
- [ ] `estimate-bracket` exact response + current bucket→1–5 mapping.
- [ ] Current Commander Brackets official definitions.
- [ ] Current Game Changers list.
- [ ] EDHREC deck-table JSON: confirm all fields beyond urlhash/savedate/price.
- [ ] Whether EDHREC indexed decks carry any power/bracket label (vs. inferring).
