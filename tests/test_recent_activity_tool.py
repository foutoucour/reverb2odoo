"""Tests for odoo_mcp/tools/recent_activity.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from models import GearRecord, KitPartRecord, KitRecord, ListingRecord
from odoo_mcp.tools.recent_activity import (
    _render_gear_update,
    _render_kit_part_update,
    _render_kit_update,
    _render_new_listing,
    _render_sold_listing,
    run,
)

# ── renderers ─────────────────────────────────────────────────────────────────


def test_render_new_listing_includes_model_price_url() -> None:
    listing = ListingRecord.from_odoo(
        {
            "id": 1,
            "x_model_id": [10, "Les Paul"],
            "x_price": 2000.0,
            "x_currency_id": [1, "CAD"],
            "x_platform": "reverb",
            "x_status": "watching",
            "x_url": "https://reverb.com/item/x",
            "x_studio_listing_score": 80,
        }
    )
    line = _render_new_listing(listing)
    assert "Les Paul" in line
    assert "2000.0 CAD" in line
    assert "reverb" in line
    assert "https://reverb.com/item/x" in line


def test_render_sold_listing_marks_sold() -> None:
    listing = ListingRecord.from_odoo(
        {
            "id": 1,
            "x_model_id": [10, "Les Paul"],
            "x_price": 2500.0,
            "x_currency_id": [1, "CAD"],
            "x_platform": "reverb",
            "x_url": "",
        }
    )
    line = _render_sold_listing(listing)
    assert "sold at 2500.0" in line


def test_render_gear_update_includes_id_status_model() -> None:
    gear = GearRecord.from_odoo(
        {
            "id": 42,
            "x_name": "2021 Les Paul",
            "x_status": "owned",
            "x_model_id": [10, "Les Paul"],
            "x_intent": "keeper",
        }
    )
    line = _render_gear_update(gear)
    assert "id=42" in line
    assert "[owned]" in line
    assert "Les Paul" in line
    assert "keeper" in line


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(
    *,
    new_listings: list[dict] | None = None,
    sold_listings: list[dict] | None = None,
    gear_updates: list[dict] | None = None,
    kit_updates: list[dict] | None = None,
    kit_part_updates: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    listing_proxy = MagicMock()
    gear_proxy = MagicMock()
    kit_proxy = MagicMock()
    kit_part_proxy = MagicMock()

    def listing_search_read(domain: list, fields: list) -> list[dict]:
        clauses = [c for c in domain if isinstance(c, tuple)]
        # Sold = has ("x_status", "=", "sold")
        if any(c == ("x_status", "=", "sold") for c in clauses):
            return sold_listings or []
        # New = has create_date filter and no status filter
        return new_listings or []

    listing_proxy.search_read.side_effect = listing_search_read
    gear_proxy.search_read.return_value = gear_updates or []
    kit_proxy.search_read.return_value = kit_updates or []
    kit_part_proxy.search_read.return_value = kit_part_updates or []

    proxies = {
        "x_listing": listing_proxy,
        "x_gear": gear_proxy,
        "x_kit": kit_proxy,
        "x_kit_part": kit_part_proxy,
    }

    def get_model(name: str) -> MagicMock:
        return proxies[name]

    conn.get_model.side_effect = get_model
    return conn


def test_run_empty_window_returns_all_empty_notices() -> None:
    conn = _make_conn()
    result = run(conn, days=7)
    assert "*No new listings.*" in result
    assert "*No listings sold in window.*" in result
    assert "*No gear records updated.*" in result


def test_run_includes_section_counts() -> None:
    new = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 2000.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_url": "",
        "x_studio_listing_score": 0,
    }
    conn = _make_conn(new_listings=[new])
    result = run(conn, days=7)
    assert "## New Listings (1)" in result


def test_run_clamps_negative_days_to_one() -> None:
    conn = _make_conn()
    result = run(conn, days=-3)
    assert "last 1 days" in result


def test_run_includes_window_in_header() -> None:
    conn = _make_conn()
    result = run(conn, days=30)
    assert "last 30 days" in result


# ── kit renderers ─────────────────────────────────────────────────────────────


def test_render_kit_update_includes_id_status_name() -> None:
    kit = KitRecord.from_odoo(
        {
            "id": 7,
            "x_name": "TV Yellow Korina Explorer",
            "x_studio_status": "building",
            "x_studio_notes": False,
            "x_studio_gear_id": False,
            "x_studio_kit_part_ids": False,
            "x_studio_price": False,
            "x_studio_currency_id": False,
            "x_studio_finishing": False,
        }
    )
    line = _render_kit_update(kit)
    assert "id=7" in line
    assert "[building]" in line
    assert "TV Yellow Korina Explorer" in line


def test_render_kit_part_update_includes_kit_listing_status() -> None:
    part = KitPartRecord.from_odoo(
        {
            "id": 100,
            "x_studio_kit_id": [7, "TV Yellow Korina Explorer"],
            "x_studio_listing_id": [500, "Gotoh SD91 Tuners"],
            "x_studio_quantity": 1,
            "x_studio_status": "ordered",
        }
    )
    line = _render_kit_part_update(part)
    assert "TV Yellow Korina Explorer" in line
    assert "Gotoh SD91 Tuners" in line
    assert "[ordered]" in line


# ── kit section in run() ──────────────────────────────────────────────────────


def test_run_includes_kit_activity_section_with_counts() -> None:
    conn = _make_conn(
        kit_updates=[
            {
                "id": 1,
                "x_name": "Kit A",
                "x_studio_status": "idea",
                "x_studio_notes": False,
                "x_studio_gear_id": False,
                "x_studio_kit_part_ids": False,
                "x_studio_price": False,
                "x_studio_currency_id": False,
                "x_studio_finishing": False,
            }
        ],
        kit_part_updates=[
            {
                "id": 10,
                "x_studio_kit_id": [1, "Kit A"],
                "x_studio_listing_id": [500, "p"],
                "x_studio_quantity": 1,
                "x_studio_status": "wanted",
            }
        ],
    )
    result = run(conn, days=7)
    assert "## Kit Activity (2)" in result
    assert "Kit A" in result


def test_run_no_kit_activity_shows_placeholder() -> None:
    conn = _make_conn()
    result = run(conn, days=7)
    assert "*No kit activity in window.*" in result


def test_run_queries_kits_with_write_date_filter() -> None:
    conn = _make_conn()
    run(conn, days=7)
    domain = conn.get_model("x_kit").search_read.call_args[0][0]
    assert any(c[0] == "write_date" and c[1] == ">=" for c in domain)
