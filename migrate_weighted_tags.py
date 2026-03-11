"""Migrate x_guitar_familly entries into x_weighted_tags.

All records in x_guitar_familly whose name does NOT start with ``pool-`` are
copied to x_weighted_tags, preserving:

  - x_name        (tag label)
  - x_studio_score
  - x_studio_model_ids  (many2many link to x_models)

Records already present in x_weighted_tags (matched by x_name) are skipped.

Usage (dry-run, default)::

    reverb2odoo migrate-weighted-tags

Usage (apply)::

    reverb2odoo migrate-weighted-tags --apply
"""

from __future__ import annotations

import click
from loguru import logger

_FAM_FIELDS: list[str] = ["x_name", "x_studio_score", "x_studio_guitar_models"]
_WT_FIELDS: list[str] = ["x_name"]


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _fetch_source(conn) -> list[dict]:
    """Return x_guitar_familly records that should be migrated (non-pool-)."""
    model = conn.get_model("x_guitar_familly")
    records = model.search_read(
        [("x_name", "not like", "pool-%")],
        _FAM_FIELDS,
        order="x_name asc",
    )
    return records


def _fetch_existing_wt(conn) -> set[str]:
    """Return the set of x_name values already in x_weighted_tags."""
    model = conn.get_model("x_weighted_tags")
    records = model.search_read([], _WT_FIELDS)
    return {r["x_name"] for r in records}


def compute_plan(conn) -> list[dict]:
    """Return source records that need to be created in x_weighted_tags.

    Each item in the returned list is a dict with:
        x_name, x_studio_score, model_ids (list[int])
    """
    logger.info("Fetching x_guitar_familly records (excluding pool-)…")
    source = _fetch_source(conn)
    logger.info("  {} record(s) eligible", len(source))

    logger.info("Fetching existing x_weighted_tags names…")
    existing = _fetch_existing_wt(conn)
    logger.info("  {} already present", len(existing))

    plan = []
    for r in source:
        if r["x_name"] in existing:
            logger.debug("  skip '{}' (already exists)", r["x_name"])
            continue
        plan.append(
            {
                "x_name": r["x_name"],
                "x_studio_score": r["x_studio_score"] or 0,
                "model_ids": r["x_studio_guitar_models"] or [],
            }
        )

    return plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_plan(conn, plan: list[dict]) -> None:
    """Create x_weighted_tags records and link them to x_models."""
    wt_model = conn.get_model("x_weighted_tags")

    for item in plan:
        model_ids: list[int] = item["model_ids"]
        new_id = wt_model.create(
            {
                "x_name": item["x_name"],
                "x_studio_score": item["x_studio_score"],
                "x_studio_model_ids": [(6, 0, model_ids)],
            }
        )
        logger.success(
            "Created '{}' (id={}) score={} → {} model(s)",
            item["x_name"],
            new_id,
            item["x_studio_score"],
            len(model_ids),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("migrate-weighted-tags")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Migrate non-pool x_guitar_familly entries into x_weighted_tags.

    Copies name, score, and model links. Skips entries already present.
    Runs in dry-run mode by default; pass --apply to write changes.
    """
    conn = ctx.obj["conn"]

    plan = compute_plan(conn)

    # ── Dry-run report ──────────────────────────────────────────────────────
    total_links = sum(len(item["model_ids"]) for item in plan)

    logger.info("")
    logger.info("=== DRY-RUN REPORT ===")
    logger.info("")

    if plan:
        logger.info(
            "x_weighted_tags to CREATE ({} record(s), {} model link(s) total):",
            len(plan),
            total_links,
        )
        for item in plan:
            logger.info(
                "  '{}' score={} → {} model(s)",
                item["x_name"],
                item["x_studio_score"],
                len(item["model_ids"]),
            )
    else:
        logger.info("Nothing to migrate.")

    logger.info("")

    if not apply:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    logger.info("Applying changes…")
    apply_plan(conn, plan)
    logger.success("Done — {} record(s) created.", len(plan))
