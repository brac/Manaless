"""Shared HTTP substrate: per-host rate limiting, disk caching, JSON fetch.

Built once in Phase 0 and consumed by every API client (edhrec, scryfall,
spellbook). Keeping the politeness + caching policy in one place is how we stay
a good API citizen against free community services (CLAUDE.md §2, §4).
"""

from manaless.http.cache import DiskCache
from manaless.http.client import HttpClient, HOST_DELAYS
from manaless.http.rate_limiter import RateLimiter

__all__ = ["DiskCache", "HttpClient", "HOST_DELAYS", "RateLimiter"]
