"""MCP tool: search x_models by name, sorted by score/price/name.

Builds an Odoo domain from the optional ``query`` (ilike on ``x_name``),
orders by the requested key, and returns a compact markdown card list.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from models import ModelsRecord

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Map the public sort_by parameter to (odoo_field, direction).
_SORT_OPTIONS: dict[str, tuple[str, str]] = {
    "weighted_score": ("x_studio_weighted_score", "desc"),
    "p50": ("x_price_p50", "desc"),
    "name": ("x_name", "asc"),
}

_DEFAULT_SORT = "weighted_score"
_DEFAULT_LIMIT = 20


def _label(value: tuple[int, str] | None) -> str:
    """Extract display name from a normalised many2one value."""
    return value[1] if value else ""


def _scalar(value: object, fallback: str = "") -> str:
    """Return str(value) unless it is False/None/empty, in which case return fallback."""
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _resolve_order(sort_by: str) -> tuple[str, str]:
    """Map sort_by to an Odoo order clause; fall back to default when unknown."""
    key = (sort_by or "").strip().lower()
    if key not in _SORT_OPTIONS:
        if key:
            logger.warning(
                "search_models: unknown sort_by '{}', defaulting to '{}'", sort_by, _DEFAULT_SORT
            )
        key = _DEFAULT_SORT
    field, direction = _SORT_OPTIONS[key]
    return key, f"{field} {direction}"


def _render_card(model: ModelsRecord) -> str:
    """Render a single x_models record as a compact markdown bullet."""
    name = _scalar(model.x_name, fallback="(unnamed)")
    brand = _label(model.x_studio_partner_id)
    model_type = _scalar(model.x_studio_model_type)
    wanna = "yes" if model.x_studio_wanna else "no"
    score = _scalar(model.x_studio_weighted_score)
    p50 = _scalar(model.x_price_p50)

    parts: list[str] = [f"- **{name}**"]
    if brand:
        parts.append(f"({brand})")
    parts.append(f"| type={model_type or '-'}")
    parts.append(f"| wanna={wanna}")
    parts.append(f"| score={score or '0'}")
    parts.append(f"| p50={p50 or '-'}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    conn: Any,
    query: str = "",
    sort_by: str = _DEFAULT_SORT,
    limit: int = _DEFAULT_LIMIT,
) -> str:
    """Search x_models by name and return a sorted markdown card list.

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    query:
        Substring matched against ``x_name`` (ilike). Empty matches all.
    sort_by:
        One of ``"weighted_score"`` (default, desc), ``"p50"`` (desc),
        ``"name"`` (asc). Unknown values fall back to the default.
    limit:
        Maximum number of records to return. Non-positive values fall back
        to the default of ``20``.

    Returns
    -------
    str
        Markdown string with one bullet per matching model, or a "no
        results" notice when nothing matches.
    """
    domain: list = []
    if query.strip():
        domain.append(("x_name", "ilike", query.strip()))

    sort_key, order = _resolve_order(sort_by)
    effective_limit = limit if isinstance(limit, int) and limit > 0 else _DEFAULT_LIMIT

    logger.info("search_models: domain={} order='{}' limit={}", domain, order, effective_limit)

    models_proxy = conn.get_model("x_models")
    rows: list[dict] = models_proxy.search_read(
        domain,
        ModelsRecord.odoo_fields(),
        order=order,
        limit=effective_limit,
    )
    logger.info("search_models: {} record(s) found", len(rows))

    if not rows:
        return "No models found matching the supplied filters."

    records = [ModelsRecord.from_odoo(r) for r in rows]
    header = f"# Models Search Results ({len(records)} found, sort={sort_key})\n"
    lines: list[str] = [header]
    for model in records:
        lines.append(_render_card(model))

    return "\n".join(lines)
