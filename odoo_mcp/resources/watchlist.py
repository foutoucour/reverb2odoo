"""MCP resource: watchlist — models with x_studio_wanna=True and their watching listings."""

from __future__ import annotations

import odoolib
from loguru import logger

from models import ListingRecord, ModelsRecord


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _render_listing(listing: ListingRecord) -> str:
    """Render a single listing as a markdown bullet block."""
    listing_score = listing.x_studio_listing_score or 0
    price_score = listing.x_studio_price_score or 0
    price = _scalar(listing.x_price)
    currency = _label(listing.x_currency_id)
    platform = _scalar(listing.x_platform)
    url = _scalar(listing.x_url)
    notes = _scalar(listing.x_studio_notes)

    lines = [f"- [score:{listing_score} price:{price_score}] {price} {currency} on {platform}"]
    if url:
        lines.append(f"  {url}")
    if notes:
        lines.append(f"  Notes: {notes}")

    return "\n".join(lines)


def _render_model(model: ModelsRecord, listings: list[ListingRecord]) -> str:
    """Render a single model block with its watching listings."""
    name = _scalar(model.x_name, fallback="(unnamed)")
    brand = _label(model.x_studio_partner_id)
    model_type = _scalar(model.x_studio_model_type)
    scale = _scalar(model.x_studio_scale)
    neck_feel = _label(model.x_studio_guitar_neck_feel_id)
    p25 = _scalar(model.x_price_p25)
    p50 = _scalar(model.x_price_p50)
    p75 = _scalar(model.x_price_p75)

    sorted_listings = sorted(
        listings,
        key=lambda lst: lst.x_studio_listing_score or 0,
        reverse=True,
    )

    lines: list[str] = [
        f"## {name} — {brand}",
        f"**Type**: {model_type} | **Scale**: {scale} | **Neck**: {neck_feel}",
        f"**Brackets**: p25={p25} p50={p50} p75={p75}",
        "",
    ]

    n = len(sorted_listings)
    if n == 0:
        lines.append("### Watching (0 listings)")
        lines.append("No listings tracked")
    else:
        lines.append(f"### Watching ({n} listings, best first)")
        for listing in sorted_listings:
            lines.append(_render_listing(listing))

    return "\n".join(lines)


def render(conn: odoolib.main.Connection) -> str:
    """Return a markdown string of all wanna=True models and their watching listings.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Formatted markdown with one section per model.
    """
    models_proxy = conn.get_model("x_models")
    model_rows: list[dict] = models_proxy.search_read(
        [("x_studio_wanna", "=", True)],
        ModelsRecord.odoo_fields(),
    )
    wanna_models = [ModelsRecord.from_odoo(r) for r in model_rows]
    logger.info("Watchlist: {} wanna models found", len(wanna_models))

    if not wanna_models:
        return "# Watchlist\n\nNo models on the watchlist.\n"

    model_ids = [m.id for m in wanna_models]

    listing_proxy = conn.get_model("x_listing")
    listing_rows: list[dict] = listing_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        ListingRecord.odoo_fields(),
    )
    watching_listings = [ListingRecord.from_odoo(r) for r in listing_rows]
    logger.info("Watchlist: {} watching listings fetched", len(watching_listings))

    listings_by_model: dict[int, list[ListingRecord]] = {m.id: [] for m in wanna_models}
    for listing in watching_listings:
        if listing.x_model_id is None:
            continue
        mid = listing.x_model_id[0]
        if mid in listings_by_model:
            listings_by_model[mid].append(listing)

    sections = ["# Watchlist", ""]
    for model in wanna_models:
        sections.append(_render_model(model, listings_by_model[model.id]))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
