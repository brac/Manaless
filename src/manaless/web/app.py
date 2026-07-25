"""FastAPI app — the substitution builder (build step 4).

Sync route handlers (FastAPI runs them in its threadpool) over one app-scoped,
thread-safe synchronous `HttpClient`: the pipeline is sync and its rate limiter /
cache / httpx client are all thread-safe, so there's no async rewrite. Network
clients + the session store live on ``app.state`` and are exposed through small
``Depends`` functions so tests can override them with fakes.

The funnel: ``/`` search -> ``/decks`` picker -> ``/build`` (POST builds, GET
re-renders) -> HTMX ``/build/{substitute,remove,add}`` fragment updates ->
``/build/export.dck`` download.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from manaless.buy import deck_diff, is_basic_land, mass_entry_url, single_card_url
from manaless.card_category import category_of
from manaless.collection import Collection
from manaless.composition import NOTABLE_DELTA, compare
from manaless.deck_builder import (
    CommanderNotFound,
    NoDecksAvailable,
    build_deck,
    enrich_card,
)
from manaless.edhrec_client import EdhrecClient, EdhrecError
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.names import norm_name
from manaless.paths import CACHE_DIR, PROJECT_ROOT
from manaless.scryfall_client import (
    autocomplete_names,
    get_collection,
    search_commanders,
)
from manaless.spellbook_client import SpellbookUnavailable
from manaless.web.readout import compute_readouts
from manaless.web.session import COOKIE_NAME, BuildSession, SessionStore

# Friendly EDHREC-failure text, including the §4 runbook hint. Shown instead of a
# bare 500 when a deck/commander fetch fails (build-id rotation is auto-handled;
# a persistent failure usually means EDHREC is blocking requests).
_EDHREC_HINT = (
    "EDHREC didn’t respond as expected. If it redeployed, the build ID was "
    "refreshed automatically — try again. If this keeps happening, EDHREC may be "
    "rate-limiting or blocking requests; wait a bit and retry."
)

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
# Per-card "Buy" links resolve through this in any template (build step 5).
templates.env.globals["buy_url"] = single_card_url

# The owned-cards file (§9). Gitignored; local only. Imported from a Collectr CSV.
COLLECTION_PATH = PROJECT_ROOT / "collection.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open one shared HttpClient (+ EDHREC client / enricher) for the process."""
    http = HttpClient(DiskCache(CACHE_DIR))
    app.state.http = http
    app.state.edhrec = EdhrecClient(http)
    app.state.enrich = lambda names: get_collection(http, names)[0]
    # Scryfall name lookups: card type-ahead (swap box) + commander browse/search.
    app.state.autocomplete = lambda query: autocomplete_names(http, query)
    app.state.search_commanders = lambda query, page: search_commanders(http, query, page)
    app.state.sessions = SessionStore()
    app.state.collection_path = COLLECTION_PATH
    app.state.collection = Collection.load(COLLECTION_PATH)
    try:
        yield
    finally:
        http.close()


