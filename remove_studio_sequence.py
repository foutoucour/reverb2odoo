"""Remove all occurrences of x_studio_sequence from the Odoo instance.

  - Views   : removes <field name="x_studio_sequence" widget="handle"/> lines,
              fixes default_order attributes, and re-anchors Studio xpath nodes
              that targeted the handle field.
  - Database: unlinks the 12 ir.model.fields records so the column is dropped.
  - Code    : no Python file references found.

Usage (dry-run, default)::

    reverb2odoo remove-studio-sequence

Usage (apply)::

    reverb2odoo remove-studio-sequence --apply
"""

from __future__ import annotations

import re

import click
from loguru import logger

# ---------------------------------------------------------------------------
# View IDs
# ---------------------------------------------------------------------------

#: Base list views: only need the handle field removed (+ default_order fixes).
_BASE_LIST_VIEW_IDS: list[int] = [649, 562, 541, 546, 736, 587, 595, 579, 592, 728, 664]

#: Form / customisation views that embed a list containing the handle field.
_FORM_VIEW_IDS: list[int] = [568, 561, 582, 628]

#: Studio xpath views whose anchor is //field[@name='x_studio_sequence'].
#: The anchor is re-pointed to x_name (the first field that remains).
_XPATH_VIEW_IDS: list[int] = [660, 591, 599]

# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------

_HANDLE_RE = re.compile(
    r"[ \t]*<field\s+name=[\"']x_studio_sequence[\"']\s+widget=[\"']handle[\"']\s*/>\n?",
    re.MULTILINE,
)

_DEFAULT_ORDER_RE = re.compile(r'\s*default_order="x_studio_sequence asc,id desc"')

_XPATH_ANCHOR_OLD = "//field[@name='x_studio_sequence']"
_XPATH_ANCHOR_NEW = "//field[@name='x_name']"
_XPATH_POSITION_OLD = 'position="after"'
_XPATH_POSITION_NEW = 'position="before"'


def _remove_handle(arch: str) -> str:
    return _HANDLE_RE.sub("", arch)


def _fix_default_order(arch: str) -> str:
    return _DEFAULT_ORDER_RE.sub("", arch)


def _fix_xpath_anchor(arch: str) -> str:
    arch = arch.replace(_XPATH_ANCHOR_OLD, _XPATH_ANCHOR_NEW)
    # Only swap position for the specific x_studio_sequence xpaths (already replaced above)
    arch = arch.replace(
        f"expr='{_XPATH_ANCHOR_NEW}' {_XPATH_POSITION_OLD}",
        f"expr='{_XPATH_ANCHOR_NEW}' {_XPATH_POSITION_NEW}",
    )
    return arch


