"""MCP resource: watchlist — models with x_studio_wanna=True and their watching listings."""

from __future__ import annotations

import odoolib
from loguru import logger

from odoo_connector import LISTING_FIELDS_MCP, MODEL_FIELDS_MCP


def _label(value: list | bool | None) -> str:
    """Extract display name from a many2one field value ([id, name] or False)."""
    if isinstance(value, list) and len(value) == 2:
        return str(value[1])
    return ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None, in which case return fallback."""
    if value is False or value is None:
        return fallback
    return str(value)


def _render_listing(listing: dict) -> str:
    """Render a single listing as a markdown bullet block."""
    listing_score = listing.get("x_studio_listing_score") or 0
    price_score = listing.get("x_studio_price_score") or 0
    price = _scalar(listing.get("x_price"))
    currency = _label(listing.get("x_currency_id"))
    platform = _scalar(listing.get("x_platform"))
    url = _scalar(listing.get("x_url"))
    notes = _scalar(listing.get("x_studio_notes"))

    lines = [f"- [score:{listing_score} price:{price_score}] {price} {currency} on {platform}"]
    if url:
        lines.append(f"  {url}")
    if notes:
        lines.append(f"  Notes: {notes}")

    return "\n".join(lines)


def _render_model(model: dict, listings: list[dict]) -> str:
    """Render a single model block with its watching listings."""
    name = _scalar(model.get("x_name"), fallback="(unnamed)")
    brand = _label(model.get("x_studio_partner_id"))
    model_type = _scalar(model.get("x_studio_model_type"))
    scale = _scalar(model.get("x_studio_scale"))
    neck_feel = _label(model.get("x_studio_guitar_neck_feel_id"))
    p25 = _scalar(model.get("x_studio_p25"))
    p50 = _scalar(model.get("x_studio_p50"))
    p75 = _scalar(model.get("x_studio_p75"))

    sorted_listings = sorted(
        listings,
        key=lambda lst: lst.get("x_studio_listing_score") or 0,
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
    wanna_models: list[dict] = models_proxy.search_read(
        [("x_studio_wanna", "=", True)],
        MODEL_FIELDS_MCP,
    )
    logger.info("Watchlist: {} wanna models found", len(wanna_models))

    if not wanna_models:
        return "# Watchlist\n\nNo models on the watchlist.\n"

    model_ids = [m["id"] for m in wanna_models]

    listing_proxy = conn.get_model("x_listing")
    watching_listings: list[dict] = listing_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        LISTING_FIELDS_MCP,
    )
    logger.info("Watchlist: {} watching listings fetched", len(watching_listings))

    listings_by_model: dict[int, list[dict]] = {m["id"]: [] for m in wanna_models}
    for listing in watching_listings:
        model_ref = listing.get("x_model_id")
        if isinstance(model_ref, list) and len(model_ref) == 2:
            mid = model_ref[0]
            if mid in listings_by_model:
                listings_by_model[mid].append(listing)

    sections = ["# Watchlist", ""]
    for model in wanna_models:
        mid = model["id"]
        sections.append(_render_model(model, listings_by_model[mid]))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
