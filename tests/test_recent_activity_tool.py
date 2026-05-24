"""Tests for odoo_mcp/tools/recent_activity.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from odoo_mcp.tools.recent_activity import (
    _render_gear_update,
    _render_new_listing,
    _render_sold_listing,
    run,
)

# ── renderers ─────────────────────────────────────────────────────────────────


def test_render_new_listing_includes_model_price_url() -> None:
    listing = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 2000.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_url": "https://reverb.com/item/x",
        "x_studio_listing_score": 80,
    }
    line = _render_new_listing(listing)
    assert "Les Paul" in line
    assert "2000.0 CAD" in line
    assert "reverb" in line
    assert "https://reverb.com/item/x" in line


def test_render_sold_listing_marks_sold() -> None:
    listing = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 2500.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_url": "",
    }
    line = _render_sold_listing(listing)
    assert "sold at 2500.0" in line


def test_render_gear_update_includes_id_status_model() -> None:
    gear = {
        "id": 42,
        "x_name": "2021 Les Paul",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "keeper",
    }
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
) -> MagicMock:
    conn = MagicMock()
    listing_proxy = MagicMock()
    gear_proxy = MagicMock()

    def listing_search_read(domain: list, fields: list) -> list[dict]:
        clauses = [c for c in domain if isinstance(c, tuple)]
        # Sold = has ("x_status", "=", "sold")
        if any(c == ("x_status", "=", "sold") for c in clauses):
            return sold_listings or []
        # New = has create_date filter and no status filter
        return new_listings or []

    listing_proxy.search_read.side_effect = listing_search_read
    gear_proxy.search_read.return_value = gear_updates or []

    def get_model(name: str) -> MagicMock:
        if name == "x_listing":
            return listing_proxy
        return gear_proxy

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
