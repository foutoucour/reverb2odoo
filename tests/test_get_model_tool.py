"""Tests for odoo_mcp/tools/get_model.py."""

from unittest.mock import MagicMock

import pytest

from models import GearRecord, ListingRecord, ModelsRecord
from odoo_mcp.tools.get_model import (
    _label,
    _render_gear_section,
    _render_listing_section,
    _render_model_spec,
    _scalar,
    run,
)

# ---------------------------------------------------------------------------
# _label / _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param((1, "Gibson"), "Gibson", id="valid-m2o"),
        pytest.param(None, "", id="none-m2o"),
    ],
)
def test_label(field: object, expected: str) -> None:
    assert _label(field) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param("solidbody", "solidbody", id="string"),
        pytest.param(False, "", id="false"),
        pytest.param(None, "", id="none"),
    ],
)
def test_scalar(value: object, expected: str) -> None:
    assert _scalar(value) == expected


# ---------------------------------------------------------------------------
# _render_model_spec
# ---------------------------------------------------------------------------


def _model_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 10,
        "x_name": "Les Paul Standard",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_model_type": "solidbody",
        "x_studio_wanna": True,
        "x_studio_guitar_familly_ids": False,
        "x_studio_guitar_neck_feel_id": [1, "SlimTaper"],
        "x_studio_scale": "24.75",
        "x_studio_finish": [2, "Gloss"],
        "x_studio_fretboard_1": [3, "Rosewood"],
        "x_price_p25": 1800.0,
        "x_price_p50": 2200.0,
        "x_price_p75": 2700.0,
        "x_studio_weighted_tag_ids": [],
        "x_studio_weighted_score": False,
    }
    base.update(overrides)
    return base


def _make_model(**overrides: object) -> ModelsRecord:
    return ModelsRecord.from_odoo(_model_dict(**overrides))


def test_render_model_spec_name_and_brand_in_header() -> None:
    model = _make_model()
    result = _render_model_spec(model, [])
    assert "# Les Paul Standard — Gibson" in result


def test_render_model_spec_wanna_yes() -> None:
    model = _make_model(x_studio_wanna=True)
    result = _render_model_spec(model, [])
    assert "**Wanna**: yes" in result


def test_render_model_spec_wanna_no() -> None:
    model = _make_model(x_studio_wanna=False)
    result = _render_model_spec(model, [])
    assert "**Wanna**: no" in result


def test_render_model_spec_too_expensive_yes() -> None:
    model = _make_model(x_studio_too_expensive=True)
    result = _render_model_spec(model, [])
    assert "**Too expensive**: yes" in result


def test_render_model_spec_too_expensive_no() -> None:
    model = _make_model(x_studio_too_expensive=False)
    result = _render_model_spec(model, [])
    assert "**Too expensive**: no" in result


def test_render_model_spec_price_brackets() -> None:
    model = _make_model()
    result = _render_model_spec(model, [])
    assert "p25=1800.0" in result
    assert "p50=2200.0" in result
    assert "p75=2700.0" in result


def test_render_model_spec_scale_neck_fretboard() -> None:
    model = _make_model()
    result = _render_model_spec(model, [])
    assert "24.75" in result
    assert "SlimTaper" in result
    assert "Rosewood" in result


def test_render_model_spec_omits_family_when_empty() -> None:
    model = _make_model(x_studio_guitar_familly_ids=False)
    result = _render_model_spec(model, [])
    assert "**Construction**" not in result


def test_render_model_spec_shows_family_when_provided() -> None:
    model = _make_model()
    result = _render_model_spec(model, ["Set neck", "Carved top"])
    assert "**Construction**: Set neck, Carved top" in result


def test_render_model_spec_shows_weighted_score_when_present() -> None:
    model = _make_model(x_studio_weighted_score=42)
    result = _render_model_spec(model, [])
    assert "**Weighted score**: 42" in result


def test_render_model_spec_omits_weighted_score_when_absent() -> None:
    model = _make_model(x_studio_weighted_score=False)
    result = _render_model_spec(model, [])
    assert "**Weighted score**" not in result


