"""MCP resource: render the brand catalog as markdown.

Fetches merged brand data from brand_cache and formats it as a markdown
document grouped by res.partner category, suitable for LLM context windows.

Guitar-maker brands (any category containing "guitar", case-insensitive)
show: country, made_in, price_range, single_cut_models, average_price,
description.

Non-guitar brands show: country, average_price only.

Brands that exist in Odoo but not in the README render without README fields
(no error raised).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from odoo_mcp import brand_cache

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_UNCATEGORIZED = "Uncategorized"


def _is_guitar_brand(categories: list[str]) -> bool:
    """Return True if any category name contains the word 'guitar' (case-insensitive)."""
    return any("guitar" in cat.lower() for cat in categories)


def _group_by_category(brands: list[dict]) -> dict[str, list[dict]]:
    """Build a mapping of category name → list of brands.

    A brand with multiple categories appears under each category.
    Brands with no categories fall into 'Uncategorized'.
    """
    grouped: dict[str, list[dict]] = {}

    for brand in brands:
        categories = brand.get("categories") or []

        if not categories:
            grouped.setdefault(_UNCATEGORIZED, []).append(brand)
            continue

        for category in categories:
            grouped.setdefault(category, []).append(brand)

    return grouped


def _render_guitar_brand(brand: dict) -> list[str]:
    """Render a guitar-maker brand block. Returns a list of non-empty lines."""
    lines: list[str] = [f"### {brand['name']}"]

    # First detail line: country | made_in | price_range (omit absent fields)
    detail_parts: list[str] = []
    if brand.get("country"):
        detail_parts.append(f"Country: {brand['country']}")
    if brand.get("made_in"):
        detail_parts.append(f"Made in: {brand['made_in']}")
    if brand.get("price_range"):
        detail_parts.append(f"Price range: {brand['price_range']}")
    if detail_parts:
        lines.append(" | ".join(detail_parts))

    if brand.get("single_cut_models"):
        lines.append(f"Models: {brand['single_cut_models']}")

    if brand.get("average_price"):
        lines.append(f"Avg price: {brand['average_price']}")

    if brand.get("description"):
        lines.append(brand["description"])

    return lines


def _render_non_guitar_brand(brand: dict) -> list[str]:
    """Render a non-guitar brand block. Returns a list of non-empty lines."""
    lines: list[str] = [f"### {brand['name']}"]

    detail_parts: list[str] = []
    if brand.get("country"):
        detail_parts.append(f"Country: {brand['country']}")
    if brand.get("average_price"):
        detail_parts.append(f"Avg price: {brand['average_price']}")
    if detail_parts:
        lines.append(" | ".join(detail_parts))

    return lines


def _render_brand(brand: dict) -> str:
    """Render a single brand as a markdown block."""
    categories = brand.get("categories") or []
    if _is_guitar_brand(categories):
        lines = _render_guitar_brand(brand)
    else:
        lines = _render_non_guitar_brand(brand)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render(conn: Any) -> str:
    """Return a markdown string with the brand catalog grouped by category.

    Parameters
    ----------
    conn:
        An authenticated Odoo connection (odoolib or compatible).

    Returns
    -------
    str
        Formatted markdown document with one H2 section per category.
    """
    logger.info("Rendering brand catalog resource")
    brands = brand_cache.get_brands(conn)
    logger.debug("Got {} brand(s) from cache", len(brands))

    grouped = _group_by_category(brands)
    logger.debug("Grouped into {} category section(s)", len(grouped))

    sections: list[str] = ["# Brand Catalog"]

    for category, category_brands in sorted(grouped.items()):
        sections.append(f"\n## {category}\n")
        for brand in sorted(category_brands, key=lambda b: b["name"].lower()):
            sections.append(_render_brand(brand))

    return "\n".join(sections)
