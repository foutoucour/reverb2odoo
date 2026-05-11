"""MCP tool: clear all server-side caches.

Use after editing Odoo data (Studio, CLI sync, validate) when the MCP should
serve fresh data immediately instead of waiting for the TTL to expire.
"""

from __future__ import annotations

from odoo_mcp.cache import clear_all


def run() -> str:
    """Drop result cache, brand cache, and connection memo. Returns a summary."""
    return clear_all()
