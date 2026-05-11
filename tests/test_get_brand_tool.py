"""Tests for odoo_mcp/tools/get_brand.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from odoo_mcp import brand_cache
from odoo_mcp.tools.get_brand import _find_brand, _render_linked_models, run


@pytest.fixture(autouse=True)
def reset_brand_cache():
    brand_cache._cache = []
    brand_cache._fetched_at = None
    yield
    brand_cache._cache = []
    brand_cache._fetched_at = None


# ── _find_brand ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "needle, expected_name",
    [
        pytest.param("Gibson", "Gibson", id="exact-match"),
        pytest.param("gibson", "Gibson", id="case-insensitive-exact"),
        pytest.param("gibs", "Gibson", id="substring-match"),
    ],
)
def test_find_brand_matches(needle: str, expected_name: str) -> None:
    brands = [{"name": "Gibson"}, {"name": "Fender"}]
    result = _find_brand(brands, needle)
    assert result is not None
    assert result["name"] == expected_name


def test_find_brand_prefers_exact_over_substring() -> None:
    brands = [
        {"name": "PRS Guitars"},  # substring match would catch this first
        {"name": "PRS"},
    ]
    result = _find_brand(brands, "PRS")
    assert result is not None
    assert result["name"] == "PRS"


def test_find_brand_returns_none_when_missing() -> None:
    brands = [{"name": "Gibson"}]
    assert _find_brand(brands, "Fender") is None


def test_find_brand_returns_none_when_empty_needle() -> None:
    brands = [{"name": "Gibson"}]
    assert _find_brand(brands, "  ") is None


# ── _render_linked_models ─────────────────────────────────────────────────────


def test_render_linked_models_empty_shows_no_records() -> None:
    result = _render_linked_models([])
    assert "No x_models records" in result


def test_render_linked_models_groups_wanted_and_other() -> None:
    models = [
        {"x_name": "Les Paul", "x_studio_wanna": True, "x_studio_p50": 2200.0},
        {"x_name": "SG", "x_studio_wanna": False, "x_studio_p50": 1500.0},
    ]
    result = _render_linked_models(models)
    assert "### Wanted" in result
    assert "### Other" in result
    assert "Les Paul" in result
    assert "SG" in result


def test_render_linked_models_shows_p50() -> None:
    models = [{"x_name": "Les Paul", "x_studio_wanna": True, "x_studio_p50": 2200.0}]
    result = _render_linked_models(models)
    assert "p50=2200.0" in result


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(models: list[dict] | None = None) -> MagicMock:
    conn = MagicMock()
    models_proxy = MagicMock()
    models_proxy.search_read.return_value = models or []
    conn.get_model.return_value = models_proxy
    return conn


def test_run_returns_not_found_when_brand_absent() -> None:
    with patch("odoo_mcp.tools.get_brand.brand_cache.get_brands", return_value=[]):
        conn = _make_conn()
        result = run(conn, "Gibson")
    assert "No brand found" in result


def test_run_returns_empty_input_message_when_name_blank() -> None:
    result = run(MagicMock(), "  ")
    assert "No brand name provided" in result


def test_run_returns_brand_card_when_found() -> None:
    brands = [
        {
            "name": "Gibson",
            "odoo_id": 38,
            "average_price": "$$$",
            "country": "USA",
            "website": "https://gibson.com",
            "categories": ["Guitar makers"],
            "made_in": "🇺🇸",
            "price_range": "💰💰💰",
            "single_cut_models": "Les Paul",
            "description": "Iconic American maker.",
        }
    ]
    with patch("odoo_mcp.tools.get_brand.brand_cache.get_brands", return_value=brands):
        conn = _make_conn(models=[])
        result = run(conn, "Gibson")
    assert "### Gibson" in result
    assert "USA" in result


def test_run_queries_models_by_partner_id() -> None:
    brands = [
        {
            "name": "Gibson",
            "odoo_id": 38,
            "average_price": None,
            "country": None,
            "website": None,
            "categories": ["Guitar makers"],
            "made_in": None,
            "price_range": None,
            "single_cut_models": None,
            "description": None,
        }
    ]
    with patch("odoo_mcp.tools.get_brand.brand_cache.get_brands", return_value=brands):
        conn = _make_conn(models=[])
        run(conn, "Gibson")
    domain = conn.get_model.return_value.search_read.call_args[0][0]
    assert ("x_studio_partner_id", "=", 38) in domain


def test_run_no_odoo_id_skips_model_query() -> None:
    brands = [
        {
            "name": "Tiny Maker",
            "odoo_id": None,
            "average_price": None,
            "country": None,
            "website": None,
            "categories": [],
            "made_in": None,
            "price_range": None,
            "single_cut_models": None,
            "description": None,
        }
    ]
    with patch("odoo_mcp.tools.get_brand.brand_cache.get_brands", return_value=brands):
        conn = _make_conn(models=[])
        result = run(conn, "Tiny Maker")
    assert "no `res.partner` entry" in result
    conn.get_model.assert_not_called()
