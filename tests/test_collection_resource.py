"""Tests for odoo_mcp/resources/collection.py."""

from unittest.mock import MagicMock

import pytest

from models import GearRecord, ListingRecord
from odoo_mcp.resources.collection import _name, _render_gear, _render_listing, _val, render

# ---------------------------------------------------------------------------
# _name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param((42, "Gibson Les Paul"), "Gibson Les Paul", id="valid-m2o"),
        pytest.param(None, "", id="none-m2o"),
    ],
)
def test_name(field: object, expected: str) -> None:
    assert _name(field) == expected


# ---------------------------------------------------------------------------
# _val
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param("active", "active", id="string-value"),
        pytest.param(1500.0, "1500.0", id="float-value"),
        pytest.param(False, "", id="false-value"),
        pytest.param(None, "", id="none-value"),
    ],
)
def test_val(field: object, expected: str) -> None:
    assert _val(field) == expected


# ---------------------------------------------------------------------------
# _render_listing
# ---------------------------------------------------------------------------


def _listing_dict(**overrides: object) -> dict:
    base: dict = {
        "id": overrides.pop("id", 100),
        "x_platform": "reverb",
        "x_url": "https://reverb.com/item/12345-les-paul",
        "x_price": 2500.0,
        "x_currency_id": [1, "CAD"],
        "x_studio_listing_score": 85,
        "x_studio_notes": False,
    }
    base.update(overrides)
    return base


def _make_listing(**overrides: object) -> ListingRecord:
    return ListingRecord.from_odoo(_listing_dict(**overrides))


def test_render_listing_basic() -> None:
    listing = _make_listing()
    result = _render_listing(listing)
    assert result.startswith("- [reverb]")
    assert "https://reverb.com/item/12345-les-paul" in result
    assert "2500.0 CAD" in result
    assert "score: 85" in result


def test_render_listing_includes_notes_when_present() -> None:
    listing = _make_listing(x_studio_notes="Great condition, no fret wear")
    result = _render_listing(listing)
    assert "Notes: Great condition, no fret wear" in result


def test_render_listing_omits_notes_when_false() -> None:
    listing = _make_listing(x_studio_notes=False)
    result = _render_listing(listing)
    assert "Notes:" not in result


def test_render_listing_omits_score_when_false() -> None:
    listing = _make_listing(x_studio_listing_score=False)
    result = _render_listing(listing)
    assert "score:" not in result


# ---------------------------------------------------------------------------
# _render_gear
# ---------------------------------------------------------------------------


def _gear_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "2021 Gibson Les Paul Standard",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul Standard"],
        "x_studio_current_condition": "excellent",
        "x_intent": "keeper",
        "x_studio_acquiring_price": 2200.0,
        "x_serial_number": "SN123456",
        "x_studio_notes": False,
        "x_studio_lsting_ids": [],
    }
    base.update(overrides)
    return base


def _make_gear(**overrides: object) -> GearRecord:
    return GearRecord.from_odoo(_gear_dict(**overrides))


def test_render_gear_header_contains_name_and_status() -> None:
    gear = _make_gear()
    result = _render_gear(gear, [])
    assert "## 2021 Gibson Les Paul Standard [owned]" in result


def test_render_gear_second_line_contains_model_condition_intent() -> None:
    gear = _make_gear()
    result = _render_gear(gear, [])
    assert "**Model**: Les Paul Standard" in result
    assert "**Condition**: excellent" in result
    assert "**Intent**: keeper" in result


def test_render_gear_third_line_contains_price_and_serial() -> None:
    gear = _make_gear()
    result = _render_gear(gear, [])
    assert "**Acquired for**: 2200.0" in result
    assert "**Serial**: SN123456" in result


def test_render_gear_shows_notes_when_present() -> None:
    gear = _make_gear(x_studio_notes="Pickup swap — Burstbucker Pro")
    result = _render_gear(gear, [])
    assert "**Notes**: Pickup swap — Burstbucker Pro" in result


def test_render_gear_omits_notes_when_false() -> None:
    gear = _make_gear(x_studio_notes=False)
    result = _render_gear(gear, [])
    assert "**Notes**:" not in result


def test_render_gear_no_listings_shows_placeholder() -> None:
    gear = _make_gear()
    result = _render_gear(gear, [])
    assert "*No listings recorded*" in result


def test_render_gear_with_listings() -> None:
    gear = _make_gear()
    listing = _make_listing()
    result = _render_gear(gear, [listing])
    assert "*No listings recorded*" not in result
    assert "- [reverb]" in result


# ---------------------------------------------------------------------------
# render (integration — conn mocked)
# ---------------------------------------------------------------------------


def _make_conn(gear_records: list[dict], listing_records: list[dict]) -> MagicMock:
    """Build a minimal mock conn whose get_model returns predictable proxies."""
    conn = MagicMock()

    gear_proxy = MagicMock()
    gear_proxy.search_read.return_value = gear_records

    listing_proxy = MagicMock()
    listing_proxy.search_read.return_value = listing_records

    def get_model(name: str) -> MagicMock:
        return gear_proxy if name == "x_gear" else listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_render_returns_markdown_heading() -> None:
    conn = _make_conn([], [])
    result = render(conn)
    assert result.startswith("# My Collection")


def test_render_queries_correct_gear_statuses() -> None:
    conn = _make_conn([], [])
    render(conn)
    gear_proxy = conn.get_model("x_gear")
    call_args = gear_proxy.search_read.call_args
    domain = call_args[0][0]
    assert ("x_status", "in", ["owned", "for_sale"]) in domain


def test_render_owned_gear_queries_acquired_listings() -> None:
    gear = _gear_dict(id=1, x_status="owned", x_studio_lsting_ids=[10])
    conn = _make_conn([gear], [])
    render(conn)
    listing_proxy = conn.get_model("x_listing")
    call_args = listing_proxy.search_read.call_args
    domain = call_args[0][0]
    assert ("x_status", "in", ["acquired"]) in domain
    assert ("x_gear_id", "=", 1) in domain


def test_render_for_sale_gear_queries_for_sale_and_sold_listings() -> None:
    gear = _gear_dict(id=2, x_status="for_sale", x_studio_lsting_ids=[20])
    conn = _make_conn([gear], [])
    render(conn)
    listing_proxy = conn.get_model("x_listing")
    call_args = listing_proxy.search_read.call_args
    domain = call_args[0][0]
    assert ("x_status", "in", ["for_sale", "sold"]) in domain
    assert ("x_gear_id", "=", 2) in domain


def test_render_includes_gear_name_in_output() -> None:
    gear = _gear_dict(x_name="2019 Fender Telecaster", x_status="owned")
    conn = _make_conn([gear], [])
    result = render(conn)
    assert "2019 Fender Telecaster" in result


def test_render_multiple_gear_records() -> None:
    gear1 = _gear_dict(id=1, x_name="Les Paul", x_status="owned")
    gear2 = _gear_dict(id=2, x_name="Telecaster", x_status="for_sale")
    conn = _make_conn([gear1, gear2], [])
    result = render(conn)
    assert "Les Paul" in result
    assert "Telecaster" in result
