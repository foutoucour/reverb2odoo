"""MCP tool: aggregate financial view of the gear collection.

Computes:

- **Owned** — count, total spent (sum of ``x_studio_acquiring_price``),
  total notional value (sum of linked model's ``x_studio_p50``), and the
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

from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP, MODEL_FIELDS_MCP


def _label(value: list | bool | None) -> str:
    if isinstance(value, list) and len(value) == 2:
        return str(value[1])
    return ""


def _float_or_zero(value: object) -> float:
    if value is False or value is None or value == "":
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _model_id_from(record: dict) -> int | None:
    ref = record.get("x_model_id")
    if isinstance(ref, list) and len(ref) == 2:
        return int(ref[0])
    return None


def _currency_name(field: Any) -> str | None:
    if isinstance(field, list) and len(field) == 2:
        return str(field[1])
    return None


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
    owned_gear: list[dict] = gear_proxy.search_read(
        [("x_status", "=", "owned")],
        GEAR_FIELDS_MCP,
    )
    sold_gear: list[dict] = gear_proxy.search_read(
        [("x_status", "=", "sold")],
        GEAR_FIELDS_MCP,
    )
    logger.info(
        "portfolio_summary: {} owned, {} sold gear records",
        len(owned_gear),
        len(sold_gear),
    )

    # Build x_models lookup for p50.
    model_ids = {mid for g in owned_gear + sold_gear if (mid := _model_id_from(g)) is not None}
    models_by_id: dict[int, dict] = {}
    if model_ids:
        models_proxy = conn.get_model("x_models")
        records = models_proxy.search_read(
            [("id", "in", list(model_ids))],
            MODEL_FIELDS_MCP,
        )
        models_by_id = {r["id"]: r for r in records}

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
        spent = _float_or_zero(gear.get("x_studio_acquiring_price"))
        mid = _model_id_from(gear)
        model = models_by_id.get(mid) if mid is not None else None
        notional = _float_or_zero(model.get("x_studio_p50") if model else 0)

        owned_total_spent += spent
        owned_total_notional += notional

        brand = _label(model.get("x_studio_partner_id")) if model else "(unknown)"
        intent = gear.get("x_intent") or "unknown"

        for pivot, key in ((by_brand, brand or "(unknown)"), (by_intent, intent)):
            pivot[key]["count"] += 1
            pivot[key]["spent"] += spent
            pivot[key]["notional"] += notional

    # Sold aggregates (realized P&L = sale - acquiring).
    sold_listing_ids: list[int] = []
    for gear in sold_gear:
        ids = gear.get("x_listing_ids") or []
        sold_listing_ids.extend(int(i) for i in ids)

    sold_listings_by_gear: dict[int, dict] = {}
    currencies_seen: set[str] = set()
    if sold_listing_ids:
        listing_proxy = conn.get_model("x_listing")
        listings = listing_proxy.search_read(
            [("id", "in", sold_listing_ids), ("x_status", "=", "sold")],
            LISTING_FIELDS_MCP,
        )
        for lst in listings:
            gid_ref = lst.get("x_gear_id")
            if isinstance(gid_ref, list) and len(gid_ref) == 2:
                sold_listings_by_gear[int(gid_ref[0])] = lst
            cname = _currency_name(lst.get("x_currency_id"))
            if cname:
                currencies_seen.add(cname)

    sold_realized = 0.0
    for gear in sold_gear:
        spent = _float_or_zero(gear.get("x_studio_acquiring_price"))
        listing = sold_listings_by_gear.get(int(gear["id"]))
        if listing is None:
            continue
        sale = _float_or_zero(listing.get("x_price"))
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

    sections.append("")
    sections.append("## Pivots")
    sections.append("")
    sections.extend(_render_pivot("By Brand", dict(by_brand)))
    sections.append("")
    sections.extend(_render_pivot("By Intent", dict(by_intent)))

    return "\n".join(sections).rstrip() + "\n"
