"""Create views, window actions, and menu items for x_gear and x_listing.

Usage (dry-run, default)::

    reverb2odoo create-odoo-views

Usage (apply changes)::

    reverb2odoo create-odoo-views --apply
"""

from __future__ import annotations

from loguru import logger

# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------


def get_view_id(conn, model: str, view_type: str, name: str) -> int | None:
    """Return the ir.ui.view id matching (model, type, name), or None."""
    ir_view = conn.get_model("ir.ui.view")
    results = ir_view.search_read(
        [("model", "=", model), ("type", "=", view_type), ("name", "=", name)],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_view(
    conn,
    model: str,
    view_type: str,
    name: str,
    arch: str,
    *,
    dry_run: bool,
) -> int | None:
    """Create an ir.ui.view if one with (model, type, name) does not exist.

    Returns the id (existing or new), or None in dry-run when missing.
    """
    existing_id = get_view_id(conn, model, view_type, name)
    if existing_id:
        logger.info("  View {} ({}) already exists (id={})", name, view_type, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create {} view: {}", view_type, name)
        return None

    ir_view = conn.get_model("ir.ui.view")
    new_id = ir_view.create({"name": name, "model": model, "type": view_type, "arch": arch})
    logger.success("  Created {} view: {} (id={})", view_type, name, new_id)
    return new_id
