"""In-memory build sessions — the current deck a browser tab is editing.

A build-in-progress is ephemeral (the durable artifact is the exported `.dck`),
so sessions live in a module-level dict, not on disk. Each is keyed by a cookie
(`manaless_sid`) and guarded by its own lock, since HTMX can fire overlapping
substitution posts for the same tab. Single-user localhost tool — deliberately
minimal (no eviction, no persistence, no auth).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from threading import Lock

from manaless.deck_model import DeckModel
from manaless.edhrec_client import PopularityIndex
from manaless.scryfall_client import ScryfallCard
from manaless.web.readout import Readouts

COOKIE_NAME = "manaless_sid"


@dataclass
class BuildSession:
    """One tab's current build: the deck, its readouts, and commander card stats."""

    deck: DeckModel
    # Win-condition + bracket readouts. Computed lazily (the two Spellbook POSTs
    # cost ~2s), so an edit updates ``deck`` instantly and the readouts panel
    # fetches ``/build/readouts`` in the background. ``None`` until first computed.
    readouts: Readouts | None = None
    # Aggregate EDHREC card popularity for this commander; fetched once at build
    # time (it doesn't change as the user substitutes within the same commander).
    popularity: PopularityIndex = field(default_factory=lambda: PopularityIndex({}))
    # Scryfall metadata (type line + image) for the substitution-palette candidates,
    # enriched once at build time so the palette can show a card-type tag and a
    # hover preview without any per-edit network call. Keyed by card name.
    palette_meta: dict[str, ScryfallCard] = field(default_factory=dict)
    # Swap-suggestion memo (build step 4): the same commander pool classified into
    # functional categories (Ramp/Removal/…) once, then reused across swaps. Popularity
    # is fixed per commander and a card's category never changes, so only the per-request
    # deck-exclusion filter varies. Populated lazily on first swap-modal open.
    suggest_cat: dict[str, str] = field(default_factory=dict)  # card name -> functional category
    suggest_meta: dict[str, ScryfallCard] = field(default_factory=dict)  # card name -> enrichment
    lock: Lock = field(default_factory=Lock)


class SessionStore:
    """Thread-safe map of session id -> BuildSession."""

    def __init__(self) -> None:
        self._sessions: dict[str, BuildSession] = {}
        self._lock = Lock()

    def new_id(self) -> str:
        return secrets.token_urlsafe(16)

    def get(self, sid: str | None) -> BuildSession | None:
        if not sid:
            return None
        with self._lock:
            return self._sessions.get(sid)

    def set(self, sid: str, session: BuildSession) -> None:
        with self._lock:
            self._sessions[sid] = session

    def reset(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)
