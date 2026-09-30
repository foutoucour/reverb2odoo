"""Tests for odoo_mcp/tools/search_listings.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models import ListingRecord
from odoo_mcp.tools.search_listings import _render_card, run

# ── _render_card ──────────────────────────────────────────────────────────────


def test_render_card_includes_model_and_url() -> None:
    listing = ListingRecord.from_odoo(
        {
            "id": 1,
            "x_model_id": [10, "Les Paul"],
            "x_price": 1800.0,
            "x_currency_id": [1, "CAD"],
            "x_platform": "reverb",
            "x_status": "watching",
            "x_studio_listing_score": 85,
            "x_url": "https://reverb.com/item/abc",
        }
    )
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


def test_render_card_includes_listing_id() -> None:
    listing = ListingRecord.from_odoo({"id": 4242, "x_model_id": [10, "Les Paul"]})
    assert "(id=4242)" in _render_card(listing)


@pytest.mark.parametrize(
    "is_candidate, too_expensive, expected, absent",
    [
        pytest.param(True, True, "| candidate, too_expensive", None, id="both-flags"),
        pytest.param(True, False, "| candidate", "too_expensive", id="candidate-only"),
        pytest.param(False, True, "| too_expensive", "candidate", id="too-expensive-only"),
    ],
)
def test_render_card_shows_triage_flags(
    is_candidate: bool, too_expensive: bool, expected: str, absent: str | None
) -> None:
    listing = ListingRecord.from_odoo(
        {
            "id": 1,
            "x_model_id": [10, "Les Paul"],
            "x_studio_is_candidate": is_candidate,
            "x_studio_model_id_too_expensive": too_expensive,
        }
    )
    result = _render_card(listing)
    assert expected in result
    if absent:
        assert absent not in result


def test_render_card_omits_flags_when_unset() -> None:
    listing = ListingRecord.from_odoo({"id": 1, "x_model_id": [10, "Les Paul"]})
    result = _render_card(listing)
    assert "candidate" not in result
    assert "too_expensive" not in result


@pytest.mark.parametrize(
    "kwargs, expected_clause",
    [
        pytest.param({"is_candidate": True}, ("x_studio_is_candidate", "=", True), id="cand-true"),
        pytest.param(
            {"is_candidate": False}, ("x_studio_is_candidate", "=", False), id="cand-false"
        ),
        pytest.param(
            {"too_expensive": True},
            ("x_studio_model_id_too_expensive", "=", True),
            id="too-expensive-true",
        ),
        pytest.param(
            {"too_expensive": False},
            ("x_studio_model_id_too_expensive", "=", False),
            id="too-expensive-false",
        ),
    ],
)
def test_run_applies_boolean_filters(kwargs: dict, expected_clause: tuple) -> None:
    conn = _make_conn(listings=[])
    run(conn, **kwargs)
    domain = conn.get_model("x_listing").search_read.call_args[0][0]
    assert expected_clause in domain


def test_run_boolean_filters_default_to_no_clause() -> None:
    conn = _make_conn(listings=[])
    run(conn)
    domain = conn.get_model("x_listing").search_read.call_args[0][0]
    fields = {clause[0] for clause in domain}
    assert "x_studio_is_candidate" not in fields
    assert "x_studio_model_id_too_expensive" not in fields
