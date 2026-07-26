"""Mechanical UI audit for the Manaless builder — the phase-gate instrument.

Prints numbers only; it never judges appearance. Ben is the visual judge (see the
phase-loop standing rule), so this measures the things a screenshot can't tell you
and that a human shouldn't have to eyeball:

  * CLS   — cumulative layout shift accumulated across an htmx swap. This is the
            "everything jumps while I scroll" bug as a number.
  * SCROLL— scroll position drift across a swap. A swap that moves the viewport is
            a bug even when CLS is 0.
  * IMG   — images with no intrinsic size (no width/height attrs and no CSS
            aspect-ratio). Each one is a guaranteed reflow when it loads.
  * OVERX — horizontal document overflow at a viewport width (mobile killer).
  * TAP   — interactive elements below the 44x44 CSS-px touch-target floor
            (WCAG 2.5.5 Target Size / Apple HIG).
  * CHURN — DOM nodes destroyed+recreated by one swap, i.e. blast radius.

Usage:
    python scripts/verify/ui_audit.py                  # audit against localhost:8000
    python scripts/verify/ui_audit.py --base URL
    python scripts/verify/ui_audit.py --shots DIR      # also write screenshots
    python scripts/verify/ui_audit.py --json           # machine-readable

Exit code is 0 when every threshold passes, 1 otherwise, so it works as a gate.
Thresholds live in THRESHOLDS below; they are the plan's hard numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

DEFAULT_BASE = "http://127.0.0.1:8000"
COMMANDER = "Atraxa, Praetors' Voice"

# Viewports audited. Mobile width matches a modern iPhone in CSS px (the device Ben
# actually reaches this on over the LAN); desktop is a common laptop.
VIEWPORTS = {
    "mobile": {"width": 390, "height": 844, "is_mobile": True},
    "desktop": {"width": 1440, "height": 900, "is_mobile": False},
}

# Hard gate thresholds.
#   cls: Google's "good" Core Web Vital bound is 0.1 for a whole page load. A single
#        in-place swap should be near-zero; 0.02 leaves room for scrollbar-width
#        jitter without permitting a real reflow.
#   scroll_drift_px: a swap must not move the viewport. 2px absorbs sub-pixel
#        rounding on fractional-DPR displays.
#   settle_drift_px: how far an untouched section heading moves AFTER htmx has
#        already settled. Nothing should move once the swap is done — anything that
#        does is media loading in without a reserved box, i.e. the reported bug.
#        Deliberately excludes the swap's own reflow (a card genuinely left the
#        grid) and the harness's click-actionability scroll; measuring those as one
#        number made the gate unmeetable and blamed the wrong code.
#   swap_scroll_px: viewport movement caused by the edit itself. PHASE 3 — reported
#        as context until then, because fixing it means reducing swap blast radius.
THRESHOLDS = {
    "settle_drift_px": 2,
    "swap_scroll_px": 2,
    "cls_after_swap": 0.02,
    "scroll_drift_px": 2,
    "unsized_images": 0,
    # Rendered aspect ratio must match the real asset — reserving a box is useless
    # if it is the wrong shape. See _RENDERED_RATIO for the regression this caught.
    "misshaped_images": 0,
    # The full-size card view must not be squashed. Rect checks skip it because it
    # is [hidden] until opened, so the audit opens it for real. Shipped squashed once
    # (351x680 instead of 351x489) because the height attribute pinned its height.
    "modal_ratio_off": 0,
    # Tiles must stay browsable on a phone. 1.1 cards per screen shipped once.
    "min_cards_per_screen": 2.0,
    "horizontal_overflow_px": 0,
    # Two tiers, deliberately. Demanding 44x44 everywhere is structurally
    # unmeetable in a 76-card grid whose tiles carry three controls each — it would
    # force the dense browse layout to become a list. So:
    #   * every interactive element must clear WCAG 2.5.8 (AA) at 24x24;
    #   * primary chrome (topbar nav/actions) must clear WCAG 2.5.5 (AAA) at 44x44,
    #     because those are the thumb targets on a phone.
    "targets_under_24": 0,
    "primary_targets_under_44": 0,
}
TAP_MIN_AA = 24
TAP_MIN_PRIMARY = 44
PRIMARY_SCOPE = ".topbar"

# Instrumentation injected before any app script runs, so no shift is missed.
# NOTE: add_init_script takes a script BODY, not a function expression. A bare
# `() => {...}` is evaluated and thrown away without ever being called, leaving the
# probe silently absent — so this must be an IIFE. (page.evaluate is the opposite:
# it takes a function expression and calls it. The other probes below rely on that.)
#
# Order matters inside: define the state and the reset hook BEFORE observe(), which
# can throw if the entry type is unsupported — otherwise a throw leaves __clsReset
# undefined and the harness dies far away from the real cause.
_CLS_PROBE = """
(() => {
  window.__cls = 0;
  window.__shifts = [];
  window.__clsSupported = false;
  window.__clsAll = 0;      // input-inclusive: see the note below
  window.__clsReset = () => { window.__cls = 0; window.__clsAll = 0; window.__shifts = []; };
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        // CRITICAL: the spec marks any shift within 500ms of a user input with
        // hadRecentInput=true and EXCLUDES it from CLS. A click-driven htmx swap
        // lands entirely inside that window, so standard CLS is structurally blind
        // to this app's jank and always reads 0. Track both: __cls is the
        // web-vital-comparable number, __clsAll is the one that can see a swap.
        window.__clsAll += entry.value;
        window.__shifts.push({ v: entry.value, recentInput: !!entry.hadRecentInput });
        if (entry.hadRecentInput) continue;
        window.__cls += entry.value;
      }
    });
    po.observe({ type: 'layout-shift', buffered: true });
    window.__clsSupported = true;
  } catch (e) {
    window.__clsError = String(e);
  }
})();
"""

# An image is "unsized" when nothing reserves its box before the bytes arrive:
# no width/height attribute pair, and no CSS aspect-ratio. Those are the elements
# that pop from 0px to full height and shove the page around.
_UNSIZED_IMAGES = """
() => {
  const bad = [];
  for (const img of document.querySelectorAll('img')) {
    const hasAttrs = img.hasAttribute('width') && img.hasAttribute('height');
    const ar = getComputedStyle(img).aspectRatio;
    const hasAR = ar && ar !== 'auto';
    if (!hasAttrs && !hasAR) bad.push(img.className || img.src.slice(-40));
  }
  return { count: bad.length, sample: bad.slice(0, 5) };
}
"""

# Reserving a box is not enough — it has to be the RIGHT box. Shipped once: adding
# width/height attributes made them presentational hints (height: 680px), which with
# `width: 100%` meant both dimensions were specified and `aspect-ratio` was ignored,
# rendering 155x680 cards. The old check passed because sizing hints *existed*.
# This measures what actually rendered.
_RENDERED_RATIO = """
() => {
  const want = 488 / 680, TOL = 0.02;
  const bad = [];
  let checked = 0;
  for (const img of document.querySelectorAll('#cardlist .card img')) {
    const r = img.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    checked++;
    const ratio = r.width / r.height;
    if (Math.abs(ratio - want) > TOL) {
      bad.push({ w: Math.round(r.width), h: Math.round(r.height), ratio: +ratio.toFixed(3) });
    }
  }
  return { checked, count: bad.length, want: +want.toFixed(3), sample: bad.slice(0, 4) };
}
"""

# A card must not eat the whole phone screen. 760px-tall tiles on an 844px viewport
# (1.1 cards visible) is the regression this catches; 2 tiles per screen is the
# floor for a grid that is meant to be browsable.
_CARD_FIT = """
() => {
  const c = document.querySelector('#cardlist .card');
  if (!c) return null;
  const r = c.getBoundingClientRect();
  return { cardH: Math.round(r.height), cardW: Math.round(r.width),
           perScreen: +(window.innerHeight / r.height).toFixed(2) };
}
"""

_OVERFLOW = """
() => {
  const d = document.documentElement;
  const overflow = d.scrollWidth - d.clientWidth;
  const wide = [];
  if (overflow > 0) {
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.right > d.clientWidth + 1 && r.width > 0) {
        wide.push({ tag: el.tagName.toLowerCase(), cls: (el.className || '').toString().slice(0, 40),
                    right: Math.round(r.right) });
      }
    }
  }
  return { overflow, offenders: wide.slice(0, 8) };
}
"""

_TAP_TARGETS = f"""
() => {{
  const AA = {TAP_MIN_AA}, PRIMARY = {TAP_MIN_PRIMARY}, SCOPE = '{PRIMARY_SCOPE}';
  const sel = 'a, button, input, select, textarea, [role=button], [hx-post], [hx-get]';
  const underAA = [], underPrimary = [];
  for (const el of document.querySelectorAll(sel)) {{
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;          // hidden
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const rec = {{ tag: el.tagName.toLowerCase(),
                  cls: (el.className || '').toString().slice(0, 36),
                  w: Math.round(r.width), h: Math.round(r.height) }};
    if (r.width < AA || r.height < AA) underAA.push(rec);
    if (el.closest(SCOPE) && (r.width < PRIMARY || r.height < PRIMARY)) underPrimary.push(rec);
  }}
  return {{ under_aa: underAA.length, under_aa_sample: underAA.slice(0, 8),
           under_primary: underPrimary.length, under_primary_sample: underPrimary.slice(0, 8) }};
}}
"""


# Card art lives on cards.scryfall.io; delay it so an unreserved box has time to
# visibly collapse and then pop. 250ms is well under the harness's 2.5s settle
# window, so a correctly-sized layout still measures 0 drift.
_IMAGE_GLOB = "**/cards.scryfall.io/**"
_IMAGE_DELAY_S = 0.25


def _delay_image(route):
    time.sleep(_IMAGE_DELAY_S)
    route.continue_()


def _measure_modal(page) -> dict:
    """Open the full-size card view and measure it.

    A static check cannot cover this: `#cardmodal` is `[hidden]` until clicked, and
    `getComputedStyle().height` returns the USED value (resolved px) for anything
    laid out, so it cannot tell a resolved `auto` from a pinned 680px. The only
    honest way to gate the modal is to open it and measure the rendered box.
    """
    want = 488 / 680
    try:
        page.locator("#cardlist .card img").first.click()
        page.wait_for_timeout(700)
        m = page.evaluate(
            """() => { const i = document.querySelector('#cardmodal img');
                 if (!i) return null; const r = i.getBoundingClientRect();
                 return { w: Math.round(r.width), h: Math.round(r.height),
                          ratio: r.height ? r.width / r.height : 0 }; }"""
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except Exception as exc:
        return {"error": str(exc)[:80], "off": 1}
    if not m or not m["ratio"]:
        return {"error": "modal image not measurable", "off": 1}
    m["want"] = round(want, 3)
    m["ratio"] = round(m["ratio"], 3)
    m["off"] = 1 if abs(m["ratio"] - want) > 0.02 else 0
    return m


def _open_builder(page, base: str) -> None:
    """Drive the real UI to a built deck (no API shortcuts — audit what ships)."""
    page.goto(f"{base}/decks?commander={COMMANDER.replace(' ', '%20')}", wait_until="load")
    page.locator('form[action="/build"] button, form:has(input[name="deck_id"]) button').first.click()
    page.wait_for_selector("#cardlist .card", timeout=120_000)
    # Card images are lazy; settle the ones in view so the baseline isn't mid-load.
    page.wait_for_timeout(1500)


def _do_swap(page) -> dict:
    """Open the swap modal on a mid-list card and take the first suggestion.

    Returns the measured swap deltas. Falls back to the ✕ remove control if the
    modal yields no suggestion, since both hit the same #cardlist replacement.
    """
    cards = page.locator("#cardlist .card:not(.commander)")
    target = cards.nth(min(12, cards.count() - 1))
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(600)  # let lazy images under the viewport settle

    # The metric that actually models the complaint: pick a stable element the swap
    # does NOT touch (a section heading in a different category) and measure how far
    # it moves relative to the viewport. Scroll drift alone misses the case where
    # scrollY is unchanged but content reflowed underneath it; this catches both.
    anchor_sel = "#cardlist section.cat:last-of-type h3"
    before_anchor = page.evaluate(
        "(sel) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect().top : null; }",
        anchor_sel,
    )
    before_nodes = page.evaluate("() => document.querySelectorAll('#cardlist *').length")

    # Open the modal FIRST, then take the baseline. Measured: clicking the
    # swap-open button makes Playwright scroll that specific button into view
    # (+214px at mobile width). That is harness actionability, not app behaviour —
    # baselining before it would charge the app for the harness's own scrolling.
    used = "swap"
    target.locator("button.swap-open").click()
    try:
        page.wait_for_selector("#swapmodal-body .addlist button.add", timeout=20_000)
    except Exception:
        used = "remove"
        page.keyboard.press("Escape")
    page.wait_for_timeout(400)

    before_scroll = page.evaluate("() => window.scrollY")
    page.evaluate("() => window.__clsReset()")

    if used == "swap":
        page.locator("#swapmodal-body .addlist button.add").first.click()
    else:
        target.locator("button.rm").click()

    # Two post-swap samples. The gap between them is the metric that isolates the
    # image bug: anything that moves AFTER htmx has settled is async media loading
    # in without a reserved box. Movement at t+150ms is the swap's own legitimate
    # reflow (a card really did leave the grid) and is reported, not gated here.
    page.wait_for_timeout(150)
    settled_scroll = page.evaluate("() => window.scrollY")
    anchor_at_settle = page.evaluate(
        "(sel) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect().top : null; }",
        anchor_sel,
    )
    page.wait_for_timeout(2500)  # let every lazy image finish arriving
    after_anchor = page.evaluate(
        "(sel) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect().top : null; }",
        anchor_sel,
    )
    def _delta(a, b):
        return abs(b - a) if a is not None and b is not None else None

    return {
        "action": used,
        # THE phase-1 metric: movement after htmx settled == unsized media loading in.
        "settle_drift": _delta(anchor_at_settle, after_anchor),
        # Legitimate reflow from the edit itself, plus htmx/browser scroll behaviour.
        # Real, but it is swap-blast-radius work, not an image-box bug.
        "swap_scroll_delta": _delta(before_scroll, settled_scroll),
        "anchor_total": _delta(before_anchor, after_anchor),
        "cls": page.evaluate("() => window.__cls"),
        "cls_all": page.evaluate("() => window.__clsAll"),
        "shifts": page.evaluate("() => window.__shifts.length"),
        "shifts_input_flagged": page.evaluate(
            "() => window.__shifts.filter(s => s.recentInput).length"
        ),
        "scroll_before": before_scroll,
        "scroll_after": page.evaluate("() => window.scrollY"),
        "nodes_before": before_nodes,
        "nodes_after": page.evaluate("() => document.querySelectorAll('#cardlist *').length"),
    }


def audit(base: str, shots: Path | None) -> dict:
    results: dict = {"base": base, "viewports": {}}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for name, vp in VIEWPORTS.items():
                ctx = browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    device_scale_factor=2 if vp["is_mobile"] else 1,
                    is_mobile=vp["is_mobile"],
                    has_touch=vp["is_mobile"],
                )
                # Card art must arrive LATE, or this whole gate is vacuous. Verified
                # the hard way: with a warm cache the browser re-renders a swapped
                # tile's image instantly, so even 78 unsized images produced 0.0px of
                # settle drift and the gate passed against the unfixed bug. Delaying
                # image responses (and killing the cache) reproduces the real
                # first-scroll condition, where an unreserved box pops 0 -> full
                # height and shoves the list.
                ctx.route(_IMAGE_GLOB, _delay_image)
                page = ctx.new_page()
                cdp = ctx.new_cdp_session(page)
                cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
                page.add_init_script(_CLS_PROBE)
                _open_builder(page, base)

                # A dead observer reports CLS 0.0000 and every gate "passes" — a
                # vacuous green. Refuse to report rather than bless a broken probe.
                if not page.evaluate("() => window.__clsSupported"):
                    err = page.evaluate("() => window.__clsError || 'unknown'")
                    raise RuntimeError(f"layout-shift observer unavailable ({err}); CLS gate would be vacuous")

                r: dict = {
                    "load_cls": page.evaluate("() => window.__cls"),
                    "unsized_images": page.evaluate(_UNSIZED_IMAGES),
                    "rendered_ratio": page.evaluate(_RENDERED_RATIO),
                    "card_fit": page.evaluate(_CARD_FIT),
                    "modal": _measure_modal(page),
                    "overflow": page.evaluate(_OVERFLOW),
                    "tap_targets": page.evaluate(_TAP_TARGETS),
                }
                if shots:
                    page.screenshot(path=str(shots / f"{name}-build.png"), full_page=False)
                r["swap"] = _do_swap(page)
                if shots:
                    page.screenshot(path=str(shots / f"{name}-after-swap.png"), full_page=False)

                results["viewports"][name] = r
                ctx.close()
        finally:
            browser.close()
    return results


def report(results: dict) -> bool:
    ok = True
    for name, r in results["viewports"].items():
        sw = r["swap"]
        churn = sw["nodes_before"]
        checks = [
            ("settle drift px", sw["settle_drift"] if sw["settle_drift"] is not None else 9999,
             THRESHOLDS["settle_drift_px"], "<="),
            ("unsized images", r["unsized_images"]["count"], THRESHOLDS["unsized_images"], "<="),
            ("misshaped images", r["rendered_ratio"]["count"], THRESHOLDS["misshaped_images"], "<="),
            ("modal img squashed", r["modal"]["off"], THRESHOLDS["modal_ratio_off"], "<="),
            ("min cards/screen", -(r["card_fit"]["perScreen"] if r["card_fit"] else 0),
             -THRESHOLDS["min_cards_per_screen"], "<="),
            ("horiz overflow px", r["overflow"]["overflow"], THRESHOLDS["horizontal_overflow_px"], "<="),
            ("targets < 24px (AA)", r["tap_targets"]["under_aa"], THRESHOLDS["targets_under_24"], "<="),
            ("topbar < 44px (AAA)", r["tap_targets"]["under_primary"],
             THRESHOLDS["primary_targets_under_44"], "<="),
        ]
        print(f"\n=== {name} ({VIEWPORTS[name]['width']}x{VIEWPORTS[name]['height']}) ===")
        print(f"  swap action        : {sw['action']}  (churned ~{churn} nodes)")
        print(f"  shift events       : {sw['shifts']} total, {sw['shifts_input_flagged']} flagged hadRecentInput")
        print(f"  CLS excl. input    : {sw['cls']:.4f}   (spec CLS — blind to click-driven swaps)")
        print("  -- phase 3 context (not gated yet) --")
        print(f"  swap scroll delta  : {sw['swap_scroll_delta']}px   (edit moves the viewport)")
        print(f"  total anchor move  : {sw['anchor_total']:.1f}px   (incl. legitimate one-card reflow)")
        print(f"  swap shift score   : {sw['cls_all']:.4f}   (incl. legitimate reflow)")
        for label, value, limit, _ in checks:
            passed = value <= limit
            ok = ok and passed
            mark = "PASS" if passed else "FAIL"
            shown = f"{value:.4f}" if isinstance(value, float) else str(value)
            print(f"  [{mark}] {label:<19}: {shown:>8}  (limit {limit})")
        cf = r["card_fit"]
        if cf:
            print(f"  card tile          : {cf['cardW']}x{cf['cardH']}px  ->  {cf['perScreen']} per screen")
        md = r["modal"]
        if "error" in md:
            print(f"  full-size view     : ERROR {md['error']}")
        else:
            print(f"  full-size view     : {md['w']}x{md['h']}  ratio {md['ratio']} (want {md['want']})")
        rr = r["rendered_ratio"]
        print(f"  image ratio        : {rr['checked']} checked, want {rr['want']}, {rr['count']} off")
        if rr["count"]:
            print(f"         misshaped      : {rr['sample']}")
        if r["unsized_images"]["count"]:
            print(f"         unsized sample : {r['unsized_images']['sample']}")
        if r["overflow"]["overflow"] > 0:
            print(f"         overflow from  : {r['overflow']['offenders']}")
        if r["tap_targets"]["under_aa"]:
            print(f"         under 24px     : {r['tap_targets']['under_aa_sample'][:6]}")
        if r["tap_targets"]["under_primary"]:
            print(f"         topbar <44px   : {r['tap_targets']['under_primary_sample'][:6]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--shots", type=Path, default=None, help="directory for screenshots")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)
    results = audit(args.base, args.shots)
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    ok = report(results)
    print("\n" + ("ALL GATES PASS" if ok else "GATES FAILED"))
    if args.shots:
        print(f"screenshots -> {args.shots.resolve()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
