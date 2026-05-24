"""TTL result cache for MCP resources and tools.

Public API:
    cached         — decorator that memoizes function results with TTL + LRU
    clear_all      — drop result cache, brand cache, and connection memo
    get_default_ttl — current TTL in seconds (env-driven)
    get_max_size   — current LRU cap

Cache key: ``(module, qualname, args, sorted_kwargs_items)``.

Configured via ``ODOO_MCP_CACHE_TTL_SECONDS`` (default 300) and
``ODOO_MCP_CACHE_MAX_SIZE`` (default 128).
"""

from __future__ import annotations

import functools
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from loguru import logger


def get_default_ttl() -> int:
    return int(os.environ.get("ODOO_MCP_CACHE_TTL_SECONDS", "300"))


def get_max_size() -> int:
    return int(os.environ.get("ODOO_MCP_CACHE_MAX_SIZE", "128"))


class TTLCache:
    """LRU cache with per-entry TTL. Not thread-safe; fine for stdio MCP."""

    def __init__(self, ttl_seconds: int, max_size: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_size = max_size
        self._store: OrderedDict[tuple, tuple[Any, float]] = OrderedDict()

    def get(self, key: tuple) -> Any | None:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.monotonic() >= expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key: tuple, value: Any) -> None:
        if key in self._store:
            del self._store[key]
        self._store[key] = (value, time.monotonic() + self.ttl_seconds)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_default_cache: TTLCache = TTLCache(ttl_seconds=get_default_ttl(), max_size=get_max_size())


def _make_key(func: Callable, args: tuple, kwargs: dict) -> tuple:
    return (
        func.__module__,
        func.__qualname__,
        args,
        tuple(sorted(kwargs.items())),
    )


def cached(func: Callable) -> Callable:
    """Memoize ``func`` in the module-level TTL cache.

    Args and kwargs must be hashable. Connection objects should NOT be
    passed as arguments — fetch them inside the wrapped function.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = _make_key(func, args, kwargs)
        cached_value = _default_cache.get(key)
        if cached_value is not None:
            logger.debug("cache HIT: {}", func.__qualname__)
            return cached_value
        logger.debug("cache MISS: {}", func.__qualname__)
        value = func(*args, **kwargs)
        _default_cache.set(key, value)
        return value

    return wrapper


def clear_all() -> str:
    """Clear result cache, brand cache, and connection memo.

    Returns a short human-readable summary suitable for an MCP tool reply.
    """
    result_count = len(_default_cache)
    _default_cache.clear()

    from odoo_mcp import brand_cache

    brand_was_cached = brand_cache._fetched_at is not None
    brand_cache._cache = []
    brand_cache._fetched_at = None

    from odoo_mcp import config

    conn_was_cached = config._conn_cache is not None
    config._conn_cache = None
    config._conn_fetched_at = None

    logger.info(
        "Cache cleared — result entries: {}, brand_cache: {}, connection: {}",
        result_count,
        brand_was_cached,
        conn_was_cached,
    )
    return (
        f"Caches cleared. Result entries dropped: {result_count}. "
        f"Brand cache: {'cleared' if brand_was_cached else 'was empty'}. "
        f"Connection: {'dropped' if conn_was_cached else 'was empty'}."
    )
