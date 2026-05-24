"""Tests for odoo_mcp/tools/portfolio_summary.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.tools.portfolio_summary import _float_or_zero, _format_money, run

# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param(1500.0, 1500.0, id="float"),
        pytest.param("1500", 1500.0, id="numeric-string"),
        pytest.param(False, 0.0, id="false"),
        pytest.param(None, 0.0, id="none"),
        pytest.param("garbage", 0.0, id="garbage"),
    ],
)
def test_float_or_zero(value: object, expected: float) -> None:
    assert _float_or_zero(value) == expected


def test_format_money_uses_thousand_separator() -> None:
    assert _format_money(12345.6) == "12,345.60"


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(
    *,
    owned: list[dict] | None = None,
    sold: list[dict] | None = None,
    models: list[dict] | None = None,
    sold_listings: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    gear_proxy = MagicMock()
    models_proxy = MagicMock()
    listing_proxy = MagicMock()

    def gear_search_read(domain: list, fields: list) -> list[dict]:
        for clause in domain:
            if isinstance(clause, tuple) and clause[0] == "x_status":
                if clause[2] == "owned":
                    return owned or []
                if clause[2] == "sold":
                    return sold or []
        return []

    gear_proxy.search_read.side_effect = gear_search_read
    models_proxy.search_read.return_value = models or []
    listing_proxy.search_read.return_value = sold_listings or []

    def get_model(name: str) -> MagicMock:
        if name == "x_gear":
            return gear_proxy
        if name == "x_models":
            return models_proxy
        return listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_empty_collection_renders_zero_totals() -> None:
    conn = _make_conn()
    result = run(conn)
    assert "**Count**: 0" in result
    assert "**Spent**: 0.00" in result


def test_run_aggregates_owned_spent_and_notional() -> None:
    gear1 = {
        "id": 1,
        "x_name": "LP",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "keeper",
        "x_studio_acquiring_price": 1800.0,
        "x_listing_ids": [],
    }
    gear2 = {
        "id": 2,
        "x_name": "SG",
        "x_status": "owned",
        "x_model_id": [11, "SG"],
        "x_intent": "flip",
        "x_studio_acquiring_price": 1200.0,
        "x_listing_ids": [],
    }
    model_lp = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_p50": 2200.0,
    }
    model_sg = {
        "id": 11,
        "x_name": "SG",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_p50": 1500.0,
    }
    conn = _make_conn(owned=[gear1, gear2], models=[model_lp, model_sg])
    result = run(conn)

    assert "**Count**: 2" in result
    assert "3,000.00" in result  # spent = 1800 + 1200
    assert "3,700.00" in result  # notional = 2200 + 1500
    assert "700.00" in result  # unrealized P&L


def test_run_pivots_by_brand() -> None:
    gear = {
        "id": 1,
        "x_name": "LP",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "keeper",
        "x_studio_acquiring_price": 1800.0,
        "x_listing_ids": [],
    }
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_p50": 2200.0,
    }
    conn = _make_conn(owned=[gear], models=[model])
    result = run(conn)
    assert "### By Brand" in result
    assert "| Gibson |" in result


def test_run_pivots_by_intent() -> None:
    gear = {
        "id": 1,
        "x_name": "LP",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "flip",
        "x_studio_acquiring_price": 1800.0,
        "x_listing_ids": [],
    }
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_p50": 2200.0,
    }
    conn = _make_conn(owned=[gear], models=[model])
    result = run(conn)
    assert "### By Intent" in result
    assert "| flip |" in result


def test_run_realized_pnl_uses_sold_listing_price() -> None:
    gear = {
        "id": 5,
        "x_name": "Sold-LP",
        "x_status": "sold",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "flip",
        "x_studio_acquiring_price": 1500.0,
        "x_listing_ids": [99],
    }
    sold_listing = {
        "id": 99,
        "x_gear_id": [5, "Sold-LP"],
        "x_price": 2000.0,
        "x_currency_id": [1, "CAD"],
    }
    conn = _make_conn(sold=[gear], sold_listings=[sold_listing])
    result = run(conn)
    # realized = 2000 - 1500 = 500
    assert "500.00" in result


def test_run_flags_mixed_currencies() -> None:
    gear = {
        "id": 5,
        "x_name": "Sold-LP",
        "x_status": "sold",
        "x_model_id": [10, "Les Paul"],
        "x_intent": "flip",
        "x_studio_acquiring_price": 1500.0,
        "x_listing_ids": [99, 100],
    }
    listing_cad = {
        "id": 99,
        "x_gear_id": [5, "Sold-LP"],
        "x_price": 2000.0,
        "x_currency_id": [1, "CAD"],
    }
    listing_usd = {
        "id": 100,
        "x_gear_id": [5, "Sold-LP"],
        "x_price": 1500.0,
        "x_currency_id": [2, "USD"],
    }
    conn = _make_conn(sold=[gear], sold_listings=[listing_cad, listing_usd])
    result = run(conn)
    assert "mixed currencies" in result
