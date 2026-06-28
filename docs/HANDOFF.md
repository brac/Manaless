# Handoff — Manaless

> **Read this first, then [`CLAUDE.md`](CLAUDE.md) (the bible).** This file is the
> live "where we are" for a fresh agent picking up the work. Last updated after
> **build step 4** (substitution + `.dck` export) core landed.

## TL;DR — current position

- **Phase 0 (groundwork): COMPLETE** — scaffold, shared HTTP layer, EDHREC spine
  spike, §12 verification sweep, prior-art + precon dataset.
- **Build step 1 (deck-fetch + enrich pipeline): COMPLETE and live-validated.**
  `build_deck(commander) -> DeckModel` works against live EDHREC + Scryfall.
  **The ~3 min cold-build wart is FIXED**: enrichment now batches through
  Scryfall `cards/collection` (≤75/req) — a cold Atraxa build is **~6s**, warm <1s.
- **Build step 2 (win conditions): COMPLETE and live-validated.** Three-source
  merge: Spellbook combos + grouped "Add 1" lines, local alt-win scan, the
  non-combo oracle heuristic. `python -m manaless.win_conditions <commander>`.
- **Build step 3 (inferred bracket): COMPLETE and calibration-validated.**
  EDHREC label for unmodified decks; Spellbook `estimate-bracket` tag→1–5 +
  custom fast-mana/interaction layer for modified decks. **Precon calibration
  passes: 16/17 sampled precons read bracket 2, one upgraded precon at 3** — the
  "cluster at 2, tail into 3" the spec predicted. `python -m manaless.bracket <commander>`.
- **Build step 4 (substitution + `.dck` export): CORE COMPLETE and live-validated.**
  `dck_export.to_dck/write_dck` emits XMage `.dck` (commander in `SB:`, DFC front
  face, placeholder `[XXX:0]` printing — XMage's importer requires the bracket and
  falls back to name lookup). Headless substitution lives on `DeckModel`
  (`.remove/.add/.substitute`, all pure → new model, provenance cleared) +
  `deck_builder.substitute_card` (enrich-and-swap). **A user-facing UI is NOT
  built** — that's a deliberate open decision (web vs TUI), see "What to do next".
  `python -m manaless.dck_export <commander> [-o DIR]`.
- **Build steps 5–6: NOT STARTED** (buy stubs in place, tagged with their step).
- **Tests: 108 passing**, no live network in the suite (httpx MockTransport).
- The strict build order is in [CLAUDE.md §3](CLAUDE.md). Do not jump ahead.

## Run it

> **Environment is now native Windows** (this machine, `C:\Users\Ben Bracamonte\Work\Manaless`).
> System python is **3.12.10**; a project **`.venv`** holds `httpx` + `pytest`.
> (The prior WSL/Debian-3.14 bootstrap notes are retired.) Recreate if missing:
> ```powershell
> python -m venv .venv
> .\.venv\Scripts\python.exe -m pip install "httpx>=0.27" "pytest>=8.0"
> ```

```powershell
.\.venv\Scripts\python.exe -m pytest                 # 108 tests, ~1s (pytest sets pythonpath=src)

# Module CLIs need PYTHONPATH=src (package isn't pip install -e'd):
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m manaless.deck_builder   "Atraxa, Praetors' Voice"  # step 1: enriched deck
.\.venv\Scripts\python.exe -m manaless.win_conditions "Atraxa, Praetors' Voice"  # step 2: win readout
.\.venv\Scripts\python.exe -m manaless.bracket        "Atraxa, Praetors' Voice"  # step 3: bracket (--infer to ignore label)
.\.venv\Scripts\python.exe -m manaless.dck_export     "Atraxa, Praetors' Voice"  # step 4: .dck text (-o DIR to write a file)
```

Repeat runs are instant (disk cache in `cache/`).

## What's built (module by module)

