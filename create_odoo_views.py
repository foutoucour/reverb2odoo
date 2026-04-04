"""Create views, window actions, and menu items for x_gear and x_listing.

Usage (dry-run, default)::

    reverb2odoo create-odoo-views

Usage (apply changes)::

    reverb2odoo create-odoo-views --apply
"""

from __future__ import annotations

import click
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


def get_menu_id(conn, name: str, parent_id: int | None = None) -> int | None:
    """Return the ir.ui.menu id matching (name, parent_id), or None.

    Uses stored fields only — ``complete_name`` is computed and cannot be
    filtered in Odoo 19.
    """
    menu = conn.get_model("ir.ui.menu")
    results = menu.search_read(
        [("name", "=", name), ("parent_id", "=", parent_id or False)],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_menu(
    conn,
    name: str,
    *,
    parent_id: int | None,
    action_id: int | None,
    dry_run: bool,
) -> int | None:
    """Create an ir.ui.menu entry if one with (name, parent_id) does not exist.

    Returns the id (existing or new), or None in dry-run when missing.
    """
    existing_id = get_menu_id(conn, name, parent_id)
    if existing_id:
        logger.info("  Menu '{}' already exists (id={})", name, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create menu: {}", name)
        return None

    vals: dict = {"name": name}
    if parent_id is not None:
        vals["parent_id"] = parent_id
    if action_id is not None:
        vals["action"] = f"ir.actions.act_window,{action_id}"

    menu = conn.get_model("ir.ui.menu")
    new_id = menu.create(vals)
    logger.success("  Created menu: {} (id={})", name, new_id)
    return new_id


# ---------------------------------------------------------------------------
# x_gear view definitions
# ---------------------------------------------------------------------------

_GEAR_LIST_ARCH = """\
<list string="Gear">
  <field name="x_name"/>
  <field name="x_model_id"/>
  <field name="x_status"/>
  <field name="x_condition"/>
  <field name="x_intent"/>
  <field name="x_is_not_interested"/>
</list>"""

_GEAR_FORM_ARCH = """\
<form string="Gear">
  <sheet>
    <field name="x_image" widget="image" class="oe_avatar" options="{'preview_image': 'x_image'}"/>
    <group>
      <group>
        <field name="x_name"/>
        <field name="x_model_id"/>
        <field name="x_status"/>
      </group>
      <group>
        <field name="x_condition"/>
        <field name="x_intent"/>
        <field name="x_is_not_interested"/>
        <field name="x_guitar_id"/>
      </group>
    </group>
    <notebook>
      <page string="Listings">
        <field name="x_listing_ids">
          <list>
            <field name="x_name"/>
            <field name="x_platform"/>
            <field name="x_price"/>
            <field name="x_currency_id"/>
            <field name="x_status"/>
            <field name="x_is_available"/>
          </list>
        </field>
      </page>
    </notebook>
  </sheet>
</form>"""

_GEAR_SEARCH_ARCH = """\
<search string="Gear">
  <field name="x_name"/>
  <field name="x_model_id"/>
  <filter string="Watching" name="watching" domain="[('x_status', '=', 'watching')]"/>
  <filter string="Owned" name="owned" domain="[('x_status', '=', 'owned')]"/>
  <filter string="Closed" name="closed" domain="[('x_status', '=', 'closed')]"/>
  <filter string="Not Interested" name="not_interested" domain="[('x_is_not_interested', '=', 1)]"/>
  <filter string="Status" name="group_status" context="{'group_by': 'x_status'}"/>
  <filter string="Model" name="group_model" context="{'group_by': 'x_model_id'}"/>
</search>"""

_GEAR_VIEWS: list[tuple[str, str, str]] = [
    ("list", "x_gear.list", _GEAR_LIST_ARCH),
    ("form", "x_gear.form", _GEAR_FORM_ARCH),
    ("search", "x_gear.search", _GEAR_SEARCH_ARCH),
]


def create_gear_views(conn, *, dry_run: bool) -> None:
    """Create list, form, and search views for x_gear."""
    for view_type, name, arch in _GEAR_VIEWS:
        ensure_view(conn, "x_gear", view_type, name, arch, dry_run=dry_run)


# ---------------------------------------------------------------------------
# x_listing view definitions
# ---------------------------------------------------------------------------

_LISTING_LIST_ARCH = """\
<list string="Listings">
  <field name="x_name"/>
  <field name="x_gear_id"/>
  <field name="x_platform"/>
  <field name="x_price"/>
  <field name="x_currency_id"/>
  <field name="x_status"/>
  <field name="x_is_available"/>
  <field name="x_published_at"/>
</list>"""

_LISTING_FORM_ARCH = """\
<form string="Listing">
  <sheet>
    <field name="x_image" widget="image" class="oe_avatar" options="{'preview_image': 'x_image'}"/>
    <group>
      <group>
        <field name="x_name"/>
        <field name="x_gear_id"/>
        <field name="x_url" widget="url"/>
        <field name="x_platform"/>
        <field name="x_status"/>
        <field name="x_published_at"/>
        <field name="x_guitar_id"/>
      </group>
      <group>
        <field name="x_price"/>
        <field name="x_currency_id"/>
        <field name="x_shipping"/>
        <field name="x_is_available"/>
        <field name="x_can_accept_offers"/>
        <field name="x_is_taxed"/>
        <field name="x_is_too_expensive"/>
      </group>
    </group>
  </sheet>
</form>"""

_LISTING_SEARCH_ARCH = """\
<search string="Listings">
  <field name="x_name"/>
  <field name="x_gear_id"/>
  <filter string="Active" name="active" domain="[('x_status', '=', 'active')]"/>
  <filter string="Acquired" name="acquired" domain="[('x_status', '=', 'acquired')]"/>
  <filter string="Passed" name="passed" domain="[('x_status', '=', 'passed')]"/>
  <filter string="Available" name="available" domain="[('x_is_available', '=', 1)]"/>
  <filter string="Reverb" name="platform_reverb" domain="[('x_platform', '=', 'reverb')]"/>
  <filter string="Status" name="group_status" context="{'group_by': 'x_status'}"/>
  <filter string="Platform" name="group_platform" context="{'group_by': 'x_platform'}"/>
  <filter string="Gear" name="group_gear" context="{'group_by': 'x_gear_id'}"/>
</search>"""

_LISTING_VIEWS: list[tuple[str, str, str]] = [
    ("list", "x_listing.list", _LISTING_LIST_ARCH),
    ("form", "x_listing.form", _LISTING_FORM_ARCH),
    ("search", "x_listing.search", _LISTING_SEARCH_ARCH),
]


def create_listing_views(conn, *, dry_run: bool) -> None:
    """Create list, form, and search views for x_listing."""
    for view_type, name, arch in _LISTING_VIEWS:
        ensure_view(conn, "x_listing", view_type, name, arch, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

#: Display name for the top-level "Gear" menu entry.
_MENU_ROOT_NAME = "Gear"


def create_views(conn, *, dry_run: bool) -> None:
    """Create all views, actions, and menus for x_gear and x_listing.

    Execution order:
    1. x_gear views (list, form, search)
    2. x_listing views (list, form, search)
    3. Window actions for both models
    4. Top-level "Gear" menu + two sub-menus
    """
    # ── Views ──────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== x_gear views ===")
    create_gear_views(conn, dry_run=dry_run)

    logger.info("")
    logger.info("=== x_listing views ===")
    create_listing_views(conn, dry_run=dry_run)

    # ── Actions ────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== window actions ===")
    gear_action_id = ensure_action(conn, "Gear Items", "x_gear", "list,form", dry_run=dry_run)
    listing_action_id = ensure_action(conn, "Listings", "x_listing", "list,form", dry_run=dry_run)

    # ── Menus ──────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== menus ===")
    root_id = ensure_menu(
        conn,
        _MENU_ROOT_NAME,
        parent_id=None,
        action_id=None,
        dry_run=dry_run,
    )
    ensure_menu(
        conn,
        "Gear Items",
        parent_id=root_id,
        action_id=gear_action_id,
        dry_run=dry_run,
    )
    ensure_menu(
        conn,
        "Listings",
        parent_id=root_id,
        action_id=listing_action_id,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("create-odoo-views")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Create views, actions, and menus for x_gear and x_listing.

    Creates list/form/search views, window actions, and a top-level
    'Gear' menu with 'Gear Items' and 'Listings' sub-entries.

    Runs in dry-run mode by default; pass --apply to write to Odoo.
    Idempotent: existing views, actions, and menus are skipped.
    """
    conn = ctx.obj["conn"]
    dry_run = not apply

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written.  Pass --apply to apply.")

    create_views(conn, dry_run=dry_run)

    logger.info("")
    if dry_run:
        logger.info("[DRY-RUN] Done.  Run with --apply to create the views.")
    else:
        logger.success("View creation complete.")
