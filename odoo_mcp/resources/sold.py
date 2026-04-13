"""MCP resource: sold gear summary with P&L computation.

Public interface:
    render(conn) -> str

Returns a markdown string listing all x_gear records with x_status='sold',
each annotated with the corresponding sold x_listing and a computed P&L.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _name(field: Any) -> str:
    """Extract the display name from a many2one field value ([id, name] or False)."""
    if isinstance(field, (list, tuple)) and len(field) > 1:
        return str(field[1])
    return ""


def _currency_symbol(currency_field: Any) -> str:
    """Return a best-effort currency symbol from a many2one currency field."""
    name = _name(currency_field)
    _symbols: dict[str, str] = {
        "CAD": "CA$",
        "USD": "US$",
        "EUR": "€",
        "GBP": "£",
    }
    return _symbols.get(name, name)


def _format_price(price: Any, currency_field: Any) -> str:
    """Return a human-readable price string, or 'unknown' when unavailable."""
    if not price:
        return "unknown"
    symbol = _currency_symbol(currency_field)
    return f"{symbol}{price:,.2f}"


def _compute_pnl(
    acquiring_price: Any,
    sold_listings: list[dict],
) -> str:
    """Compute the P&L string for a sold gear record.

    Rules:
    - No sold listing found                              → "unknown"
    - acquiring_price is False/None/0                   → "unknown"
    - Multiple sold listings with different currency_ids → "mixed currencies"
    - Otherwise: "+X.XX" / "-X.XX" prefixed with currency symbol
    """
    if not sold_listings:
        return "unknown"

    if not acquiring_price:
        return "unknown"

    # Collect unique currency ids from sold listings.
    currency_ids: set[Any] = set()
    for listing in sold_listings:
        cf = listing.get("x_currency_id")
        cid = cf[0] if isinstance(cf, (list, tuple)) and cf else cf
        currency_ids.add(cid)

    if len(currency_ids) > 1:
        return "mixed currencies"

    # Use the first (and only) listing's price and currency.
    listing = sold_listings[0]
    sale_price = listing.get("x_price") or 0.0
    pnl_value = sale_price - float(acquiring_price)

    symbol = _currency_symbol(listing.get("x_currency_id"))
    if pnl_value >= 0:
        return f"+{symbol}{pnl_value:,.2f}"
    return f"-{symbol}{abs(pnl_value):,.2f}"


def _fetch_sold_listings(conn: Any, listing_ids: list[int]) -> list[dict]:
    """Fetch x_listing records from *listing_ids* where x_status='sold'."""
    if not listing_ids:
        return []
    model = conn.get_model("x_listing")
    results: list[dict] = model.search_read(
        [("id", "in", listing_ids), ("x_status", "=", "sold")],
        LISTING_FIELDS_MCP,
    )
    return results


def _render_gear(gear: dict, sold_listings: list[dict]) -> str:
    """Render a single gear record as a markdown block."""
    name = gear.get("x_name") or "Unknown"
    model = _name(gear.get("x_model_id")) or "unknown"
    condition = gear.get("x_condition") or "unknown"
    acquiring_price = gear.get("x_studio_acquiring_price")
    notes = gear.get("x_studio_notes") or ""

    # Acquiring price display — use first sold listing's currency when available.
    if sold_listings and acquiring_price:
        acquiring_currency = sold_listings[0].get("x_currency_id")
    else:
        acquiring_currency = False
    acquiring_display = _format_price(acquiring_price, acquiring_currency)

    # Sale price display.
    if sold_listings:
        listing = sold_listings[0]
        sale_price = _format_price(listing.get("x_price"), listing.get("x_currency_id"))
        platform = listing.get("x_platform") or "unknown"
    else:
        sale_price = "unknown"
        platform = "unknown"

    pnl = _compute_pnl(acquiring_price, sold_listings)

    lines: list[str] = [
        f"## {name}",
        f"**Model**: {model} | **Condition**: {condition}",
        f"**Acquired**: {acquiring_display} | **Sold**: {sale_price} on {platform} | "
        f"**P&L**: {pnl}",
    ]
    if notes:
        lines.append(f"**Notes**: {notes}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def render(conn: Any) -> str:
    """Query sold gear and return a formatted markdown string.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Markdown document with one section per sold gear record.
    """
    gear_model = conn.get_model("x_gear")
    sold_gear: list[dict] = gear_model.search_read(
        [("x_status", "=", "sold")],
        GEAR_FIELDS_MCP,
    )
    logger.info("Found {} sold gear records", len(sold_gear))

    if not sold_gear:
        return "# Sold Gear\n\n_No sold gear records found._"

    sections: list[str] = ["# Sold Gear"]

    for gear in sold_gear:
        listing_ids: list[int] = gear.get("x_listing_ids") or []
        sold_listings = _fetch_sold_listings(conn, listing_ids)
        logger.debug(
            "Gear '{}' — {} listing_ids, {} sold",
            gear.get("x_name"),
            len(listing_ids),
            len(sold_listings),
        )
        sections.append(_render_gear(gear, sold_listings))

    return "\n\n".join(sections)
