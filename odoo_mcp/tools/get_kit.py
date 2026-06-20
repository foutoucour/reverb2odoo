"""MCP tool: fetch a single x_kit record with its parts, grouped by supplier.

Output shape:

    # {kit name} [{status}]
    **Linked gear**: {gear name} (id={id})        (only when x_studio_gear_id is set)
    **Notes**: {kit notes}                        (only when present)

    ## Parts

    ### {supplier slug} ({n} parts, {subtotal} {currency})
    - [wanted]   1× Gotoh SD91 Vintage Tuners — 89.00 CAD — https://…
      Notes: black, schaller bushing
    - [ordered]  2× CTS 500K Audio Pot — 4.50 CAD — https://…
    ...

    **Grand total**: 234.50 CAD + 45.00 USD

Parts within a supplier section are sorted by lifecycle (wanted → ordered →
received) so unfilled needs surface at the top.
"""

from __future__ import annotations

from collections import defaultdict

import odoolib
from loguru import logger

from models import KitPartRecord, KitRecord, ListingRecord

# Sort order applied within each supplier section so unfulfilled parts surface
# first; unknown statuses fall to the end.
_STATUS_ORDER: dict[str, int] = {"wanted": 0, "ordered": 1, "received": 2}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _label(m2o: tuple[int, str] | None) -> str:
    return m2o[1] if m2o else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _format_price(value: object) -> str:
    if value is False or value is None or value == "":
        return "0.00"
    try:
        return f"{float(value):.2f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "0.00"


def _price_as_float(value: object) -> float:
    if value is False or value is None or value == "":
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _status_sort_key(part: KitPartRecord) -> tuple[int, int]:
    status = (part.x_studio_status or "").lower()
    return (_STATUS_ORDER.get(status, 99), part.id or 0)


def _render_kit_header(kit: KitRecord) -> str:
    name = _scalar(kit.x_name, fallback="(unnamed)")
    status = _scalar(kit.x_studio_status)
    notes = _scalar(kit.x_studio_notes)
    finishing = _scalar(kit.x_studio_finishing)
    price = kit.x_studio_price
    currency = _label(kit.x_studio_currency_id)

    lines: list[str] = [f"# {name} [{status}]"]

    if kit.x_studio_gear_id is not None:
        gear_label = _label(kit.x_studio_gear_id)
        gear_id = kit.x_studio_gear_id[0]
        lines.append(f"**Linked gear**: {gear_label} (id={gear_id})")

    if price is not None:
        lines.append(f"**Roll-up price**: {price:.2f} {currency}".rstrip())

    if finishing:
        lines.append(f"**Finishing**: {finishing}")

    if notes:
        lines.append("")
        lines.append(f"**Notes**: {notes}")

    return "\n".join(lines)


def _render_part_line(part: KitPartRecord, listing: ListingRecord) -> str:
    status = _scalar(part.x_studio_status)
    qty = part.x_studio_quantity if part.x_studio_quantity is not None else 1
    part_name = _label(listing.x_model_id) or _scalar(listing.x_name, fallback="(unnamed part)")
    price = _format_price(listing.x_price)
    currency = _label(listing.x_currency_id)
    url = _scalar(listing.x_url)
    part_notes = _scalar(part.x_studio_notes)
    listing_notes = _scalar(listing.x_studio_notes)

    line = f"- [{status}] {qty}× {part_name} — {price} {currency}"
    if url:
        line += f" — {url}"
    if part_notes:
        line += f"\n  Part notes: {part_notes}"
    if listing_notes:
        line += f"\n  Listing notes: {listing_notes}"
    return line


