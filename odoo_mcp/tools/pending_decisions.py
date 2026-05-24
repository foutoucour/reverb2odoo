"""MCP tool: surface listings that need a yes/no decision.

Inbox-zero for deal triage. Returns active watching listings on wanna=True
models that the user has not yet triaged:

- ``x_status = 'watching'``
- linked model has ``x_studio_wanna = True``
- ``x_is_too_expensive`` is not set
- no linked gear (``x_gear_id`` is empty)
- no notes (``x_studio_notes`` is empty)

Sorted by ``x_studio_listing_score`` descending so the strongest candidates
surface first.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from odoo_connector import MODEL_FIELDS_MCP

_LISTING_FIELDS_PENDING: list[str] = [
    "id",
    "x_name",
    "x_model_id",
    "x_url",
    "x_platform",
    "x_price",
    "x_currency_id",
    "x_shipping",
    "x_condition",
    "x_status",
    "x_published_at",
    "x_gear_id",
    "x_studio_listing_score",
    "x_studio_price_score",
    "x_studio_notes",
    "x_is_too_expensive",
]


def _label(value: list | bool | None) -> str:
    if isinstance(value, list) and len(value) == 2:
        return str(value[1])
    return ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _is_untriaged(listing: dict) -> bool:
    if listing.get("x_is_too_expensive"):
        return False
    if listing.get("x_gear_id"):
        return False
    notes = listing.get("x_studio_notes")
    return not (notes and str(notes).strip())


def _render_listing(listing: dict, model: dict) -> list[str]:
    model_name = _scalar(model.get("x_name"), fallback="(unnamed)")
    brand = _label(model.get("x_studio_partner_id"))
    price = _scalar(listing.get("x_price"))
    currency = _label(listing.get("x_currency_id"))
    platform = _scalar(listing.get("x_platform"))
    condition = _scalar(listing.get("x_condition"))
    listing_score = _scalar(listing.get("x_studio_listing_score"))
    price_score = _scalar(listing.get("x_studio_price_score"))
    p50 = _scalar(model.get("x_studio_p50"))
    published = _scalar(listing.get("x_published_at"))
    url = _scalar(listing.get("x_url"))

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
    wanna_models: list[dict] = models_proxy.search_read(
        [("x_studio_wanna", "=", True)],
        MODEL_FIELDS_MCP,
    )
    if not wanna_models:
        return "# Pending Decisions\n\n*No models marked `wanna=True`. Nothing to triage.*\n"

    model_by_id: dict[int, dict] = {m["id"]: m for m in wanna_models}
    model_ids = list(model_by_id.keys())

    listing_proxy = conn.get_model("x_listing")
    listings: list[dict] = listing_proxy.search_read(
        [("x_model_id", "in", model_ids), ("x_status", "=", "watching")],
        _LISTING_FIELDS_PENDING,
    )
    logger.info("pending_decisions: {} watching listings", len(listings))

    pending = [lst for lst in listings if _is_untriaged(lst)]
    pending.sort(key=lambda lst: lst.get("x_studio_listing_score") or 0, reverse=True)
    logger.info("pending_decisions: {} require triage", len(pending))

    sections: list[str] = [f"# Pending Decisions ({len(pending)})", ""]
    if not pending:
        sections.append("*Inbox zero — every watching listing has been triaged.*")
        return "\n".join(sections) + "\n"

    for listing in pending:
        ref = listing.get("x_model_id")
        if not isinstance(ref, list) or len(ref) != 2:
            continue
        model = model_by_id.get(int(ref[0]))
        if model is None:
            continue
        sections.extend(_render_listing(listing, model))

    return "\n".join(sections).rstrip() + "\n"
