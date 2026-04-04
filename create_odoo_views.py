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


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------


def get_action_id(conn, name: str) -> int | None:
    """Return the ir.actions.act_window id with the given name, or None."""
    act = conn.get_model("ir.actions.act_window")
    results = act.search_read(
        [("name", "=", name), ("type", "=", "ir.actions.act_window")],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_action(
    conn,
    name: str,
    res_model: str,
    view_mode: str,
    *,
    dry_run: bool,
) -> int | None:
    """Create an ir.actions.act_window if one with *name* does not exist.

    Returns the id (existing or new), or None in dry-run when missing.
    """
    existing_id = get_action_id(conn, name)
    if existing_id:
        logger.info("  Action '{}' already exists (id={})", name, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create action: {}", name)
        return None

    act = conn.get_model("ir.actions.act_window")
    new_id = act.create(
        {
            "name": name,
            "res_model": res_model,
            "view_mode": view_mode,
            "type": "ir.actions.act_window",
        }
    )
    logger.success("  Created action: {} (id={})", name, new_id)
    return new_id


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------


def get_menu_id(conn, complete_name: str) -> int | None:
    """Return the ir.ui.menu id whose complete_name matches, or None.

    *complete_name* is the full slash-joined path displayed in Odoo's
    menu list (e.g. ``"Gear"`` or ``"Gear / Gear Items"``).
    """
    menu = conn.get_model("ir.ui.menu")
    results = menu.search_read([("complete_name", "=", complete_name)], ["id"], limit=1)
    return results[0]["id"] if results else None


def ensure_menu(
    conn,
    name: str,
    *,
    parent_id: int | None,
    action_id: int | None,
    dry_run: bool,
    complete_name: str | None = None,
) -> int | None:
    """Create an ir.ui.menu entry if one matching *complete_name* does not exist.

    *complete_name* defaults to *name* when omitted (top-level menu).
    Returns the id (existing or new), or None in dry-run when missing.
    """
    lookup = complete_name or name
    existing_id = get_menu_id(conn, lookup)
    if existing_id:
        logger.info("  Menu '{}' already exists (id={})", lookup, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create menu: {}", lookup)
        return None

    vals: dict = {"name": name}
    if parent_id is not None:
        vals["parent_id"] = parent_id
    if action_id is not None:
        vals["action"] = f"ir.actions.act_window,{action_id}"

    menu = conn.get_model("ir.ui.menu")
    new_id = menu.create(vals)
    logger.success("  Created menu: {} (id={})", lookup, new_id)
    return new_id
