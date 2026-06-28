"""JSON disk cache keyed by ``(namespace, key)``.

Card metadata and decklists-by-hash are effectively immutable, so they cache
forever (``ttl_seconds=None``). The EDHREC deck table changes ~daily, so its
reads pass a TTL. See the caching table in docs/architecture.md.

Each entry is a file at ``<root>/<namespace>/<safe-key>.json`` wrapping
``{"stored_at": <epoch>, "value": <payload>}``. Writes are atomic (temp file +
replace) so a crash mid-write never leaves a half-written cache entry.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

_UNSAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]")
_READABLE_MAX = 60
_DIGEST_LEN = 12


class DiskCache:
    """Namespaced JSON cache on disk with optional per-read TTL."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def get(
        self, namespace: str, key: str, ttl_seconds: float | None = None
    ) -> Any | None:
        """Return the cached value, or ``None`` if missing, expired, or corrupt.

        A corrupt or unreadable entry is treated as a miss rather than raised —
        the caller will simply refetch.
        """
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        if ttl_seconds is not None:
            age = time.time() - entry.get("stored_at", 0)
            if age > ttl_seconds:
                return None
        return entry.get("value")

    def set(self, namespace: str, key: str, value: Any) -> None:
        """Store ``value`` under ``(namespace, key)``, overwriting any prior entry."""
        path = self._path(namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"stored_at": time.time(), "value": value}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _path(self, namespace: str, key: str) -> Path:
        return self._root / namespace / f"{self._safe_key(key)}.json"

    @staticmethod
    def _safe_key(key: str) -> str:
        """Map an arbitrary key (card name, slug, DFC ``A // B``, list hash) to a
        filesystem-safe, collision-resistant filename.

        A readable prefix is kept for debuggability; a short content hash
        guarantees uniqueness when distinct keys sanitise to the same prefix.
        """
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:_DIGEST_LEN]
        readable = _UNSAFE_CHARS.sub("_", key)[:_READABLE_MAX].strip("_")
        return f"{readable}-{digest}" if readable else digest
