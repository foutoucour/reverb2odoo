"""Tests for odoo_mcp/tools/search_listings.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from odoo_mcp.tools.search_listings import _render_card, run

# ── _render_card ──────────────────────────────────────────────────────────────


def test_render_card_includes_model_and_url() -> None:
    listing = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 1800.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_studio_listing_score": 85,
        "x_url": "https://reverb.com/item/abc",
    }
    result = _render_card(listing)
    assert "Les Paul" in result
    assert "[watching]" in result
    assert "1800.0 CAD" in result
    assert "score=85" in result
    assert "https://reverb.com/item/abc" in result


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(
    *,
    model_records: list[dict] | None = None,
    listings: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    models_proxy = MagicMock()
    listing_proxy = MagicMock()

    models_proxy.search_read.return_value = model_records or []
    listing_proxy.search_read.return_value = listings or []

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        return listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_no_filters_returns_all() -> None:
    listing = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 1800.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_studio_listing_score": 80,
        "x_url": "",
    }
    conn = _make_conn(listings=[listing])
    result = run(conn)
    assert "1 found" in result


def test_run_empty_result_returns_notice() -> None:
    conn = _make_conn(listings=[])
    result = run(conn)
    assert "No listings found" in result


def test_run_brand_with_no_matching_models_short_circuits() -> None:
    conn = _make_conn(model_records=[])
    result = run(conn, brand="NoSuchBrand")
    assert "No listings found matching brand" in result


def test_run_applies_max_price_filter() -> None:
    listing = {
        "x_model_id": [10, "Les Paul"],
        "x_price": 1000.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_studio_listing_score": 0,
        "x_url": "",
    }
    conn = _make_conn(listings=[listing])
    run(conn, max_price=1500.0)
    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    assert ("x_price", "<=", 1500.0) in domain


def test_run_applies_platform_and_status() -> None:
    conn = _make_conn(listings=[])
    run(conn, platform="reverb", status="sold")
    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    assert ("x_platform", "=", "reverb") in domain
    assert ("x_status", "=", "sold") in domain


def test_run_sorts_by_score_desc() -> None:
    low = {
        "id": 1,
        "x_model_id": [10, "LP"],
        "x_price": 1000.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_studio_listing_score": 30,
        "x_url": "https://reverb.com/item/low",
    }
    high = {
        "id": 2,
        "x_model_id": [10, "LP"],
        "x_price": 1500.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_studio_listing_score": 90,
        "x_url": "https://reverb.com/item/high",
    }
    conn = _make_conn(listings=[low, high])
    result = run(conn)
    assert result.index("/item/high") < result.index("/item/low")
