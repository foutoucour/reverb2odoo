"""Tests for odoo_mcp/resources/brands.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from odoo_mcp.resources import brands

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _brand(
    name: str,
    categories: list[str] | None = None,
    country: str | None = None,
    made_in: str | None = None,
    price_range: str | None = None,
    single_cut_models: str | None = None,
    average_price: str | None = None,
    description: str | None = None,
    odoo_id: int | None = 1,
    website: str | None = None,
) -> dict:
    """Build a brand dict with sensible defaults."""
    return {
        "name": name,
        "odoo_id": odoo_id,
        "average_price": average_price,
        "country": country,
        "website": website,
        "categories": categories or [],
        "made_in": made_in,
        "price_range": price_range,
        "single_cut_models": single_cut_models,
        "description": description,
    }


# ---------------------------------------------------------------------------
# _is_guitar_brand
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "categories, expected",
    [
        pytest.param(["Guitar Makers", "Boutique"], True, id="exact-guitar-makers"),
        pytest.param(["guitar"], True, id="lowercase-guitar"),
        pytest.param(["GUITAR MAKERS"], True, id="uppercase-guitar"),
        pytest.param(["Boutique", "Amp Builders"], False, id="no-guitar-category"),
        pytest.param([], False, id="empty-categories"),
    ],
)
def test_is_guitar_brand(categories: list[str], expected: bool) -> None:
    assert brands._is_guitar_brand(categories) == expected


# ---------------------------------------------------------------------------
# _group_by_category
# ---------------------------------------------------------------------------


def test_group_by_category_single_category() -> None:
    b = _brand("Collings", categories=["Guitar Makers"])
    result = brands._group_by_category([b])
    assert list(result.keys()) == ["Guitar Makers"]
    assert result["Guitar Makers"] == [b]


def test_group_by_category_multiple_categories() -> None:
    b = _brand("PRS", categories=["Guitar Makers", "Boutique"])
    result = brands._group_by_category([b])
    assert "Guitar Makers" in result
    assert "Boutique" in result
    assert result["Guitar Makers"] == [b]
    assert result["Boutique"] == [b]


def test_group_by_category_no_categories_goes_to_uncategorized() -> None:
    b = _brand("Mystery Brand", categories=[])
    result = brands._group_by_category([b])
    assert brands._UNCATEGORIZED in result
    assert result[brands._UNCATEGORIZED] == [b]


def test_group_by_category_mixed() -> None:
    guitar = _brand("Gibson", categories=["Guitar Makers"])
    pedal = _brand("Strymon", categories=["Pedal Builders"])
    no_cat = _brand("Unknown", categories=[])
    result = brands._group_by_category([guitar, pedal, no_cat])
    assert set(result.keys()) == {"Guitar Makers", "Pedal Builders", brands._UNCATEGORIZED}


# ---------------------------------------------------------------------------
# _render_brand — guitar brands
# ---------------------------------------------------------------------------


def test_render_guitar_brand_all_fields() -> None:
    b = _brand(
        "Collings",
        categories=["Guitar Makers"],
        country="USA",
        made_in="Austin, TX",
        price_range="$3,000–$6,000",
        single_cut_models="290, 360",
        average_price="$4,500",
        description="Premium acoustic and electric guitars.",
    )
    output = brands._render_brand(b)
    assert "### Collings" in output
    assert "Country: USA" in output
    assert "Made in: Austin, TX" in output
    assert "Price range: $3,000–$6,000" in output
    assert "Models: 290, 360" in output
    assert "Avg price: $4,500" in output
    assert "Premium acoustic and electric guitars." in output


def test_render_guitar_brand_omits_none_fields() -> None:
    b = _brand(
        "Collings",
        categories=["Guitar Makers"],
        country="USA",
        # made_in, price_range, single_cut_models, average_price, description all None
    )
    output = brands._render_brand(b)
    assert "Made in" not in output
    assert "Price range" not in output
    assert "Models:" not in output
    assert "Avg price" not in output


def test_render_guitar_brand_odoo_only_no_readme_fields() -> None:
    """Brand in Odoo but not README: renders without README fields, no error."""
    b = _brand(
        "NewBrand",
        categories=["Guitar Makers"],
        country="Canada",
        made_in=None,
        price_range=None,
        single_cut_models=None,
        average_price=None,
        description=None,
    )
    output = brands._render_brand(b)
    assert "### NewBrand" in output
    assert "Country: Canada" in output
    assert "Made in" not in output


# ---------------------------------------------------------------------------
# _render_brand — non-guitar brands
# ---------------------------------------------------------------------------


def test_render_non_guitar_brand_shows_country_and_avg_price() -> None:
    b = _brand(
        "Strymon",
        categories=["Pedal Builders"],
        country="USA",
        average_price="$350",
        description="Effects pedals — should not appear.",
        made_in="California",
    )
    output = brands._render_brand(b)
    assert "### Strymon" in output
    assert "Country: USA" in output
    assert "Avg price: $350" in output
    # Non-guitar fields must be absent
    assert "Made in" not in output
    assert "Price range" not in output
    assert "Models:" not in output
    assert "Effects pedals" not in output


def test_render_non_guitar_brand_omits_none_fields() -> None:
    b = _brand("Strymon", categories=["Pedal Builders"])
    output = brands._render_brand(b)
    assert "Country" not in output
    assert "Avg price" not in output


# ---------------------------------------------------------------------------
# render() — integration-level (brand_cache patched)
# ---------------------------------------------------------------------------


def _make_conn() -> MagicMock:
    return MagicMock()


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_returns_markdown_header(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = []
    conn = _make_conn()
    result = brands.render(conn)
    assert result.startswith("# Brand Catalog")
    mock_get_brands.assert_called_once_with(conn)


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_one_category_section(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = [
        _brand("Gibson", categories=["Guitar Makers"], country="USA"),
    ]
    result = brands.render(_make_conn())
    assert "## Guitar Makers" in result
    assert "### Gibson" in result


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_categories_sorted_alphabetically(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = [
        _brand("Zoom", categories=["Zoom Cat"]),
        _brand("Alpha", categories=["Alpha Cat"]),
    ]
    result = brands.render(_make_conn())
    alpha_pos = result.index("## Alpha Cat")
    zoom_pos = result.index("## Zoom Cat")
    assert alpha_pos < zoom_pos


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_brands_sorted_alphabetically_within_category(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = [
        _brand("Zephyr", categories=["Guitar Makers"]),
        _brand("Alamo", categories=["Guitar Makers"]),
    ]
    result = brands.render(_make_conn())
    alamo_pos = result.index("### Alamo")
    zephyr_pos = result.index("### Zephyr")
    assert alamo_pos < zephyr_pos


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_brand_in_multiple_categories_appears_in_each(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = [
        _brand("PRS", categories=["Guitar Makers", "Boutique"]),
    ]
    result = brands.render(_make_conn())
    assert "## Guitar Makers" in result
    assert "## Boutique" in result
    assert result.count("### PRS") == 2


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_uncategorized_brand(mock_get_brands: MagicMock) -> None:
    mock_get_brands.return_value = [
        _brand("Mystery", categories=[]),
    ]
    result = brands.render(_make_conn())
    assert f"## {brands._UNCATEGORIZED}" in result
    assert "### Mystery" in result


@patch("odoo_mcp.resources.brands.brand_cache.get_brands")
def test_render_non_guitar_brand_no_readme_fields_in_output(mock_get_brands: MagicMock) -> None:
    """Non-guitar brand should not expose made_in or description even if present."""
    mock_get_brands.return_value = [
        _brand(
            "Boss",
            categories=["Pedal Builders"],
            country="Japan",
            made_in="Japan factory",
            description="Famous pedal brand.",
            average_price="$120",
        ),
    ]
    result = brands.render(_make_conn())
    assert "Country: Japan" in result
    assert "Avg price: $120" in result
    assert "Made in" not in result
    assert "Famous pedal brand" not in result