def test_render_model_spec_shows_tags_when_provided() -> None:
    model = _make_model()
    result = _render_model_spec(model, [], tag_labels=["Figured maple (score=5)", "Lightweight"])
    assert "**Tags**: Figured maple (score=5), Lightweight" in result


def test_render_model_spec_omits_tags_when_absent() -> None:
    model = _make_model()
    result = _render_model_spec(model, [], tag_labels=[])
    assert "**Tags**" not in result


# ---------------------------------------------------------------------------
# _render_gear_section
# ---------------------------------------------------------------------------


def _gear_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "2021 Gibson Les Paul",
        "x_status": "owned",
        "x_studio_current_condition": "excellent",
        "x_intent": "keeper",
        "x_model_id": [10, "Les Paul Standard"],
        "x_studio_notes": False,
        "x_studio_lsting_ids": [],
    }
    base.update(overrides)
    return base


def _make_gear(**overrides: object) -> GearRecord:
    return GearRecord.from_odoo(_gear_dict(**overrides))


def test_render_gear_section_empty_returns_none_recorded() -> None:
    result = _render_gear_section([])
    assert "*None recorded*" in result


def test_render_gear_section_shows_gear_name_and_id() -> None:
    gear = _make_gear(id=42)
    result = _render_gear_section([gear])
    assert "2021 Gibson Les Paul" in result
    assert "id=42" in result


def test_render_gear_section_groups_by_status() -> None:
    gear1 = _make_gear(id=1, x_status="owned", x_name="Gear A")
    gear2 = _make_gear(id=2, x_status="watching", x_name="Gear B")
    result = _render_gear_section([gear1, gear2])
    assert "### owned" in result
    assert "### watching" in result


def test_render_gear_section_shows_condition_and_intent() -> None:
    gear = _make_gear(x_studio_current_condition="good", x_intent="flip")
    result = _render_gear_section([gear])
    assert "Condition: good" in result
    assert "Intent: flip" in result


# ---------------------------------------------------------------------------
# _render_listing_section
# ---------------------------------------------------------------------------


def _listing_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 100,
        "x_name": "Les Paul Standard",
        "x_model_id": [10, "Les Paul Standard"],
        "x_url": "https://reverb.com/item/12345",
        "x_platform": "reverb",
        "x_price": 2500.0,
        "x_currency_id": [1, "CAD"],
        "x_shipping": 50.0,
        "x_condition": "excellent",
        "x_status": "watching",
        "x_is_available": True,
        "x_can_accept_offers": False,
        "x_is_taxed": False,
        "x_published_at": "2025-01-15",
        "x_gear_id": False,
        "x_studio_listing_score": 80,
        "x_studio_price_score": 75,
        "x_studio_notes": False,
    }
    base.update(overrides)
    return base


def _make_listing(**overrides: object) -> ListingRecord:
    return ListingRecord.from_odoo(_listing_dict(**overrides))


def test_render_listing_section_empty_returns_none_recorded() -> None:
    result = _render_listing_section([])
    assert "*None recorded*" in result


def test_render_listing_section_groups_by_status() -> None:
    l1 = _make_listing(x_status="watching")
    l2 = _make_listing(x_status="passed")
    result = _render_listing_section([l1, l2])
    assert "### watching" in result
    assert "### passed" in result


def test_render_listing_section_shows_price_and_platform() -> None:
    listing = _make_listing()
    result = _render_listing_section([listing])
    assert "2500.0 CAD" in result
    assert "reverb" in result


def test_render_listing_section_shows_url() -> None:
    listing = _make_listing()
    result = _render_listing_section([listing])
    assert "https://reverb.com/item/12345" in result


def test_render_listing_section_shows_scores_when_present() -> None:
    listing = _make_listing(x_studio_listing_score=90, x_studio_price_score=85)
    result = _render_listing_section([listing])
    assert "listing=90" in result
    assert "price=85" in result


