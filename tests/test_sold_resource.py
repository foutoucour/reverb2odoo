"""Tests for odoo_mcp/resources/sold.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.resources.sold import (
    _compute_pnl,
    _currency_symbol,
    _fetch_sold_listings,
    _format_price,
    _name,
    _render_gear,
    render,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn(gear_records: list[dict], listing_records: list[dict]) -> MagicMock:
    """Build a minimal mock connection that returns given records."""
    conn = MagicMock()

    gear_model = MagicMock()
    gear_model.search_read.return_value = gear_records

    listing_model = MagicMock()
    listing_model.search_read.return_value = listing_records

    def get_model(name: str):
        if name == "x_gear":
            return gear_model
        if name == "x_listing":
            return listing_model
        raise ValueError(f"Unexpected model: {name}")

    conn.get_model.side_effect = get_model
    return conn


_CAD = [6, "CAD"]
_USD = [7, "USD"]


def _gear(
    *,
    name: str = "Telecaster",
    model_id: Any = None,
    condition: str = "Excellent",
    acquiring_price: float | bool = 1200.0,
    listing_ids: list[int] | None = None,
    notes: str = "",
) -> dict:
    if model_id is None:
        model_id = [10, "Fender Telecaster"]
    return {
        "id": 1,
        "x_name": name,
        "x_model_id": model_id,
        "x_condition": condition,
        "x_studio_acquiring_price": acquiring_price,
        "x_listing_ids": listing_ids or [],
        "x_studio_notes": notes,
        "x_status": "sold",
        "x_intent": "flip",
    }


def _listing(
    *,
    listing_id: int = 99,
    price: float = 1500.0,
    currency: list = _CAD,
    platform: str = "reverb",
    status: str = "sold",
) -> dict:
    return {
        "id": listing_id,
        "x_price": price,
        "x_currency_id": currency,
        "x_platform": platform,
        "x_status": status,
        "x_name": "Listing #99",
        "x_studio_notes": "",
    }


# Suppress the Any type hint used inside the fixture helpers above.
from typing import Any  # noqa: E402 — placed after function defs intentionally

# ---------------------------------------------------------------------------
# _name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param([10, "Fender Telecaster"], "Fender Telecaster", id="many2one-list"),
        pytest.param((10, "Fender Telecaster"), "Fender Telecaster", id="many2one-tuple"),
        pytest.param(False, "", id="false-value"),
        pytest.param(None, "", id="none-value"),
        pytest.param([], "", id="empty-list"),
        pytest.param([10], "", id="single-element-list"),
    ],
)
def test_name(field: Any, expected: str) -> None:
    assert _name(field) == expected


# ---------------------------------------------------------------------------
# _currency_symbol
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "currency_field, expected",
    [
        pytest.param([6, "CAD"], "CA$", id="cad"),
        pytest.param([7, "USD"], "US$", id="usd"),
        pytest.param([8, "EUR"], "€", id="eur"),
        pytest.param([9, "GBP"], "£", id="gbp"),
        pytest.param([10, "JPY"], "JPY", id="unknown-falls-back-to-code"),
        pytest.param(False, "", id="false-no-symbol"),
    ],
)
def test_currency_symbol(currency_field: Any, expected: str) -> None:
    assert _currency_symbol(currency_field) == expected


# ---------------------------------------------------------------------------
# _format_price
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "price, currency_field, expected",
    [
        pytest.param(1200.0, _CAD, "CA$1,200.00", id="cad-price"),
        pytest.param(999.5, _USD, "US$999.50", id="usd-price"),
        pytest.param(0, _CAD, "unknown", id="zero-is-unknown"),
        pytest.param(False, _CAD, "unknown", id="false-is-unknown"),
        pytest.param(None, _CAD, "unknown", id="none-is-unknown"),
    ],
)
def test_format_price(price: Any, currency_field: Any, expected: str) -> None:
    assert _format_price(price, currency_field) == expected


# ---------------------------------------------------------------------------
# _compute_pnl
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "acquiring_price, sold_listings, expected",
    [
        pytest.param(None, [], "unknown", id="no-listings-no-price"),
        pytest.param(1200.0, [], "unknown", id="no-listings-with-price"),
        pytest.param(False, [_listing()], "unknown", id="no-acquiring-price"),
        pytest.param(0, [_listing()], "unknown", id="zero-acquiring-price"),
        pytest.param(1200.0, [_listing(price=1500.0, currency=_CAD)], "+CA$300.00", id="profit"),
        pytest.param(1500.0, [_listing(price=1200.0, currency=_CAD)], "-CA$300.00", id="loss"),
        pytest.param(1200.0, [_listing(price=1200.0, currency=_CAD)], "+CA$0.00", id="breakeven"),
        pytest.param(
            1200.0,
            [
                _listing(listing_id=1, price=1500.0, currency=_CAD),
                _listing(listing_id=2, price=1600.0, currency=_USD),
            ],
            "mixed currencies",
            id="mixed-currencies",
        ),
        pytest.param(
            1200.0,
            [
                _listing(listing_id=1, price=1500.0, currency=_CAD),
                _listing(listing_id=2, price=1600.0, currency=_CAD),
            ],
            "+CA$300.00",
            id="two-listings-same-currency-uses-first",
        ),
    ],
)
def test_compute_pnl(acquiring_price: Any, sold_listings: list[dict], expected: str) -> None:
    assert _compute_pnl(acquiring_price, sold_listings) == expected


# ---------------------------------------------------------------------------
# _fetch_sold_listings
# ---------------------------------------------------------------------------


def test_fetch_sold_listings_calls_search_read_with_correct_domain() -> None:
    conn = MagicMock()
    listing_model = MagicMock()
    listing_model.search_read.return_value = [_listing()]
    conn.get_model.return_value = listing_model

    result = _fetch_sold_listings(conn, [99, 100])

    conn.get_model.assert_called_once_with("x_listing")
    args, _ = listing_model.search_read.call_args
    domain = args[0]
    assert ("id", "in", [99, 100]) in domain
    assert ("x_status", "=", "sold") in domain
    assert result == [_listing()]


def test_fetch_sold_listings_empty_ids_returns_empty() -> None:
    conn = MagicMock()
    result = _fetch_sold_listings(conn, [])
    conn.get_model.assert_not_called()
    assert result == []


# ---------------------------------------------------------------------------
# _render_gear
# ---------------------------------------------------------------------------


def test_render_gear_with_sold_listing() -> None:
    gear = _gear(name="Telecaster", acquiring_price=1200.0, listing_ids=[99])
    listing = _listing(price=1500.0, currency=_CAD, platform="reverb")

    output = _render_gear(gear, [listing])

    assert "## Telecaster" in output
    assert "Fender Telecaster" in output
    assert "Excellent" in output
    assert "CA$1,200.00" in output
    assert "CA$1,500.00" in output
    assert "reverb" in output
    assert "+CA$300.00" in output
    assert "Notes" not in output


def test_render_gear_with_notes() -> None:
    gear = _gear(notes="Great neck pocket.")
    output = _render_gear(gear, [_listing()])
    assert "**Notes**: Great neck pocket." in output


def test_render_gear_no_sold_listing() -> None:
    gear = _gear(listing_ids=[])
    output = _render_gear(gear, [])
    assert "unknown" in output
    assert "P&L**: unknown" in output


def test_render_gear_no_acquiring_price() -> None:
    gear = _gear(acquiring_price=False)
    output = _render_gear(gear, [_listing()])
    assert "Acquired**: unknown" in output
    assert "P&L**: unknown" in output


# ---------------------------------------------------------------------------
# render (integration)
# ---------------------------------------------------------------------------


def test_render_returns_markdown_header() -> None:
    conn = _make_conn(
        gear_records=[_gear(listing_ids=[99])],
        listing_records=[_listing()],
    )
    result = render(conn)
    assert result.startswith("# Sold Gear")


def test_render_no_sold_gear() -> None:
    conn = _make_conn(gear_records=[], listing_records=[])
    result = render(conn)
    assert "# Sold Gear" in result
    assert "No sold gear records found" in result


def test_render_queries_correct_models() -> None:
    conn = _make_conn(
        gear_records=[_gear(listing_ids=[99])],
        listing_records=[_listing()],
    )
    render(conn)

    gear_model = conn.get_model("x_gear")
    gear_model.search_read.assert_called_once()
    domain = gear_model.search_read.call_args[0][0]
    assert ("x_status", "=", "sold") in domain


def test_render_includes_all_gear_sections() -> None:
    gear1 = {**_gear(name="Telecaster", listing_ids=[10]), "id": 1}
    gear2 = {**_gear(name="Les Paul", listing_ids=[20]), "id": 2}
    conn = _make_conn(
        gear_records=[gear1, gear2],
        listing_records=[_listing()],
    )
    result = render(conn)
    assert "## Telecaster" in result
    assert "## Les Paul" in result
