"""MCP tool: fetch a single brand by name with linked x_models.

Resolves brand via :mod:`odoo_mcp.brand_cache` (Odoo + GitHub README merged),
then queries x_models linked to the matching partner and renders both.
"""

from __future__ import annotations

from typing import Any

import odoolib
from loguru import logger

from models import ModelsRecord
from odoo_mcp import brand_cache
from odoo_mcp.resources.brands import _render_brand


def _label(value: tuple[int, str] | None) -> str:
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _find_brand(brands: list[dict], name: str) -> dict | None:
    """Return the first brand whose name matches (case-insensitive, exact or substring)."""
    needle = name.strip().lower()
    if not needle:
        return None

    # Prefer exact case-insensitive match.
    for brand in brands:
        if brand["name"].lower() == needle:
            return brand

    # Fall back to substring match.
    for brand in brands:
        if needle in brand["name"].lower():
            return brand

    return None


def _render_linked_models(models: list[ModelsRecord]) -> str:
    if not models:
        return "## Models in catalog\n\n*No x_models records linked to this partner.*"

    lines: list[str] = [f"## Models in catalog ({len(models)})"]

    wanted: list[ModelsRecord] = []
    others: list[ModelsRecord] = []
    for model in models:
        is_candidate = bool(model.x_studio_wanna) and not model.x_studio_too_expensive
        (wanted if is_candidate else others).append(model)

    def _line(model: ModelsRecord) -> str:
        name = _scalar(model.x_name, fallback="(unnamed)")
        mtype = _scalar(model.x_studio_model_type)
        p50 = _scalar(model.x_price_p50)
        parts: list[str] = [f"**{name}**"]
        if mtype:
            parts.append(f"type={mtype}")
        if p50:
            parts.append(f"p50={p50}")
        if model.x_studio_too_expensive:
            parts.append("too_expensive=yes")
        return "- " + " | ".join(parts)

    if wanted:
        lines.append("")
        lines.append("### Wanted")
        for model in sorted(wanted, key=lambda m: (m.x_name or "").lower()):
            lines.append(_line(model))

    if others:
        lines.append("")
        lines.append("### Other")
        for model in sorted(others, key=lambda m: (m.x_name or "").lower()):
            lines.append(_line(model))

    return "\n".join(lines)


def run(conn: Any, name: str) -> str:
    """Return a markdown card for a single brand plus its linked x_models.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    name:
        Brand name (case-insensitive; exact match preferred, substring fallback).

    Returns
    -------
    str
        Formatted markdown document, or a "not found" notice.
    """
    name = name.strip()
    if not name:
        return "No brand name provided."

    logger.info("get_brand: searching for '{}'", name)
    brands = brand_cache.get_brands(conn)
    brand = _find_brand(brands, name)
    if brand is None:
        return f"No brand found matching: **{name}**"

    logger.info("get_brand: matched '{}' (odoo_id={})", brand["name"], brand.get("odoo_id"))

    sections: list[str] = [_render_brand(brand)]

    odoo_id = brand.get("odoo_id")
    if odoo_id:
        models_proxy: odoolib.main.Model = conn.get_model("x_models")
        model_rows: list[dict] = models_proxy.search_read(
            [("x_studio_partner_id", "=", odoo_id)],
            ModelsRecord.odoo_fields(),
        )
        models = [ModelsRecord.from_odoo(r) for r in model_rows]
        logger.debug("get_brand: {} linked x_models", len(models))
        sections.append("")
        sections.append(_render_linked_models(models))
    else:
        sections.append("")
        sections.append(
            "## Models in catalog\n\n*Brand has no `res.partner` entry — no linked models.*"
        )

    return "\n".join(sections)
