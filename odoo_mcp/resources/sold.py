"""MCP resource: sold gear summary with P&L computation.

Public interface:
    render(conn) -> str

Returns a markdown string listing all x_gear records with x_status='sold',
each annotated with the corresponding sold x_listing and a computed P&L.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from models import GearRecord, ListingRecord

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _name(m2o: tuple[int, str] | None) -> str:
    return m2o[1] if m2o else ""


def _currency_symbol(m2o: tuple[int, str] | None) -> str:
    """Return a best-effort currency symbol from a normalised currency m2o."""
    name = _name(m2o)
    _symbols: dict[str, str] = {
        "CAD": "CA$",
        "USD": "US$",
        "EUR": "€",
        "GBP": "£",
    }
    return _symbols.get(name, name)


def _format_price(price: float | None, currency: tuple[int, str] | None) -> str:
    """Return a human-readable price string, or 'unknown' when unavailable."""
    if not price:
        return "unknown"
    symbol = _currency_symbol(currency)
    return f"{symbol}{price:,.2f}"


def _compute_pnl(
    acquiring_price: float | None,
    sold_listings: list[ListingRecord],
) -> str:
    """Compute the P&L string for a sold gear record.

    Rules:
    - No sold listing found                              → "unknown"
    - acquiring_price is None/0                          → "unknown"
    - Multiple sold listings with different currency_ids → "mixed currencies"
    - Otherwise: "+X.XX" / "-X.XX" prefixed with currency symbol
    """
    if not sold_listings:
        return "unknown"

    if not acquiring_price:
        return "unknown"

    currency_ids: set[int | None] = {
        lst.x_currency_id[0] if lst.x_currency_id else None for lst in sold_listings
    }

    if len(currency_ids) > 1:
        return "mixed currencies"

    listing = sold_listings[0]
    sale_price = listing.x_price or 0.0
    pnl_value = sale_price - float(acquiring_price)

    symbol = _currency_symbol(listing.x_currency_id)
    if pnl_value >= 0:
        return f"+{symbol}{pnl_value:,.2f}"
    return f"-{symbol}{abs(pnl_value):,.2f}"


def _fetch_sold_listings(conn: Any, listing_ids: list[int]) -> list[ListingRecord]:
    """Fetch x_listing records from *listing_ids* where x_status='sold'."""
    if not listing_ids:
        return []
    model = conn.get_model("x_listing")
    rows: list[dict] = model.search_read(
        [("id", "in", listing_ids), ("x_status", "=", "sold")],
        ListingRecord.odoo_fields(),
    )
    return [ListingRecord.from_odoo(r) for r in rows]


def _render_gear(gear: GearRecord, sold_listings: list[ListingRecord]) -> str:
    """Render a single gear record as a markdown block."""
    name = gear.x_name or "Unknown"
    model = _name(gear.x_model_id) or "unknown"
    condition = gear.x_studio_current_condition or "unknown"
    acquiring_price = gear.x_studio_acquiring_price
    notes = gear.x_studio_notes or ""

    # Acquiring price display — use first sold listing's currency when available.
    acquiring_currency = (
        sold_listings[0].x_currency_id if sold_listings and acquiring_price else None
    )
    acquiring_display = _format_price(acquiring_price, acquiring_currency)

    # Sale price display.
    if sold_listings:
        listing = sold_listings[0]
        sale_price = _format_price(listing.x_price, listing.x_currency_id)
        platform = listing.x_platform or "unknown"
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
    rows: list[dict] = gear_model.search_read(
        [("x_status", "=", "sold")],
        GearRecord.odoo_fields(),
    )
    sold_gear = [GearRecord.from_odoo(r) for r in rows]
    logger.info("Found {} sold gear records", len(sold_gear))

    if not sold_gear:
        return "# Sold Gear\n\n_No sold gear records found._"

    sections: list[str] = ["# Sold Gear"]

    for gear in sold_gear:
        sold_listings = _fetch_sold_listings(conn, gear.x_studio_lsting_ids)
        logger.debug(
            "Gear '{}' — {} listing_ids, {} sold",
            gear.x_name,
            len(gear.x_studio_lsting_ids),
            len(sold_listings),
        )
        sections.append(_render_gear(gear, sold_listings))

    return "\n\n".join(sections)