| Module | State | Notes |
|---|---|---|
| `http/rate_limiter.py` | done | per-host min-delay, injectable clock |
| `http/cache.py` | done | JSON disk cache, TTL, atomic writes, DFC-safe keys |
| `http/client.py` | done | `get_json`/`get_text`/`_send`; **429 retry honouring Retry-After**; per-request headers; configurable delays |
| `edhrec_client.py` | done (step 1 spine) | `EdhrecClient`: build-id (auto-refresh on 404), deck table, decklist; `format_commander_name`; `filter_deck_hashes` |
| `scryfall_client.py` | done (step 1) | `get_card_metadata` (single, cards/named) + **`get_collection`** (batch cards/collection, ≤75/req, DFC front-face match, shares the per-name cache); DFC fallback; `Accept` header |
| `deck_model.py` | done (step 1/3/4) | immutable `Card` + `DeckModel`; `.category`, `.categorized()`, `.to_decklist()`, `.card_names()`, `.unresolved`; **step 4 substitution: `.remove/.add/.substitute` (pure → new model, provenance cleared)** |
| `deck_builder.py` | done (step 1/3/4) | `build_deck(edhrec, enrich, commander, deck_id=)` — BATCH enricher `Callable[[Sequence[str]], Mapping[str, ScryfallCard]]`; threads the EDHREC table **`bracket` label** into `DeckModel.edhrec_bracket`; **step 4 `substitute_card(enrich, deck, old, new)` (enrich-and-swap)** |
| `deck_model.py` | done (step 1/3) | added `DeckModel.edhrec_bracket` (1–5 label for the source deck; goes stale on substitution) |
| `http/client.py` | done | added **`post_json`** + a `cache` accessor (for clients that key entries themselves) |
| `spike.py` | done (0.3) | throwaway end-to-end driver |
| `spellbook_client.py` | done (steps 2/3) | **`find_my_combos(http, deck) -> ComboResults`** + **`estimate_bracket(http, deck) -> BracketEstimate`** (`ClassifiedCard`/`ClassifiedCombo`); both cached by `decklist_hash` |
| `win_conditions.py` | done (step 2) | **`evaluate_win_conditions(deck, combos) -> WinConditions`** — pure merge (combos + grouped `AddOneLine` + alt-win scan + non-combo heuristic); `.to_dict()` = the win-conditions.md object |
| `bracket.py` | done (step 3) | **`evaluate_bracket(deck, estimate, edhrec_bracket=) -> BracketReadout`** — pure; EDHREC label first, else tag→1–5 + custom layer; calibrated vs precons |
| `dck_export.py` | done (step 4) | **`to_dck`/`write_dck`/`dck_filename`** + CLI; commander → `SB:`, DFC front face, placeholder `[XXX:0]` printing (importer regex needs the bracket; name fallback resolves). Live-validated on a 100-card Atraxa deck |
| `buy.py`, `collection.py` | **stub** (steps 5/6) | build last, on demand |

## What to do next

**Step 4's remaining piece — the UI — is an open product decision, NOT yet made.**
The headless substitution + recompute spine is all in place: a swap is just
`substitute_card(enrich, deck, old, new)` → new `DeckModel` → re-run
`find_my_combos`/`evaluate_win_conditions` + `estimate_bracket`/`evaluate_bracket`
on it (both Spellbook calls cache-key on `decklist_hash`, so only the changed list
re-calls the network). What's missing is the *surface* a human drives. Decide with
the owner before building:
- **CLI** (smallest; fits the current module-CLI pattern: `swap OLD NEW`, print the
  recomputed win/bracket readout + write `.dck`),
- **TUI** (Textual/curses — interactive card list, live readout panel), or
- **Web app** (richest — card images via the already-enriched `image_url`, the
  "Add 1 → completes N combos" picker from step 2; but it's a new stack/dependency).
The owner's funnel (CLAUDE.md §1) implies an interactive builder, so web or TUI is
the likely end state — but confirm scope/stack first; don't unilaterally add a
frontend framework.

**Then steps 5–6 — buy.** Build step 5 (single-card → TCGplayer Mass Entry URL)
the first time a card is actually wanted; step 6 (deck-diff vs `collection.py`)
only after falling for a paper deck. Both are stubs in `buy.py`/`collection.py`.
See [buy-pipeline.md](buy-pipeline.md). Do NOT build step 6 speculatively
(CLAUDE.md §3).

### Step 4 findings worth knowing
- **XMage's `.dck` importer regex requires the `[set:num]` bracket** — a bare
  `qty name` line is silently dropped. It resolves set/number first, then falls
  back to `findPreferredCoreExpansionCard(name, set)`, so the placeholder
  `[XXX:0]` works: no printing resolves → it matches by name. (Verified against
  `DckDeckImporter` source.)
- **Commanders live in the sideboard** (`SB:` prefix) — XMage's command-zone
  convention (mirrors thebear132/MTG-To-XMage). DFC/split cards emit the **front
  face only** (`name.split("//")[0]`).
- **Substitution clears `edhrec_bracket` + `deck_id`** on the new model — the
  source label is stale the moment the list changes, so bracket must re-infer via
  `estimate-bracket` (don't pass the old EDHREC label to `evaluate_bracket` after
  an edit).

### Step 2 findings worth knowing
- `find-my-combos` is **not actually paginated** in practice: the
  `{count,next,previous,results}` wrapper comes back with null next/previous;
  read `results` directly (confirmed live on a 100-card Atraxa list).
- For a *complete* deck, `results.almostIncluded` came back **entirely
  one-card-away** (107/107 for Atraxa). The engine still filters to exactly-one
  missing (robust if that ever changes) and then **groups by the card to add**,
  ranked by lines-completed then popularity — so the UI shows "add X → completes
  N lines", not 107 noisy rows.
- The **alt-win scan is local** (substring `"win the game"` over already-enriched
  oracle text) — no extra Scryfall `oracle:` query needed, one fewer API dep.

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
