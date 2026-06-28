# Handoff — Manaless

> **Read this first, then [`CLAUDE.md`](CLAUDE.md) (the bible).** This file is the
> live "where we are" for a fresh agent picking up the work. Last updated after
> **build step 1** landed.

## TL;DR — current position

- **Phase 0 (groundwork): COMPLETE** — scaffold, shared HTTP layer, EDHREC spine
  spike, §12 verification sweep, prior-art + precon dataset.
- **Build step 1 (deck-fetch + enrich pipeline): COMPLETE and live-validated.**
  `build_deck(commander) -> DeckModel` works against live EDHREC + Scryfall;
  type categorization matches EDHREC's own per-type counts exactly.
- **Build steps 2–6: NOT STARTED** (stubs in place, tagged with their step).
- **Tests: 63 passing**, no live network in the suite (httpx MockTransport).
- The strict build order is in [CLAUDE.md §3](CLAUDE.md). Do not jump ahead.

## Run it

```bash
# Python 3.12 required (system python here is 3.9 — use python3.12 for the venv)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                              # 63 tests, ~1s

python -m manaless.spike "Atraxa, Praetors' Voice"          # 0.3 spine proof
python -m manaless.deck_builder "Atraxa, Praetors' Voice"   # step 1: enriched deck
```

First `deck_builder` run on a new commander is **slow (~3 min)** — see the
Scryfall gotcha below. Repeat runs are instant (disk cache in `cache/`).

## What's built (module by module)

| Module | State | Notes |
|---|---|---|
| `http/rate_limiter.py` | done | per-host min-delay, injectable clock |
| `http/cache.py` | done | JSON disk cache, TTL, atomic writes, DFC-safe keys |
| `http/client.py` | done | `get_json`/`get_text`/`_send`; **429 retry honouring Retry-After**; per-request headers; configurable delays |
| `edhrec_client.py` | done (step 1 spine) | `EdhrecClient`: build-id (auto-refresh on 404), deck table, decklist; `format_commander_name`; `filter_deck_hashes` |
| `scryfall_client.py` | done (step 1) | `get_card_metadata`: cards/named, DFC fallback to `card_faces[0]`, cached by name, `Accept` header |
| `deck_model.py` | done (step 1) | immutable `Card` + `DeckModel`; `.category`, `.categorized()`, `.to_decklist()`, `.card_names()`, `.unresolved` |
| `deck_builder.py` | done (step 1) | `build_deck(edhrec, enrich, commander, deck_id=)`; commander split; `NoDecksAvailable`; unresolved cards surfaced not dropped |
| `spike.py` | done (0.3) | throwaway end-to-end driver |
| `spellbook_client.py` | **stub** (steps 2/3) | schemas already verified — see verified.md §1–2 |
| `win_conditions.py` | **stub** (step 2) | |
| `bracket.py` | **stub** (step 3) | |
| `dck_export.py` | **stub** (step 4) | `.dck` format pinned in prior-art.md |
| `buy.py`, `collection.py` | **stub** (steps 5/6) | build last, on demand |

## What to do next

**Immediate recommended follow-up (a known wart, not yet done):**
Switch deck enrichment from per-card `cards/named` to **`POST https://api.scryfall.com/cards/collection`**
(≤75 identifiers/request → ~2 calls per deck instead of ~100). Scryfall throttles
per-card hammering — that is why cold builds take ~3 min. Plan:
- Add `post_json` is already feasible via `HttpClient._send("POST", ...)` — add a
  thin `HttpClient.post_json(url, json_body, headers=)` wrapper.
- Add `scryfall_client.get_collection(http, names) -> (by_name, not_found)`:
  read the per-name disk cache first, batch only the misses, cache each result.
  **Gotcha:** the collection endpoint returns cards whose `name` may differ from
  the requested name (DFCs return `"Front // Back"`), and order is not guaranteed
  alongside `not_found` — match requested→returned carefully (front-face compare).
- Point `deck_builder._enrich_unique` at `get_collection`; keep `get_card_metadata`
  for single-card substitution lookups (step 4).