def _transform(view_id: int, arch: str) -> str:
    """Apply the appropriate transformation(s) for a given view id."""
    if view_id in _BASE_LIST_VIEW_IDS:
        arch = _remove_handle(arch)
        arch = _fix_default_order(arch)
    elif view_id in _FORM_VIEW_IDS:
        arch = _remove_handle(arch)
    elif view_id in _XPATH_VIEW_IDS:
        arch = _fix_xpath_anchor(arch)
    return arch


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def compute_plan(conn) -> tuple[list[dict], list[int], list[dict], list[dict]]:
    """Return (view_updates, field_ids_to_delete, model_order_updates, filter_updates).

    view_updates       : list of {id, name, old_arch, new_arch}
    field_ids_to_delete: ir.model.fields ids
    model_order_updates: list of {id, model, old_order} for ir.model records
    filter_updates     : list of {id, name} for ir.filters records
    """
    all_view_ids = _BASE_LIST_VIEW_IDS + _FORM_VIEW_IDS + _XPATH_VIEW_IDS
    views_model = conn.get_model("ir.ui.view")
    records = views_model.read(all_view_ids, ["id", "name", "arch_db"])

    view_updates = []
    for r in records:
        new_arch = _transform(r["id"], r["arch_db"])
        if new_arch != r["arch_db"]:
            view_updates.append(
                {"id": r["id"], "name": r["name"], "old_arch": r["arch_db"], "new_arch": new_arch}
            )
        else:
            logger.warning(
                "View id={} '{}' — no change detected (already clean?)", r["id"], r["name"]
            )

    fields_model = conn.get_model("ir.model.fields")
    field_records = fields_model.search_read(
        [("name", "=", "x_studio_sequence")],
        ["id", "model"],
    )
    field_ids = [r["id"] for r in field_records]

    # ir.model records whose _order still references x_studio_sequence
    im = conn.get_model("ir.model")
    model_order_updates = im.search_read(
        [("order", "like", "x_studio_sequence")],
        ["id", "model", "order"],
    )

    # ir.filters whose sort references x_studio_sequence
    filters_model = conn.get_model("ir.filters")
    filter_updates = filters_model.search_read(
        [("sort", "like", "x_studio_sequence")],
        ["id", "name", "model_id"],
    )

    return view_updates, field_ids, field_records, model_order_updates, filter_updates


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_plan(
    conn,
    view_updates: list[dict],
    field_ids: list[int],
    model_order_updates: list[dict],
    filter_updates: list[dict],
) -> None:
    views_model = conn.get_model("ir.ui.view")
    for u in view_updates:
        views_model.write([u["id"]], {"arch_db": u["new_arch"]})
        logger.success("Updated view id={} '{}'", u["id"], u["name"])

    if field_ids:
        fields_model = conn.get_model("ir.model.fields")
        fields_model.unlink(field_ids)
        logger.success("Deleted {} ir.model.fields record(s): {}", len(field_ids), field_ids)

    if model_order_updates:
        im = conn.get_model("ir.model")
        for r in model_order_updates:
            im.write([r["id"]], {"order": "id asc"})
            logger.success("Reset ir.model order for '{}' (was '{}')", r["model"], r["order"])

    if filter_updates:
        filters_model = conn.get_model("ir.filters")
        ids = [r["id"] for r in filter_updates]
        filters_model.write(ids, {"sort": "[]"})
        for r in filter_updates:
            logger.success("Cleared sort on filter '{}' (model {})", r["name"], r["model_id"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("remove-studio-sequence")
@click.option("--apply", is_flag=True, default=False, help="Apply changes (default: dry-run).")
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Remove x_studio_sequence from all views and the database.

    Dry-run by default; pass --apply to write changes.
    """
    conn = ctx.obj["conn"]

    view_updates, field_ids, field_records, model_order_updates, filter_updates = compute_plan(conn)

    logger.info("")
    logger.info("=== DRY-RUN REPORT ===")
    logger.info("")

    logger.info("Views to update ({}):", len(view_updates))
    for u in view_updates:
        logger.info("  id={} '{}'", u["id"], u["name"])

    logger.info("")
    logger.info("ir.model.fields to delete ({}):", len(field_ids))
    for r in field_records:
        logger.info("  id={} model={}", r["id"], r["model"])

    logger.info("")
    logger.info("ir.model order to reset to 'id asc' ({}):", len(model_order_updates))
    for r in model_order_updates:
        logger.info("  id={} model={} order={}", r["id"], r["model"], r["order"])

    logger.info("")
    logger.info("ir.filters sort to clear ({}):", len(filter_updates))
    for r in filter_updates:
        logger.info("  id={} name='{}' model={}", r["id"], r["name"], r["model_id"])

    logger.info("")

    if not apply:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    apply_plan(conn, view_updates, field_ids, model_order_updates, filter_updates)
    logger.success(
        "Done — {} views updated, {} fields deleted, {} model orders reset, {} filters cleared.",
        len(view_updates),
        len(field_ids),
        len(model_order_updates),
        len(filter_updates),
    )
