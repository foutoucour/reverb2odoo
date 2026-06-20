"""Tests for odoo_mcp/tools/get_kit.py."""

from unittest.mock import MagicMock

import pytest

from models import KitPartRecord, KitRecord, ListingRecord
from odoo_mcp.tools.get_kit import (
    _label,
    _render_kit_header,
    _render_part_line,
    _render_parts_section,
    _render_supplier_section,
    _scalar,
    run,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _kit_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "TV Yellow Korina Explorer",
        "x_studio_status": "building",
        "x_studio_notes": False,
        "x_studio_gear_id": False,
        "x_studio_kit_part_ids": False,
        "x_studio_price": False,
        "x_studio_currency_id": False,
        "x_studio_finishing": False,
    }
    base.update(overrides)
    return base


def _kit_part_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 100,
        "x_name": "Tuners line",
        "x_studio_kit_id": [1, "TV Yellow Korina Explorer"],
        "x_studio_listing_id": [500, "Gotoh SD91 Tuners"],
        "x_studio_quantity": 1,
        "x_studio_status": "wanted",
        "x_studio_notes": False,
        "x_studio_total_price": False,
    }
    base.update(overrides)
    return base


def _listing_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 500,
        "x_name": "Gotoh SD91 Tuners listing",
        "x_model_id": [200, "Gotoh SD91 Vintage Tuners"],
        "x_url": "https://solomusicgear.com/p/sd91",
        "x_platform": "solomusicgear",
        "x_price": 89.0,
        "x_currency_id": [1, "CAD"],
        "x_shipping": 0.0,
        "x_condition": "new",
        "x_status": "active",
        "x_is_available": True,
        "x_can_accept_offers": False,
        "x_is_taxed": False,
        "x_published_at": "2026-05-01",
        "x_gear_id": False,
        "x_studio_listing_score": False,
        "x_studio_price_score": False,
        "x_studio_notes": False,
    }
    base.update(overrides)
    return base


def _make_kit(**overrides: object) -> KitRecord:
    return KitRecord.from_odoo(_kit_dict(**overrides))


def _make_part(**overrides: object) -> KitPartRecord:
    return KitPartRecord.from_odoo(_kit_part_dict(**overrides))


def _make_listing(**overrides: object) -> ListingRecord:
    return ListingRecord.from_odoo(_listing_dict(**overrides))


