"""MCP tool: fetch a single x_gear record with full listing details.

Returns the gear record with its notes, then all linked x_listing records
with scores, notes, and URL — formatted as markdown.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(m2o: list | bool | None) -> str:
    """Extract display name from a many2one [id, name] value, or '' when absent."""
    if isinstance(m2o, list) and len(m2o) == 2:
        return str(m2o[1])
    return ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None, in which case return fallback."""
    if value is False or value is None:
        return fallback
    return str(value)


def _render_gear_header(gear: dict) -> str:
    """Render the gear header and core fields as a markdown block."""
    name = _scalar(gear.get("x_name"), fallback="(unnamed)")
    status = _scalar(gear.get("x_status"))
    model_name = _label(gear.get("x_model_id"))
    condition = _scalar(gear.get("x_condition"))
    intent = _scalar(gear.get("x_intent"))
    serial = _scalar(gear.get("x_serial_number"))
    neck_profile = _scalar(gear.get("x_neck_profile"))
    acquiring_price = _scalar(gear.get("x_studio_acquiring_price"))
    notes = _scalar(gear.get("x_studio_notes"))

    lines: list[str] = [
        f"# {name} [{status}]",
        f"**Model**: {model_name} | **Condition**: {condition} | **Intent**: {intent}",
        f"**Acquired for**: {acquiring_price} | **Serial**: {serial} | **Neck**: {neck_profile}",
    ]

    if notes:
        lines.append("")
        lines.append(f"**Notes**: {notes}")

    return "\n".join(lines)


def _render_listing_detail(listing: dict) -> str:
    """Render a single listing as a detailed markdown block."""
    listing_id = listing.get("id", "")
    platform = _scalar(listing.get("x_platform"))
    url = _scalar(listing.get("x_url"))
    price = _scalar(listing.get("x_price"))
    currency = _label(listing.get("x_currency_id"))
    shipping = _scalar(listing.get("x_shipping"))
    condition = _scalar(listing.get("x_condition"))
    status = _scalar(listing.get("x_status"))
    is_available = listing.get("x_is_available", False)
    can_accept_offers = listing.get("x_can_accept_offers", False)
    is_taxed = listing.get("x_is_taxed", False)
    published_at = _scalar(listing.get("x_published_at"))
    listing_score = _scalar(listing.get("x_studio_listing_score"))
    price_score = _scalar(listing.get("x_studio_price_score"))
    notes = _scalar(listing.get("x_studio_notes"))

    availability_flags: list[str] = []
    if is_available:
        availability_flags.append("available")
    if can_accept_offers:
        availability_flags.append("accepts offers")
    if is_taxed:
        availability_flags.append("taxed")
    flags_str = ", ".join(availability_flags) if availability_flags else "unavailable"

    lines: list[str] = [
        f"### Listing id={listing_id} [{status}] on {platform}",
        f"**Price**: {price} {currency} + shipping {shipping} | {flags_str}",
        f"**Condition**: {condition} | **Published**: {published_at}",
    ]

    if listing_score or price_score:
        lines.append(f"**Scores**: listing={listing_score} | price={price_score}")

    if url:
        lines.append(f"**URL**: {url}")

    if notes:
        lines.append(f"**Notes**: {notes}")

    return "\n".join(lines)


def _render_listings_section(listings: list[dict]) -> str:
    """Render all listings as a markdown section."""
    if not listings:
        return "## Listings\n\n*No listings recorded*"

    lines: list[str] = [f"## Listings ({len(listings)})", ""]
    for listing in listings:
        lines.append(_render_listing_detail(listing))
        lines.append("")

    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(conn: odoolib.main.Connection, gear_id: int) -> str:
    """Fetch a single x_gear record by id with all linked listing details.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    gear_id:
        The numeric id of the x_gear record to fetch.

    Returns
    -------
    str
        Formatted markdown document with gear details and full listing blocks,
        or a "not found" notice when the id does not match any record.
    """
    logger.info("get_gear: fetching x_gear id={}", gear_id)
    gear_proxy = conn.get_model("x_gear")
    gear_records: list[dict] = gear_proxy.search_read(
        [("id", "=", gear_id)],
        GEAR_FIELDS_MCP,
        limit=1,
    )

    if not gear_records:
        return f"No gear found with id: **{gear_id}**"

    gear = gear_records[0]
    logger.info("get_gear: found gear '{}'", gear.get("x_name"))

    listing_proxy = conn.get_model("x_listing")
    listings: list[dict] = listing_proxy.search_read(
        [("x_gear_id", "=", gear_id)],
        LISTING_FIELDS_MCP,
    )
    logger.debug("get_gear: {} listing(s) found", len(listings))

    sections: list[str] = [
        _render_gear_header(gear),
        "",
        _render_listings_section(listings),
    ]

    return "\n".join(sections)