app = FastAPI(title="Manaless", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


# --- dependencies (overridable in tests) ---------------------------------

def get_http(request: Request) -> HttpClient:
    return request.app.state.http


def get_edhrec(request: Request) -> EdhrecClient:
    return request.app.state.edhrec


def get_enrich(request: Request):
    return request.app.state.enrich


def get_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_autocomplete(request: Request):
    return request.app.state.autocomplete


def get_search(request: Request):
    return request.app.state.search_commanders


def get_owned(request: Request) -> Collection:
    return request.app.state.collection


def get_collection_path(request: Request) -> Path:
    return request.app.state.collection_path


# --- helpers -------------------------------------------------------------

def _session_lost(request: Request) -> Response:
    """Response for a request whose session is gone (server restart, expiry).

    An htmx request must not follow a 303 to ``/`` — htmx would swap the whole
    homepage document into a fragment target. Signal a client-side redirect
    instead; a plain browser navigation still gets the ordinary 303.
    """
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/"})
    return RedirectResponse("/", status_code=303)


def require_same_origin(request: Request) -> None:
    """Reject a cross-origin state-changing POST (a minimal CSRF guard).

    Browsers always send ``Origin`` on a cross-site form POST; a same-origin htmx
    post sends a matching one. A request with no Origin/Referer at all (curl, the
    test client) is allowed — this is a localhost tool, not a public service.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(status_code=403, detail="cross-origin request rejected")


def _owned_summary(deck, owned: Collection) -> tuple[int, int, int]:
    """``(owned, needed, missing)`` copies for the header, all from ``deck_diff``.

    Derived from the *same* quantity-aware, basics-skipping source as the buy
    count so the header can never contradict the "N to buy" figure beside it.
    ``needed`` counts diff-eligible copies (non-basics across the whole deck);
    ``missing`` is what the buy step would purchase; ``owned = needed - missing``.
    """
    needed = sum(
        c.quantity
        for c in deck.all_cards()
        if not is_basic_land(c.name)
    )
    missing = sum(qty for qty, _ in deck_diff(deck, owned))
    return needed - missing, needed, missing


# Primary card type -> short tag shown on palette suggestions. Same precedence as
# DeckModel's categoriser (first match on the front-face type line wins).
_TYPE_ABBR: tuple[tuple[str, str], ...] = (
    ("Creature", "CRE"),
    ("Planeswalker", "PLW"),
    ("Battle", "BAT"),
    ("Instant", "INS"),
    ("Sorcery", "SOR"),
    ("Artifact", "ART"),
    ("Enchantment", "ENC"),
    ("Land", "LND"),
)


def _type_tag(type_line: str) -> tuple[str, str]:
    """``(abbreviation, full-type)`` for a palette card, or ``("", "")`` if unknown."""
    front = (type_line or "").split("//", 1)[0]
    for full, abbr in _TYPE_ABBR:
        if full in front:
            return abbr, full
    return ("", "")


def _palette_view(cp, meta) -> dict:
    """A palette suggestion as the template wants it: popularity + type tag + image."""
    abbr, full = _type_tag(meta.type_line) if meta else ("", "")
    return {
        "name": cp.name,
        "percent": cp.percent,
        "num_decks": cp.num_decks,
        "potential_decks": cp.potential_decks,
        "type_abbr": abbr,
        "type_full": full,
        "image_url": meta.image_url if meta else None,
        # Same TCGplayer estimate the deck tiles show. Free here: palette candidates
        # are already enriched through the build-time batched Scryfall call.
        "price_usd": meta.price_usd if meta else None,
    }


def _builder_ctx(
    session: BuildSession,
    owned: Collection,
    *,
    flash: str | None = None,
    flash_kind: str = "",
    sid: str = "",
) -> dict:
    have, total, missing = _owned_summary(session.deck, owned)
    return {
        "deck": session.deck,
        "owned": owned,
        "owned_have": have,
        "owned_total": total,
        # Copies still to buy (quantity-aware, basics-skipped) — the same figure
        # the buy page shows, so header and buy count agree.
        "missing_count": missing,
        "popularity": session.popularity,
        # Pure + instant (no network), so unlike the Spellbook readouts this is
        # computed inline on every edit rather than lazy-loaded.
        "composition": compare(session.deck, session.average),
        "notable_delta": NOTABLE_DELTA,
        "palette": [
            _palette_view(cp, session.palette_meta.get(cp.name))
            for cp in session.popularity.excluding(session.deck.card_names())[:PALETTE_LIMIT]
        ],
        # ``flash`` is the transient toast; ``flash_kind`` styles it ("ok" for a
        # success like "Added X", "" for the default warn tone used by errors).
        "flash": flash,
        "flash_kind": flash_kind,
        # Per-tab session id echoed by every htmx mutation (W2).
        "sid": sid,
    }


def _render_builder(request, session, owned, *, flash=None, flash_kind="", sid=""):
    """Full builder page for ``GET /build`` and the initial ``POST /build``.

    The readouts panel renders as a lazy placeholder that fetches
    ``/build/readouts`` on load, so the page paints without waiting on Spellbook.
    """
    ctx = _builder_ctx(session, owned, flash=flash, flash_kind=flash_kind, sid=sid)
    return templates.TemplateResponse(request, "build.html", ctx)


def _resolve_session(request: Request, store: SessionStore, form_sid: str = "") -> tuple:
    """Resolve the active session by page-carried sid, falling back to the cookie.

    Carrying the sid in the page (not only the cookie) means a second tab that
    mints its own sid can't hijack the first tab's edits (W2). Returns
    ``(sid, session_or_None)``.
    """
    sid = (form_sid or "").strip() or (request.cookies.get(COOKIE_NAME) or "")
    return sid, store.get(sid)


def _render_update(request, session, owned, *, flash=None, flash_kind=""):
    """HTMX fragment for an edit: card list + OOB {palette, count, flash} + an OOB
    lazy readouts placeholder. The edit returns instantly; readouts recompute in a
    follow-up ``/build/readouts`` request rather than blocking the click."""
    ctx = _builder_ctx(session, owned, flash=flash, flash_kind=flash_kind)
    return templates.TemplateResponse(request, "_update.html", ctx)


def _ensure_suggest_pool(session: BuildSession, enrich) -> None:
    """Populate ``session.suggest_cat``/``suggest_meta`` once (lazy, memoized).

    Classifies the commander's top ``SUGGEST_POOL_LIMIT`` most-played cards into
    functional categories so the swap modal can offer same-category replacements.
    Popularity + a card's category are fixed for the session, so this runs at most
    once: the build-time ``palette_meta`` seeds most of the enrichment, and only the
    misses hit Scryfall (one batched, disk-cached call). The enrichment happens
    *outside* the lock so a modal open never serializes other edits behind a
    multi-second network wait; the lock only guards the final double-checked write
    (a lost race just wastes one recomputation — W9).
    """
    if session.suggest_cat:
        return
    pool = session.popularity.excluding([])[:SUGGEST_POOL_LIMIT]
    names = [cp.name for cp in pool]
    meta = {n: session.palette_meta[n] for n in names if n in session.palette_meta}
    misses = [n for n in names if n not in meta]
    if misses:
        meta.update(enrich(misses))  # network — outside the lock
    cat = {
        cp.name: category_of(meta[cp.name]) if cp.name in meta else "Other"
        for cp in pool
    }
    with session.lock:
        if session.suggest_cat:  # another request populated it while we computed
            return
        session.suggest_meta = meta
        session.suggest_cat = cat


# --- routes --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


# How many EDHREC-ranked commanders to show per browse page (E2).
COMMANDER_PAGE_SIZE = 60  # a tidy grid; Scryfall itself returns 175/page.
# Scryfall's search page size. One Scryfall page fills several UI pages, so we
# fetch once and sub-paginate locally instead of requesting a fresh Scryfall page
# per UI page (which would silently drop cards 61–175 of every page).
SCRYFALL_PAGE_SIZE = 175
UI_PAGES_PER_SCRYFALL = -(-SCRYFALL_PAGE_SIZE // COMMANDER_PAGE_SIZE)  # ceil = 3


@app.get("/commanders", response_class=HTMLResponse)
def commanders(
    request: Request,
    q: str = "",
    page: int = 1,
    search=Depends(get_search),
    edhrec: EdhrecClient = Depends(get_edhrec),
):
    """Paginated commander browser + fuzzy search (E2/E5).

    Empty ``q`` (the "popular" browse) uses **EDHREC's own commander ranking**
    (deck count), so #1 is The Ur-Dragon — matching the site. A non-empty query
    fuzzy-matches by name via Scryfall. Both paginate; each result links to that
    commander's deck picker.
    """
    q = q.strip()
    page = max(1, page)
    # Popular browse: prefer EDHREC's deck-count ranking. If EDHREC is unavailable
    # (403/block/network), fall back to the Scryfall list below so the browse never
    # dead-ends on "no commanders found".
    try:
        ranked = edhrec.fetch_top_commanders() if not q else []
    except (EdhrecError, httpx.HTTPError):
        ranked = []
    if ranked:
        total = len(ranked)
        # Clamp: a page past the end would render an empty grid with no way back.
        last_page = max(1, -(-total // COMMANDER_PAGE_SIZE))
        page = min(page, last_page)
        start = (page - 1) * COMMANDER_PAGE_SIZE
        window = ranked[start : start + COMMANDER_PAGE_SIZE]
        items = [{"name": c.name, "decks": c.num_decks} for c in window]
        has_more = start + COMMANDER_PAGE_SIZE < total
    else:
        # Named search (or the EDHREC-unavailable fallback). Map several UI pages
        # onto one Scryfall page so results 61–175 aren't dropped.
        sub = (page - 1) % UI_PAGES_PER_SCRYFALL
        scry_page = (page - 1) // UI_PAGES_PER_SCRYFALL + 1
        result = search(q, scry_page)
        names = list(result.names[sub * COMMANDER_PAGE_SIZE : (sub + 1) * COMMANDER_PAGE_SIZE])
        # More UI pages remain if this Scryfall page has cards past our slice, or
        # Scryfall itself reports another page.
        has_more = len(result.names) > (sub + 1) * COMMANDER_PAGE_SIZE or result.has_more
        items = [{"name": name, "decks": None} for name in names]
        total = result.total
    return templates.TemplateResponse(
        request,
        "commanders.html",
        {
            "q": q,
            "page": page,
            "items": items,
            "total": total,
            "has_prev": page > 1,
            "has_next": has_more,
        },
    )


@app.get("/api/autocomplete", response_class=JSONResponse)
def api_autocomplete(
    request: Request,
    q: str = "",
    kind: str = "card",
    autocomplete=Depends(get_autocomplete),
    search=Depends(get_search),
):
    """Name suggestions for the type-ahead widgets (E5/E6): ``["Name", ...]``.

    ``kind=card`` uses Scryfall's card autocomplete (the swap box); ``kind=
    commander`` returns EDHREC-ranked commander matches (the browse search box).
    """
    q = q.strip()
    if not q:
        return JSONResponse([])
    if kind == "commander":
        return JSONResponse(list(search(q, 1).names[:10]))
    return JSONResponse(autocomplete(q)[:10])


# Deck-picker sort options: key -> (label, row field, reverse). Only fields the
# EDHREC deck table actually provides (no per-deck popularity exists, so recency
# is the "what's hot" proxy). Rows missing the field always sort to the end.
DECK_SORTS: dict[str, tuple[str, str, bool]] = {
    "recent": ("Newest", "savedate", True),
    "oldest": ("Oldest", "savedate", False),
    "price_low": ("Price: low → high", "price", False),
    "price_high": ("Price: high → low", "price", True),
    "bracket_low": ("Bracket: low → high", "bracket", False),
    "bracket_high": ("Bracket: high → low", "bracket", True),
    "salt_high": ("Saltiest", "salt", True),
    "salt_low": ("Least salty", "salt", False),
}
DECK_LIST_LIMIT = 100  # Atraxa alone has ~42k indexed decks; show the top slice.
PALETTE_LIMIT = 24  # most-played cards not in the deck, offered as add suggestions.
# Enrich a bit more than PALETTE_LIMIT once at build time so the palette still has
# type tags + hover images as removing deck cards rotates new suggestions in.
PALETTE_META_LIMIT = 80
# Swap suggestions (build step 4): classify the top SUGGEST_POOL_LIMIT most-played
# cards for the commander into functional categories once, then offer up to
# SUGGEST_LIMIT of the same category as replacements for a swapped-out card.
SUGGEST_POOL_LIMIT = 120
SUGGEST_LIMIT = 12


def _sort_deck_rows(rows: list[dict], sort: str) -> list[dict]:
    """Sort a deck table by a `DECK_SORTS` key, pushing rows missing the field last."""
    _, field, reverse = DECK_SORTS.get(sort, DECK_SORTS["recent"])
    numeric = field != "savedate"

    def value(row):
        v = row.get(field)
        if numeric:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return v or None

    present = [r for r in rows if value(r) is not None]
    missing = [r for r in rows if value(r) is None]
    present.sort(key=value, reverse=reverse)
    return present + missing


@app.get("/decks", response_class=HTMLResponse)
def decks(
    request: Request,
    commander: str,
    sort: str = "recent",
    edhrec: EdhrecClient = Depends(get_edhrec),
):
    if sort not in DECK_SORTS:
        sort = "recent"
    try:
        table = edhrec.fetch_deck_table(commander)
    except EdhrecError:
        return templates.TemplateResponse(
            request, "decks.html", {"commander": commander, "rows": [], "error": _EDHREC_HINT}
        )
    ordered = _sort_deck_rows(table, sort)
    return templates.TemplateResponse(
        request,
        "decks.html",
        {
            "commander": commander,
            "rows": ordered[:DECK_LIST_LIMIT],
            "total": len(ordered),
            "limit": DECK_LIST_LIMIT,
            "sort": sort,
            "sorts": DECK_SORTS,
        },
    )


@app.post("/build", response_class=HTMLResponse, dependencies=[Depends(require_same_origin)])
def build(
    request: Request,
    commander: str = Form(...),
    deck_id: str = Form(...),
    edhrec: EdhrecClient = Depends(get_edhrec),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    try:
        deck = build_deck(edhrec, enrich, commander, deck_id=deck_id)
    except NoDecksAvailable as exc:
        return templates.TemplateResponse(
            request, "decks.html", {"commander": commander, "rows": [], "error": str(exc)}
        )
    except CommanderNotFound as exc:
        return templates.TemplateResponse(
            request, "decks.html", {"commander": commander, "rows": [], "error": str(exc)}
        )
    except EdhrecError:
        return templates.TemplateResponse(
            request, "decks.html", {"commander": commander, "rows": [], "error": _EDHREC_HINT}
        )
    # Readouts are computed lazily (the page's placeholder fetches /build/readouts),
    # so the builder paints as soon as the deck is enriched rather than after the
    # ~2s Spellbook round-trip.
    popularity = edhrec.fetch_commander_card_stats(commander)
    # Same disk-cached commander page as the popularity call above, so this is a
    # cache hit rather than a second round trip.
    average = edhrec.fetch_commander_average(commander)
    # Enrich the palette candidates once (one batched, cached Scryfall call) so the
    # suggestions can show a type tag + hover image with no per-edit network cost.
    palette_pool = [cp.name for cp in popularity.excluding(deck.card_names())[:PALETTE_META_LIMIT]]
    palette_meta = enrich(palette_pool) if palette_pool else {}
    session = BuildSession(
        deck=deck, popularity=popularity, average=average, palette_meta=dict(palette_meta)
    )
    sid = store.new_id()
    store.set(sid, session)
    # Pass the sid into the page (W2): every htmx mutation echoes it back, so a
    # second tab that mints its own sid can't hijack the first tab's cookie.
    resp = _render_builder(request, session, owned, sid=sid)
    resp.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="lax")
    return resp


@app.get("/build", response_class=HTMLResponse)
def build_page(
    request: Request,
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    sid, session = _resolve_session(request, store)
    if session is None:
        return RedirectResponse("/", status_code=303)
    return _render_builder(request, session, owned, sid=sid)


def _deck_contains(deck, name: str) -> bool:
    """True if a card matching ``name`` (canonical key) is already in the deck."""
    key = norm_name(name)
    return any(norm_name(c.name) == key for c in deck.all_cards())


@app.post("/build/substitute", response_class=HTMLResponse)
def substitute(
    request: Request,
    old_name: str = Form(...),
    new_name: str = Form(...),
    sid: str = Form(""),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    _sid, session = _resolve_session(request, store, sid)
    if session is None:
        return _session_lost(request)
    new_name = new_name.strip()
    if not new_name:
        return _render_update(request, session, owned, flash="Enter a card name to swap in.")
    # A swap that would duplicate a non-basic already in the deck merges quantities
    # (a singleton-format violation) — warn instead (W10). A swap to itself is a no-op.
    if (
        norm_name(new_name) != norm_name(old_name)
        and not is_basic_land(new_name)
        and _deck_contains(session.deck, new_name)
    ):
        return _render_update(request, session, owned, flash=f"{new_name} is already in the deck.")
    # Enrich outside the lock (network); hold the lock only for the deck edit (W9).
    card = enrich_card(enrich, new_name)
    with session.lock:
        try:
            deck = session.deck.substitute(old_name, card)
        except KeyError:
            return _render_update(request, session, owned, flash=f"{old_name!r} is not in the deck.")
        session.deck = deck  # readouts recompute lazily via /build/readouts
    note = _unresolved_note(deck, new_name)
    if note:
        return _render_update(request, session, owned, flash=note)
    return _render_update(
        request, session, owned, flash=f"Swapped in {new_name}", flash_kind="ok"
    )


@app.get("/build/suggest", response_class=HTMLResponse)
def build_suggest(
    request: Request,
    old_name: str = "",
    sid: str = "",
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
):
    """Same-category replacement suggestions for the card being swapped (modal body).

    Classifies ``old_name`` functionally (Ramp/Removal/Draw/…), then offers the
    most-played cards of that same category not already in the deck — ranked by
    play-rate, synergy as a tiebreak. Fetched lazily by the swap modal's ``hx-get``.
    """
    _sid, session = _resolve_session(request, store, sid)
    if session is None:
        return _session_lost(request)

    key = norm_name(old_name)
    card = next((c for c in session.deck.all_cards() if norm_name(c.name) == key), None)
    _ensure_suggest_pool(session, enrich)
    if card is not None:
        category = category_of(card)
    else:  # not a deck card (shouldn't happen from the UI) — fall back to the pool
        category = session.suggest_cat.get(old_name.strip(), "Other")

    cands = [
        cp
        for cp in session.popularity.excluding(session.deck.card_names())
        if session.suggest_cat.get(cp.name) == category
    ]
    cands.sort(key=lambda cp: (cp.num_decks, cp.synergy), reverse=True)

    suggestions = [
        _palette_view(cp, session.suggest_meta.get(cp.name))
        for cp in cands[:SUGGEST_LIMIT]
    ]
    return templates.TemplateResponse(
        request,
        "_swap_suggestions.html",
        {
            "old_name": old_name.strip(),
            "category": category,
            "suggestions": suggestions,
            # Price of the card going out, so each suggestion can show what the
            # swap costs or saves. None when it's unpriced (no delta shown).
            "old_price": card.price_usd if card is not None else None,
        },
    )


@app.post("/build/remove", response_class=HTMLResponse)
def remove(
    request: Request,
    name: str = Form(...),
    sid: str = Form(""),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    _sid, session = _resolve_session(request, store, sid)
    if session is None:
        return _session_lost(request)
    with session.lock:
        try:
            deck = session.deck.remove(name)
        except KeyError:
            return _render_update(request, session, owned, flash=f"{name!r} is not in the deck.")
        session.deck = deck  # readouts recompute lazily via /build/readouts
    # No name in the toast: the card visibly leaves the list and the count
    # ticks down, and a name here would read as if it were still present.
    return _render_update(request, session, owned, flash="Removed 1 card", flash_kind="ok")


@app.post("/build/add", response_class=HTMLResponse)
def add(
    request: Request,
    name: str = Form(...),
    sid: str = Form(""),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    _sid, session = _resolve_session(request, store, sid)
    if session is None:
        return _session_lost(request)
    name = name.strip()
    if not name:  # W10: reject a blank add, as substitute already does
        return _render_update(request, session, owned, flash="Enter a card name to add.")
    # A non-basic already in the deck would silently merge to quantity 2 (a
    # singleton violation); warn instead. Basics legitimately stack (W10).
    if not is_basic_land(name) and _deck_contains(session.deck, name):
        return _render_update(request, session, owned, flash=f"{name} is already in the deck.")
    # Enrich outside the lock (network); hold the lock only for the deck edit (W9).
    card = enrich_card(enrich, name)
    with session.lock:
        session.deck = session.deck.add(card)  # readouts recompute lazily
        deck = session.deck
    note = _unresolved_note(deck, name)
    if note:
        return _render_update(request, session, owned, flash=note)
    return _render_update(request, session, owned, flash=f"Added {name}", flash_kind="ok")


@app.get("/build/readouts", response_class=HTMLResponse)
def build_readouts(
    request: Request,
    sid: str = "",
    http: HttpClient = Depends(get_http),
    store: SessionStore = Depends(get_store),
):
    """Compute + render the win-condition/bracket panel for the current deck.

    Fetched lazily by the builder's readouts placeholder (on page load and after
    every edit), so the ~2s Spellbook round-trip never blocks a click. If Spellbook
    is unreachable, render a retry state rather than 500 the whole panel.
    """
    _sid, session = _resolve_session(request, store, sid)
    if session is None:
        return _session_lost(request)
    try:
        readouts = compute_readouts(http, session.deck)
    except SpellbookUnavailable:
        return templates.TemplateResponse(request, "_readouts_unavailable.html", {})
    return templates.TemplateResponse(
        request, "_readouts_panel.html", {"readouts": readouts}
    )


@app.post("/build/reset")
def reset(request: Request, store: SessionStore = Depends(get_store)):
    store.reset(request.cookies.get(COOKIE_NAME))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/build/export.dck")
def export_dck(request: Request, store: SessionStore = Depends(get_store)):
    from manaless.dck_export import dck_filename, to_dck

    _sid, session = _resolve_session(request, store)
    if session is None:
        return _session_lost(request)
    filename = dck_filename(session.deck)
    return Response(
        content=to_dck(session.deck),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/build/buy-missing", response_class=HTMLResponse)
def buy_missing(
    request: Request,
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    """Review page: the cards in the current deck you don't own, + a TCGplayer link."""
    _sid, session = _resolve_session(request, store)
    if session is None:
        return _session_lost(request)
    missing = deck_diff(session.deck, owned)
    basics_skipped = sum(
        1
        for c in session.deck.all_cards()
        if is_basic_land(c.name) and c.quantity - owned.quantity(c.name) > 0
    )
    return templates.TemplateResponse(
        request,
        "buy_missing.html",
        {
            "deck": session.deck,
            "missing": missing,
            "to_buy": sum(qty for qty, _ in missing),
            "basics_skipped": basics_skipped,
            "buy_all_url": mass_entry_url(missing) if missing else None,
        },
    )


