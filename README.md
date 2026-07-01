# Manaless

A try-before-you-buy funnel for paper **Magic: the Gathering Commander**. Browse
real curated decklists, substitute cards with live win-condition + bracket
feedback, export to XMage to play vs AI and learn — then (rarely) buy the cards
you fell for.

> **The project bible lives in [`docs/CLAUDE.md`](docs/CLAUDE.md). Read it first.**
> Companion docs: [architecture](docs/architecture.md),
> [win-conditions](docs/win-conditions.md),
> [bracket-evaluator](docs/bracket-evaluator.md),
> [buy-pipeline](docs/buy-pipeline.md).

## Run the web builder

One command — it creates `.venv`, installs deps on first run, then serves the
builder and opens a browser tab:

```powershell
./run.ps1              # Windows / PowerShell  (http://127.0.0.1:8000)
```
```bash
./run.sh               # Linux, macOS, or Git Bash on Windows
```

Options: `./run.ps1 -Port 9000 -Reload -NoBrowser` (PowerShell) or
`PORT=9000 ./run.sh --reload` (bash). Under the hood both run
`python -m manaless.web`; first run does `pip install -e ".[web]"`, warm runs
launch instantly.

## Status

> **Picking this up fresh? Start with [`docs/HANDOFF.md`](docs/HANDOFF.md)** — it
> says exactly where we are and what to do next.

**Phase 0 — groundwork — complete** (precedes build-order step 1 in CLAUDE.md §3).

- [x] 0.1 Project scaffold + module map (`src/manaless/`)
- [x] 0.2 Shared HTTP layer: per-host rate limiter + disk cache + JSON client
- [x] 0.3 Fragile-point spike: live EDHREC build-id → deck-table → decklist
- [x] 0.4 §12 verification sweep → [`docs/verified.md`](docs/verified.md)
- [x] 0.5 Prior-art acquisition + precon calibration → [`docs/prior-art.md`](docs/prior-art.md)

**Phase 0 complete. Build step 1 (deck-fetch + enrich) is in.** `build_deck`
turns a commander into a Scryfall-enriched, type-categorized `DeckModel`
(validated live: categorization matches EDHREC's own per-type counts):

```bash
python -m manaless.deck_builder "Atraxa, Praetors' Voice"
```

> **Known follow-up:** cold-cache enrichment hits Scryfall once per card and is
> slow (~3 min/deck) because Scryfall throttles per-card lookups. Switch deck
> enrichment to `POST /cards/collection` (75 ids/request) — Scryfall's
> recommended path for many cards. Repeat builds are instant (disk-cached).

Run the spike (proves the spine against current live EDHREC):

```bash
python -m manaless.spike "Atraxa, Praetors' Voice"
```

**Phase 0.4 closed the CLAUDE.md §12 checklist** — all six items verified against
live sources on 2026-06-27; see [`docs/verified.md`](docs/verified.md). Highlights
that change the build: EDHREC deck rows already carry a `bracket` (1–5) label so
inference is a fallback, not the primary; the Spellbook `bracketTag`→bracket map is
ranges (corrects §7); Game Changers (53) are pulled live via Scryfall
`is:gamechanger` into [`data/game-changers.json`](data/game-changers.json).

Build steps 1–6 (the spine, win conditions, bracket, substitution UI, buy) are
**not** started — see CLAUDE.md §3 build order.

## Layout

```
src/manaless/
  http/              # shared substrate — every API client consumes this
    rate_limiter.py  #   per-host minimum delay (EDHREC 0.80s, Scryfall 0.12s)
    cache.py         #   JSON disk cache (slug / deck-id / card-name / list-hash)
    client.py        #   HttpClient.get_json — rate-limit + cache + User-Agent
  edhrec_client.py   # build step 1 (spine) — EdhrecClient: build-id + deck fetch
  scryfall_client.py # build step 1 — get_card_metadata, DFC fallback, cached
  deck_model.py      # build step 1/4 — immutable Card + DeckModel, type-categorized
  deck_builder.py    # build step 1 — build_deck: commander -> enriched DeckModel
  spike.py           # 0.3 driver: python -m manaless.spike "<cmdr>"
  spellbook_client.py# build steps 2 / 3
  win_conditions.py  # build step 2
  bracket.py         # build step 3
  dck_export.py      # build step 4
  buy.py             # build steps 5 / 6
  collection.py      # build step 6
```

## Develop

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
