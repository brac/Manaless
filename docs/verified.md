# Verified Facts — §12 "Don't Trust Memory" Sweep

> **Phase 0.4 deliverable.** Closes the open checklist in
> [CLAUDE.md §12](CLAUDE.md). Every item below was confirmed against a **live
> source** on the sweep date — re-verify periodically, the bracket system and
> Game Changers list move.

**Sweep date: 2026-06-27.** Method: live API probes (EDHREC JSON already in
cache; Commander Spellbook OpenAPI schema + real POSTs using a real 100-card
Atraxa list) and Spellbook source on GitHub; WotC + Scryfall for the rules data.

## §12 checklist — all resolved

| # | Item | Status | Headline |
|---|------|--------|----------|
| 1 | `find-my-combos` schema | ✅ | paginated; `results.almostIncluded` = the "Add-N-away" pool |
| 2 | `estimate-bracket` + bucket→1–5 map | ✅ | returns `bracketTag`; map is **ranges (floors)**, from Spellbook source |
| 3 | Commander Brackets definitions | ✅ | still **beta**; last rule change **2025-10-21**; tutor rule **removed** |
| 4 | Game Changers list | ✅ | **53** cards; pull live via Scryfall `is:gamechanger` → `data/game-changers.json` |
| 5 | EDHREC deck-table fields | ✅ | full field list captured |
| 6 | EDHREC decks carry a power label? | ✅ | **YES** — deck-table row has `bracket` (1–5) + `salt` |

---

## 1. Commander Spellbook `find-my-combos`

- **`POST https://backend.commanderspellbook.com/find-my-combos`** — no auth
  required (schema lists basic/cookie/jwt as optional; anonymous POST → 200).
- **Request** (`application/json`, schema `DeckRequest`; also accepts `text/plain`):
  ```json
  { "commanders": [{"card": "Atraxa, Praetors' Voice", "quantity": 1}],
    "main":       [{"card": "Sol Ring", "quantity": 1}, ...] }
  ```
  `commanders` ≤ 12, `main` ≤ 600; each item `{card: str, quantity: int=1}`.
- **Response is PAGINATED:** `{count, next, previous, results}` — the payload is
  **`results`** (schema `FindMyCombosResponse`):
  | field | meaning |
  |---|---|
  | `identity` | color identity, e.g. `"GWUB"` |
  | `included` | combos fully present in the deck (`Variant[]`) |
  | `almostIncluded` | combos missing ≥1 card but within identity — **the "Add" pool** (Atraxa: **107**) |
  | `includedByChangingCommanders` / `almostIncludedByAddingColors` / `…ByChangingCommanders` / `…ByAddingColorsAndChangingCommanders` | variants reachable by relaxing identity/commander |
- **"Add 1" (the standout feature):** the API does **not** hand you a strict
  "missing exactly one" list. `almostIncluded` is "missing ≥1 within identity."
  To get *"you're ONE swap from a wincon"*, filter `almostIncluded` to variants
  whose `uses` minus the current deck = exactly one missing card.
- **`Variant` keys (verified live):** `id, of, uses, requires, includes,
  produces, popularity, bracketTag, identity, prices, legalities, status,
  spoiler, description, manaNeeded, manaValueNeeded, variantCount,
  easyPrerequisites, notablePrerequisites, notes`.
  - `produces` → `[{feature: {id, name, status, uncountable}, quantity}]`; the
    effect text is `feature.name` (e.g. *"Target opponent loses the game"*).
  - `popularity` → int (EDHREC decks running it; sample combo: 26,571).
- **Cache** by decklist hash (stable for a fixed list).

## 2. Commander Spellbook `estimate-bracket` (+ the bucket→1–5 mapping)

- **`POST …/estimate-bracket`**, same `DeckRequest` body. Response **not** paginated.
- **Response** (`EstimateBracketResult`):
  | field | shape |
  |---|---|
  | `bracketTag` | `BracketTagEnum` (one of E/C/O/P/S/R/B) |
  | `cards` | `ClassifiedCard[]` — `{card, quantity, banned, gameChanger, massLandDenial, extraTurn}` |
  | `templates` | `ClassifiedTemplate[]` |
  | `combos` | `ClassifiedVariant[]` — `{combo, relevant, borderlineRelevant, arguablyTwoCard, definitelyTwoCard, speed:int, massLandDenial, extraTurn, lock, skipTurns, controlAllOpponents, controlSomeOpponents}` |
- **CURRENT `bracketTag` → bracket mapping** — from Spellbook's own
  `src/lib/brackets.ts` (`commander-spellbook-site`, `main`, fetched 2026-06-27).
  **They are ranges/floors, not single numbers** — this **corrects CLAUDE.md §7's
  stale "Ruthless→4, Spicy→3":**
  | code | name | bracket |
  |---|---|---|
  | `E` | Exhibition | `1+` |
  | `C` | Core | `2+` |
  | `O` | Oddball | `2-3+` |
  | `P` | Powerful | `3+` |
  | `S` | Spicy | `3-4+` |
  | `R` | Ruthless | `4+` |
  | `B` | Not Legal | `N/A` (a banned card is present) |
  - **Cross-check:** the live Atraxa deck → `S` (Spicy, 3–4+); EDHREC labeled the
    *same* deck `bracket: 3` (see item 6) → consistent.