def test_render_listing_section_omits_scores_when_absent() -> None:
    listing = _make_listing(x_studio_listing_score=False, x_studio_price_score=False)
    result = _render_listing_section([listing])
    assert "scores:" not in result


# ---------------------------------------------------------------------------
# run — integration
# ---------------------------------------------------------------------------


def _make_conn(
    *,
    model_records: list[dict] | None = None,
    gear_records: list[dict] | None = None,
    listing_records: list[dict] | None = None,
    family_records: list[dict] | None = None,
    tag_records: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    models_proxy = MagicMock()
    gear_proxy = MagicMock()
    listing_proxy = MagicMock()
    family_proxy = MagicMock()
    tag_proxy = MagicMock()

    models_proxy.search_read.return_value = model_records or []
    gear_proxy.search_read.return_value = gear_records or []
    listing_proxy.search_read.return_value = listing_records or []
    family_proxy.search_read.return_value = family_records or []
    tag_proxy.search_read.return_value = tag_records or []

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        if name == "x_gear":
            return gear_proxy
        if name == "x_listing":
            return listing_proxy
        if name == "x_guitar_familly":
            return family_proxy
        if name == "x_weighted_tags":
            return tag_proxy
        raise ValueError(f"Unexpected model: {name}")

    conn.get_model.side_effect = get_model
    return conn


def test_run_not_found_returns_notice() -> None:
    conn = _make_conn(model_records=[])
    result = run(conn, "Nonexistent")
    assert "No model found" in result


def test_run_numeric_id_uses_id_domain() -> None:
    model = _model_dict()
    conn = _make_conn(model_records=[model])
    run(conn, "10")
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert ("id", "=", 10) in domain


def test_run_name_string_uses_ilike_domain() -> None:
    model = _model_dict()
    conn = _make_conn(model_records=[model])
    run(conn, "Les Paul")
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert ("x_name", "ilike", "Les Paul") in domain


def test_run_queries_gear_by_model_id() -> None:
    model = _model_dict(id=10)
    conn = _make_conn(model_records=[model])
    run(conn, "Les Paul")
    gear_proxy = conn.get_model("x_gear")
    domain = gear_proxy.search_read.call_args[0][0]
    assert ("x_model_id", "=", 10) in domain


def test_run_queries_listings_by_model_id() -> None:
    model = _model_dict(id=10)
    conn = _make_conn(model_records=[model])
    run(conn, "Les Paul")
    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    assert ("x_model_id", "=", 10) in domain


def test_run_output_contains_model_name() -> None:
    model = _model_dict()
    conn = _make_conn(model_records=[model])
    result = run(conn, "Les Paul")
    assert "Les Paul Standard" in result


def test_run_output_contains_gear_section() -> None:
    model = _model_dict()
    gear = _gear_dict()
    conn = _make_conn(model_records=[model], gear_records=[gear])
    result = run(conn, "Les Paul")
    assert "## Gear Instances" in result
    assert "2021 Gibson Les Paul" in result


def test_run_output_contains_listing_section() -> None:
    model = _model_dict()
    listing = _listing_dict()
    conn = _make_conn(model_records=[model], listing_records=[listing])
    result = run(conn, "Les Paul")
    assert "## Listings" in result


def test_run_resolves_and_renders_linked_tags() -> None:
    model = _model_dict(x_studio_weighted_tag_ids=[10])
    tag = {
        "id": 10,
        "x_name": "Figured maple",
        "x_studio_score": 5,
        "x_studio_weighted_tag_group_id": [1, "Top Quality"],
        "x_studio_model_ids": [10],
    }
    conn = _make_conn(model_records=[model], tag_records=[tag])
    result = run(conn, "Les Paul")
    assert "**Tags**" in result
    assert "Figured maple (score=5)" in result


def test_run_strips_whitespace_from_name_or_id() -> None:
    model = _model_dict()
    conn = _make_conn(model_records=[model])
    run(conn, "  42  ")
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert ("id", "=", 42) in domain
