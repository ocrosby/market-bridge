"""Tests for the TTL cache."""

import time

from market_bridge.cache import TTLCache


def test_set_and_get():
    cache = TTLCache(default_ttl=60)
    cache.set("key1", {"data": 42})
    assert cache.get("key1") == {"data": 42}


def test_get_missing_key_returns_none():
    cache = TTLCache()
    assert cache.get("nonexistent") is None


def test_expiry():
    cache = TTLCache(default_ttl=0)
    cache.set("key1", "value", ttl=0)
    # TTL of 0 means it expires immediately at the same monotonic tick
    # We need to wait a tiny bit
    time.sleep(0.01)
    assert cache.get("key1") is None


def test_custom_ttl():
    cache = TTLCache(default_ttl=0)
    cache.set("key1", "value", ttl=60)
    assert cache.get("key1") == "value"


def test_invalidate():
    cache = TTLCache()
    cache.set("key1", "value")
    cache.invalidate("key1")
    assert cache.get("key1") is None


def test_invalidate_missing_key():
    cache = TTLCache()
    cache.invalidate("nonexistent")  # should not raise


def test_clear():
    cache = TTLCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_max_entries_eviction():
    cache = TTLCache(max_entries=3)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    cache.set("d", 4)  # should evict oldest ("a")
    assert cache.get("a") is None
    assert cache.get("d") == 4


def test_make_key():
    cache = TTLCache()
    assert cache.make_key("price", "/ES", "1h") == "price:/ES:1h"