- **`computeBracketInfo(result)` in the same file is the reference algorithm for
  build step 3.** It reasons over the official rubric directly: counts
  `cards[].gameChanger`, `cards[].banned`, mass-land-denial / extra-turn cards
  and combos, and classifies *fast game-winning two-card combos* (`speed ≥ 4 &&
  definitelyTwoCard`). Mirror it rather than re-deriving. **Key consequence:
  Game-Changer membership is flagged per card by the API** (`cards[].gameChanger`)
  — no local list match needed for Spellbook-analyzed decks.

## 3. Commander Brackets — current official definitions

- **Status: still BETA** as of 2026-06-27 (WotC Commander page). Last change to
  the **bracket rules** = **2025-10-21**; last update overall = 2026-02-09 (Game
  Changers only). WotC has signaled dropping the beta tag "later in 2026."
- **Names confirmed unchanged:** 1 Exhibition · 2 Core · 3 Upgraded · 4 Optimized · 5 cEDH.
- **Current rubric:**
  | | 1 Exhibition | 2 Core | 3 Upgraded | 4 Optimized | 5 cEDH |
  |---|---|---|---|---|---|
  | Game Changers | 0 | 0 | **≤ 3** | ∞ | ∞ |
  | Mass land denial | no | no | no | ok | ok |
  | Extra-turn cards | none | low, unchained | low, unchained | ok | ok |
  | 2-card infinite combos | no | no | no **early-game** (late ok) | ok | ok |
  | Turn "North Star" | ≥ 9 | ≥ 8 | ≥ 6 | ≥ 4 | any |
  | Restrictions | — | — | — | banlist only | banlist only (metagame intent) |
- **2025-10-21 rule changes (important):** **tutor restrictions REMOVED** from all
  brackets — tutors are now policed *only* via the Game Changers list; the
  "Core = average precon" comparison was removed; turn North-Stars added; 10
  cards cut from Game Changers.
  → **Design impact:** the §7 / bracket-evaluator.md "tutor density" custom signal
  is now **off the official rubric**. Keep it only as an optional heuristic, not
  as an official-bracket input.
- Sources: WotC announcements 2025-02-11, **2025-10-21**, 2026-02-09;
  `magic.wizards.com/en/formats/commander`; EDHREC bracket guide (cross-check).

## 4. Game Changers list

- **53 cards**, list last updated **2026-02-09** (added *Farewell*, *Biorhythm*;
  *Lutri* unbanned but deliberately kept off).
- **Authoritative live source: Scryfall `is:gamechanger`** — machine-readable and
  kept in sync with the WotC list:
  `https://api.scryfall.com/cards/search?q=is%3Agamechanger`.
- Snapshot saved to **`data/game-changers.json`** (fetched 2026-06-27, 53 names,
  Scryfall-exact). **The evaluator should re-fetch `is:gamechanger` and cache it,
  not trust the snapshot indefinitely.** And recall (item 2) that
  `estimate-bracket` already flags `cards[].gameChanger`.

## 5. EDHREC deck-table JSON — full field inventory

`GET https://json.edhrec.com/pages/decks/{slug}.json` (verified on Atraxa: 42,219 rows).

- **Per row (`table[]`):** `urlhash`, `savedate` (`YYYY-MM-DD`), `price` (int),
  `salt` (float), type counts (`creature`, `instant`, `sorcery`, `artifact`,
  `enchantment`, `battle`, `planeswalker`, `land`), **`bracket` (int 1–5)**,
  `budget_label` (int), `tags` (str[]).
- **Top level:** the type buckets, `similar`, **`bracket_counts`**,
  `budget_counts`, `tag_counts`, `savedate_counts`, `table`, `header`, `panels`,
  `description`, `container`.

## 6. Do EDHREC decks carry a power/bracket label? — YES

- **Deck-table rows include `bracket` (int 1–5)** and `salt` (float); the table
  top-level carries a `bracket_counts` distribution.
- The individual deckpreview (`_next/data/.../deckpreview/{id}.json`,
  `pageProps.data`) carries **`cedh` (bool)** and `salt` but **not** the numeric
  bracket — the numeric label lives on the **deck-table row**.
- **Design impact (bracket-evaluator.md):** for an **unmodified** EDHREC deck,
  **prefer the table's `bracket` label**. Run `estimate-bracket` + inference for
  **modified** decks (post-substitution) and as a calibration cross-check against
  the precon set.

---

## Cross-cutting findings (beyond the checklist)

- **§5 fallback trigger is HTTP 403, not an empty table.** `json.edhrec.com` 403s
  on a slug with no deck page (handled in 0.3: `fetch_deck_table` → `[]`).
- **Every combo `Variant` carries its own `bracketTag`** (in find-my-combos too),
  so individual combos can be bracket-tagged, not just whole decks.
- **`estimate-bracket` ≈ the official rubric engine.** Between `cards[].gameChanger`
  / `banned` / `extraTurn` / `massLandDenial` and the combo flags, Spellbook
  already encodes most of what brackets 1–5 need. The remaining genuinely-custom
  signal shrinks to **fast mana + cheap free interaction density** (Scryfall) —
  tutors are off-rubric, Game Changers are provided.

## Sources

- Commander Spellbook OpenAPI: `https://backend.commanderspellbook.com/schema/`
- Mapping + algorithm: `commander-spellbook-site` → `src/lib/brackets.ts` (`main`)
- WotC: `…/announcements/commander-brackets-beta-update-october-21-2025`,
  `…-february-9-2026`; `magic.wizards.com/en/formats/commander`
- Scryfall: `https://api.scryfall.com/cards/search?q=is%3Agamechanger`
- EDHREC JSON: `https://json.edhrec.com/pages/decks/{slug}.json`
