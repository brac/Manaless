# Phase 2 — Mobile fit: horizontal overflow and touch targets

**Milestone goal.** The builder must fit a 390px-wide phone with no horizontal
scrolling, and its primary controls must be thumb-sized. Ben reaches this app over
LAN on an iPhone, so mobile is a real target.

---

## 1. Research-verified facts / settled decisions — DO NOT RELITIGATE

Measured 2026-07-25 via `scripts/verify/ui_audit.py` at 390x844.

| Fact | Value |
|---|---|
| Horizontal document overflow at 390px | **123px** (document lays out 513px wide) |
| Widest offender | `.topbar .actions`, right edge **513px** |
| Also flagged | `#global-spinner.htmx-indicator` right **500px**, `.btn ghost` right **440px** |
| Interactive elements under 24x24 | **2**: `a.back` (15x25), `a` in `.owned-summary` (80x20) |
| Topbar controls under 44x44 | **3 mobile / 5 desktop**, all `.btn` / `.btn ghost` at 35–37px tall |
| Viewport meta | **already correct** — `width=device-width, initial-scale=1` in `base.html` |
| Existing breakpoint | `@media (max-width: 900px)` collapses `.layout` to one column |

**Settled diagnosis — one root cause, one follow-on.** `.topbar` is
`display:flex; justify-content:space-between` and `.topbar .actions` is a
non-wrapping flex row holding four controls (Export / Buy missing / Collection /
Reset). At 390px they cannot fit, so the document itself lays out 513px wide.
`#global-spinner` is `position:fixed; right:.8rem`, which then resolves against
that *widened* layout viewport — which is why it reports a 500px right edge.
**Fix the `.actions` overflow and the spinner follows.** Do not reposition the
spinner to chase its symptom.

**Settled decision — the 44px floor is topbar-only.** Per-tile card controls stay
as they are; forcing 44x44 there would turn the dense 76-card grid into a list.
The audit gates exactly this scope (`PRIMARY_SCOPE = ".topbar"`). Do not widen it.

---

## 2. Dependencies

**Nothing new.** CSS only. No JS changes are expected; if you think you need one,
stop and report. Do not add a CSS framework, container queries polyfill, or npm.

---

## 3. Files to modify

### `src/manaless/web/static/style.css` — expected to be the only file

1. **Let the topbar wrap.** Add `flex-wrap: wrap` to `.topbar` and to
   `.topbar .actions`. This alone should clear most of the 123px.
2. **Add a phone breakpoint.** The existing `@media (max-width: 900px)` is for the
   two-column collapse. Add a narrower one (suggest `max-width: 560px`) that:
   - makes `.topbar .actions` full width (`width: 100%`) so it forms its own row
     under the commander name rather than competing for space on one line;
   - lets the action buttons share that row (e.g. `flex: 1 1 auto`) instead of
     overflowing.
3. **Touch targets.** Give topbar controls a real hit box:
   `min-height: 44px`, and enough horizontal padding that width also clears 44.
   Apply to `.topbar .btn`, `.topbar button`, and `.topbar .back`. `.back` is
   currently a bare 15x25 "←" glyph — it needs `display: inline-flex;
   place-items: center; min-width: 44px; min-height: 44px` or equivalent.
4. **The `.owned-summary` link** (`{{ n }} to buy →`, currently 80x20) must clear
   24px: `display: inline-block` plus vertical padding is enough. Do not make it
   44px — it is body copy, not chrome, and the AA floor is what applies.

Use the existing custom properties; do not introduce new hardcoded colours.
Keep the changes additive — do not restructure unrelated rules.

### Anything else

If a template change turns out to be genuinely necessary (e.g. the topbar markup
cannot wrap sensibly without a wrapper element), you may edit
`src/manaless/web/templates/build.html` — but **report it as a deviation with the
reason**, and change nothing else.

### `scripts/verify/ui_audit.py`

**Do not modify**, including `THRESHOLDS`. It is the reviewer's instrument and the
gate you are judged by. If you believe it measures something wrongly, stop and
report. (Its gate was already found broken once this project and fixed by the
reviewer — the correct response is a report, not an edit.)

---

## 4. Stop conditions — run them yourself

Server: `./run.ps1 -BindHost 127.0.0.1 -Port 8000 -NoBrowser` (background), confirm
it answers before auditing. Restart it after editing CSS if changes don't appear.

1. **UI gate** — `./.venv/Scripts/python.exe scripts/verify/ui_audit.py`
   - `horiz overflow px` = **0** at mobile (and stays 0 at desktop)
   - `targets < 24px (AA)` = **0** at both viewports
   - `topbar < 44px (AAA)` = **0** at both viewports
   - **Phase 1 must not regress**: `settle drift px` ≤ 2 and `unsized images` = 0 at
     both viewports. These are now regression gates.
   - `swap scroll delta` will still report ~32px. That is **phase 3**. Leave it.
2. **Regression** — `./.venv/Scripts/python.exe -m pytest tests -q` exits 0
   (**343 passed** at baseline — report the actual number you observe).
3. **Screenshots** — `--shots <dir>`; report absolute paths only. Ben is the visual
   judge; do not describe or evaluate the images.

Hard numbers. If a gate cannot pass, **stop and report the measured value** and
what you tried. Never relax a threshold, never edit the gate, never report a row
green you did not observe green.

---

## 5. Out of scope — do not touch

- `swap scroll delta` / swap blast radius / `hx-preserve` / OOB restructuring (phase 3).
- Interaction states, animation, colour palette, typography, spacing rhythm.
- The card grid's per-tile controls and their sizes.
- Any Python, route, template logic, or test.
- `scripts/verify/ui_audit.py` and its `THRESHOLDS`.
- **Do not commit. The reviewer commits after approval.**

---

## 6. Report format

1. Files changed with exact diffs.
2. Every command run + exit code.
3. Stop-condition checklist: PASS/FAIL with **measured numbers**, both viewports,
   before and after — including the phase-1 regression rows.
4. Screenshot absolute paths.
5. **Deviations**, each justified. Undisclosed deviations are the failure this
   section exists to catch.
6. What you did **not** run, and why.
