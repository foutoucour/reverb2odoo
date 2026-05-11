import os
import time
from dataclasses import dataclass
from pathlib import Path

import odoolib
from dotenv import load_dotenv
from loguru import logger

from odoo_connector import get_connection

load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass
class OdooConfig:
    hostname: str
    database: str
    login: str
    password: str


def get_odoo_config() -> OdooConfig:
    return OdooConfig(
        hostname=os.environ["ODOO_HOSTNAME"],
        database=os.environ["ODOO_DATABASE"],
        login=os.environ["ODOO_LOGIN"],
        password=os.environ["ODOO_PASSWORD"],
    )


# Connection memoization. TTL shares the result-cache TTL so that
# `clear_cache` from the MCP affects connections too.
_conn_cache: odoolib.main.Connection | None = None
_conn_fetched_at: float | None = None


def _conn_ttl_seconds() -> int:
    return int(os.environ.get("ODOO_MCP_CACHE_TTL_SECONDS", "300"))


def get_connection_from_env() -> odoolib.main.Connection:
    """Return an authenticated Odoo connection, memoized by TTL.

    First call authenticates and caches the ``Connection`` object. Subsequent
    calls within the TTL window return the same instance. After the TTL
    expires, a fresh connection is created on the next call.
    """
    global _conn_cache, _conn_fetched_at

    now = time.monotonic()
    if _conn_cache is not None and _conn_fetched_at is not None:
        if (now - _conn_fetched_at) < _conn_ttl_seconds():
            return _conn_cache
        logger.debug("Connection cache expired — re-authenticating")

    cfg = get_odoo_config()
    _conn_cache = get_connection(cfg.hostname, cfg.database, cfg.login, cfg.password)
    _conn_fetched_at = now
    return _conn_cache
