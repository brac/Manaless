"""HTTP client composing the rate limiter, disk cache, and a polite User-Agent.

The single entry point the API clients use. ``get_json`` short-circuits on a
cache hit (no request, no rate-limit wait); otherwise it waits on the host's
limiter, fetches, raises on HTTP error, caches, and returns parsed JSON.
``get_text`` is the raw path used by the EDHREC build-id scrape.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx

from manaless.http.cache import DiskCache
from manaless.http.rate_limiter import RateLimiter

# A descriptive UA is the polite minimum for these free community services
# (CLAUDE.md §2). Appending a contact URL/email is encouraged but optional.
DEFAULT_USER_AGENT = "Manaless/0.1 (+https://github.com/; personal MTG Commander tool)"

# Minimum seconds between requests, per host (CLAUDE.md §4).
HOST_DELAYS: dict[str, float] = {
    "edhrec.com": 0.80,
    "json.edhrec.com": 0.80,
    "api.scryfall.com": 0.12,
    "backend.commanderspellbook.com": 0.10,
}
_DEFAULT_DELAY = 0.20
_DEFAULT_TIMEOUT = 20.0

# On HTTP 429, honour Retry-After and retry rather than failing the pipeline.
_MAX_RETRIES = 3
_RETRY_AFTER_FALLBACK = 1.0


def _retry_after_seconds(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return _RETRY_AFTER_FALLBACK


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
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
        delays = HOST_DELAYS if host_delays is None else host_delays
        self._limiters = {host: RateLimiter(delay) for host, delay in delays.items()}
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

    def get_text(self, url: str) -> str:
        """Fetch raw text (used for the EDHREC build-id homepage scrape)."""
        return self._send("GET", url).text

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
        return self._limiters.get(host, self._default_limiter)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
