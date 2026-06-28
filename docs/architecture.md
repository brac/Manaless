# Architecture

> Companion to CLAUDE.md. Module breakdown and data flow for the
> try-before-you-buy Commander tool.

## Data flow (the spine)

```
commander name
   │  format_commander_name()  → slug
   ▼
[EDHREC deck table]  json.edhrec.com/pages/decks/{slug}.json
   │  → [{urlhash, savedate, price}, ...]
   │  filter: recency + price band  → list of deck IDs
   ▼
[EDHREC deck fetch]  needs BUILD_ID (fragile adapter)
   │  edhrec.com/_next/data/{BUILD_ID}/deckpreview/{id}.json
   │  → ["1 Card Name", ...]  (flat string array)
   ▼
[Scryfall enrich]  cards/named?exact=  (cached by name)
   │  → type_line, oracle_text, image, mana value (DFC: card_faces[0])
   ▼
[Deck object]  enriched, categorized by type
   ├──► [Win-condition engine]   (Spellbook + Scryfall heuristic)
   ├──► [Bracket estimator]      (Spellbook estimate-bracket + custom layer)
   ├──► [Substitution UI]        (swap cards; palette from EDHREC synergy)
   └──► [.dck export]            → XMage → play vs AI
                                       │
                         (rare exit)   ▼
                                 [Buy steps]  diff vs collection → Mass Entry
```

## Modules

### `edhrec_client` — the spine, fragile point isolated
- `fetch_edhrec_build_id()` — scrape homepage, extract `<BUILD_ID>`, cache.
  **The single hard-break dependency.** Runbook: refresh on deck-fetch failures.
- `format_commander_name(name) -> slug`
- `fetch_deck_table(slug) -> [entries]`
- `filter_deck_hashes(table, recent, min_price, max_price) -> [deck_id]`
- `fetch_deck_by_hash(deck_id) -> [card lines]` (disk-cached per deck ID)
- Rate limiter: 0.80s between EDHREC calls.

### `scryfall_client` — enrichment, disk-cached
- `get_card_metadata(name) -> {type_line, oracle_text, image_url, scryfall_uri, mv}`
- DFC fallback to `card_faces[0]`.
- Rate limiter: 0.12s. Cache keyed by exact card name.

### `spellbook_client` — combos + bracket baseline
- `find_my_combos(decklist) -> {present: [...], add_one: [...]}`
- `estimate_bracket(decklist) -> {bucket, ...}` → map bucket → 1–5.
- Cache by decklist hash (combos don't change for a fixed list).

### `win_conditions` — three-source merge (see win-conditions.md)
- Consumes spellbook combos + scryfall oracle heuristic + alt-win scan.
- Emits the win-condition object. Recomputed on every substitution.

### `bracket` — inferred power level (see bracket-evaluator.md)
- Spellbook baseline + non-combo Scryfall signal density.
- Calibrated against precon dataset.

### `deck_model` — the in-memory deck the UI mutates
- Single source of truth for the current build. Substitutions mutate here;
  win-conditions + bracket recompute off it.

### `dck_export` — XMage output
- `to_dck(deck_model) -> str`. Emit card names; printing irrelevant for AI play.

### `buy` — on-demand, built last
- `single_card_url(name) -> mass_entry_url`
- `deck_diff_url(deck_model, collection) -> mass_entry_url`  (missing cards only)

### `collection` — thin owned-cards store
- Load/save JSON or CSV (`name`, `qty`). Hand-maintained or Deckstats export.

## Caching strategy

| Data | Key | Invalidation |
|---|---|---|
| EDHREC build ID | session | on deck-fetch failure → refetch |
| EDHREC deck table | commander slug | daily (EDHREC updates ~daily) |
| EDHREC decklist | deck ID | rarely; decks are immutable by hash |
| Scryfall card | card name | near-never; cards static |
| Spellbook combos | decklist hash | when decklist changes |

## Tech notes
- Owner stack lean: Python backend for the pipeline (matches reference repos);
  any thin UI layer the owner prefers. Streamlit is what the reference repo uses
  and is the fastest path to a working substitution UI, but not prescribed.
- Keep the pipeline UI-agnostic: `deck_model` + the engines must be callable
  headless (CLI/batch) so a practice-ladder generator can mass-produce decks.
