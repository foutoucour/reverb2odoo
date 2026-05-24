"""MCP tool: search x_listing records by brand, model_type, max_price, platform, status.

Mirrors :mod:`odoo_mcp.tools.search_gear` but operates on listings (marketplace
entries) rather than gear (physical items). All parameters are optional.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from models import ListingRecord


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _model_ids_for_brand(conn: Any, brand: str) -> list[int]:
    records: list[dict] = conn.get_model("x_models").search_read(
        [("x_studio_partner_id", "ilike", brand)],
        ["id"],
    )
    return [r["id"] for r in records]


def _model_ids_for_type(conn: Any, model_type: str) -> list[int]:
    records: list[dict] = conn.get_model("x_models").search_read(
        [("x_studio_model_type", "ilike", model_type)],
        ["id"],
    )
    return [r["id"] for r in records]


def _render_card(listing: ListingRecord) -> str:
    model_name = _label(listing.x_model_id)
    price = _scalar(listing.x_price)
    currency = _label(listing.x_currency_id)
    platform = _scalar(listing.x_platform)
    status = _scalar(listing.x_status)
    score = _scalar(listing.x_studio_listing_score)
    url = _scalar(listing.x_url)

    score_part = f" | score={score}" if score else ""
    line = f"- **{model_name}** [{status}] — {price} {currency} on {platform}{score_part}"
    if url:
        line += f"\n  {url}"
    return line


def run(
    conn: Any,
    brand: str = "",
    model_type: str = "",
    max_price: float | None = None,
    platform: str = "",
    status: str = "",
) -> str:
    """Search x_listing records with the supplied filters.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    brand, model_type:
        Resolved via x_models ilike, then constrains ``x_model_id``.
    max_price:
        Upper bound on ``x_price`` (inclusive).
    platform:
        Exact match on ``x_platform`` (e.g. ``"reverb"``).
    status:
        Exact match on ``x_status`` (e.g. ``"watching"``, ``"sold"``).

    Returns
    -------
    str
        Markdown with one bullet per matching listing.
    """
    domain: list = []

    if brand.strip():
        ids = _model_ids_for_brand(conn, brand.strip())
        if not ids:
            return f"No listings found matching brand: **{brand}**"
        domain.append(("x_model_id", "in", ids))

    if model_type.strip():
        ids = _model_ids_for_type(conn, model_type.strip())
        if not ids:
            return f"No listings found matching model_type: **{model_type}**"
        if domain and domain[-1][0] == "x_model_id":
            existing = set(domain[-1][2])
            combined = list(existing & set(ids))
            domain[-1] = ("x_model_id", "in", combined)
        else:
            domain.append(("x_model_id", "in", ids))

    if max_price is not None:
        domain.append(("x_price", "<=", float(max_price)))

    if platform.strip():
        domain.append(("x_platform", "=", platform.strip()))

    if status.strip():
        domain.append(("x_status", "=", status.strip()))

    logger.info("search_listings: domain={}", domain)
    rows: list[dict] = conn.get_model("x_listing").search_read(
        domain,
        ListingRecord.odoo_fields(),
    )
    logger.info("search_listings: {} listing(s) found", len(rows))

    if not rows:
        return "No listings found matching the supplied filters."

    listings = [ListingRecord.from_odoo(r) for r in rows]
    listings.sort(key=lambda lst: lst.x_studio_listing_score or 0, reverse=True)

    lines: list[str] = [f"# Listing Search Results ({len(listings)} found)\n"]
    for lst in listings:
        lines.append(_render_card(lst))
    return "\n".join(lines)