# ---------------------------------------------------------------------------
# _label / _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param((1, "TV Yellow Xplo P90"), "TV Yellow Xplo P90", id="valid-m2o"),
        pytest.param(None, "", id="none-m2o"),
    ],
)
def test_label(field: object, expected: str) -> None:
    assert _label(field) == expected


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("building", "", "building", id="string"),
        pytest.param(False, "", "", id="false-no-fallback"),
        pytest.param(None, "n/a", "n/a", id="none-with-fallback"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# _render_kit_header
# ---------------------------------------------------------------------------


def test_render_kit_header_contains_name_and_status() -> None:
    kit = _make_kit()
    result = _render_kit_header(kit)
    assert "# TV Yellow Korina Explorer [building]" in result


def test_render_kit_header_shows_linked_gear_when_done() -> None:
    kit = _make_kit(x_studio_status="done", x_studio_gear_id=[13, "TV Yellow Xplo P90"])
    result = _render_kit_header(kit)
    assert "**Linked gear**: TV Yellow Xplo P90 (id=13)" in result


def test_render_kit_header_omits_linked_gear_when_unset() -> None:
    kit = _make_kit(x_studio_status="building", x_studio_gear_id=False)
    result = _render_kit_header(kit)
    assert "**Linked gear**" not in result


def test_render_kit_header_shows_notes_when_present() -> None:
    kit = _make_kit(x_studio_notes="Korina slab · Nitro TV Yellow")
    result = _render_kit_header(kit)
    assert "Korina slab · Nitro TV Yellow" in result


def test_render_kit_header_omits_notes_when_absent() -> None:
    kit = _make_kit(x_studio_notes=False)
    result = _render_kit_header(kit)
    assert "**Notes**:" not in result


def test_render_kit_header_unnamed_fallback() -> None:
    kit = _make_kit(x_name=False)
    result = _render_kit_header(kit)
    assert "(unnamed)" in result


# ---------------------------------------------------------------------------
# _render_part_line
# ---------------------------------------------------------------------------


def test_render_part_line_includes_status_badge() -> None:
    part = _make_part(x_studio_status="ordered")
    listing = _make_listing()
    result = _render_part_line(part, listing)
    assert "[ordered]" in result


def test_render_part_line_includes_quantity_and_part_name() -> None:
    part = _make_part(x_studio_quantity=2)
    listing = _make_listing(x_model_id=[201, "CTS 500K Audio Pot"])
    result = _render_part_line(part, listing)
    assert "2×" in result
    assert "CTS 500K Audio Pot" in result


def test_render_part_line_falls_back_to_listing_name_when_no_model() -> None:
    part = _make_part()
    listing = _make_listing(x_model_id=False, x_name="Generic part listing")
    result = _render_part_line(part, listing)
    assert "Generic part listing" in result


def test_render_part_line_includes_price_and_currency() -> None:
    part = _make_part()
    listing = _make_listing(x_price=12.5, x_currency_id=[1, "CAD"])
    result = _render_part_line(part, listing)
    assert "12.50 CAD" in result


def test_render_part_line_includes_url() -> None:
    part = _make_part()
    listing = _make_listing(x_url="https://example.com/part")
    result = _render_part_line(part, listing)
    assert "https://example.com/part" in result


def test_render_part_line_includes_listing_notes_when_present() -> None:
    part = _make_part()
    listing = _make_listing(x_studio_notes="black, schaller bushing")
    result = _render_part_line(part, listing)
    assert "black, schaller bushing" in result


def test_render_part_line_includes_part_notes_when_present() -> None:
    part = _make_part(x_studio_notes="use black buttons")
    listing = _make_listing()
    result = _render_part_line(part, listing)
    assert "use black buttons" in result


def test_render_part_line_includes_part_and_listing_notes_when_present() -> None:
    part = _make_part(x_studio_notes="bridge pickup only")
    listing = _make_listing(x_studio_notes="includes mounting screws")
    result = _render_part_line(part, listing)
    assert "Part notes: bridge pickup only" in result
    assert "Listing notes: includes mounting screws" in result


# ---------------------------------------------------------------------------
# _render_supplier_section
# ---------------------------------------------------------------------------


def test_render_supplier_section_has_header_with_platform_and_count() -> None:
    items = [
        (_make_part(id=100), _make_listing(id=500)),
        (_make_part(id=101), _make_listing(id=501)),
    ]
    result = _render_supplier_section("solomusicgear", items)
    assert "### solomusicgear" in result
    assert "2 parts" in result


def test_render_supplier_section_subtotal_in_same_currency() -> None:
    items = [
        (
            _make_part(x_studio_quantity=1),
            _make_listing(x_price=89.0, x_currency_id=[1, "CAD"]),
        ),
        (
            _make_part(x_studio_quantity=2),
            _make_listing(x_price=5.0, x_currency_id=[1, "CAD"]),
        ),
    ]
    result = _render_supplier_section("solomusicgear", items)
    assert "99.00 CAD" in result


def test_render_supplier_section_sorts_wanted_before_received() -> None:
    items = [
        (
            _make_part(id=101, x_studio_status="received"),
            _make_listing(id=501, x_model_id=[300, "Received Part"]),
        ),
        (
            _make_part(id=100, x_studio_status="wanted"),
            _make_listing(id=500, x_model_id=[301, "Wanted Part"]),
        ),
    ]
    result = _render_supplier_section("solomusicgear", items)
    assert result.index("Wanted Part") < result.index("Received Part")


# ---------------------------------------------------------------------------
# _render_parts_section
# ---------------------------------------------------------------------------


def test_render_parts_section_empty_shows_placeholder() -> None:
    result = _render_parts_section([], {})
    assert "*No parts recorded*" in result


def test_render_parts_section_groups_by_platform() -> None:
    parts = [
        _make_part(id=100, x_studio_listing_id=[500, "Tuners"]),
        _make_part(id=101, x_studio_listing_id=[501, "Pickups"]),
    ]
    listings_by_id = {
        500: _make_listing(id=500, x_platform="solomusicgear"),
        501: _make_listing(id=501, x_platform="pegcitypickups"),
    }
    result = _render_parts_section(parts, listings_by_id)
    assert "### solomusicgear" in result
    assert "### pegcitypickups" in result


def test_render_parts_section_suppliers_sorted_alphabetically() -> None:
    parts = [
        _make_part(id=100, x_studio_listing_id=[500, "p1"]),
        _make_part(id=101, x_studio_listing_id=[501, "p2"]),
    ]
    listings_by_id = {
        500: _make_listing(id=500, x_platform="solomusicgear"),
        501: _make_listing(id=501, x_platform="amazon"),
    }
    result = _render_parts_section(parts, listings_by_id)
    assert result.index("### amazon") < result.index("### solomusicgear")


def test_render_parts_section_grand_total_single_currency() -> None:
    parts = [
        _make_part(id=100, x_studio_listing_id=[500, "p1"], x_studio_quantity=1),
        _make_part(id=101, x_studio_listing_id=[501, "p2"], x_studio_quantity=2),
    ]
    listings_by_id = {
        500: _make_listing(id=500, x_price=89.0, x_currency_id=[1, "CAD"]),
        501: _make_listing(id=501, x_price=5.0, x_currency_id=[1, "CAD"]),
    }
    result = _render_parts_section(parts, listings_by_id)
    assert "Grand total" in result
    assert "99.00 CAD" in result


def test_render_parts_section_grand_total_mixed_currencies() -> None:
    parts = [
        _make_part(id=100, x_studio_listing_id=[500, "p1"]),
        _make_part(id=101, x_studio_listing_id=[501, "p2"]),
    ]
    listings_by_id = {
        500: _make_listing(id=500, x_price=100.0, x_currency_id=[1, "CAD"]),
        501: _make_listing(id=501, x_price=50.0, x_currency_id=[2, "USD"]),
    }
    result = _render_parts_section(parts, listings_by_id)
    assert "100.00 CAD" in result
    assert "50.00 USD" in result


def test_render_parts_section_skips_parts_with_missing_listing() -> None:
    """A kit_part whose listing id is not in the lookup should be skipped, not crash."""
    parts = [
        _make_part(id=100, x_studio_listing_id=[500, "present"]),
        _make_part(id=101, x_studio_listing_id=[999, "missing"]),
    ]
    listings_by_id = {500: _make_listing(id=500, x_platform="amazon")}
    result = _render_parts_section(parts, listings_by_id)
    assert "### amazon" in result
    assert "1 parts" in result


def test_render_parts_section_distinguishes_missing_listing_details() -> None:
    parts = [_make_part(id=100, x_studio_listing_id=[999, "missing"])]
    result = _render_parts_section(parts, {})
    assert "*Parts recorded, but listing details are unavailable*" in result


# ---------------------------------------------------------------------------
# run — integration
# ---------------------------------------------------------------------------


def _make_conn(
    *,
    kit_records: list[dict] | None = None,
    kit_part_records: list[dict] | None = None,
    listing_records: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    kit_proxy = MagicMock()
    kit_part_proxy = MagicMock()
    listing_proxy = MagicMock()

    kit_proxy.search_read.return_value = kit_records or []
    kit_part_proxy.search_read.return_value = kit_part_records or []
    listing_proxy.search_read.return_value = listing_records or []

    proxies = {
        "x_kit": kit_proxy,
        "x_kit_part": kit_part_proxy,
        "x_listing": listing_proxy,
    }

    def get_model(name: str) -> MagicMock:
        return proxies[name]

    conn.get_model.side_effect = get_model
    return conn


def test_run_not_found_returns_notice() -> None:
    conn = _make_conn(kit_records=[])
    result = run(conn, 999)
    assert "No kit found" in result
    assert "999" in result


def test_run_fetches_kit_by_id() -> None:
    conn = _make_conn(kit_records=[_kit_dict(id=42)])
    run(conn, 42)
    domain = conn.get_model("x_kit").search_read.call_args[0][0]
    assert ("id", "=", 42) in domain


def test_run_fetches_kit_parts_by_kit_id() -> None:
    conn = _make_conn(kit_records=[_kit_dict(id=42)])
    run(conn, 42)
    domain = conn.get_model("x_kit_part").search_read.call_args[0][0]
    assert ("x_studio_kit_id", "=", 42) in domain


def test_run_fetches_listings_by_ids() -> None:
    kit = _kit_dict(id=42)
    part = _kit_part_dict(id=100, x_studio_listing_id=[500, "Tuners"])
    conn = _make_conn(kit_records=[kit], kit_part_records=[part])
    run(conn, 42)
    domain = conn.get_model("x_listing").search_read.call_args[0][0]
    # one of the conditions must constrain id ∈ [500]
    assert any(c[0] == "id" and c[1] == "in" and 500 in c[2] for c in domain)


def test_run_dedupes_listing_ids_before_fetching() -> None:
    kit = _kit_dict(id=42)
    parts = [
        _kit_part_dict(id=100, x_studio_listing_id=[500, "Tuners"]),
        _kit_part_dict(id=101, x_studio_listing_id=[500, "Tuners"]),
    ]
    conn = _make_conn(kit_records=[kit], kit_part_records=parts)
    run(conn, 42)
    domain = conn.get_model("x_listing").search_read.call_args[0][0]
    assert any(c == ("id", "in", [500]) for c in domain)


def test_run_skips_listing_fetch_when_no_parts() -> None:
    conn = _make_conn(kit_records=[_kit_dict(id=42)], kit_part_records=[])
    run(conn, 42)
    conn.get_model("x_listing").search_read.assert_not_called()


def test_run_output_contains_kit_name() -> None:
    kit = _kit_dict(id=42, x_name="TV Yellow Korina Explorer")
    conn = _make_conn(kit_records=[kit])
    result = run(conn, 42)
    assert "TV Yellow Korina Explorer" in result


def test_run_output_contains_parts_grouped_by_supplier() -> None:
    kit = _kit_dict(id=42)
    part = _kit_part_dict(id=100, x_studio_listing_id=[500, "Tuners"])
    listing = _listing_dict(id=500, x_platform="solomusicgear")
    conn = _make_conn(
        kit_records=[kit],
        kit_part_records=[part],
        listing_records=[listing],
    )
    result = run(conn, 42)
    assert "### solomusicgear" in result


def test_run_empty_parts_shows_placeholder() -> None:
    conn = _make_conn(kit_records=[_kit_dict(id=42)])
    result = run(conn, 42)
    assert "*No parts recorded*" in result
