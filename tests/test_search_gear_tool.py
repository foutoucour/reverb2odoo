"""Tests for odoo_mcp/tools/search_gear.py."""

from unittest.mock import MagicMock

import pytest

from odoo_mcp.tools.search_gear import _label, _render_card, _scalar, run

# ---------------------------------------------------------------------------
# _label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param([10, "Gibson"], "Gibson", id="valid-m2o"),
        pytest.param(False, "", id="false-m2o"),
        pytest.param(None, "", id="none-m2o"),
        pytest.param([], "", id="empty-list"),
    ],
)
def test_label(field: object, expected: str) -> None:
    assert _label(field) == expected


# ---------------------------------------------------------------------------
# _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("owned", "", "owned", id="string-value"),
        pytest.param(1500.0, "", "1500.0", id="float-value"),
        pytest.param(False, "", "", id="false-no-fallback"),
        pytest.param(None, "n/a", "n/a", id="none-with-fallback"),
        pytest.param(0, "", "0", id="zero-is-truthy-enough"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# _render_card
# ---------------------------------------------------------------------------


def _make_gear(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "2021 Gibson Les Paul Standard",
        "x_status": "owned",
        "x_model_id": [10, "Les Paul Standard"],
        "x_condition": "excellent",
        "x_intent": "keeper",
        "x_serial_number": "SN001",
        "x_neck_profile": False,
        "x_studio_acquiring_price": False,
        "x_studio_notes": False,
        "x_listing_ids": [],
    }
    base.update(overrides)
    return base


def test_render_card_contains_name_and_status() -> None:
    gear = _make_gear()
    result = _render_card(gear)
    assert "**2021 Gibson Les Paul Standard**" in result
    assert "[owned]" in result


def test_render_card_contains_model_condition_intent() -> None:
    gear = _make_gear()
    result = _render_card(gear)
    assert "Model: Les Paul Standard" in result
    assert "Condition: excellent" in result
    assert "Intent: keeper" in result


def test_render_card_handles_missing_fields() -> None:
    gear = _make_gear(x_name=False, x_model_id=False, x_status=False)
    result = _render_card(gear)
    assert "(unnamed)" in result


# ---------------------------------------------------------------------------
# run — no filters
# ---------------------------------------------------------------------------


def _make_conn(
    *,
    model_ids_brand: list[int] | None = None,
    model_ids_type: list[int] | None = None,
    gear_records: list[dict] | None = None,
) -> MagicMock:
    """Build a minimal mock conn for search_gear.run tests."""
    conn = MagicMock()

    models_proxy = MagicMock()
    gear_proxy = MagicMock()

    def models_search_read(domain: list, fields: list, **kwargs: object) -> list[dict]:
        # Determine which call based on the domain field being searched.
        field = domain[0][0] if domain else ""
        if field == "x_studio_partner_id":
            return [{"id": mid} for mid in (model_ids_brand or [])]
        if field == "x_studio_model_type":
            return [{"id": mid} for mid in (model_ids_type or [])]
        return []

    models_proxy.search_read.side_effect = models_search_read
    gear_proxy.search_read.return_value = gear_records or []

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        return gear_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_no_filters_returns_all_gear() -> None:
    gear = _make_gear()
    conn = _make_conn(gear_records=[gear])
    result = run(conn)
    assert "2021 Gibson Les Paul Standard" in result


def test_run_no_filters_passes_empty_domain() -> None:
    conn = _make_conn(gear_records=[])
    run(conn)
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert domain == []


def test_run_returns_no_results_notice_when_empty() -> None:
    conn = _make_conn(gear_records=[])
    result = run(conn)
    assert "No gear found" in result


# ---------------------------------------------------------------------------
# run — brand filter
# ---------------------------------------------------------------------------


def test_run_brand_resolves_model_ids_then_filters_gear() -> None:
    conn = _make_conn(model_ids_brand=[5, 6], gear_records=[])
    run(conn, brand="Gibson")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_model_id", "in", [5, 6]) in domain


def test_run_brand_not_found_returns_early_without_gear_query() -> None:
    conn = _make_conn(model_ids_brand=[], gear_records=[])
    result = run(conn, brand="UnknownBrand")
    gear_proxy = conn.get_model("x_gear")
    gear_proxy.search_read.assert_not_called()
    assert "UnknownBrand" in result


# ---------------------------------------------------------------------------
# run — model_type filter
# ---------------------------------------------------------------------------


def test_run_model_type_resolves_model_ids_then_filters_gear() -> None:
    conn = _make_conn(model_ids_type=[7, 8], gear_records=[])
    run(conn, model_type="solidbody")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_model_id", "in", [7, 8]) in domain


def test_run_model_type_not_found_returns_early_without_gear_query() -> None:
    conn = _make_conn(model_ids_type=[], gear_records=[])
    result = run(conn, model_type="unknown_type")
    gear_proxy = conn.get_model("x_gear")
    gear_proxy.search_read.assert_not_called()
    assert "unknown_type" in result


# ---------------------------------------------------------------------------
# run — status and intent filters
# ---------------------------------------------------------------------------


def test_run_status_filter_appended_to_domain() -> None:
    conn = _make_conn(gear_records=[])
    run(conn, status="watching")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_status", "=", "watching") in domain


def test_run_intent_filter_appended_to_domain() -> None:
    conn = _make_conn(gear_records=[])
    run(conn, intent="flip")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_intent", "=", "flip") in domain


def test_run_combined_status_and_intent() -> None:
    conn = _make_conn(gear_records=[])
    run(conn, status="owned", intent="keeper")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_status", "=", "owned") in domain
    assert ("x_intent", "=", "keeper") in domain


# ---------------------------------------------------------------------------
# run — multiple results output
# ---------------------------------------------------------------------------


def test_run_multiple_results_shows_count_in_header() -> None:
    records = [_make_gear(id=i, x_name=f"Gear {i}") for i in range(3)]
    conn = _make_conn(gear_records=records)
    result = run(conn)
    assert "3 found" in result


def test_run_all_gear_names_present_in_output() -> None:
    records = [_make_gear(id=1, x_name="Les Paul"), _make_gear(id=2, x_name="Telecaster")]
    conn = _make_conn(gear_records=records)
    result = run(conn)
    assert "Les Paul" in result
    assert "Telecaster" in result


# ---------------------------------------------------------------------------
# run — brand + model_type intersection
# ---------------------------------------------------------------------------


def test_run_brand_and_model_type_intersects_model_ids() -> None:
    """When both brand and model_type are given, only overlapping model ids are used."""
    conn = MagicMock()
    models_proxy = MagicMock()
    gear_proxy = MagicMock()
    gear_proxy.search_read.return_value = []

    call_count = 0

    def models_search_read(domain: list, fields: list, **kwargs: object) -> list[dict]:
        nonlocal call_count
        call_count += 1
        field = domain[0][0] if domain else ""
        if field == "x_studio_partner_id":
            return [{"id": 1}, {"id": 2}, {"id": 3}]
        if field == "x_studio_model_type":
            return [{"id": 2}, {"id": 3}, {"id": 4}]
        return []

    models_proxy.search_read.side_effect = models_search_read

    def get_model(name: str) -> MagicMock:
        return models_proxy if name == "x_models" else gear_proxy

    conn.get_model.side_effect = get_model

    run(conn, brand="Gibson", model_type="solidbody")

    domain = gear_proxy.search_read.call_args[0][0]
    model_clause = next(c for c in domain if c[0] == "x_model_id")
    # Intersection of {1,2,3} and {2,3,4} = {2,3}
    assert set(model_clause[2]) == {2, 3}
