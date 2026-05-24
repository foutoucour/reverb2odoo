"""MCP tool: surface listings that need a yes/no decision.

Inbox-zero for deal triage. Returns active watching listings on wanna=True
models that the user has not yet triaged:

- ``x_status = 'watching'``
- linked model has ``x_studio_wanna = True``
- ``x_studio_is_candidate`` is still True (proxy for "not triaged out")
- no linked gear (``x_gear_id`` is empty)
- no notes (``x_studio_notes`` is empty)

Sorted by ``x_studio_listing_score`` descending so the strongest candidates
surface first.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from models import ListingRecord, ModelsRecord


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _is_untriaged(listing: ListingRecord) -> bool:
    # ``x_studio_is_candidate`` is the proxy for the design-only
    # ``x_is_too_expensive`` flag (which never made it into Odoo Studio).
    # When False, treat as triaged out.
    if listing.x_studio_is_candidate is False:
        return False
    if listing.x_gear_id is not None:
        return False
    notes = listing.x_studio_notes
    return not (notes and str(notes).strip())


def _render_listing(listing: ListingRecord, model: ModelsRecord) -> list[str]:
    model_name = _scalar(model.x_name, fallback="(unnamed)")
    brand = _label(model.x_studio_partner_id)
    price = _scalar(listing.x_price)
    currency = _label(listing.x_currency_id)
    platform = _scalar(listing.x_platform)
    condition = _scalar(listing.x_condition)
    listing_score = _scalar(listing.x_studio_listing_score)
    price_score = _scalar(listing.x_studio_price_score)
    p50 = _scalar(model.x_price_p50)
    published = _scalar(listing.x_published_at)
    url = _scalar(listing.x_url)

    lines: list[str] = [
        f"- **{model_name}** ({brand}) — {price} {currency} on {platform}",
        f"  condition: {condition} | published: {published} | model p50: {p50}",
        f"  scores: listing={listing_score} price={price_score}",
    ]
    if url:
        lines.append(f"  {url}")
    return lines


def run(conn: Any) -> str:
    """Return a markdown report of listings needing triage.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Markdown document with one bullet per pending listing.
    """
    logger.info("pending_decisions: scanning watching listings")
    models_proxy = conn.get_model("x_models")
    wanna_rows: list[dict] = models_proxy.search_read(
        [("x_studio_wanna", "=", True)],
        ModelsRecord.odoo_fields(),
    )
    if not wanna_rows:
        return "# Pending Decisions\n\n*No models marked `wanna=True`. Nothing to triage.*\n"

    model_by_id: dict[int, ModelsRecord] = {r["id"]: ModelsRecord.from_odoo(r) for r in wanna_rows}
    model_ids = list(model_by_id.keys())

    listing_proxy = conn.get_model("x_listing")
    listing_rows: list[dict] = listing_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        ListingRecord.odoo_fields(),
    )
    listings = [ListingRecord.from_odoo(r) for r in listing_rows]
    logger.info("pending_decisions: {} watching listings", len(listings))

    pending = [lst for lst in listings if _is_untriaged(lst)]
    pending.sort(key=lambda lst: lst.x_studio_listing_score or 0, reverse=True)

    if not pending:
        return "# Pending Decisions\n\n*No watching listings need triage. Inbox zero.*\n"

    sections: list[str] = [f"# Pending Decisions ({len(pending)})", ""]
    for listing in pending:
        if listing.x_model_id is None:
            continue
        model = model_by_id.get(listing.x_model_id[0])
        if model is None:
            continue
        sections.extend(_render_listing(listing, model))

    return "\n".join(sections).rstrip() + "\n"
