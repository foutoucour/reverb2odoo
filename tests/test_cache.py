"""Tests for odoo_mcp/cache.py — TTLCache, cached decorator, clear_all."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from odoo_mcp import brand_cache, config
from odoo_mcp.cache import TTLCache, _default_cache, cached, clear_all


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset module-level caches before and after each test."""
    _default_cache.clear()
    brand_cache._cache = []
    brand_cache._fetched_at = None
    config._conn_cache = None
    config._conn_fetched_at = None
    yield
    _default_cache.clear()
    brand_cache._cache = []
    brand_cache._fetched_at = None
    config._conn_cache = None
    config._conn_fetched_at = None


# ── TTLCache ──────────────────────────────────────────────────────────────────


def test_ttl_cache_returns_none_on_miss() -> None:
    c = TTLCache(ttl_seconds=10, max_size=5)
    assert c.get(("k",)) is None


def test_ttl_cache_returns_value_on_hit() -> None:
    c = TTLCache(ttl_seconds=10, max_size=5)
    c.set(("k",), "v")
    assert c.get(("k",)) == "v"


def test_ttl_cache_expires_entry_after_ttl() -> None:
    c = TTLCache(ttl_seconds=10, max_size=5)
    c.set(("k",), "v")
    with patch("odoo_mcp.cache.time.monotonic", return_value=time.monotonic() + 20):
        assert c.get(("k",)) is None


def test_ttl_cache_evicts_oldest_at_max_size() -> None:
    c = TTLCache(ttl_seconds=60, max_size=2)
    c.set(("a",), 1)
    c.set(("b",), 2)
    c.set(("c",), 3)  # should evict ("a",)
    assert c.get(("a",)) is None
    assert c.get(("b",)) == 2
    assert c.get(("c",)) == 3


def test_ttl_cache_get_marks_recent() -> None:
    c = TTLCache(ttl_seconds=60, max_size=2)
    c.set(("a",), 1)
    c.set(("b",), 2)
    # touch a so b becomes the oldest
    c.get(("a",))
    c.set(("c",), 3)  # should evict b, not a
    assert c.get(("a",)) == 1
    assert c.get(("b",)) is None


def test_ttl_cache_clear_drops_all() -> None:
    c = TTLCache(ttl_seconds=60, max_size=5)
    c.set(("a",), 1)
    c.clear()
    assert c.get(("a",)) is None
    assert len(c) == 0


# ── cached decorator ──────────────────────────────────────────────────────────


def test_cached_decorator_caches_result() -> None:
    calls = {"n": 0}

    @cached
    def f(x: int) -> int:
        calls["n"] += 1
        return x * 2

    assert f(3) == 6
    assert f(3) == 6
    assert calls["n"] == 1


def test_cached_decorator_distinct_args_distinct_keys() -> None:
    calls = {"n": 0}

    @cached
    def f(x: int) -> int:
        calls["n"] += 1
        return x

    f(1)
    f(2)
    f(1)
    assert calls["n"] == 2


def test_cached_decorator_respects_kwargs() -> None:
    calls = {"n": 0}

    @cached
    def f(x: int, y: int = 0) -> int:
        calls["n"] += 1
        return x + y

    f(1, y=1)
    f(1, y=2)
    f(1, y=1)
    assert calls["n"] == 2


# ── clear_all ─────────────────────────────────────────────────────────────────


def test_clear_all_drops_result_cache() -> None:
    @cached
    def f() -> str:
        return "x"

    f()
    assert len(_default_cache) == 1
    clear_all()
    assert len(_default_cache) == 0


def test_clear_all_drops_brand_cache() -> None:
    brand_cache._cache = [{"name": "x"}]
    brand_cache._fetched_at = object()  # truthy
    clear_all()
    assert brand_cache._cache == []
    assert brand_cache._fetched_at is None


def test_clear_all_drops_connection_cache() -> None:
    config._conn_cache = object()
    config._conn_fetched_at = 1.0
    clear_all()
    assert config._conn_cache is None
    assert config._conn_fetched_at is None


def test_clear_all_returns_summary_string() -> None:
    result = clear_all()
    assert isinstance(result, str)
    assert "cleared" in result.lower() or "empty" in result.lower()
