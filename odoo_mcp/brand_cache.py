"""Brand cache — fetches GitHub README and merges with res.partner from Odoo.

Public interface (contract for brands.py):
    get_brands(conn) -> list[dict]

Each dict has keys:
    name: str
    odoo_id: int | None
    average_price: str | None
    country: str | None
    website: str | None
    categories: list[str]
    made_in: str | None
    price_range: str | None
    single_cut_models: str | None
    description: str | None
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

_README_URL = (
    "https://raw.githubusercontent.com/foutoucour/awesome-single-cut-guitars/main/README.md"
)
_TTL = timedelta(days=30)

# Module-level cache
_cache: list[dict] = []
_fetched_at: datetime | None = None


def parse_readme_brands(text: str) -> list[dict]:
    """Parse ``## Brand:`` sections from the README text.

    Returns one dict per brand with keys: name, web, made_in, price_range,
    single_cut_models, description.
    """
    brands: list[dict] = []

    # Split on the section header; first element is preamble — skip it.
    sections = text.split("## Brand:")
    for section in sections[1:]:
        lines = section.splitlines()
        if not lines:
            continue

        name = lines[0].strip()
        if not name:
            continue

        brand: dict[str, Any] = {
            "name": name,
            "web": None,
            "made_in": None,
            "price_range": None,
            "single_cut_models": None,
            "description": None,
        }

        description_lines: list[str] = []
        in_description = False

        for line in lines[1:]:
            if in_description:
                description_lines.append(line)
                continue

            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith("description:"):
                in_description = True
                # Anything after the colon on the same line is part of the description.
                rest = stripped[len("description:") :].strip()
                if rest:
                    description_lines.append(rest)
                continue

            if ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip().lower()
                value = value.strip()
                if key == "web":
                    brand["web"] = value or None
                elif key == "made_in":
                    brand["made_in"] = value or None
                elif key == "price_range":
                    brand["price_range"] = value or None
                elif key == "single_cut_models":
                    brand["single_cut_models"] = value or None

        if description_lines:
            brand["description"] = "\n".join(description_lines).strip() or None

        brands.append(brand)

    logger.debug("Parsed {} brands from README", len(brands))
    return brands


def _fetch_readme() -> str:
    """Fetch the README from GitHub and return its text."""
    logger.info("Fetching README from {}", _README_URL)
    response = httpx.get(_README_URL, follow_redirects=True, timeout=30)
    response.raise_for_status()
    return response.text


def _fetch_odoo_partners(conn: Any) -> list[dict]:
    """Fetch res.partner records that have at least one category."""
    model = conn.get_model("res.partner")
    partners: list[dict] = model.search_read(
        [("category_id", "!=", False)],
        ["id", "name", "x_studio_average_price", "country_id", "website", "category_id"],
    )
    logger.debug("Fetched {} Odoo partners with categories", len(partners))
    return partners


def _merge(readme_brands: list[dict], odoo_partners: list[dict]) -> list[dict]:
    """Merge README brands with Odoo partners by case-insensitive name match."""
    readme_by_name: dict[str, dict] = {b["name"].lower(): b for b in readme_brands}
    odoo_by_name: dict[str, dict] = {p["name"].lower(): p for p in odoo_partners}

    result: list[dict] = []

    # Brands present in Odoo (may or may not exist in README).
    for partner in odoo_partners:
        key = partner["name"].lower()
        readme = readme_by_name.get(key, {})

        country_field = partner.get("country_id")
        has_country = isinstance(country_field, (list, tuple)) and len(country_field) > 1
        country = country_field[1] if has_country else None

        category_field = partner.get("category_id") or []
        categories = [
            pair[1] for pair in category_field if isinstance(pair, (list, tuple)) and len(pair) > 1
        ]

        result.append(
            {
                "name": partner["name"],
                "odoo_id": partner["id"],
                "average_price": partner.get("x_studio_average_price") or None,
                "country": country,
                "website": partner.get("website") or readme.get("web"),
                "categories": categories,
                "made_in": readme.get("made_in"),
                "price_range": readme.get("price_range"),
                "single_cut_models": readme.get("single_cut_models"),
                "description": readme.get("description"),
            }
        )

    # Brands present only in README (no Odoo partner found).
    odoo_keys = set(odoo_by_name.keys())
    for readme in readme_brands:
        if readme["name"].lower() not in odoo_keys:
            result.append(
                {
                    "name": readme["name"],
                    "odoo_id": None,
                    "average_price": None,
                    "country": None,
                    "website": readme.get("web"),
                    "categories": [],
                    "made_in": readme.get("made_in"),
                    "price_range": readme.get("price_range"),
                    "single_cut_models": readme.get("single_cut_models"),
                    "description": readme.get("description"),
                }
            )

    logger.debug("Merged result: {} brand records", len(result))
    return result


def get_brands(conn: Any) -> list[dict]:
    """Return merged brand list, using a 30-day module-level cache.

    On cache miss (first call or TTL exceeded): fetches the GitHub README,
    parses brands, fetches Odoo res.partner records, merges, and stores result.
    """
    global _cache, _fetched_at

    now = datetime.now(tz=UTC)
    if _fetched_at is not None and (now - _fetched_at) < _TTL and _cache:
        logger.debug("Returning cached brands ({} records)", len(_cache))
        return _cache

    logger.info("Cache miss — refreshing brand data")
    readme_text = _fetch_readme()
    readme_brands = parse_readme_brands(readme_text)
    odoo_partners = _fetch_odoo_partners(conn)
    _cache = _merge(readme_brands, odoo_partners)
    _fetched_at = now
    return _cache
