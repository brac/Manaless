# Prior Art & Calibration Data

> **Phase 0.5 deliverable.** Indexes the §10 reference repos (what each gives us
> and what's already harvested), records the **precon calibration dataset** pulled
> for build step 3, and pins the exact **`.dck` format** for build step 4 — so
> nothing here gets reinvented later.

Acquired / recorded on **2026-06-27**.

## Precon calibration dataset (build step 3)

The bracket evaluator's ground truth: every official precon as JSON. Per
bracket-evaluator.md, run the evaluator across these and confirm they cluster at
~bracket 2 before trusting it on EDHREC decks.

- **Source:** `taw/magic-preconstructed-decks-data` (GitHub, `master`).
- **Local file:** `data/precons/decks_v2.json` (~26 MB). **Gitignored** — see
  license note. Use `decks_v2.json`, not `decks.json` (v2 adds explicit
  `commander` / `displayCommander` / `planarDeck` / `schemeDeck`).
- **License: NONE declared** → treat as **local calibration only; do not
  redistribute or commit.** `data/precons/` is in `.gitignore` for this reason.
  Refresh by re-downloading the raw file (repo is updated continuously — last
  push 2026-06-27).

### Shape (verified by loading the file)
- Top level: JSON **array of 2810 decks**.
- **201 decks carry a `commander`** (the Commander-format subset = the
  calibration set). Span 2009-08-26 → 2026-06-26; median total size 100 cards.
- Deck fields: `name, type, set_code, set_name, release_date, cards[],
  sideboard[], commander[], displayCommander, planarDeck, schemeDeck`.
- Card fields: `name, set_code, number, foil, count, mtgjson_uuid,
  multiverseid?`.
- **Selector for calibration:** `deck.get("commander")` is truthy (more robust
  than `type == "Commander Deck"` — 190 are typed that way, 11 more are
  commander products under other types).

### Calibration nuance
WotC positions precons as the **bracket-2** reference, but not uniformly — some
modern/upgraded precons play at bracket 3. Expect the evaluator to **cluster**
at 2 with a tail into 3, not a hard single point. Cross-check against the EDHREC
`bracket` label (verified.md item 6) as a second ground truth.

## `.dck` export format (build step 4)

Authoritative line format, from `thebear132/MTG-To-XMage` (`utils.py`), matching
CLAUDE.md §8. XMage resolves by **card name alone**, so `[SET:NUM]` may be
placeholders — but this is the exact shape its importer round-trips:

```
1 [SET:NUM] Card Name           # mainboard: "{qty} [{set}:{num}] {name}"
SB: 1 [SET:NUM] Card Name       # sideboard
```

- **Commanders go in the sideboard** with the `SB:` prefix — XMage's convention
  for the command zone. (MTG-To-XMage moves every commander into `sideboard`
  before writing.)
- **DFC / split / "//": emit the FRONT FACE name only** (`name[:name.index("//")-1]`).
- File: `<DeckName>.dck`, UTF-8, dropped in the XMage `/decks` folder.
- No `LAYOUT` header is required; the flat `qty [set:num] name` lines suffice.

## §10 reference index

| Repo | Gives us | Status |
|---|---|---|
| `spicyFajitas/edhrec-deck-tools` | EDHREC raw-endpoint pipeline: build-id, slug, rate limiting, DFC | **Patterns absorbed** into `edhrec_client.py` (Phase 0.3) |
| `SpaceCowMedia/commander-spellbook-backend` + `-site` | Spellbook OpenAPI schemas; `bracketTag`→bracket map (`src/lib/brackets.ts`); `computeBracketInfo` reference algorithm; `ClassifiedCard` flags | **Mined in Phase 0.4** → docs/verified.md |
| `jamese.dev "Combinator"` | UX reference for surfacing `find-my-combos` + the "Add 1" tab | API behavior verified directly (0.4); keep as the UX model for step 2 |
| `thebear132/MTG-To-XMage` | `.dck` line format + commander/DFC handling | **Format captured above** for step 4 |
| `taw/magic-preconstructed-decks-data` | Precon calibration ground truth | **Acquired** → `data/precons/decks_v2.json` |

## Net: what's actually left to build (still just the two custom pieces)
Everything above is pulled or mirrored. Per CLAUDE.md §2, the only genuinely
custom code remains: **(a)** the non-combo win-condition heuristic (§6, ~50 lines)
and **(b)** the collection-diff buy step (step 6). The bracket evaluator (step 3)
is now mostly *consume-and-combine* — EDHREC's `bracket` label + Spellbook's
`estimate-bracket`/`computeBracketInfo` — not a from-scratch model.
