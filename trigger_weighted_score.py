"""Trigger x_studio_weighted_score recalculation on all x_models.

The computed field x_studio_weighted_score only refreshes when
x_studio_compute changes.  This command toggles the boolean on every
x_models record (flip, then restore to original value), forcing Odoo
to recompute the score for all records.

Usage (dry-run, default)::

    reverb2odoo trigger-weighted-score

Usage (apply)::

    reverb2odoo trigger-weighted-score --apply
"""

from __future__ import annotations

import click
from loguru import logger


def _fetch_models(conn) -> list[dict]:
    """Return all x_models records with their current x_studio_compute value."""
    xm = conn.get_model("x_models")
    return xm.search_read([], ["id", "x_studio_compute"])


def apply_trigger(conn, records: list[dict]) -> None:
    """Toggle x_studio_compute on each record then restore the original value."""
    xm = conn.get_model("x_models")

    true_ids = [r["id"] for r in records if r["x_studio_compute"]]
    false_ids = [r["id"] for r in records if not r["x_studio_compute"]]

    logger.info("Flipping x_studio_compute on {} model(s)…", len(records))
    if true_ids:
        xm.write(true_ids, {"x_studio_compute": False})
    if false_ids:
        xm.write(false_ids, {"x_studio_compute": True})

    logger.info("Restoring x_studio_compute on {} model(s)…", len(records))
    if true_ids:
        xm.write(true_ids, {"x_studio_compute": True})
    if false_ids:
        xm.write(false_ids, {"x_studio_compute": False})


@click.command("trigger-weighted-score")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Force x_studio_weighted_score recomputation on all x_models.

    Toggles x_studio_compute on every record (flip then restore) to trigger
    the computed field.  Dry-run by default; pass --apply to write changes.
    """
    conn = ctx.obj["conn"]

    records = _fetch_models(conn)
    true_count = sum(1 for r in records if r["x_studio_compute"])
    false_count = len(records) - true_count

    logger.info("")
    logger.info("=== DRY-RUN REPORT ===")
    logger.info("")
    logger.info(
        "Would toggle x_studio_compute on {} model(s): {} currently True, {} currently False.",
        len(records),
        true_count,
        false_count,
    )
    logger.info("")

    if not apply:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    apply_trigger(conn, records)
    logger.success("Done — x_studio_weighted_score recomputed on {} model(s).", len(records))
