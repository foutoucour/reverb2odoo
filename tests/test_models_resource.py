"""Tests for odoo_mcp/resources/models.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.resources.models import (
    _build_spec_line,
    _label,
    _render_model_section,
    _scalar,
    render,
)

# ---------------------------------------------------------------------------
# _label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param([1, "Gibson"], "Gibson", id="valid-m2o"),
        pytest.param(False, "", id="false-m2o"),
        pytest.param(None, "", id="none-m2o"),
        pytest.param([], "", id="empty-list"),
    ],
)
def test_label(value: object, expected: str) -> None:
    assert _label(value) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("59", "", "59", id="string-value"),
        pytest.param(1500.0, "", "1500.0", id="float-value"),
        pytest.param(False, "", "", id="false-returns-fallback"),
        pytest.param(None, "", "", id="none-returns-fallback"),
        pytest.param("", "N/A", "N/A", id="empty-string-returns-fallback"),
        pytest.param(False, "N/A", "N/A", id="false-with-custom-fallback"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# _build_spec_line
# ---------------------------------------------------------------------------


def _make_model(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "Les Paul Standard",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_model_type": "electric",
        "x_studio_wanna": True,
        "x_studio_guitar_neck_feel_id": [5, "Standard C"],
        "x_studio_scale": '24.75"',
        "x_studio_finish": [3, "Gloss"],
        "x_studio_fretboard_1": [2, "Rosewood"],
        "x_studio_p25": 1800.0,
        "x_studio_p50": 2200.0,
        "x_studio_p75": 2600.0,
    }
    base.update(overrides)
    return base


def test_build_spec_line_all_fields() -> None:
    model = _make_model()
    result = _build_spec_line(model)
    assert 'scale=24.75"' in result
    assert "neck=Standard C" in result
    assert "fretboard=Rosewood" in result
    assert "finish=Gloss" in result


def test_build_spec_line_omits_false_fields() -> None:
    model = _make_model(
        x_studio_scale=False,
        x_studio_guitar_neck_feel_id=False,
        x_studio_fretboard_1=False,
        x_studio_finish=False,
    )
    result = _build_spec_line(model)
    assert result == ""


def test_build_spec_line_partial_fields() -> None:
    model = _make_model(
        x_studio_scale='25.5"',
        x_studio_guitar_neck_feel_id=False,
        x_studio_fretboard_1=False,
        x_studio_finish=False,
    )
    result = _build_spec_line(model)
    assert 'scale=25.5"' in result
    assert "neck=" not in result
    assert "fretboard=" not in result
    assert "finish=" not in result


# ---------------------------------------------------------------------------
# _render_model_section
# ---------------------------------------------------------------------------


def test_render_model_section_header() -> None:
    model = _make_model()
    result = _render_model_section(model, {}, 0)
    assert "### Les Paul Standard" in result


def test_render_model_section_brand_type_wanna() -> None:
    model = _make_model()
    result = _render_model_section(model, {}, 0)
    assert "**Brand**: Gibson" in result
    assert "**Type**: electric" in result
    assert "**Wanna**: yes" in result


def test_render_model_section_wanna_false() -> None:
    model = _make_model(x_studio_wanna=False)
    result = _render_model_section(model, {}, 0)
    assert "**Wanna**: no" in result


def test_render_model_section_brackets() -> None:
    model = _make_model()
    result = _render_model_section(model, {}, 0)
    assert "**Brackets**: p25=1800.0 p50=2200.0 p75=2600.0" in result


def test_render_model_section_gear_counts() -> None:
    model = _make_model()
    gear_counts = {"owned": 2, "for_sale": 1, "sold": 3}
    result = _render_model_section(model, gear_counts, 4)
    assert "**Gear**: 2 owned, 1 for_sale, 3 sold | 4 watching listings" in result


def test_render_model_section_zero_counts() -> None:
    model = _make_model()
    result = _render_model_section(model, {}, 0)
    assert "**Gear**: 0 owned, 0 for_sale, 0 sold | 0 watching listings" in result


def test_render_model_section_omits_spec_line_when_all_false() -> None:
    model = _make_model(
        x_studio_scale=False,
        x_studio_guitar_neck_feel_id=False,
        x_studio_fretboard_1=False,
        x_studio_finish=False,
    )
    result = _render_model_section(model, {}, 0)
    assert "**Specs**:" not in result


def test_render_model_section_includes_spec_line_when_present() -> None:
    model = _make_model()
    result = _render_model_section(model, {}, 0)
    assert "**Specs**:" in result


# ---------------------------------------------------------------------------
# render — integration with mocked conn
# ---------------------------------------------------------------------------


def _make_conn(
    model_records: list[dict],
    gear_records: list[dict],
    listing_records: list[dict],
) -> MagicMock:
    """Build a minimal mock conn that returns predictable data per model name."""
    conn = MagicMock()

    models_proxy = MagicMock()
    models_proxy.search_read.return_value = model_records

    gear_proxy = MagicMock()
    gear_proxy.search_read.return_value = gear_records

    listing_proxy = MagicMock()
    listing_proxy.search_read.return_value = listing_records

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        if name == "x_gear":
            return gear_proxy
        return listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_render_heading() -> None:
    conn = _make_conn([], [], [])
    result = render(conn)
    assert result.startswith("# Models Catalog")


def test_render_no_models_returns_empty_message() -> None:
    conn = _make_conn([], [], [])
    result = render(conn)
    assert "No models found." in result


def test_render_queries_all_models_no_filter() -> None:
    conn = _make_conn([], [], [])
    render(conn)
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert domain == []


def test_render_full_catalog_section_present() -> None:
    model = _make_model()
    conn = _make_conn([model], [], [])
    result = render(conn)
    assert "## Full Catalog" in result


def test_render_wanted_no_listings_section_present() -> None:
    model = _make_model(x_studio_wanna=True)
    conn = _make_conn([model], [], [])
    result = render(conn)
    assert "## Wanted — No Listings Tracked" in result


def test_render_wanted_model_with_no_watching_listed_in_alert() -> None:
    model = _make_model(id=1, x_name="ES-335", x_studio_wanna=True)
    conn = _make_conn([model], [], [])
    result = render(conn)
    assert "ES-335" in result.split("## Wanted")[1].split("## Full Catalog")[0]


def test_render_wanted_model_with_watching_listing_not_in_alert() -> None:
    model = _make_model(id=1, x_name="ES-335", x_studio_wanna=True)
    watching = {"id": 10, "x_model_id": [1, "ES-335"]}
    conn = _make_conn([model], [], [watching])
    result = render(conn)
    alert_section = result.split("## Wanted")[1].split("## Full Catalog")[0]
    assert "ES-335" not in alert_section


def test_render_no_wanted_models_shows_placeholder() -> None:
    model = _make_model(x_studio_wanna=False)
    conn = _make_conn([model], [], [])
    result = render(conn)
    assert "All wanted models have at least one watching listing." in result


def test_render_gear_counts_aggregated_correctly() -> None:
    model = _make_model(id=1)
    gear1 = {"id": 10, "x_model_id": [1, "Les Paul Standard"], "x_status": "owned"}
    gear2 = {"id": 11, "x_model_id": [1, "Les Paul Standard"], "x_status": "owned"}
    gear3 = {"id": 12, "x_model_id": [1, "Les Paul Standard"], "x_status": "sold"}
    conn = _make_conn([model], [gear1, gear2, gear3], [])
    result = render(conn)
    assert "2 owned" in result
    assert "1 sold" in result


def test_render_watching_count_aggregated_correctly() -> None:
    model = _make_model(id=1)
    listing1 = {"id": 20, "x_model_id": [1, "Les Paul Standard"]}
    listing2 = {"id": 21, "x_model_id": [1, "Les Paul Standard"]}
    conn = _make_conn([model], [], [listing1, listing2])
    result = render(conn)
    assert "2 watching listings" in result


def test_render_gear_from_other_model_not_counted() -> None:
    model_a = _make_model(id=1, x_name="Les Paul")
    model_b = _make_model(id=2, x_name="SG Standard", x_studio_partner_id=[38, "Gibson"])
    gear_for_b = {"id": 99, "x_model_id": [2, "SG Standard"], "x_status": "owned"}
    conn = _make_conn([model_a, model_b], [gear_for_b], [])
    result = render(conn)
    # Les Paul section should show 0 owned
    lp_section = result.split("### Les Paul")[1].split("### SG Standard")[0]
    assert "0 owned" in lp_section
    # SG section should show 1 owned
    sg_section = result.split("### SG Standard")[1]
    assert "1 owned" in sg_section


def test_render_model_name_in_full_catalog() -> None:
    model = _make_model(x_name="Flying V")
    conn = _make_conn([model], [], [])
    result = render(conn)
    full_catalog = result.split("## Full Catalog")[1]
    assert "### Flying V" in full_catalog


def test_render_bulk_gear_query_uses_all_model_ids() -> None:
    model_a = _make_model(id=5)
    model_b = _make_model(id=7, x_name="SG")
    conn = _make_conn([model_a, model_b], [], [])
    render(conn)
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    model_id_filter = next(d for d in domain if d[0] == "x_model_id")
    assert set(model_id_filter[2]) == {5, 7}


def test_render_bulk_listing_query_filters_watching_status() -> None:
    model = _make_model(id=3)
    conn = _make_conn([model], [], [])
    render(conn)
    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    assert ("x_status", "=", "watching") in domain
