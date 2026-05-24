"""Trigger x_studio_compute recalculation on x_listing records.

The computed field only refreshes when x_studio_compute changes.  This
command toggles the boolean on the selected x_listing records (flip, then
restore to original value), forcing Odoo to recompute for all of them.

Usage (single model, dry-run)::

    reverb2odoo trigger-listing-compute "Frank Brothers Arcane"

Usage (all listings, apply)::

    reverb2odoo trigger-listing-compute --all --apply

Usage (wanna models only, apply)::

    reverb2odoo trigger-listing-compute --wanna --apply
"""

from __future__ import annotations

import click
from loguru import logger

from sync_model import _find_model


def _fetch_listings_for_model(conn, model_id: int) -> list[dict]:
    """Return x_listing records linked to *model_id*."""
    xl = conn.get_model("x_listing")
    return xl.search_read([("x_model_id", "=", model_id)], ["id", "x_studio_compute"])


def _fetch_all_listings(conn) -> list[dict]:
    """Return all x_listing records."""
    xl = conn.get_model("x_listing")
    return xl.search_read([], ["id", "x_studio_compute"])


def _fetch_wanna_listings(conn) -> list[dict]:
    """Return x_listing records whose model is flagged as wanna."""
    xl = conn.get_model("x_listing")
    return xl.search_read(
        [("x_model_id.x_studio_wanna", "=", True)],
        ["id", "x_studio_compute"],
    )


def _apply_trigger(conn, records: list[dict]) -> None:
    """Toggle x_studio_compute on each record then restore the original value."""
    xl = conn.get_model("x_listing")

    true_ids = [r["id"] for r in records if r["x_studio_compute"]]
    false_ids = [r["id"] for r in records if not r["x_studio_compute"]]

    logger.info("Flipping x_studio_compute on {} listing(s)…", len(records))
    if true_ids:
        xl.write(true_ids, {"x_studio_compute": False})
    if false_ids:
        xl.write(false_ids, {"x_studio_compute": True})

    logger.info("Restoring x_studio_compute on {} listing(s)…", len(records))
    if true_ids:
        xl.write(true_ids, {"x_studio_compute": True})
    if false_ids:
        xl.write(false_ids, {"x_studio_compute": False})


@click.command("trigger-listing-compute")
@click.argument("model_name", required=False, default=None)
@click.option("--all", "all_listings", is_flag=True, help="Run on all x_listing records.")
@click.option(
    "--wanna",
    is_flag=True,
    help="Only listings whose model is flagged as wanna (x_studio_wanna). Implies --all.",
)
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    model_name: str | None,
    all_listings: bool,
    wanna: bool,
    apply: bool,
) -> None:
    """Force x_studio_compute recomputation on x_listing records.

    Provide MODEL_NAME to target a single model, or use --all / --wanna
    to process multiple models at once.  Toggles x_studio_compute (flip
    then restore) to trigger the computed field.  Dry-run by default;
    pass --apply to write changes.
    """
    if wanna:
        all_listings = True

    if not all_listings and not model_name:
        raise click.UsageError("Provide a MODEL_NAME, or use --all / --wanna.")

    conn = ctx.obj["conn"]

    if model_name:
        model_info = _find_model(conn, model_name)
        records = _fetch_listings_for_model(conn, model_info["id"])
    elif wanna:
        records = _fetch_wanna_listings(conn)
    else:
        records = _fetch_all_listings(conn)

    true_count = sum(1 for r in records if r["x_studio_compute"])
    false_count = len(records) - true_count

    logger.info("")
    logger.info("=== DRY-RUN REPORT ===")
    logger.info("")
    logger.info(
        "Would toggle x_studio_compute on {} listing(s): {} currently True, {} currently False.",
        len(records),
        true_count,
        false_count,
    )
    logger.info("")

    if not apply:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    _apply_trigger(conn, records)
    logger.success("Done — x_studio_compute recomputed on {} listing(s).", len(records))
