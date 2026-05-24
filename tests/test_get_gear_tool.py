"""Tests for odoo_mcp/tools/get_gear.py."""

from unittest.mock import MagicMock

import pytest

from models import GearRecord, ListingRecord
from odoo_mcp.tools.get_gear import (
    _label,
    _render_gear_header,
    _render_listing_detail,
    _render_listings_section,
    _scalar,
    run,
)

# ---------------------------------------------------------------------------
# _label / _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param((1, "Reverb"), "Reverb", id="valid-m2o"),
        pytest.param(None, "", id="none-m2o"),
    ],
)
def test_label(field: object, expected: str) -> None:
    assert _label(field) == expected


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("keeper", "", "keeper", id="string"),
        pytest.param(False, "", "", id="false-no-fallback"),
        pytest.param(None, "n/a", "n/a", id="none-with-fallback"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# _render_gear_header
# ---------------------------------------------------------------------------


def _gear_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "2021 Gibson Les Paul Standard",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul Standard"],
        "x_studio_current_condition": "excellent",
        "x_intent": "keeper",
        "x_serial_number": "SN123456",
        "x_studio_acquiring_price": 2200.0,
        "x_studio_notes": False,
        "x_studio_lsting_ids": [],
    }
    base.update(overrides)
    return base


def _make_gear(**overrides: object) -> GearRecord:
    return GearRecord.from_odoo(_gear_dict(**overrides))


def test_render_gear_header_contains_name_and_status() -> None:
    gear = _make_gear()
    result = _render_gear_header(gear)
    assert "# 2021 Gibson Les Paul Standard [owned]" in result


def test_render_gear_header_contains_model_condition_intent() -> None:
    gear = _make_gear()
    result = _render_gear_header(gear)
    assert "**Model**: Les Paul Standard" in result
    assert "**Condition**: excellent" in result
    assert "**Intent**: keeper" in result


def test_render_gear_header_contains_acquiring_price_and_serial() -> None:
    gear = _make_gear()
    result = _render_gear_header(gear)
    assert "**Acquired for**: 2200.0" in result
    assert "**Serial**: SN123456" in result


def test_render_gear_header_shows_notes_when_present() -> None:
    gear = _make_gear(x_studio_notes="Pickup swap done")
    result = _render_gear_header(gear)
    assert "**Notes**: Pickup swap done" in result


def test_render_gear_header_omits_notes_when_false() -> None:
    gear = _make_gear(x_studio_notes=False)
    result = _render_gear_header(gear)
    assert "**Notes**:" not in result


def test_render_gear_header_unnamed_fallback() -> None:
    gear = _make_gear(x_name=False)
    result = _render_gear_header(gear)
    assert "(unnamed)" in result


# ---------------------------------------------------------------------------
# _render_listing_detail
# ---------------------------------------------------------------------------


def _listing_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 100,
        "x_name": "Les Paul Standard listing",
        "x_model_id": [10, "Les Paul Standard"],
        "x_url": "https://reverb.com/item/12345-les-paul",
        "x_platform": "reverb",
        "x_price": 2500.0,
        "x_currency_id": [1, "CAD"],
        "x_shipping": 50.0,
        "x_condition": "excellent",
        "x_status": "watching",
        "x_is_available": True,
        "x_can_accept_offers": True,
        "x_is_taxed": False,
        "x_published_at": "2025-01-15",
        "x_gear_id": [1, "2021 Gibson Les Paul Standard"],
        "x_studio_listing_score": 85,
        "x_studio_price_score": 78,
        "x_studio_notes": False,
    }
    base.update(overrides)
    return base


def _make_listing(**overrides: object) -> ListingRecord:
    return ListingRecord.from_odoo(_listing_dict(**overrides))


def test_render_listing_detail_header_contains_id_status_platform() -> None:
    listing = _make_listing()
    result = _render_listing_detail(listing)
    assert "### Listing id=100 [watching] on reverb" in result


def test_render_listing_detail_shows_price_and_currency() -> None:
    listing = _make_listing()
    result = _render_listing_detail(listing)
    assert "2500.0 CAD" in result


def test_render_listing_detail_shows_url() -> None:
    listing = _make_listing()
    result = _render_listing_detail(listing)
    assert "https://reverb.com/item/12345-les-paul" in result


