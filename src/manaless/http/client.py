"""HTTP client composing the rate limiter, disk cache, and a polite User-Agent.

The single entry point the API clients use. ``get_json`` short-circuits on a
cache hit (no request, no rate-limit wait); otherwise it waits on the host's
limiter, fetches, raises on HTTP error, caches, and returns parsed JSON.
``get_text`` is the raw path used by the EDHREC build-id scrape.
"""

from __future__ import annotations

import email.utils
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from manaless.http.cache import DiskCache
from manaless.http.rate_limiter import RateLimiter

# A descriptive UA is the polite minimum for these free community services
# (CLAUDE.md §2), and a reachable contact URL lets an API operator tell us apart
# from an abusive scraper rather than just blocking.
DEFAULT_USER_AGENT = "Manaless/0.1 (+https://github.com/brac/Manaless; personal MTG Commander tool)"

# Minimum seconds between requests, per host (CLAUDE.md §4).
HOST_DELAYS: dict[str, float] = {
    "edhrec.com": 0.80,
    "json.edhrec.com": 0.80,
    "api.scryfall.com": 0.12,
    "backend.commanderspellbook.com": 0.10,
}
# Hosts that belong to the same service share ONE limiter, so interleaved traffic
# to two domains of one provider (json.edhrec.com + edhrec.com) still honours a
# single combined cadence instead of hitting the provider at ~2x the promise.
_HOST_GROUP: dict[str, str] = {
    "edhrec.com": "edhrec",
    "json.edhrec.com": "edhrec",
    "api.scryfall.com": "scryfall",
    "backend.commanderspellbook.com": "spellbook",
}
_DEFAULT_DELAY = 0.20
_DEFAULT_TIMEOUT = 20.0

# On HTTP 429, honour Retry-After and retry rather than failing the pipeline.
_MAX_RETRIES = 3
_RETRY_AFTER_FALLBACK = 1.0
# Never let a server's Retry-After park the whole pipeline: a hostile or buggy
# "Retry-After: 86400" would otherwise sleep for a day.
_RETRY_AFTER_MAX = 30.0


def _retry_after_seconds(response: httpx.Response) -> float:
    """Seconds to wait per a 429's ``Retry-After``, in either standard form.

    Accepts the delta-seconds form (``120``) and the HTTP-date form
    (``Wed, 21 Oct 2026 07:28:00 GMT``); clamps the result to a sane ceiling and
    falls back to a short default if the header is absent or unparseable.
    """
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return _RETRY_AFTER_FALLBACK
    try:
        delay = float(raw)
    except ValueError:
        delay = _http_date_delay(raw)
    return max(0.0, min(delay, _RETRY_AFTER_MAX))


def _http_date_delay(raw: str) -> float:
    """Seconds from now until an HTTP-date ``Retry-After``; fallback if unparseable."""
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (ValueError, TypeError):
        return _RETRY_AFTER_FALLBACK
    if parsed is None:
        return _RETRY_AFTER_FALLBACK
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed - datetime.now(timezone.utc)).total_seconds()


class HttpClient:
    """Rate-limited, disk-cached JSON/text fetcher shared by all API clients."""

    def __init__(
        self,
        cache: DiskCache,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = _DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
        host_delays: dict[str, float] | None = None,
        default_delay: float = _DEFAULT_DELAY,
    ) -> None:
        self._cache = cache
        # Only close a client we created; an injected one is the caller's to own.
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
        delays = HOST_DELAYS if host_delays is None else host_delays
        # Collapse hosts into shared groups; a group's delay is the most
        # conservative (largest) promised across its member hosts.
        group_delays: dict[str, float] = {}
        for host, delay in delays.items():
            group = _HOST_GROUP.get(host, host)
            group_delays[group] = max(group_delays.get(group, 0.0), delay)
        self._limiters = {group: RateLimiter(delay) for group, delay in group_delays.items()}
        self._default_limiter = RateLimiter(default_delay)

    def get_json(
        self,
        url: str,
        *,
        cache_namespace: str | None = None,
        cache_key: str | None = None,
        ttl_seconds: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Fetch and parse JSON, consulting the cache when a key is supplied.

        Caching is enabled only when both ``cache_namespace`` and ``cache_key``
        are given. Raises ``httpx.HTTPStatusError`` on a non-2xx response (after
        retrying 429s per ``Retry-After``).
        """
        cacheable = cache_namespace is not None and cache_key is not None
        if cacheable:
            hit = self._cache.get(cache_namespace, cache_key, ttl_seconds)
            if hit is not None:
                return hit

        data = self._send("GET", url, headers=headers).json()

        if cacheable:
            self._cache.set(cache_namespace, cache_key, data)
        return data

    def post_json(
        self,
        url: str,
        json_body: Any,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """POST a JSON body and parse the JSON response (no HTTP-layer caching).

        Used for Scryfall's batch ``cards/collection`` and the Commander
        Spellbook POST endpoints, which take a decklist in the body. Callers
        that want caching key it themselves (per-card for Scryfall, per-decklist
        hash for Spellbook). Raises ``httpx.HTTPStatusError`` on a non-2xx
        response (after retrying 429s per ``Retry-After``).
        """
        return self._send("POST", url, json=json_body, headers=headers).json()

    def get_text(self, url: str) -> str:
        """Fetch raw text (used for the EDHREC build-id homepage scrape)."""
        return self._send("GET", url).text

    @property
    def cache(self) -> DiskCache:
        """The shared disk cache, for clients that key entries themselves.

        ``scryfall_client.get_collection`` reads/writes per-card entries here so
        a batched fetch and a later single ``get_card_metadata`` share one cache.
        """
        return self._cache

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Rate-limited request with bounded 429 retry honouring ``Retry-After``."""
        limiter = self._limiter_for(url)
        response: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES + 1):
            limiter.wait()
            response = self._client.request(method, url, **kwargs)
            if response.status_code == 429 and attempt < _MAX_RETRIES:
                time.sleep(_retry_after_seconds(response))
                continue
            break
        assert response is not None  # loop always assigns at least once
        response.raise_for_status()
        return response

    def _limiter_for(self, url: str) -> RateLimiter:
        host = urlparse(url).netloc
        group = _HOST_GROUP.get(host, host)
        return self._limiters.get(group, self._default_limiter)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
