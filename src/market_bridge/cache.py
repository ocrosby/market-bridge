"""TTL-based cache to reduce redundant API calls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


@dataclass
class TTLCache:
    default_ttl: int = 30
    max_entries: int = 500
    _store: dict[str, CacheEntry] = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if len(self._store) >= self.max_entries:
            self._evict_expired()
        if len(self._store) >= self.max_entries:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]

        expires_at = time.monotonic() + (ttl if ttl is not None else self.default_ttl)
        self._store[key] = CacheEntry(value=value, expires_at=expires_at)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]

    def make_key(self, *parts: str) -> str:
        return ":".join(str(p) for p in parts)
