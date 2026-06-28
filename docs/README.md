# MTG Commander Try-Before-You-Buy — Docs

Starter documentation set. Read `CLAUDE.md` first — it's the project bible and
the handoff artifact for Claude Code.

## The project in one line
A try-before-you-buy funnel for paper Commander: browse real curated decklists,
substitute cards with live win-condition + bracket feedback, export to XMage to
play vs AI and learn, then (rarely) buy the cards you fell for.

## Files
- **CLAUDE.md** — project bible. Principles, build order, exact endpoints,
  component status, verify-at-build-time checklist. Start here.
- **docs/architecture.md** — data flow + module breakdown + caching.
- **docs/win-conditions.md** — three-source merge (Spellbook + Scryfall).
- **docs/bracket-evaluator.md** — power-level estimation + practice ladder.
- **docs/buy-pipeline.md** — the minimal, build-last purchase exit.

## Build order (from CLAUDE.md §3)
1. Deck-fetch + enrich pipeline (the spine)
2. Win-condition module
3. Inferred bracket
4. Substitution UI + `.dck` export
5. Single-card buy (when first wanted)
6. Deck-diff buy (when first wanting a paper deck)

## The two genuinely custom pieces
Everything else is pulled from existing APIs/data. Only these are yours to build:
1. The non-combo win-condition heuristic (~50 lines of Scryfall oracle matching).
2. The collection-diff buy step.

## One thing to never forget
The EDHREC **build ID** is the single hard-break dependency. If deck fetches
start failing, refresh the build ID first. Everything else degrades gracefully.

## Verify-at-build-time (don't trust memory — see CLAUDE.md §12)
Spellbook schemas + bucket→1–5 mapping, current Commander Brackets definitions,
current Game Changers list, EDHREC deck-table fields, and whether indexed decks
carry a power label.