**Then build step 2 — win conditions** (see [win-conditions.md](win-conditions.md)
and [verified.md §1](verified.md)): three-source merge.
- Combos: `POST backend.commanderspellbook.com/find-my-combos` (paginated; read
  `results`). The "Add 1" pool = `results.almostIncluded` **filtered to variants
  missing exactly one card** vs the current deck.
- Alt-wins: Scryfall `oracle:"win the game"` scan.
- Non-combo plan: the ~50-line oracle heuristic over the enriched `DeckModel`
  (this is one of only two genuinely-custom pieces — see CLAUDE.md §2).

## Critical knowledge (do not relearn the hard way)

- **EDHREC build id is THE fragile point.** If deck fetches start 404ing, the
  build id rotated — `EdhrecClient.fetch_deck` already auto-refreshes once. Isolated
  in `edhrec_client._scrape_build_id`.
- **A commander with no deck page returns HTTP 403** (not an empty table).
  `fetch_deck_table` maps 403/404 → `[]` = the §5 "average-deck fallback" signal.
  **The §5 average-deck fallback itself is NOT built** — `build_deck` raises
  `NoDecksAvailable` instead. Build it when first needed.
- **EDHREC deck-table rows already carry a `bracket` (1–5) label** + `salt`. For
  build step 3, PREFER that label for unmodified decks; infer only for modified
  ones. (verified.md item 6.)
- **Spellbook `estimate-bracket` returns a `bracketTag`** mapped to bracket
  *ranges* (E=1+, C=2+, O=2-3+, P=3+, S=3-4+, R=4+, B=N/A) — not single numbers.
  It also flags `cards[].gameChanger`/`banned`/`extraTurn`/`massLandDenial`, so it
  basically implements the official rubric. (verified.md item 2.)
- **Game Changers**: 53 cards in `data/game-changers.json`; refetch live via
  Scryfall `is:gamechanger`, don't hardcode. Bracket rules are still WotC **beta**
  (last change 2025-10-21; tutor restriction removed → tutor-density signal is now
  off-rubric). (verified.md items 3–4.)
- **Be a good API citizen**: all three services are free community APIs. Caching +
  rate limits are mandatory, not optional (CLAUDE.md §2).

## Repo conventions

- **Commits**: conventional (`feat:`/`docs:`/`chore:`/...), no attribution trailer
  (user disables it globally). Branch is `main`; user works solo, pushes direct to
  `main`, no PRs. **Commit only when the user asks.**
- **Gitignored / never committed**: `cache/` (rebuilt), `data/precons/` (26 MB,
  unlicensed — local calibration only), the personal collection file
  (`myCollection.csv`), `.venv/`. **Committed data**: `data/game-changers.json`.
- **Two untracked files are intentionally left out of git**: the root `CLAUDE.md`
  (a harness-generated duplicate of `docs/CLAUDE.md` — `docs/CLAUDE.md` is the
  canonical bible) and `myCollection.csv` (personal). Leave them be.
- **Line endings**: git warns LF→CRLF (`core.autocrlf=true` on this machine);
  blobs are stored LF, harmless. No `.gitattributes` yet.
- **Tests**: pytest, deterministic, no live network (httpx MockTransport, zeroed
  rate delays). Keep it that way — verify live behavior with the `spike`/`deck_builder`
  CLIs, not the suite.

## Doc map

- [`CLAUDE.md`](CLAUDE.md) — the bible: principles, build order, endpoints. Start here.
- [`architecture.md`](architecture.md) — data flow + module breakdown.
- [`verified.md`](verified.md) — **live-verified API schemas, mappings, EDHREC fields** (the §12 sweep). Consult before wiring Spellbook/Scryfall/EDHREC.
- [`win-conditions.md`](win-conditions.md) / [`bracket-evaluator.md`](bracket-evaluator.md) / [`buy-pipeline.md`](buy-pipeline.md) — per-feature specs for steps 2/3 and 5/6.
- [`prior-art.md`](prior-art.md) — reference repos + the precon dataset + the `.dck` format for step 4.