def test_render_listing_detail_shows_scores() -> None:
    listing = _make_listing()
    result = _render_listing_detail(listing)
    assert "listing=85" in result
    assert "price=78" in result


def test_render_listing_detail_omits_scores_when_absent() -> None:
    listing = _make_listing(x_studio_listing_score=False, x_studio_price_score=False)
    result = _render_listing_detail(listing)
    assert "**Scores**:" not in result


def test_render_listing_detail_shows_notes_when_present() -> None:
    listing = _make_listing(x_studio_notes="Neck crack repaired")
    result = _render_listing_detail(listing)
    assert "**Notes**: Neck crack repaired" in result


def test_render_listing_detail_omits_notes_when_false() -> None:
    listing = _make_listing(x_studio_notes=False)
    result = _render_listing_detail(listing)
    assert "**Notes**:" not in result


def test_render_listing_detail_availability_flags() -> None:
    listing = _make_listing(x_is_available=True, x_can_accept_offers=True, x_is_taxed=True)
    result = _render_listing_detail(listing)
    assert "available" in result
    assert "accepts offers" in result
    assert "taxed" in result


def test_render_listing_detail_unavailable_when_all_false() -> None:
    listing = _make_listing(x_is_available=False, x_can_accept_offers=False, x_is_taxed=False)
    result = _render_listing_detail(listing)
    assert "unavailable" in result


# ---------------------------------------------------------------------------
# _render_listings_section
# ---------------------------------------------------------------------------


def test_render_listings_section_empty_returns_placeholder() -> None:
    result = _render_listings_section([])
    assert "*No listings recorded*" in result


def test_render_listings_section_shows_count() -> None:
    listings = [_make_listing(id=i) for i in range(3)]
    result = _render_listings_section(listings)
    assert "## Listings (3)" in result


def test_render_listings_section_includes_all_listings() -> None:
    l1 = _make_listing(id=1, x_url="https://reverb.com/item/1")
    l2 = _make_listing(id=2, x_url="https://reverb.com/item/2")
    result = _render_listings_section([l1, l2])
    assert "https://reverb.com/item/1" in result
    assert "https://reverb.com/item/2" in result


# ---------------------------------------------------------------------------
# run — integration
# ---------------------------------------------------------------------------


def _make_conn(
    *,
    gear_records: list[dict] | None = None,
    listing_records: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    gear_proxy = MagicMock()
    listing_proxy = MagicMock()

    gear_proxy.search_read.return_value = gear_records or []
    listing_proxy.search_read.return_value = listing_records or []

    def get_model(name: str) -> MagicMock:
        return gear_proxy if name == "x_gear" else listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_not_found_returns_notice() -> None:
    conn = _make_conn(gear_records=[])
    result = run(conn, 999)
    assert "No gear found" in result
    assert "999" in result


def test_run_fetches_gear_by_id() -> None:
    gear = _gear_dict(id=42)
    conn = _make_conn(gear_records=[gear])
    run(conn, 42)
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("id", "=", 42) in domain


def test_run_fetches_listings_by_gear_id() -> None:
    gear = _gear_dict(id=42)
    conn = _make_conn(gear_records=[gear])
    run(conn, 42)
    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    assert ("x_gear_id", "=", 42) in domain


def test_run_output_contains_gear_name() -> None:
    gear = _gear_dict()
    conn = _make_conn(gear_records=[gear])
    result = run(conn, 1)
    assert "2021 Gibson Les Paul Standard" in result


def test_run_output_contains_listing_url() -> None:
    gear = _gear_dict()
    listing = _listing_dict()
    conn = _make_conn(gear_records=[gear], listing_records=[listing])
    result = run(conn, 1)
    assert "https://reverb.com/item/12345-les-paul" in result


def test_run_no_listings_shows_placeholder() -> None:
    gear = _gear_dict()
    conn = _make_conn(gear_records=[gear], listing_records=[])
    result = run(conn, 1)
    assert "*No listings recorded*" in result


def test_run_gear_notes_included_in_output() -> None:
    gear = _gear_dict(x_studio_notes="Custom wiring harness")
    conn = _make_conn(gear_records=[gear])
    result = run(conn, 1)
    assert "Custom wiring harness" in result


def test_run_listing_not_queried_when_gear_not_found() -> None:
    conn = _make_conn(gear_records=[])
    run(conn, 999)
    listing_proxy = conn.get_model("x_listing")
    listing_proxy.search_read.assert_not_called()
