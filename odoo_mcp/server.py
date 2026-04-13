"""MCP server entry point for the odoo-collection server.

Wires FastMCP resources and tools to the underlying render/run functions
from the odoo_mcp package.  Transport defaults to stdio (Claude Desktop).

READ-ONLY CONSTRAINT
====================
This server is strictly read-only.  Every Odoo call in this package uses
``search_read`` (or equivalent read operations) — no ``write``, ``create``,
or ``unlink`` calls are permitted.  Resources and tools must never mutate
Odoo state.  Enforce this when adding new resources or tools.
"""

from mcp.server.fastmcp import FastMCP

from odoo_mcp.config import get_connection_from_env
from odoo_mcp.resources import brands as brands_mod
from odoo_mcp.resources import collection as collection_mod
from odoo_mcp.resources import models as models_mod
from odoo_mcp.resources import sold as sold_mod
from odoo_mcp.resources import watchlist as watchlist_mod
from odoo_mcp.tools import get_gear as get_gear_mod
from odoo_mcp.tools import get_model as get_model_mod
from odoo_mcp.tools import search_gear as search_gear_mod

mcp = FastMCP("odoo-collection")


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("odoo://collection")
def resource_collection() -> str:
    return collection_mod.render(get_connection_from_env())


@mcp.resource("odoo://watchlist")
def resource_watchlist() -> str:
    return watchlist_mod.render(get_connection_from_env())


@mcp.resource("odoo://sold")
def resource_sold() -> str:
    return sold_mod.render(get_connection_from_env())


@mcp.resource("odoo://brands")
def resource_brands() -> str:
    return brands_mod.render(get_connection_from_env())


@mcp.resource("odoo://models")
def resource_models() -> str:
    return models_mod.render(get_connection_from_env())


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def search_gear(
    brand: str = "",
    model_type: str = "",
    status: str = "",
    intent: str = "",
) -> str:
    """Search gear by brand, model type, status, or intent. All params optional."""
    return search_gear_mod.run(get_connection_from_env(), brand, model_type, status, intent)


@mcp.tool()
def get_model(name_or_id: str) -> str:
    """Get full spec for a model by name (partial match) or numeric id."""
    return get_model_mod.run(get_connection_from_env(), name_or_id)


@mcp.tool()
def get_gear(gear_id: int) -> str:
    """Get detailed info for a single gear item by its Odoo id."""
    return get_gear_mod.run(get_connection_from_env(), gear_id)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()
