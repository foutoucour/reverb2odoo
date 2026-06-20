"""MCP tool: fetch a single x_gear record with full listing details.

Returns the gear record with its notes, then all linked x_listing records
with scores, notes, and URL — formatted as markdown.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from models import GearRecord, KitRecord, ListingRecord

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(m2o: tuple[int, str] | None) -> str:
    """Extract display name from a normalised many2one value."""
    return m2o[1] if m2o else ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None/empty, in which case return fallback."""
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _render_gear_header(gear: GearRecord, kit: KitRecord | None = None) -> str:
    """Render the gear header and core fields as a markdown block.

    When ``kit`` is provided, an extra "Built from kit" line surfaces the
    reverse link from ``x_kit.x_gear_id``.
    """
    name = _scalar(gear.x_name, fallback="(unnamed)")
    status = _scalar(gear.x_status)
    model_name = _label(gear.x_model_id)
    condition = _scalar(gear.x_studio_current_condition)
    intent = _scalar(gear.x_intent)
    serial = _scalar(gear.x_serial_number)
    acquiring_price = _scalar(gear.x_studio_acquiring_price)
    notes = _scalar(gear.x_studio_notes)

    lines: list[str] = [
        f"# {name} [{status}]",
        f"**Model**: {model_name} | **Condition**: {condition} | **Intent**: {intent}",
        f"**Acquired for**: {acquiring_price} | **Serial**: {serial}",
    ]

    if kit is not None:
        kit_name = _scalar(kit.x_name, fallback="(unnamed)")
        kit_status = _scalar(kit.x_studio_status)
        lines.append(f"**Built from kit**: {kit_name} [{kit_status}] (id={kit.id})")

    if notes:
        lines.append("")
        lines.append(f"**Notes**: {notes}")

    return "\n".join(lines)


def _render_listing_detail(listing: ListingRecord) -> str:
    """Render a single listing as a detailed markdown block."""
    platform = _scalar(listing.x_platform)
    url = _scalar(listing.x_url)
    price = _scalar(listing.x_price)
    currency = _label(listing.x_currency_id)
    shipping = _scalar(listing.x_shipping)
    condition = _scalar(listing.x_condition)
    status = _scalar(listing.x_status)
    published_at = _scalar(listing.x_published_at)
    listing_score = _scalar(listing.x_studio_listing_score)
    price_score = _scalar(listing.x_studio_price_score)
    notes = _scalar(listing.x_studio_notes)

    availability_flags: list[str] = []
    if listing.x_is_available:
        availability_flags.append("available")
    if listing.x_can_accept_offers:
        availability_flags.append("accepts offers")
    if listing.x_is_taxed:
        availability_flags.append("taxed")
    flags_str = ", ".join(availability_flags) if availability_flags else "unavailable"

    lines: list[str] = [
        f"### Listing id={listing.id} [{status}] on {platform}",
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


def _render_listings_section(listings: list[ListingRecord]) -> str:
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
    gear_rows: list[dict] = gear_proxy.search_read(
        [("id", "=", gear_id)],
        GearRecord.odoo_fields(),
        limit=1,
    )

    if not gear_rows:
        return f"No gear found with id: **{gear_id}**"

    gear = GearRecord.from_odoo(gear_rows[0])
    logger.info("get_gear: found gear '{}'", gear.x_name)

    listing_proxy = conn.get_model("x_listing")
    listing_rows: list[dict] = listing_proxy.search_read(
        [("x_gear_id", "=", gear_id)],
        ListingRecord.odoo_fields(),
    )
    listings = [ListingRecord.from_odoo(r) for r in listing_rows]
    logger.debug("get_gear: {} listing(s) found", len(listings))

    kit_proxy = conn.get_model("x_kit")
    kit_rows: list[dict] = kit_proxy.search_read(
        [("x_studio_gear_id", "=", gear_id)],
        KitRecord.odoo_fields(),
        limit=1,
    )
    kit = KitRecord.from_odoo(kit_rows[0]) if kit_rows else None
    if kit is not None:
        logger.debug("get_gear: linked kit '{}' found", kit.x_name)

    sections: list[str] = [
        _render_gear_header(gear, kit=kit),
        "",
        _render_listings_section(listings),
    ]

    return "\n".join(sections)
