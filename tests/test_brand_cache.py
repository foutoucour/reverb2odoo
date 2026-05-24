"""Tests for odoo_mcp/brand_cache.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

import odoo_mcp.brand_cache as brand_cache
from odoo_mcp.brand_cache import get_brands, parse_readme_brands

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_README = """\
# Awesome Single-Cut Guitars

Some preamble text.

## Brand: Collings

id: brand::collings

web: https://collingsguitars.com/electrics-category/solid-body/
brand_type: major
country: 🇺🇸
made_in: 🇺🇸
single_cut_models: City Limits series
finish: Poly & Nitro
price_range: 💰💰💰

description:
Single-cut model(s): City Limits series.
Great build quality.

## Brand: Novo

id: brand::novo

web: https://novoguitars.com/
made_in: 🇺🇸
price_range: 💰💰💰💰

description:
Boutique builder.
"""

SAMPLE_README_NO_DESCRIPTION = """\
## Brand: MiniBrand

web: https://example.com/
made_in: 🇨🇦
price_range: 💰
"""


# ── parse_readme_brands ───────────────────────────────────────────────────────


def test_parse_readme_brands_returns_correct_count():
    brands = parse_readme_brands(SAMPLE_README)
    assert len(brands) == 2


@pytest.mark.parametrize(
    "index, field, expected",
    [
        pytest.param(0, "name", "Collings", id="collings-name"),
        pytest.param(
            0,
            "web",
            "https://collingsguitars.com/electrics-category/solid-body/",
            id="collings-web",
        ),
        pytest.param(0, "made_in", "🇺🇸", id="collings-made_in"),
        pytest.param(0, "price_range", "💰💰💰", id="collings-price_range"),
        pytest.param(0, "single_cut_models", "City Limits series", id="collings-single_cut_models"),
        pytest.param(1, "name", "Novo", id="novo-name"),
        pytest.param(1, "web", "https://novoguitars.com/", id="novo-web"),
        pytest.param(1, "made_in", "🇺🇸", id="novo-made_in"),
        pytest.param(1, "price_range", "💰💰💰💰", id="novo-price_range"),
        pytest.param(1, "single_cut_models", None, id="novo-single_cut_models-none"),
    ],
)
def test_parse_readme_brands_fields(index: int, field: str, expected):
    brands = parse_readme_brands(SAMPLE_README)
    assert brands[index][field] == expected


def test_parse_readme_brands_description_collings():
    brands = parse_readme_brands(SAMPLE_README)
    assert "City Limits series" in brands[0]["description"]
    assert "Great build quality" in brands[0]["description"]


def test_parse_readme_brands_description_novo():
    brands = parse_readme_brands(SAMPLE_README)
    assert "Boutique builder" in brands[1]["description"]


def test_parse_readme_brands_no_description():
    brands = parse_readme_brands(SAMPLE_README_NO_DESCRIPTION)
    assert len(brands) == 1
    assert brands[0]["description"] is None


def test_parse_readme_brands_empty_text():
    brands = parse_readme_brands("")
    assert brands == []


def test_parse_readme_brands_no_brand_sections():
    brands = parse_readme_brands("# Just a title\n\nSome text with no brand sections.")
    assert brands == []


# ── get_brands — cache behaviour ──────────────────────────────────────────────


def _make_conn(partners: list[dict] | None = None) -> MagicMock:
    """Return a mock conn whose res.partner model returns `partners`."""
    if partners is None:
        partners = []
    conn = MagicMock()
    model = MagicMock()
    model.search_read.return_value = partners
    conn.get_model.return_value = model
    return conn


def _reset_cache() -> None:
    """Reset module-level cache to force a fresh fetch."""
    brand_cache._cache = []
    brand_cache._fetched_at = None


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure each test starts with a cold cache."""
    _reset_cache()
    yield
    _reset_cache()


def test_get_brands_fetches_readme_on_cold_cache():
    conn = _make_conn()
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README) as mock_fetch:
        result = get_brands(conn)
    mock_fetch.assert_called_once()
    # README-only brands have odoo_id=None
    assert any(b["odoo_id"] is None for b in result)


def test_get_brands_uses_cache_on_second_call():
    conn = _make_conn()
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README) as mock_fetch:
        get_brands(conn)
        get_brands(conn)
    # Second call must not re-fetch
    assert mock_fetch.call_count == 1


