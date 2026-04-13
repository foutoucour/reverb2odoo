"""Tests for odoo_mcp/brand_cache.py — parse_readme_brands() and get_brands()."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

import odoo_mcp.brand_cache as bc
from odoo_mcp.brand_cache import get_brands, parse_readme_brands

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_README = """\
# Awesome Single-Cut Guitars

Preamble text.

## Brand: Gibson

web: https://gibson.com/
made_in: 🇺🇸
price_range: 💰💰💰
single_cut_models: Les Paul
"""


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level cache before and after each test."""
    bc._cache = []
    bc._fetched_at = None
    yield
    bc._cache = []
    bc._fetched_at = None


# ── parse_readme_brands ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected_name",
    [
        pytest.param(SAMPLE_README, "Gibson", id="extracts-gibson-name"),
    ],
)
def test_parse_readme_brands_extracts_name(text: str, expected_name: str):
    """parse_readme_brands() extracts brand name from ## Brand: header."""
    brands = parse_readme_brands(text)
    assert len(brands) >= 1
    assert brands[0]["name"] == expected_name


@pytest.mark.parametrize(
    "text, expected_made_in",
    [
        pytest.param(SAMPLE_README, "🇺🇸", id="extracts-made-in-flag"),
    ],
)
def test_parse_readme_brands_extracts_made_in(text: str, expected_made_in: str):
    """parse_readme_brands() extracts made_in value from brand section."""
    brands = parse_readme_brands(text)
    assert brands[0]["made_in"] == expected_made_in


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "## Brand: NoBrand\n\nweb: https://example.com/\n",
            id="brand-without-made-in",
        ),
    ],
)
def test_parse_readme_brands_none_when_missing(text: str):
    """parse_readme_brands() returns made_in=None when the field is absent."""
    brands = parse_readme_brands(text)
    assert len(brands) == 1
    assert brands[0]["made_in"] is None


# ── get_brands — cache behaviour ──────────────────────────────────────────────


def test_get_brands_uses_cache_when_fresh():
    """get_brands() returns cached data without an HTTP call when cache is fresh."""
    bc._cache = [{"name": "test"}]
    bc._fetched_at = datetime.now(UTC)

    conn = MagicMock()

    with patch("odoo_mcp.brand_cache.httpx.get") as mock_http:
        result = get_brands(conn)

    mock_http.assert_not_called()
    assert result == [{"name": "test"}]


# ── Merge logic — Odoo-only brand ─────────────────────────────────────────────


def test_get_brands_odoo_only_brand_has_no_readme_fields():
    """Brand in Odoo but absent from README → partial record with made_in=None."""
    fender_partner = {
        "id": 7,
        "name": "Fender",
        "x_studio_average_price": None,
        "country_id": False,
        "website": None,
        "category_id": [],
    }

    conn = MagicMock()
    model_mock = MagicMock()
    model_mock.search_read.return_value = [fender_partner]
    conn.get_model.return_value = model_mock

    # README contains only Gibson — Fender is absent.
    with patch("odoo_mcp.brand_cache.httpx.get") as mock_http:
        response_mock = MagicMock()
        response_mock.text = SAMPLE_README
        mock_http.return_value = response_mock

        result = get_brands(conn)

    fender = next(b for b in result if b["name"] == "Fender")
    assert fender["odoo_id"] == 7
    assert fender["made_in"] is None
    assert fender["price_range"] is None
    assert fender["single_cut_models"] is None
    assert fender["description"] is None