@app.get("/collection", response_class=HTMLResponse)
def collection_page(
    request: Request,
    owned: Collection = Depends(get_owned),
):
    # No message/error query params: the only writer (collection_import) renders the
    # template directly with its own context, and reflecting arbitrary query text as
    # an app banner is a needless spoofing surface (W16).
    return templates.TemplateResponse(request, "collection.html", {"owned": owned})


@app.post(
    "/collection/import",
    response_class=HTMLResponse,
    dependencies=[Depends(require_same_origin)],
)
def collection_import(
    request: Request,
    file: UploadFile = File(...),
    path: Path = Depends(get_collection_path),
):
    """Import a Collectr (or any name+qty) CSV/JSON export into the owned-cards file."""
    import json

    raw = file.file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        if (file.filename or "").casefold().endswith(".json"):
            owned = Collection.from_json(json.loads(text))
        else:
            owned = Collection.from_csv(text)
    except (ValueError, json.JSONDecodeError) as exc:
        return templates.TemplateResponse(
            request,
            "collection.html",
            {"owned": request.app.state.collection, "error": f"Couldn't read {file.filename!r}: {exc}"},
        )
    owned.save(path)
    request.app.state.collection = owned  # live app now sees the new collection
    msg = f"Imported {owned.distinct} cards ({owned.total} total) from {file.filename!r}."
    return templates.TemplateResponse(request, "collection.html", {"owned": owned, "message": msg})


def _unresolved_note(deck, name: str) -> str | None:
    """A gentle banner if the just-touched card didn't resolve on Scryfall."""
    if name in deck.unresolved:
        return f"{name!r} didn't resolve on Scryfall — check the spelling. Kept in the list, unenriched."
    return None
