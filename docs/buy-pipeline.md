# Buy Pipeline

> The rare, deliberate exit from the funnel. Built LAST and kept minimal.

## Principle

Purchase fires occasionally, not in the main loop. Do not over-build it. The
vendors already do pricing, cheapest-seller selection, and shipping optimization
— lean on them. The only custom value here is **"buy only what I don't already
own"**, which no vendor button does.

Two distinct shapes, only one needs the collection diff:

## Shape A — Single card ("I want that card I saw in play")

No diff needed.
```
card name → TCGplayer Mass Entry URL → open browser tab
```
Bookmark-tier effort. Build this the first time you actually want a card.

## Shape B — Whole deck ("I fell in love with this deck")

```
.dck file
  → parse to (qty, name) list
  → diff against local collection file (name + qty)
  → missing cards only
  → TCGplayer Mass Entry payload → open browser tab
```
Mass Entry then optimizes cheapest-per-seller across vendors and minimizes
shipping server-side. Build this ONLY after first wanting a paper deck — let real
usage tell you what it needs.

## TCGplayer Mass Entry — the mechanism

- It's the **public web form** their own "Buy Deck" buttons target — NOT the
  locked-down affiliate/developer API. No key needed.
- Accepts newline-delimited `quantity cardname` lines, with or without set codes
  and collector numbers. Less specificity = "any printing".
- Gear icon → preferences for acceptable printings/conditions (default: all
  printings, Moderately Played and better).
- You construct the list and open the URL; the cart builds on their side.

### Name normalization (the fiddly part)
- Strip XMage set codes/collector numbers from `.dck` lines.
- Handle split/DFC naming: TCGplayer may want the front face or full `A // B`
  depending on card. Test against a few real DFCs and adjust.
- This is the main source of buy-step bugs; keep a small override map for the
  handful of cards that don't resolve cleanly.

## Secondary vendors
- **Card Kingdom** — has its own mass-entry; single-vendor, consistent
  condition, simpler shipping. Good for "what TCGplayer's cheapest sellers lack".
- **Cardmarket** — relevant if buying from Europe.

## Zero-code cross-check
**Deckstats** imports XMage decks, tracks a collection, and shows multi-vendor
price comparison (TCGplayer, Card Kingdom, Cardhoarder, Miracle Games,
Cardmarket). If you ever don't want to maintain the diff yourself, its collection
tracker does the "what do I own" subtraction. Worth knowing as a fallback so you
don't over-invest in custom buy tooling.

## What NOT to build
- No vendor-side cart logic — Mass Entry owns that.
- No price scraping for the buy step — open the tab and let the vendor price it.
- No speculative multi-vendor optimizer — Mass Entry already optimizes.
