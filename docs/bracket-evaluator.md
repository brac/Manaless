# Bracket Evaluator

> How the tool estimates a deck's power level (1–5) so the user can feel each
> bracket and assemble a practice ladder.

## Goal

"Understand what brackets feel like" is a primary requirement. To deliver it, the
tool needs to (a) estimate where a given deck sits, and (b) mass-produce decks at
a chosen level so the user can play a graded ladder against AI.

The framework is the official **Commander Brackets** system: 1 (exhibition) →
2 (core) → 3 (upgraded) → 4 (optimized) → 5 (cEDH), with a semi-official
**Game Changers** list of the highest-power cards (fast mana, powerful tutors,
etc.) anchoring the upper brackets.

## Approach — don't build from scratch

### Baseline: Commander Spellbook `estimate-bracket`
POST a decklist; the endpoint returns bracket-relevant information, mainly
two-card combos classified by their requirements. This was purpose-built by the
Spellbook backend dev for bracket estimation — use it as the baseline rather
than hand-rolling combo analysis.

**Caveat — bucket mapping.** The API returns *thematic buckets*, not the 1–5
scale directly. The maintainers use a conversion (e.g. Ruthless→4, Spicy→3, …).
Apply that mapping yourself. **Verify the current mapping before baking it in** —
it has shifted as the bracket system settled.

### Custom layer: non-combo power signal (Scryfall)
A combo-focused endpoint underweights decks that are powerful for non-combo
reasons. Add a small density score over enriched card data:
- **Game Changers count** — how many cards from the current official list.
- **Fast mana** — Sol Ring, Mana Crypt, rituals, etc.
- **Tutors** — density of "search your library" effects.
- **Cheap/free interaction** — Swan Song, Force of Will, Fierce Guardianship, etc.

Combine: `bracket = f(spellbook_baseline, gamechanger_density, fastmana,
tutors, free_interaction)`. Keep it explainable — a weighted count, not a model.

### Calibration: precon dataset
**taw/magic-preconstructed-decks-data** — every official precon as JSON with
correct cards/commander/printing. Precons are Wizards' bracket-2 reference
decks. Run the evaluator across all precons; confirm they cluster at ~2. If they
don't, retune weights before trusting the evaluator on EDHREC decks. This is your
ground truth.

## Practice-ladder generation

Because the pipeline is headless/batch-capable (see architecture.md), you can:
1. Pick a commander (or several).
2. Pull its real decks, score each.
3. Bucket by estimated bracket.
4. Batch-export `.dck` files per bracket → a graded set to play against AI.

This is where the EDHREC pipeline + evaluator combine into the "feel each
bracket" experience that motivates the whole project.

## Verify before baking in (don't trust memory)
- [ ] Current Commander Brackets official definitions.
- [ ] Current Game Changers list (updated periodically).
- [ ] Current Spellbook bucket → 1–5 mapping.
- [ ] Whether EDHREC indexed decks already carry a power/bracket label — if so,
      prefer the label and use inference only as a cross-check / fallback.

## Notes
- Price band (from the EDHREC deck table) is a crude pre-filter but a real one —
  cEDH decks skew expensive. Use it to narrow before the finer estimate, not as
  the estimate itself.
- The evaluator and the win-condition engine share the Scryfall enrichment and
  the Spellbook client — build those once, consume from both.
