"""MCP tool: report what changed in the last *days* days.

Three sections:

- **New listings** — ``x_listing`` records created in the window (``create_date``).
- **Sold listings** — ``x_listing`` records whose ``x_status='sold'`` and were
  last updated in the window (``write_date``).
- **Gear updates** — ``x_gear`` records updated in the window (``write_date``),
  excluding gear with status ``closed`` (already-archived items).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP


def _label(value: list | bool | None) -> str:
    if isinstance(value, list) and len(value) == 2:
        return str(value[1])
    return ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _render_new_listing(listing: dict) -> str:
    model = _label(listing.get("x_model_id"))
    price = _scalar(listing.get("x_price"))
    currency = _label(listing.get("x_currency_id"))
    platform = _scalar(listing.get("x_platform"))
    status = _scalar(listing.get("x_status"))
    url = _scalar(listing.get("x_url"))
    score = _scalar(listing.get("x_studio_listing_score"))

    line = f"- **{model}** [{status}] — {price} {currency} on {platform}"
    if score:
        line += f" | score={score}"
    if url:
        line += f"\n  {url}"
    return line


def _render_sold_listing(listing: dict) -> str:
    model = _label(listing.get("x_model_id"))
    price = _scalar(listing.get("x_price"))
    currency = _label(listing.get("x_currency_id"))
    platform = _scalar(listing.get("x_platform"))
    url = _scalar(listing.get("x_url"))

    line = f"- **{model}** — sold at {price} {currency} on {platform}"
    if url:
        line += f"\n  {url}"
    return line


def _render_gear_update(gear: dict) -> str:
    name = _scalar(gear.get("x_name"), fallback="(unnamed)")
    status = _scalar(gear.get("x_status"))
    model = _label(gear.get("x_model_id"))
    intent = _scalar(gear.get("x_intent"))
    gear_id = gear.get("id", "")
    return f"- **{name}** (id={gear_id}) [{status}] | model: {model} | intent: {intent}"


def run(conn: Any, days: int = 7) -> str:
    """Return a markdown report of activity in the last *days* days.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    days:
        Look-back window in days. Defaults to 7. Values < 1 are clamped to 1.

    Returns
    -------
    str
        Markdown document with three sections.
    """
    if days < 1:
        days = 1

    cutoff_dt = datetime.now(tz=UTC) - timedelta(days=days)
    cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
    logger.info("recent_activity: window={} days (cutoff={})", days, cutoff)

    listing_proxy = conn.get_model("x_listing")
    gear_proxy = conn.get_model("x_gear")

    new_listings: list[dict] = listing_proxy.search_read(
        [("create_date", ">=", cutoff)],
        LISTING_FIELDS_MCP,
    )
    logger.debug("recent_activity: {} new listings", len(new_listings))

    sold_listings: list[dict] = listing_proxy.search_read(
        [("x_status", "=", "sold"), ("write_date", ">=", cutoff)],
        LISTING_FIELDS_MCP,
    )
    logger.debug("recent_activity: {} sold listings", len(sold_listings))

    gear_updates: list[dict] = gear_proxy.search_read(
        [("write_date", ">=", cutoff), ("x_status", "!=", "closed")],
        GEAR_FIELDS_MCP,
    )
    logger.debug("recent_activity: {} gear updates", len(gear_updates))

    sections: list[str] = [
        f"# Recent Activity (last {days} days)",
        "",
        f"## New Listings ({len(new_listings)})",
        "",
    ]
    if new_listings:
        for listing in new_listings:
            sections.append(_render_new_listing(listing))
    else:
        sections.append("*No new listings.*")

    sections.append("")
    sections.append(f"## Sold Listings ({len(sold_listings)})")
    sections.append("")
    if sold_listings:
        for listing in sold_listings:
            sections.append(_render_sold_listing(listing))
    else:
        sections.append("*No listings sold in window.*")

    sections.append("")
    sections.append(f"## Gear Updates ({len(gear_updates)})")
    sections.append("")
    if gear_updates:
        for gear in gear_updates:
            sections.append(_render_gear_update(gear))
    else:
        sections.append("*No gear records updated.*")

    return "\n".join(sections).rstrip() + "\n"
