"""Disk cache: roundtrip, miss, TTL, corrupt entries, and key safety."""

from manaless.http.cache import DiskCache


def test_set_then_get_roundtrips(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("scryfall-card", "Sol Ring", {"mv": 1})
    assert cache.get("scryfall-card", "Sol Ring") == {"mv": 1}


def test_missing_key_returns_none(tmp_path):
    assert DiskCache(tmp_path).get("scryfall-card", "Nonexistent") is None


def test_expired_ttl_returns_none(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("deck-table", "atraxa-praetors-voice", [1, 2, 3])
    # A negative TTL means "anything older than ~now" -> always expired.
    assert cache.get("deck-table", "atraxa-praetors-voice", ttl_seconds=-1) is None


def test_large_ttl_returns_value(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("deck-table", "atraxa-praetors-voice", [1, 2, 3])
    assert cache.get("deck-table", "atraxa-praetors-voice", ttl_seconds=86_400) == [1, 2, 3]


def test_corrupt_entry_is_a_miss(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("scryfall-card", "Sol Ring", {"mv": 1})
    # Corrupt the stored file on disk.
    stored = next((tmp_path / "scryfall-card").glob("*.json"))
    stored.write_text("{ not json", encoding="utf-8")
    assert cache.get("scryfall-card", "Sol Ring") is None


def test_unsafe_keys_do_not_collide_and_are_storable(tmp_path):
    cache = DiskCache(tmp_path)
    # DFC names, apostrophes, slashes — must each store/retrieve independently.
    cache.set("scryfall-card", "Fire // Ice", "split")
    cache.set("scryfall-card", "Jace, Vryn's Prodigy // Jace, Telepath Unbound", "dfc")
    cache.set("scryfall-card", "Liliana of the Veil", "pw")

    assert cache.get("scryfall-card", "Fire // Ice") == "split"
    assert cache.get("scryfall-card", "Jace, Vryn's Prodigy // Jace, Telepath Unbound") == "dfc"
    assert cache.get("scryfall-card", "Liliana of the Veil") == "pw"
