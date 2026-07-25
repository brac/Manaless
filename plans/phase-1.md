# Phase 1 — Layout stability: stop the swap from moving the page

**Milestone goal.** An htmx edit (swap / add / remove) must not move content that
the edit did not change. Today an untouched section heading jumps ~39–57px per
swap. After this phase it must not move more than 2px.

Scope is layout stability only. Mobile overflow, touch targets, and swap blast
radius are later phases — see *Out of scope*.

---

## 1. Research-verified facts / settled decisions — DO NOT RELITIGATE

Measured on this machine against the running app, 2026-07-25. These are settled;
do not re-derive them, and do not "improve" the decisions.

| Fact | Value | How it was verified |
|---|---|---|
| Scryfall `normal` image intrinsic size | **488 × 680** (ratio 0.71765 = 61/85) | Fetched real bytes, parsed the JPEG SOF header |
| `.card .noimg` current aspect-ratio | `5/7` = 0.71429 — **wrong by 0.5%** | Read `style.css:101` |
| `.card img` current aspect-ratio | **none at all** | Read `style.css:100` |
| Unsized images on the build page | **78** | `scripts/verify/ui_audit.py` |
| Anchor jump across one swap | **56.9px mobile / 38.9px desktop** | audit script |
| Input-inclusive shift score across one swap | **0.2519 / 0.2071** | audit script |
| Scroll drift across one swap | **14px / 32px** | audit script |
| Nodes churned per single-card edit | **~599** | audit script |

**Settled decision — spec CLS is the wrong instrument.** `layout-shift` entries
within 500ms of a click are flagged `hadRecentInput` and excluded from CLS by
spec. Every shift a click-driven htmx swap causes lands in that window. Measured
here: spec CLS `0.0000` while the input-inclusive score was `0.25`, with **every**
shift event flagged (1/1 mobile, 2/2 desktop). Gate on `anchor jump` and the
input-inclusive `shift score` from the audit script. Do not add a CLS-based gate.

**Settled decision — fix the reserved box, do not fight htmx.** The jump is caused
by images having no intrinsic box, not by htmx's swap semantics. Do **not** reach
for `hx-preserve`, `hx-swap` scroll/show modifiers, morphing, or an idiomorph
extension in this phase. Reducing swap blast radius is phase 3; if the box is
reserved correctly, a full replacement is already visually stable.

---

## 2. Dependencies

**Pin: nothing new.** No npm, no CDN, no CSS tooling, no htmx extension. The fix is
CSS plus two HTML attributes. `playwright` is already installed in `.venv` for the
audit script. If you believe you need a dependency, stop and report instead.

---

## 3. Files to modify

### `src/manaless/web/static/style.css`

Give the real image the same reserved box the placeholder already has, and correct
the placeholder's ratio to match the actual asset.

- `.card img` (line ~100): add `aspect-ratio: 488 / 680;` and
  `object-fit: cover;`. Keep `width: 100%`, `display: block`.
- `.card .noimg` (line ~101): change `aspect-ratio: 5/7` → `aspect-ratio: 488 / 680`
  so a card does not resize when enrichment resolves.
- Add a short comment above both explaining *why* the ratio is hardcoded (Scryfall
  `normal` is a fixed 488×680) so a later reader does not "simplify" it away.

Write the ratio as `488 / 680`, not a decimal — it documents its own origin.

### `src/manaless/web/templates/_cardlist.html`

In the `card_media` macro, add `width="488" height="680"` to the `<img>` tag.

Why both this *and* the CSS: the attributes give the browser an aspect ratio during
initial parse, before stylesheets resolve; the CSS rule keeps the box correct when
the grid resizes the element. Neither alone is sufficient. Keep `loading="lazy"` —
it is safe once the box is reserved, and it matters for a 100-card list on a phone.

### `scripts/verify/ui_audit.py`

Do not modify. It is the reviewer's instrument and the gate you are judged by. If
you believe it is measuring something incorrectly, **stop and report** — do not
edit it and do not adjust `THRESHOLDS`.

---

## 4. Stop conditions — all must pass, run them yourself

