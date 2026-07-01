# Backlog

Post-MVP items surfaced from real use of the web builder. Grouped into **bugs**
(something behaves wrong) and **enhancements** (new/better behavior). Not yet
prioritized or scheduled — captured so nothing is lost.

> **Guiding principle from the owner:** *nothing should ever be randomly added or
> dropped from the deck.* Every add/remove/swap must be an explicit, deterministic
> user action. (Confirmed clean at the model layer — `DeckModel.remove/add/
> substitute` in `src/manaless/deck_model.py` are pure and never inject a random
> card. The bugs below are in the web wiring / display, not the model.)

---

## Bugs

### B1 — Card count "stays at 100" after removing a card
X-ing out a card in the builder appears to leave the count at 100. The removal
itself is correct (`DeckModel.remove` drops exactly the named card and reduces
`total_cards` by 1); the displayed count is stale. **Likely root cause:** the
`{{ deck.total_cards }} cards` counter lives in the topbar (`web/templates/
build.html:7`), which is *outside* the HTMX-swapped region. Edits return
`_update.html`, which only refreshes `#cardlist` + the readouts panel + the flash
banner — never the topbar count. Fix: move the count into the swapped fragment (or
add an `hx-swap-oob` for it) so it re-renders on every edit.

### B2 — Card count "stays at 100" after adding a popular card
Same underlying display bug as **B1**. Note the deck *should* read 101 after an
add, not 100: `/build/add` (`web/app.py:287`) is **append-only** — it never drops
anything, so nothing is "randomly dropped." The stale topbar counter just hides
the change. Fixing B1 fixes the visible symptom here too. Separately decide the
intended UX: should adding past 100 warn/block, or is going to 101 fine until the
user trims?

### B3 — Swapping in a wincon card: unclear/absent "swap out"
The "Add 1" wincon suggestion and the popular-card palette both POST to
`/build/add`, which only **adds** — nothing is swapped out. So the "seems random"
impression is really: a card was added (→101) while the stale counter still showed
100, reading as a silent swap. Decide the intended model:
- **Add-only** (current): keep, but make it obvious a card was *added* (count
  moves, toast says "Added X"), and let the user remove something explicitly.
- **True swap:** if these actions should replace a card, the UI must let the user
  pick the card to swap *out* — never choose one implicitly.

Whichever we pick, it must be explicit and deterministic (guiding principle above).

---

## Enhancements

### E1 — Full-size card image modal on click
Clicking a card in the builder should open a nice modal with the full-size card
image. (Images are already enriched — `card.image_url` in `_cardlist.html`;
Scryfall `image_uris.normal` / DFC front face.)

### E2 — Paginated commander listing
Let me page through the full commander list rather than only what fits now. Applies
to the commander browse/search surface (`web/app.py` index/search + templates).

### E3 — Commander listed first in the deck builder
Show the commander(s) as the first entry in the builder card list. `DeckModel`
already keeps `commanders` separate from `cards` and `all_cards()` returns
commanders first — surface that ordering in `_cardlist.html` (currently the list
renders `categorized()` mainboard only; commanders are separate).

### E4 — Note owned cards on the corresponding builder card
If a card is in my collection, mark it on that card in the builder. Per HANDOFF a
"✓ owned" flag + "you own X of Y" summary already exists — so this is likely
**verify/repair**: confirm it renders when a collection is imported at
`/collection`, and that per-card marking (not just the summary) shows. If the
collection isn't imported yet, that's why nothing appears.

### E5 — Fuzzy commander search
Don't require the exact commander name. Add fuzzy matching so near-misses resolve
(e.g. Scryfall `cards/autocomplete` / fuzzy named, or local fuzzy match over the
commander set). Pairs well with E2/E6.

### E6 — Autocomplete the "Swap to" input (or remove it)
The free-text "Swap to" box is unhelpful when it demands the exact card name.
Either add type-ahead autocomplete (Scryfall `cards/autocomplete`) or drop the box
in favor of the palette-driven flow. Owner's call; leaving a raw exact-match field
is the one option to avoid.
