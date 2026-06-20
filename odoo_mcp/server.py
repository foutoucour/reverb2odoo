"""MCP server entry point for the odoo-collection server.

Wires FastMCP resources, parameterized resource templates, tools, and prompts
to the underlying render/run functions in the ``odoo_mcp`` package. Every
public entry point is wrapped with :func:`odoo_mcp.cache.cached` so identical
calls within the TTL window are served from memory.

Transport defaults to stdio (Claude Desktop).

READ-ONLY CONSTRAINT
====================
This server is strictly read-only. Every Odoo call in this package uses
``search_read`` (or equivalent read operations) — no ``write``, ``create``,
or ``unlink`` calls are permitted. Resources and tools must never mutate
Odoo state. Enforce this when adding new resources or tools.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from odoo_mcp import prompts as prompts_mod
from odoo_mcp.cache import cached
from odoo_mcp.config import get_connection_from_env
from odoo_mcp.resources import brands as brands_mod
from odoo_mcp.resources import collection as collection_mod
from odoo_mcp.resources import kits as kits_mod
from odoo_mcp.resources import models as models_mod
from odoo_mcp.resources import sold as sold_mod
from odoo_mcp.resources import tags as tags_mod
from odoo_mcp.resources import watchlist as watchlist_mod
from odoo_mcp.tools import clear_cache as clear_cache_mod
from odoo_mcp.tools import get_brand as get_brand_mod
from odoo_mcp.tools import get_gear as get_gear_mod
from odoo_mcp.tools import get_kit as get_kit_mod
from odoo_mcp.tools import get_model as get_model_mod
from odoo_mcp.tools import get_tag as get_tag_mod
from odoo_mcp.tools import missed_deals as missed_deals_mod
from odoo_mcp.tools import pending_decisions as pending_decisions_mod
from odoo_mcp.tools import portfolio_summary as portfolio_summary_mod
from odoo_mcp.tools import recent_activity as recent_activity_mod
from odoo_mcp.tools import search_gear as search_gear_mod
from odoo_mcp.tools import search_listings as search_listings_mod
from odoo_mcp.tools import search_models as search_models_mod

mcp = FastMCP("odoo-collection")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("odoo://collection")
@cached
def resource_collection() -> str:
    return collection_mod.render(get_connection_from_env())


@mcp.resource("odoo://watchlist")
@cached
def resource_watchlist() -> str:
    return watchlist_mod.render(get_connection_from_env())


@mcp.resource("odoo://sold")
@cached
def resource_sold() -> str:
    return sold_mod.render(get_connection_from_env())


@mcp.resource("odoo://brands")
@cached
def resource_brands() -> str:
    return brands_mod.render(get_connection_from_env())


@mcp.resource("odoo://models")
@cached
def resource_models() -> str:
    return models_mod.render(get_connection_from_env())


@mcp.resource("odoo://tags")
@cached
def resource_tags() -> str:
    return tags_mod.render(get_connection_from_env())


@mcp.resource("odoo://kits")
@cached
def resource_kits() -> str:
    return kits_mod.render(get_connection_from_env())


# ---------------------------------------------------------------------------
# Resource templates (parameterized)
# ---------------------------------------------------------------------------


@mcp.resource("odoo://model/{name}")
@cached
def resource_model_by_name(name: str) -> str:
    """Single x_models record by name or numeric id (ilike search)."""
    return get_model_mod.run(get_connection_from_env(), name)


@mcp.resource("odoo://brand/{name}")
@cached
def resource_brand_by_name(name: str) -> str:
    """Single brand card by name with linked x_models."""
    return get_brand_mod.run(get_connection_from_env(), name)


@mcp.resource("odoo://gear/{gear_id}")
@cached
def resource_gear_by_id(gear_id: str) -> str:
    """Single x_gear record by id with full listing details."""
    try:
        gid = int(gear_id)
    except ValueError:
        return f"Invalid gear id: **{gear_id}** (expected integer)"
    return get_gear_mod.run(get_connection_from_env(), gid)


@mcp.resource("odoo://tag/{name}")
@cached
def resource_tag_by_name(name: str) -> str:
    """Single x_weighted_tags record by name or numeric id (ilike search)."""
    return get_tag_mod.run(get_connection_from_env(), name)


@mcp.resource("odoo://kit/{kit_id}")
@cached
def resource_kit_by_id(kit_id: str) -> str:
    """Single x_kit record by id with parts grouped by supplier."""
    try:
        kid = int(kit_id)
    except ValueError:
        return f"Invalid kit id: **{kit_id}** (expected integer)"
    return get_kit_mod.run(get_connection_from_env(), kid)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
@cached
def search_gear(
    brand: str = "",
    model_type: str = "",
    status: str = "",
    intent: str = "",
) -> str:
    """Search gear by brand, model type, status, or intent. All params optional."""
    return search_gear_mod.run(get_connection_from_env(), brand, model_type, status, intent)


@mcp.tool()
@cached
def get_model(name_or_id: str) -> str:
    """Get full spec for a model by name (partial match) or numeric id."""
    return get_model_mod.run(get_connection_from_env(), name_or_id)


@mcp.tool()
@cached
def get_gear(gear_id: int) -> str:
    """Get detailed info for a single gear item by its Odoo id."""
    return get_gear_mod.run(get_connection_from_env(), gear_id)


@mcp.tool()
@cached
def get_kit(kit_id: int) -> str:
    """Get a kit build with parts grouped by supplier and per-supplier subtotals."""
    return get_kit_mod.run(get_connection_from_env(), kit_id)


@mcp.tool()
@cached
def get_brand(name: str) -> str:
    """Get full info for a brand by name, with linked models."""
    return get_brand_mod.run(get_connection_from_env(), name)


@mcp.tool()
@cached
def get_tag(name_or_id: str) -> str:
    """Get a weighted tag by name (partial match) or numeric id, with linked models."""
    return get_tag_mod.run(get_connection_from_env(), name_or_id)


@mcp.tool()
@cached
def missed_deals(days_lookback: int = 30) -> str:
    """Surface under-p25 active deals and recently-closed listings on wanna models."""
    return missed_deals_mod.run(get_connection_from_env(), days_lookback)


@mcp.tool()
@cached
def recent_activity(days: int = 7) -> str:
    """Report new listings, sold listings, and gear updates in the last N days."""
    return recent_activity_mod.run(get_connection_from_env(), days)


@mcp.tool()
@cached
def portfolio_summary() -> str:
    """Aggregate financial view: owned/sold counts, P&L, by-brand and by-intent pivots."""
    return portfolio_summary_mod.run(get_connection_from_env())


@mcp.tool()
@cached
def pending_decisions() -> str:
    """List watching listings on wanna models that have not been triaged."""
    return pending_decisions_mod.run(get_connection_from_env())


@mcp.tool()
@cached
def search_models(
    query: str = "",
    sort_by: str = "weighted_score",
    limit: int = 20,
) -> str:
    """Search x_models by name and return them sorted by score/price/name.

    ``sort_by`` accepts ``weighted_score`` (default, desc), ``p50`` (desc), ``name`` (asc).
    """
    return search_models_mod.run(
        get_connection_from_env(),
        query=query,
        sort_by=sort_by,
        limit=limit,
    )


@mcp.tool()
@cached
def search_listings(
    brand: str = "",
    model_type: str = "",
    max_price: float | None = None,
    platform: str = "",
    status: str = "",
) -> str:
    """Search x_listing records by brand, model_type, max_price, platform, status."""
    return search_listings_mod.run(
        get_connection_from_env(),
        brand=brand,
        model_type=model_type,
        max_price=max_price,
        platform=platform,
        status=status,
    )


@mcp.tool()
def clear_cache() -> str:
    """Drop server-side caches (result cache, brand cache, connection memo).

    Use after editing Odoo data when the MCP should serve fresh data without
    waiting for the TTL to expire. Not cached itself.
    """
    return clear_cache_mod.run()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@mcp.prompt()
def daily_check() -> str:
    """Daily routine: watchlist + missed deals + pending decisions + recent activity."""
    return prompts_mod.daily_check()


@mcp.prompt()
def deal_hunt(brand: str = "", model: str = "") -> str:
    """Hunt for deals on a specific brand or model."""
    return prompts_mod.deal_hunt(brand=brand, model=model)


@mcp.prompt()
def portfolio_review() -> str:
    """Portfolio review with financial commentary and suggested actions."""
    return prompts_mod.portfolio_review()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()
