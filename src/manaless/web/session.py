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
from manaless.web.readout import Readouts

COOKIE_NAME = "manaless_sid"


@dataclass
class BuildSession:
    """One tab's current build: the deck plus its last-computed readouts."""

    deck: DeckModel
    readouts: Readouts
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