Run against the live server. Start it if needed:
`./run.ps1 -BindHost 127.0.0.1 -Port 8000 -NoBrowser`

1. **UI gate** — `python scripts/verify/ui_audit.py`
   - `unsized images` = **0** at both viewports
   - `anchor jump px` ≤ **2** at both viewports
   - `shift score (swap)` ≤ **0.02** at both viewports
   - `scroll drift px` ≤ **2** at both viewports
   - Horizontal-overflow and tap-target rows **may still FAIL** — those are phases
     2–3. Report their numbers; do not fix them here.
2. **Regression** — `python -m pytest tests -q` exits 0 (343 tests at baseline).
3. **Visual evidence** — `python scripts/verify/ui_audit.py --shots <dir>` and
   report the absolute paths. Do not describe what the images look like; Ben is the
   visual judge.

These numbers are hard. If a gate genuinely cannot pass, **stop and report with the
measured value** — do not relax a threshold, do not edit the audit script, do not
report a gate green that is not.

---

---

## 4b. REVIEWER AMENDMENT — the original gate was invalid (2026-07-25)

The stop conditions above (`anchor jump`, `shift score`, `scroll drift`) were
**wrong**, and the implementer was right to report them failing rather than force
them green. Recorded here because the mistake is instructive:

- Those three metrics conflated **three different movements**: (a) Playwright's own
  click-actionability scroll, measured at **+214px** at mobile width just from
  opening the modal; (b) the swap's legitimate reflow — a card really does leave a
  76-tile grid; (c) the actual bug, async images popping in without a reserved box.
  Only (c) was in scope, so the gate was unmeetable by construction.
- Fixed by baselining **after** the modal opens (excludes (a)) and measuring anchor
  movement **between t+150ms and t+2500ms after the swap** (excludes (b), isolates
  (c)). New metric: `settle drift`.
- **The first version of that new metric was vacuous.** It read 0.0px even against
  the fully unfixed code, because a warm browser cache re-renders a swapped tile's
  image instantly — no late arrival, no pop. Caught by negative-proofing the gate
  against reverted code, which is why that step is non-negotiable.
- Final instrument delays `cards.scryfall.io` responses by 250ms and disables the
  HTTP cache, reproducing the real first-scroll condition. Negative proof:
  **3465px (mobile) / 1451px (desktop)** drift with the bug present, **0.0px** with
  the fix. The gate now demonstrably detects what it claims to.

This was an instrument defect, not a threshold relaxation — the fixed gate is
strictly *stricter* than the broken one, which could not fail correctly.

**Accepted deviations from the implementer:** `width`/`height` added to the two
bare `<img>` tags in `build.html` (`#cardmodal`, `#cardpreview`). Not in the plan's
file list, but they were 2 of the 78 unsized images and the gate counts globally.
Correct call. (Its report said "353 passed"; ground truth re-run is **343 passed**
with no test files modified — a misreport in the report, not a code change.)

`swap scroll delta` remains **32px** at both viewports. That is real and deferred
to phase 3 — it is the edit's own reflow, not an image-box bug.

## 5. Out of scope — do not touch

- Horizontal overflow / the topbar `.actions` row / `.htmx-indicator` (phase 2).
- Touch-target sizing (phase 2).
- Swap blast radius, `hx-preserve`, OOB restructuring, morphing (phase 3).
- Interaction states, colours, typography, spacing rhythm — the visual language is
  staying as-is this phase.
- Any Python outside `scripts/verify/` — no route, model, or client changes.
- `scripts/verify/ui_audit.py` itself, including `THRESHOLDS`.
- **Do not commit. The reviewer commits after approval.**

---

## 6. Report format

1. Files changed, with the exact diff of each CSS rule and the `<img>` tag.
2. Every command run, with its exit code.
3. Stop-condition checklist — each item PASS/FAIL with the **measured number**,
   both viewports, before and after.
4. Screenshot absolute paths.
5. **Deviations**, each with justification. If you did something the plan did not
   specify, say so explicitly — an undisclosed deviation is the failure mode this
   section exists to catch.
6. Anything you did **not** run, and why.
