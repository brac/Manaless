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

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from manaless.buy import deck_diff, is_basic_land, mass_entry_url, single_card_url
from manaless.collection import Collection
from manaless.deck_builder import (
    NoDecksAvailable,
    add_card,
    build_deck,
    substitute_card,
)
from manaless.edhrec_client import EdhrecClient
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.paths import CACHE_DIR, PROJECT_ROOT
from manaless.scryfall_client import get_collection
from manaless.web.readout import compute_readouts
from manaless.web.session import COOKIE_NAME, BuildSession, SessionStore

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


def get_owned(request: Request) -> Collection:
    return request.app.state.collection


def get_collection_path(request: Request) -> Path:
    return request.app.state.collection_path


# --- helpers -------------------------------------------------------------

def _owned_summary(deck, owned: Collection) -> tuple[int, int]:
    """``(distinct mainboard cards owned, distinct mainboard cards)`` for the header."""
    return sum(1 for c in deck.cards if owned.owns(c.name)), len(deck.cards)


def _builder_ctx(session: BuildSession, owned: Collection, error: str | None) -> dict:
    have, total = _owned_summary(session.deck, owned)
    return {
        "deck": session.deck,
        "readouts": session.readouts,
        "owned": owned,
        "owned_have": have,
        "owned_total": total,
        "missing_count": len(deck_diff(session.deck, owned)),
        "popularity": session.popularity,
        "palette": session.popularity.excluding(session.deck.card_names())[:PALETTE_LIMIT],
        "error": error,
    }


def _render_builder(request, session, owned, *, error=None):
    """Full builder page for ``GET /build`` and the initial ``POST /build``."""
    return templates.TemplateResponse(request, "build.html", _builder_ctx(session, owned, error))


def _render_update(request, session, owned, *, error=None):
    """HTMX fragment: new card list (primary target) + OOB readouts + flash."""
    return templates.TemplateResponse(request, "_update.html", _builder_ctx(session, owned, error))


def _recompute_into(session: BuildSession, http: HttpClient, deck) -> None:
    session.deck = deck
    session.readouts = compute_readouts(http, deck)


# --- routes --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


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
    table = edhrec.fetch_deck_table(commander)
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


@app.post("/build", response_class=HTMLResponse)
def build(
    request: Request,
    commander: str = Form(...),
    deck_id: str = Form(...),
    http: HttpClient = Depends(get_http),
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
    readouts = compute_readouts(http, deck)
    popularity = edhrec.fetch_commander_card_stats(commander)
    session = BuildSession(deck=deck, readouts=readouts, popularity=popularity)
    sid = store.new_id()
    store.set(sid, session)
    resp = _render_builder(request, session, owned)
    resp.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="lax")
    return resp


@app.get("/build", response_class=HTMLResponse)
def build_page(
    request: Request,
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    return _render_builder(request, session, owned)


@app.post("/build/substitute", response_class=HTMLResponse)
def substitute(
    request: Request,
    old_name: str = Form(...),
    new_name: str = Form(...),
    http: HttpClient = Depends(get_http),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    new_name = new_name.strip()
    if not new_name:
        return _render_update(request, session, owned, error="Enter a card name to swap in.")
    with session.lock:
        try:
            deck = substitute_card(enrich, session.deck, old_name, new_name)
        except KeyError:
            return _render_update(request, session, owned, error=f"{old_name!r} is not in the deck.")
        _recompute_into(session, http, deck)
        error = _unresolved_note(deck, new_name)
        return _render_update(request, session, owned, error=error)


@app.post("/build/remove", response_class=HTMLResponse)
def remove(
    request: Request,
    name: str = Form(...),
    http: HttpClient = Depends(get_http),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    with session.lock:
        try:
            deck = session.deck.remove(name)
        except KeyError:
            return _render_update(request, session, owned, error=f"{name!r} is not in the deck.")
        _recompute_into(session, http, deck)
        return _render_update(request, session, owned)


@app.post("/build/add", response_class=HTMLResponse)
def add(
    request: Request,
    name: str = Form(...),
    http: HttpClient = Depends(get_http),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
    owned: Collection = Depends(get_owned),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    with session.lock:
        deck = add_card(enrich, session.deck, name.strip())
        _recompute_into(session, http, deck)
        return _render_update(request, session, owned, error=_unresolved_note(deck, name.strip()))


@app.post("/build/reset")
def reset(request: Request, store: SessionStore = Depends(get_store)):
    store.reset(request.cookies.get(COOKIE_NAME))
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


@app.get("/build/export.dck")
def export_dck(request: Request, store: SessionStore = Depends(get_store)):
    from manaless.dck_export import dck_filename, to_dck

    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
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
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
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
    message: str | None = None,
    error: str | None = None,
):
    return templates.TemplateResponse(
        request, "collection.html", {"owned": owned, "message": message, "error": error}
    )


@app.post("/collection/import", response_class=HTMLResponse)
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
