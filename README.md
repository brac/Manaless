# Manaless

A try-before-you-buy funnel for paper **Magic: the Gathering Commander**. Browse
real curated decklists, substitute cards with live win-condition + bracket
feedback, export to XMage to play vs AI and learn — then (rarely) buy the cards
you fell for.

The loop: pick a commander → start from a **real published decklist** → swap cards
freely while a live panel shows **win conditions**, **combo completeness**, and an
inferred **power bracket (1–5)** → export an XMage `.dck` to practice vs AI → and,
only once you love a deck, diff it against your collection and buy the gaps. XMage
is the demo environment; buying is the rare, deliberate exit, not the main loop.

> **The project bible lives in [`docs/CLAUDE.md`](docs/CLAUDE.md).** Companion docs:
> [architecture](docs/architecture.md), [win-conditions](docs/win-conditions.md),
> [bracket-evaluator](docs/bracket-evaluator.md), [buy-pipeline](docs/buy-pipeline.md),
> and [HANDOFF](docs/HANDOFF.md) — the live "where we are".

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

## What it does

The full funnel is live in the FastAPI + HTMX web app (`manaless.web`):

- **Browse commanders** — fuzzy search, or a "popular" list ranked by EDHREC deck
  count (with a Scryfall fallback if EDHREC is momentarily down).
- **Pick a real deck** — the curated deck picker for that commander, sortable by
  newest/oldest, price, EDHREC bracket, or saltiness (top 100 of up to ~42k rows).
- **Build & substitute** — swap any card via a modal offering **category-matched
  suggestions** (Ramp / Removal / Draw / Board Wipe / Counterspell, inferred from
  card text) alongside a fuzzy card search; add from a most-played **palette**;
  each card shows its EDHREC inclusion rate.
- **Live readouts** — win conditions (combos present, "one swap from a wincon",
  alt-wins, non-combo plan) and an inferred **bracket 1–5**, recomputed on every
  edit. Cards in a combo get colour-coded outlines matching the combo panel.
- **Export to XMage** — one-click `.dck` download to play vs AI and learn the rules.
- **Buy (the rare exit)** — a per-card TCGplayer link, or diff the deck against an
  imported collection and buy only the missing cards via TCGplayer Mass Entry.

## Data sources

EDHREC (deck tables, decklists, per-commander card popularity), Scryfall (card
enrichment), and Commander Spellbook (combos + bracket estimate) — all free
community APIs, rate-limited and disk-cached per CLAUDE.md §4. The one fragile
point (EDHREC's Next.js build id) is isolated in `edhrec_client.py` with a
self-healing refresh on a 404.

## Layout

```
src/manaless/
  http/              # shared substrate — per-host rate limiter + disk cache + JSON client
  edhrec_client.py   # spine — build-id + deck table/list + commander card stats
  scryfall_client.py # card enrichment (batched cards/collection), DFC fallback, cached
  deck_model.py      # immutable Card + DeckModel, type-categorized
  deck_builder.py    # build_deck: commander -> enriched DeckModel; substitute / add
  spellbook_client.py# find-my-combos + estimate-bracket (cached by decklist hash)
  win_conditions.py  # three-source win-condition merge
  bracket.py         # inferred bracket 1–5 (Game Changers + fast-mana layer)
  card_category.py   # functional-category classifier (swap suggestions)
  dck_export.py      # XMage .dck writer
  buy.py             # TCGplayer Mass Entry URLs (single card + deck diff)
  collection.py      # owned-cards file (Collectr CSV / JSON import)
  web/               # FastAPI + HTMX + Jinja app — routes, templates, static
```

## Develop

```bash
python -m venv .venv && . .venv/Scripts/activate    # or: source .venv/bin/activate
pip install -e ".[dev,web]"
pytest
```

### Headless CLI

The pipeline runs without the web UI — handy for spot checks:

```bash
python -m manaless.deck_builder   "Atraxa, Praetors' Voice"   # build + enrich a deck
python -m manaless.win_conditions "Atraxa, Praetors' Voice"   # win-condition readout
python -m manaless.bracket        "Atraxa, Praetors' Voice"   # inferred bracket 1–5
python -m manaless.spike          "Atraxa, Praetors' Voice"   # prove the EDHREC spine live
```
