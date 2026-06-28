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

## Status

**Phase 0 — groundwork** (precedes build-order step 1 in CLAUDE.md §3).

- [x] 0.1 Project scaffold + module map (`src/manaless/`)
- [x] 0.2 Shared HTTP layer: per-host rate limiter + disk cache + JSON client
- [ ] 0.3 Fragile-point spike: live EDHREC build-id → deck-table → decklist
- [ ] 0.4 §12 verification sweep → `docs/verified.md`
- [ ] 0.5 Prior-art acquisition + precon calibration dataset

Build steps 1–6 (the spine, win conditions, bracket, substitution UI, buy) are
**not** started — see CLAUDE.md §3 build order.

## Layout

```
src/manaless/
  http/              # shared substrate — every API client consumes this
    rate_limiter.py  #   per-host minimum delay (EDHREC 0.80s, Scryfall 0.12s)
    cache.py         #   JSON disk cache (slug / deck-id / card-name / list-hash)
    client.py        #   HttpClient.get_json — rate-limit + cache + User-Agent
  edhrec_client.py   # build step 1 (spine) — stubs; build-id wired in 0.3
  scryfall_client.py # build step 1
  spellbook_client.py# build steps 2 / 3
  win_conditions.py  # build step 2
  bracket.py         # build step 3
  deck_model.py      # build step 4
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
