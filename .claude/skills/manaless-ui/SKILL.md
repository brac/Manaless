---
name: manaless-ui
description: UI invariants for the Manaless web builder — FastAPI + Jinja + htmx + hand-written CSS, no build step and no framework. Use when touching anything under src/manaless/web/ (templates/, static/style.css, static/ui.js) or when changing an htmx swap, an OOB target, a card tile, or the responsive layout. Covers layout stability across swaps, OOB discipline, touch-target floors, and the measurement gate that proves a change worked.
---

# Manaless UI

The builder is a **server-rendered Jinja app driven by htmx**. There is no build
step, no framework, no CSS preprocessor, and no npm. `htmx.min.js` is vendored in
`src/manaless/web/static/`. Ship plain HTML, plain CSS, and small vanilla JS.

Do not introduce React/Vue/Tailwind/PostCSS/a bundler, and do not add a CDN link —
the app is served over LAN to a phone and must work with no external hosts.

## The layout-stability rule (this app's #1 historical bug)

An edit replaces `#cardlist` wholesale — ~600 DOM nodes and ~76 card tiles for a
one-card change. **Every element in a swapped region must reserve its box before
its content arrives**, or the list reflows and the page visibly jumps while the
user scrolls.

Concretely, for any media inside a swap target:

- Card images need an intrinsic box. Scryfall `normal` images are **488x680**
  (aspect ratio 61/85, ~0.7176). Set `aspect-ratio` in CSS *and* `width`/`height`
  attributes on the tag — the attributes give the browser a ratio before CSS
  applies, the CSS rule survives responsive width changes.
- The `.noimg` placeholder and the real `img` must share the same aspect ratio, or
  a card flips size the moment enrichment resolves.
- `loading="lazy"` re-arms on every recreated element. It is fine *only* when the
  box is already reserved; otherwise it guarantees a reflow storm on each swap.

### Measuring it — CLS will lie to you

`layout-shift` entries within 500ms of a click carry `hadRecentInput: true` and are
**excluded from CLS by spec**. Every shift an htmx swap causes lands in that window,
so standard CLS reads `0.0000` on a page that is visibly jumping. Measured on this
app: spec CLS `0.0000` while the input-inclusive score was `0.25`.

Never gate this app's swap behaviour on CLS. Use `scripts/verify/ui_audit.py`, which
measures the thing directly:

```bash
python scripts/verify/ui_audit.py            # exit 0 = all gates pass
python scripts/verify/ui_audit.py --shots DIR  # also write PNGs for Ben to judge
```

Its load-bearing metric is **anchor jump**: how far an untouched section heading
moves relative to the viewport across a swap. That is the complaint, as a number.

## htmx conventions already in place

- `#cardlist` is the primary target (`hx-swap="outerHTML"`). `_update.html` is the
  edit response and OOB-swaps everything else: readouts placeholder, `#composition`,
  `#palette`, `#cardcount`, `#flash`.
- **Every mutating control must carry the session id.** `#builder` sets
  `hx-vals='{"sid": ...}'` so it is inherited; a control placed outside `#builder`
  silently loses it and the endpoint falls back to the cookie, which breaks
  multi-tab isolation. Keep new controls inside `#builder`.
- Readouts are **lazy** (`/build/readouts`) because two Spellbook POSTs cost ~2s.
  Composition is **inline** because it is pure and instant. Preserve that split:
  never move a network-bound readout inline, never make a pure one lazy.
- New OOB region: give it a stable `id`, include it in `build.html` (first paint)
  **and** `_update.html` (with `hx-swap-oob="true"`), or it goes stale after the
  first edit. Forgetting the `_update.html` half is the classic bug here.

## Responsive floors

Ben reaches this over LAN **on an iPhone**, so mobile is a real target, not a
courtesy. Gates enforced by the audit script:

- **No horizontal document overflow at 390px.** The topbar `.actions` row and the
  `.htmx-indicator` have both caused this.
- **Every interactive element >= 24x24 CSS px** (WCAG 2.5.8 AA).
- **Topbar controls >= 44x44** (WCAG 2.5.5 / Apple HIG) — those are thumb targets.

The 44px floor is deliberately scoped to primary chrome. Applying it to the card
grid's per-tile controls would force the dense browse layout into a list; that
tradeoff was considered and rejected.

## Style conventions

- Dark theme via CSS custom properties in `:root` (`--muted`, `--good`, `--bad`,
  `--accent`, `--border`, `--panel2`). Use the tokens; do not hardcode hex.
- Numeric columns get `font-variant-numeric: tabular-nums` so figures align down a
  column (prices, composition counts, curve buckets).
- Wide content (the curve table) scrolls inside its own `overflow-x: auto`
  container. The page body must never scroll horizontally.

## Verification

A UI change is not done until:

1. `python scripts/verify/ui_audit.py` exits 0.
2. `python -m pytest tests -q` is green (the web tests assert on rendered markup,
   so template edits break them and that is working as intended).
3. Screenshots are handed to **Ben** — he is the visual judge. Do not ask a model to
   look at them; report the paths and the measured numbers.
