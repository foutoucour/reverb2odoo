"""MCP tool: aggregate financial view of the gear collection.

Computes:

- **Owned** — count, total spent (sum of ``x_studio_acquiring_price``),
  total notional value (sum of linked model's ``x_price_p50``), and the
  unrealized P&L (notional − spent).
- **Sold** — count and realized P&L summed from sold listings.
- **By brand** and **by intent** pivots.

Totals are summed numerically without currency conversion — values from
different currencies are commingled. The tool emits a note when more than
one currency is observed across listings.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger

from models import GearRecord, KitRecord, ListingRecord, ModelsRecord

_KIT_STATUSES: list[str] = ["idea", "planning", "sourcing", "building", "done"]


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _float_or_zero(value: object) -> float:
    if value is False or value is None or value == "":
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _format_money(value: float) -> str:
    return f"{value:,.2f}"


def _render_pivot(title: str, totals: dict[str, dict[str, float]]) -> list[str]:
    if not totals:
        return [f"### {title}", "*No data.*"]

    lines: list[str] = [f"### {title}", ""]
    lines.append("| Key | Count | Spent | Notional | Unrealized P&L |")
    lines.append("|---|---:|---:|---:|---:|")
    for key in sorted(totals.keys(), key=lambda k: k.lower()):
        row = totals[key]
        lines.append(
            f"| {key} | {int(row['count'])} | "
            f"{_format_money(row['spent'])} | "
            f"{_format_money(row['notional'])} | "
            f"{_format_money(row['notional'] - row['spent'])} |"
        )
    return lines


def run(conn: Any) -> str:
    """Return a markdown summary of the gear portfolio.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.

    Returns
    -------
    str
        Markdown report with owned, sold, by-brand, and by-intent sections.
    """
    logger.info("portfolio_summary: aggregating gear collection")
    gear_proxy = conn.get_model("x_gear")
    owned_rows: list[dict] = gear_proxy.search_read(
        [("x_status", "=", "owned")],
        GearRecord.odoo_fields(),
    )
    sold_rows: list[dict] = gear_proxy.search_read(
        [("x_status", "=", "sold")],
        GearRecord.odoo_fields(),
    )
    owned_gear = [GearRecord.from_odoo(r) for r in owned_rows]
    sold_gear = [GearRecord.from_odoo(r) for r in sold_rows]
    logger.info(
        "portfolio_summary: {} owned, {} sold gear records",
        len(owned_gear),
        len(sold_gear),
    )

    # Build x_models lookup for p50.
    model_ids = {g.x_model_id[0] for g in owned_gear + sold_gear if g.x_model_id is not None}
    models_by_id: dict[int, ModelsRecord] = {}
    if model_ids:
        models_proxy = conn.get_model("x_models")
        model_rows = models_proxy.search_read(
            [("id", "in", list(model_ids))],
            ModelsRecord.odoo_fields(),
        )
        models_by_id = {r["id"]: ModelsRecord.from_odoo(r) for r in model_rows}

    # Owned aggregates.
    owned_total_spent = 0.0
    owned_total_notional = 0.0
    by_brand: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "spent": 0.0, "notional": 0.0}
    )
    by_intent: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "spent": 0.0, "notional": 0.0}
    )

    for gear in owned_gear:
        spent = _float_or_zero(gear.x_studio_acquiring_price)
        mid = gear.x_model_id[0] if gear.x_model_id else None
        model = models_by_id.get(mid) if mid is not None else None
        notional = _float_or_zero(model.x_price_p50 if model else 0)

        owned_total_spent += spent
        owned_total_notional += notional

        brand = _label(model.x_studio_partner_id) if model else "(unknown)"
        intent = gear.x_intent or "unknown"

        for pivot, key in ((by_brand, brand or "(unknown)"), (by_intent, intent)):
            pivot[key]["count"] += 1
            pivot[key]["spent"] += spent
            pivot[key]["notional"] += notional

    # Sold aggregates (realized P&L = sale - acquiring).
    sold_listing_ids: list[int] = []
    for gear in sold_gear:
        sold_listing_ids.extend(gear.x_studio_lsting_ids)

    sold_listings_by_gear: dict[int, ListingRecord] = {}
    currencies_seen: set[str] = set()
    if sold_listing_ids:
        listing_proxy = conn.get_model("x_listing")
        listing_rows = listing_proxy.search_read(
            [("id", "in", sold_listing_ids), ("x_status", "=", "sold")],
            ListingRecord.odoo_fields(),
        )
        for row in listing_rows:
            lst = ListingRecord.from_odoo(row)
            if lst.x_gear_id is not None:
                sold_listings_by_gear[lst.x_gear_id[0]] = lst
            if lst.x_currency_id is not None:
                currencies_seen.add(lst.x_currency_id[1])

    sold_realized = 0.0
    for gear in sold_gear:
        spent = _float_or_zero(gear.x_studio_acquiring_price)
        listing = sold_listings_by_gear.get(gear.id)
        if listing is None:
            continue
        sale = _float_or_zero(listing.x_price)
        sold_realized += sale - spent

    # Render.
    sections: list[str] = ["# Portfolio Summary", ""]

    sections.append("## Owned")
    sections.append(f"- **Count**: {len(owned_gear)}")
    sections.append(f"- **Spent**: {_format_money(owned_total_spent)}")
    sections.append(f"- **Notional (p50 sum)**: {_format_money(owned_total_notional)}")
    sections.append(
        f"- **Unrealized P&L**: {_format_money(owned_total_notional - owned_total_spent)}"
    )

    sections.append("")
    sections.append("## Sold")
    sections.append(f"- **Count**: {len(sold_gear)}")
    sections.append(f"- **Realized P&L**: {_format_money(sold_realized)}")

    if len(currencies_seen) > 1:
        sections.append(
            f"- *Note: mixed currencies across sold listings ({', '.join(sorted(currencies_seen))})"
            " — totals are not currency-normalized.*"
        )

    # Kits in flight and done.
    kit_proxy = conn.get_model("x_kit")
    kit_rows: list[dict] = kit_proxy.search_read([], KitRecord.odoo_fields())
    kits = [KitRecord.from_odoo(r) for r in kit_rows]
    logger.info("portfolio_summary: {} kit record(s)", len(kits))

    if kits:
        kit_counts: dict[str, int] = {status: 0 for status in _KIT_STATUSES}
        for kit in kits:
            status = (kit.x_studio_status or "").lower()
            if status in kit_counts:
                kit_counts[status] += 1
        sections.append("")
        sections.append("## Kits")
        for status in _KIT_STATUSES:
            sections.append(f"- **{status.capitalize()}**: {kit_counts[status]}")

    sections.append("")
    sections.append("## Pivots")
    sections.append("")
    sections.extend(_render_pivot("By Brand", dict(by_brand)))
    sections.append("")
    sections.extend(_render_pivot("By Intent", dict(by_intent)))

    return "\n".join(sections).rstrip() + "\n"
