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

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from manaless.deck_builder import (
    NoDecksAvailable,
    add_card,
    build_deck,
    substitute_card,
)
from manaless.edhrec_client import EdhrecClient
from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient
from manaless.paths import CACHE_DIR
from manaless.scryfall_client import get_collection
from manaless.web.readout import compute_readouts
from manaless.web.session import COOKIE_NAME, BuildSession, SessionStore

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open one shared HttpClient (+ EDHREC client / enricher) for the process."""
    http = HttpClient(DiskCache(CACHE_DIR))
    app.state.http = http
    app.state.edhrec = EdhrecClient(http)
    app.state.enrich = lambda names: get_collection(http, names)[0]
    app.state.sessions = SessionStore()
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


# --- helpers -------------------------------------------------------------

def _render_builder(request: Request, session: BuildSession, *, error: str | None = None):
    """Full builder page for ``GET /build`` and the initial ``POST /build``."""
    return templates.TemplateResponse(
        request,
        "build.html",
        {"deck": session.deck, "readouts": session.readouts, "error": error},
    )


def _render_update(request: Request, session: BuildSession, *, error: str | None = None):
    """HTMX fragment: new card list (primary target) + OOB readouts + flash."""
    return templates.TemplateResponse(
        request,
        "_update.html",
        {"deck": session.deck, "readouts": session.readouts, "error": error},
    )


def _recompute_into(session: BuildSession, http: HttpClient, deck) -> None:
    session.deck = deck
    session.readouts = compute_readouts(http, deck)


# --- routes --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/decks", response_class=HTMLResponse)
def decks(request: Request, commander: str, edhrec: EdhrecClient = Depends(get_edhrec)):
    table = edhrec.fetch_deck_table(commander)
    rows = sorted(table, key=lambda r: r.get("savedate", ""), reverse=True)
    return templates.TemplateResponse(
        request, "decks.html", {"commander": commander, "rows": rows}
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
):
    try:
        deck = build_deck(edhrec, enrich, commander, deck_id=deck_id)
    except NoDecksAvailable as exc:
        return templates.TemplateResponse(
            request, "decks.html", {"commander": commander, "rows": [], "error": str(exc)}
        )
    readouts = compute_readouts(http, deck)
    session = BuildSession(deck=deck, readouts=readouts)
    sid = store.new_id()
    store.set(sid, session)
    resp = _render_builder(request, session)
    resp.set_cookie(COOKIE_NAME, sid, httponly=True, samesite="lax")
    return resp


@app.get("/build", response_class=HTMLResponse)
def build_page(request: Request, store: SessionStore = Depends(get_store)):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    return _render_builder(request, session)


@app.post("/build/substitute", response_class=HTMLResponse)
def substitute(
    request: Request,
    old_name: str = Form(...),
    new_name: str = Form(...),
    http: HttpClient = Depends(get_http),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    new_name = new_name.strip()
    if not new_name:
        return _render_update(request, session, error="Enter a card name to swap in.")
    with session.lock:
        try:
            deck = substitute_card(enrich, session.deck, old_name, new_name)
        except KeyError:
            return _render_update(request, session, error=f"{old_name!r} is not in the deck.")
        _recompute_into(session, http, deck)
        error = _unresolved_note(deck, new_name)
        return _render_update(request, session, error=error)


@app.post("/build/remove", response_class=HTMLResponse)
def remove(
    request: Request,
    name: str = Form(...),
    http: HttpClient = Depends(get_http),
    store: SessionStore = Depends(get_store),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    with session.lock:
        try:
            deck = session.deck.remove(name)
        except KeyError:
            return _render_update(request, session, error=f"{name!r} is not in the deck.")
        _recompute_into(session, http, deck)
        return _render_update(request, session)


@app.post("/build/add", response_class=HTMLResponse)
def add(
    request: Request,
    name: str = Form(...),
    http: HttpClient = Depends(get_http),
    enrich=Depends(get_enrich),
    store: SessionStore = Depends(get_store),
):
    session = store.get(request.cookies.get(COOKIE_NAME))
    if session is None:
        return RedirectResponse("/", status_code=303)
    with session.lock:
        deck = add_card(enrich, session.deck, name.strip())
        _recompute_into(session, http, deck)
        return _render_update(request, session, error=_unresolved_note(deck, name.strip()))


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


def _unresolved_note(deck, name: str) -> str | None:
    """A gentle banner if the just-touched card didn't resolve on Scryfall."""
    if name in deck.unresolved:
        return f"{name!r} didn't resolve on Scryfall — check the spelling. Kept in the list, unenriched."
    return None