def _render_supplier_section(
    platform: str,
    items: list[tuple[KitPartRecord, ListingRecord]],
) -> str:
    subtotals: dict[str, float] = defaultdict(float)
    for part, listing in items:
        qty = part.x_studio_quantity if part.x_studio_quantity is not None else 1
        price = _price_as_float(listing.x_price)
        currency = _label(listing.x_currency_id) or "(no currency)"
        subtotals[currency] += qty * price

    subtotal_str = " + ".join(f"{value:,.2f} {cur}" for cur, value in sorted(subtotals.items()))

    sorted_items = sorted(items, key=lambda pair: _status_sort_key(pair[0]))

    lines: list[str] = [f"### {platform} ({len(items)} parts, {subtotal_str})"]
    for part, listing in sorted_items:
        lines.append(_render_part_line(part, listing))
    return "\n".join(lines)


def _render_parts_section(
    parts: list[KitPartRecord],
    listings_by_id: dict[int, ListingRecord],
) -> str:
    if not parts:
        return "## Parts\n\n*No parts recorded*"

    grouped: dict[str, list[tuple[KitPartRecord, ListingRecord]]] = defaultdict(list)
    grand_total: dict[str, float] = defaultdict(float)
    matched = 0
    for part in parts:
        if part.x_studio_listing_id is None:
            continue
        listing_id = part.x_studio_listing_id[0]
        listing = listings_by_id.get(listing_id)
        if listing is None:
            continue
        platform = _scalar(listing.x_platform, fallback="(no supplier)")
        grouped[platform].append((part, listing))
        qty = part.x_studio_quantity if part.x_studio_quantity is not None else 1
        currency = _label(listing.x_currency_id) or "(no currency)"
        grand_total[currency] += qty * _price_as_float(listing.x_price)
        matched += 1

    if matched == 0:
        return "## Parts\n\n*Parts recorded, but listing details are unavailable*"

    lines: list[str] = ["## Parts", ""]
    for platform in sorted(grouped.keys()):
        lines.append(_render_supplier_section(platform, grouped[platform]))
        lines.append("")

    grand_total_str = " + ".join(
        f"{value:,.2f} {cur}" for cur, value in sorted(grand_total.items())
    )
    lines.append(f"**Grand total**: {grand_total_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(conn: odoolib.main.Connection, kit_id: int) -> str:
    """Fetch a single x_kit by id and render its parts grouped by supplier.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    kit_id:
        The numeric id of the x_kit record to fetch.

    Returns
    -------
    str
        Markdown document with kit header and supplier-grouped parts, or a
        "not found" notice when the id does not match any record.
    """
    logger.info("get_kit: fetching x_kit id={}", kit_id)
    kit_proxy = conn.get_model("x_kit")
    kit_rows: list[dict] = kit_proxy.search_read(
        [("id", "=", kit_id)],
        KitRecord.odoo_fields(),
        limit=1,
    )

    if not kit_rows:
        return f"No kit found with id: **{kit_id}**"

    kit = KitRecord.from_odoo(kit_rows[0])
    logger.info("get_kit: found kit '{}'", kit.x_name)

    kit_part_proxy = conn.get_model("x_kit_part")
    part_rows: list[dict] = kit_part_proxy.search_read(
        [("x_studio_kit_id", "=", kit_id)],
        KitPartRecord.odoo_fields(),
    )
    parts = [KitPartRecord.from_odoo(r) for r in part_rows]
    logger.debug("get_kit: {} part(s) found", len(parts))

    listings_by_id: dict[int, ListingRecord] = {}
    listing_ids = sorted(
        {p.x_studio_listing_id[0] for p in parts if p.x_studio_listing_id is not None}
    )
    if listing_ids:
        listing_proxy = conn.get_model("x_listing")
        listing_rows: list[dict] = listing_proxy.search_read(
            [("id", "in", listing_ids)],
            ListingRecord.odoo_fields(),
        )
        listings_by_id = {row["id"]: ListingRecord.from_odoo(row) for row in listing_rows}
        logger.debug("get_kit: {} listing(s) joined", len(listings_by_id))

    sections: list[str] = [
        _render_kit_header(kit),
        "",
        _render_parts_section(parts, listings_by_id),
    ]
    return "\n".join(sections)
