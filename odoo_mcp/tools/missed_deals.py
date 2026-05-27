"""MCP tool: surface deals that should have been acted on.

Two buckets:

- **A — Under-p25 active deals**: candidate models (wanna=True AND
  too_expensive=False) with a currently watching listing priced below the
  model's p25 bracket.
- **B — Got away**: closed or sold listings on candidate models where the
  user owns no gear of that model. Filtered to the last *days_lookback* days
  (default 30) via ``write_date``.

Sort order in output: bucket B first (retrospective alert), then bucket A
sorted by gap (p25 − price) descending.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from models import ListingRecord, ModelsRecord


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _format_under_p25(
    listings_and_gaps: list[tuple[ListingRecord, ModelsRecord, float]],
) -> list[str]:
    if not listings_and_gaps:
        return ["*No active listings priced below p25 on wanted models.*"]

    lines: list[str] = []
    for listing, model, gap in listings_and_gaps:
        model_name = _scalar(model.x_name, fallback="(unnamed)")
        brand = _label(model.x_studio_partner_id)
        price = _scalar(listing.x_price)
        currency = _label(listing.x_currency_id)
        platform = _scalar(listing.x_platform)
        p25 = _scalar(model.x_price_p25)
        url = _scalar(listing.x_url)
        listing_score = _scalar(listing.x_studio_listing_score)

        header = f"- **{model_name}** ({brand}) — {price} {currency} on {platform}"
        details = f"  gap: {gap:.0f} below p25={p25} | listing_score={listing_score}"
        lines.append(header)
        lines.append(details)
        if url:
            lines.append(f"  {url}")
    return lines


def _format_got_away(
    listings_by_model: dict[int, list[ListingRecord]],
    models: dict[int, ModelsRecord],
) -> list[str]:
    if not listings_by_model:
        return ["*No closed/sold listings on wanted models within the window.*"]

    def _sort_key(mid: int) -> str:
        return (models[mid].x_name or "").lower()

    lines: list[str] = []
    for mid in sorted(listings_by_model.keys(), key=_sort_key):
        model = models[mid]
        model_name = _scalar(model.x_name, fallback="(unnamed)")
        brand = _label(model.x_studio_partner_id)
        listings = listings_by_model[mid]
        lines.append(f"- **{model_name}** ({brand}) — {len(listings)} got away")
        for listing in listings:
            status = _scalar(listing.x_status)
            price = _scalar(listing.x_price)
            currency = _label(listing.x_currency_id)
            platform = _scalar(listing.x_platform)
            published = _scalar(listing.x_published_at)
            url = _scalar(listing.x_url)
            lines.append(f"  - [{status}] {price} {currency} on {platform} | published {published}")
            if url:
                lines.append(f"    {url}")
    return lines


def run(conn: Any, days_lookback: int = 30) -> str:
    """Return a markdown report of missed deals.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    days_lookback:
        Look-back window in days for the "got away" bucket (closed/sold
        listings). Defaults to 30. Bucket A (active listings) ignores time.

    Returns
    -------
    str
        Markdown document with both sections.
    """
    if days_lookback < 0:
        days_lookback = 30

    logger.info("missed_deals: days_lookback={}", days_lookback)

    models_proxy = conn.get_model("x_models")
    wanna_rows: list[dict] = models_proxy.search_read(
        [("x_studio_wanna", "=", True), ("x_studio_too_expensive", "=", False)],
        ModelsRecord.odoo_fields(),
    )
    wanna_models = [ModelsRecord.from_odoo(r) for r in wanna_rows]
    logger.info("missed_deals: {} candidate models (wanna & not too_expensive)", len(wanna_models))

    if not wanna_models:
        return (
            "# Missed Deals\n\n"
            "*No candidate models (wanna=True and too_expensive=False). "
            "Mark candidates in Odoo to enable this tool.*"
        )

    model_by_id: dict[int, ModelsRecord] = {m.id: m for m in wanna_models}
    model_ids: list[int] = list(model_by_id.keys())

    # Models the user already owns gear of (excludes them from bucket B).
    gear_proxy = conn.get_model("x_gear")
    owned_records: list[dict] = gear_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "owned")],
        ["id", "x_model_id"],
    )
    owned_model_ids: set[int] = set()
    for gear in owned_records:
        ref = gear.get("x_model_id")
        if isinstance(ref, list) and len(ref) == 2:
            owned_model_ids.add(int(ref[0]))
    logger.debug("missed_deals: user owns gear of {} wanna models", len(owned_model_ids))

    listing_proxy = conn.get_model("x_listing")

    # Bucket A — active watching listings below p25.
    watching_rows: list[dict] = listing_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        ListingRecord.odoo_fields(),
    )
    watching_listings = [ListingRecord.from_odoo(r) for r in watching_rows]
    logger.info("missed_deals: {} watching listings on wanna models", len(watching_listings))

    under_p25: list[tuple[ListingRecord, ModelsRecord, float]] = []
    for listing in watching_listings:
        if listing.x_model_id is None:
            continue
        model = model_by_id.get(listing.x_model_id[0])
        if model is None:
            continue
        price = listing.x_price
        p25 = model.x_price_p25
        if price is None or p25 is None or price >= p25:
            continue
        under_p25.append((listing, model, p25 - price))

    # Sort by gap descending (biggest discount first).
    under_p25.sort(key=lambda t: t[2], reverse=True)

    # Bucket B — closed/sold listings within the window, excluding owned models.
    cutoff = (datetime.now(tz=UTC) - timedelta(days=days_lookback)).strftime("%Y-%m-%d %H:%M:%S")
    missed_rows: list[dict] = listing_proxy.search_read(
        [
            ("x_model_id", "in", model_ids),
            ("x_status", "in", ["closed", "sold"]),
            ("write_date", ">=", cutoff),
        ],
        ListingRecord.odoo_fields(),
    )
    missed_candidates = [ListingRecord.from_odoo(r) for r in missed_rows]
    logger.info("missed_deals: {} closed/sold listings in window", len(missed_candidates))

    got_away_by_model: dict[int, list[ListingRecord]] = {}
    for listing in missed_candidates:
        if listing.x_model_id is None:
            continue
        mid = listing.x_model_id[0]
        if mid in owned_model_ids:
            continue
        got_away_by_model.setdefault(mid, []).append(listing)

    sections: list[str] = [
        "# Missed Deals",
        "",
        f"## Got Away (closed/sold, last {days_lookback} days)",
        "",
    ]
    sections.extend(_format_got_away(got_away_by_model, model_by_id))
    sections.append("")
    sections.append("## Under-p25 Active Deals")
    sections.append("")
    sections.extend(_format_under_p25(under_p25))

    return "\n".join(sections).rstrip() + "\n"
