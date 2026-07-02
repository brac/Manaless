"""web.session — the in-memory build-session store."""

from manaless.deck_model import Card, DeckModel
from manaless.web.session import MAX_SESSIONS, BuildSession, SessionStore


def _session():
    deck = DeckModel(commanders=(Card("Cmd", 1),), cards=())
    return BuildSession(deck=deck)


def test_set_get_roundtrip():
    store = SessionStore()
    sid = store.new_id()
    store.set(sid, _session())
    assert store.get(sid) is not None


def test_get_missing_or_none_returns_none():
    store = SessionStore()
    assert store.get(None) is None
    assert store.get("nope") is None


def test_reset_removes_session():
    store = SessionStore()
    sid = store.new_id()
    store.set(sid, _session())
    store.reset(sid)
    assert store.get(sid) is None


def test_ids_are_unique():
    store = SessionStore()
    assert store.new_id() != store.new_id()


def test_session_has_its_own_lock():
    s = _session()
    # used to serialise overlapping HTMX edits for one tab
    with s.lock:
        assert s.lock.locked()


def test_store_evicts_oldest_beyond_cap():
    store = SessionStore()
    sids = []
    for _ in range(MAX_SESSIONS + 1):
        sid = store.new_id()
        store.set(sid, _session())
        sids.append(sid)
    assert store.get(sids[0]) is None          # oldest evicted
    assert store.get(sids[-1]) is not None      # newest kept


def test_access_refreshes_recency():
    store = SessionStore()
    first = store.new_id()
    store.set(first, _session())
    for _ in range(MAX_SESSIONS - 1):
        store.set(store.new_id(), _session())
    store.get(first)  # touch -> most recently used
    store.set(store.new_id(), _session())  # one more -> evicts the now-oldest
    assert store.get(first) is not None  # survived because it was refreshed