def test_get_brands_refreshes_after_ttl_expired():
    conn = _make_conn()
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README) as mock_fetch:
        get_brands(conn)
        # Wind the clock back past the TTL
        brand_cache._fetched_at = datetime.now(tz=UTC) - timedelta(days=31)
        get_brands(conn)
    assert mock_fetch.call_count == 2


def test_get_brands_within_ttl_does_not_refresh():
    conn = _make_conn()
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README) as mock_fetch:
        get_brands(conn)
        brand_cache._fetched_at = datetime.now(tz=UTC) - timedelta(days=29)
        get_brands(conn)
    assert mock_fetch.call_count == 1


# ── Merge logic ───────────────────────────────────────────────────────────────


def _odoo_partner(
    name: str,
    odoo_id: int = 1,
    country: list | bool = False,
    categories: list | None = None,
    website: str | None = None,
    average_price: str | None = None,
) -> dict:
    return {
        "id": odoo_id,
        "name": name,
        "x_studio_average_price": average_price,
        "country_id": country,
        "website": website,
        "category_id": categories or [],
    }


def test_get_brands_odoo_only_partner_has_no_readme_fields():
    """Brand exists in Odoo only → made_in, price_range, single_cut_models, description are None."""
    partners = [_odoo_partner("UnknownBrand", odoo_id=99)]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    unknown = next(b for b in result if b["name"] == "UnknownBrand")
    assert unknown["odoo_id"] == 99
    assert unknown["made_in"] is None
    assert unknown["price_range"] is None
    assert unknown["single_cut_models"] is None
    assert unknown["description"] is None


def test_get_brands_readme_only_brand_has_no_odoo_id():
    """Brand exists in README only → odoo_id is None."""
    # Provide an Odoo partner that does NOT match any README brand
    partners = [_odoo_partner("SomeOtherBrand", odoo_id=5)]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    readme_only = [b for b in result if b["odoo_id"] is None]
    assert len(readme_only) == 2  # Collings + Novo are not in Odoo
    names = {b["name"] for b in readme_only}
    assert "Collings" in names
    assert "Novo" in names


def test_get_brands_merged_brand_has_both_odoo_and_readme_fields():
    """Brand exists in both Odoo and README → all fields populated."""
    partners = [
        _odoo_partner(
            "Collings",
            odoo_id=10,
            country=[1, "United States"],
            categories=[[7, "Boutique"]],
            website="https://collingsguitars.com/",
            average_price="$3,500",
        )
    ]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    collings = next(b for b in result if b["name"] == "Collings")
    assert collings["odoo_id"] == 10
    assert collings["country"] == "United States"
    assert collings["categories"] == ["Boutique"]
    assert collings["average_price"] == "$3,500"
    assert collings["made_in"] == "🇺🇸"
    assert collings["price_range"] == "💰💰💰"
    assert "City Limits" in collings["single_cut_models"]
    assert collings["description"] is not None


def test_get_brands_categories_extracted_from_many2many():
    partners = [
        _odoo_partner(
            "Novo",
            odoo_id=20,
            categories=[[1, "Boutique"], [2, "USA Made"]],
        )
    ]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    novo = next(b for b in result if b["name"] == "Novo")
    assert set(novo["categories"]) == {"Boutique", "USA Made"}


def test_get_brands_country_none_when_false():
    """country_id = False (Odoo null) → country must be None."""
    partners = [_odoo_partner("Collings", odoo_id=11, country=False)]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    collings = next(b for b in result if b["name"] == "Collings")
    assert collings["country"] is None


def test_get_brands_case_insensitive_name_match():
    """Odoo name 'collings' (lowercase) must match README 'Collings'."""
    partners = [_odoo_partner("collings", odoo_id=15)]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    matched = next(b for b in result if b["odoo_id"] == 15)
    assert matched["made_in"] == "🇺🇸"


def test_get_brands_website_falls_back_to_readme_web_when_odoo_has_none():
    partners = [_odoo_partner("Collings", odoo_id=12, website=None)]
    conn = _make_conn(partners)
    with patch("odoo_mcp.brand_cache._fetch_readme", return_value=SAMPLE_README):
        result = get_brands(conn)

    collings = next(b for b in result if b["name"] == "Collings")
    assert collings["website"] == "https://collingsguitars.com/electrics-category/solid-body/"
