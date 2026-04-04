"""Migrate x_guitar records into x_gear + x_listing.

Each x_guitar record produces:
  - one ``x_gear`` record   (the physical item)
  - one ``x_listing`` record (the marketplace entry, linked to the gear)

Both records store the originating ``x_guitar`` id in their ``x_guitar_id``
field so the migration is traceable and re-runnable: records already migrated
(x_gear.x_guitar_id is not null) are skipped automatically.

Status mapping from ``x_studio_selection_field_7tf_1igs0n52h``:

  Watched        → x_gear(status=watching)
  Not Interested → x_gear(status=watching, x_is_not_interested=True)
  Bought         → x_gear(status=owned)     + x_listing(status=acquired)
  For Sale       → x_gear(status=owned)     + x_listing(status=acquired)
  Sold           → x_gear(status=closed)    + x_listing(status=acquired)
  (anything else) → x_gear(status=watching)

Usage (dry-run, default)::

    reverb2odoo migrate-guitar-to-gear-listing

Usage (apply changes)::

    reverb2odoo migrate-guitar-to-gear-listing --apply

"""

from __future__ import annotations

from typing import Any

import click
from loguru import logger

from odoo_connector import GUITAR_FIELDS

# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

#: Selection field on x_guitar that holds the lifecycle status.
_STATUS_FIELD = "x_studio_selection_field_7tf_1igs0n52h"

#: x_guitar status value → x_gear status
_GEAR_STATUS_MAP: dict[str, str] = {
    "Watched": "watching",
    "Not Interested": "watching",
    "Bought": "owned",
    "For Sale": "owned",
    "Sold": "closed",
}

#: x_guitar status values that imply the listing was acquired (bought)
_ACQUIRED_STATUSES = {"Bought", "For Sale", "Sold"}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _fetch_all_guitars(conn) -> list[dict]:
    """Fetch all x_guitar records with migration-relevant fields."""
    guitar = conn.get_model("x_guitar")
    fields = GUITAR_FIELDS + [_STATUS_FIELD]
    return guitar.search_read([], fields, order="id asc")


def _fetch_already_migrated_guitar_ids(conn) -> set[int]:
    """Return x_guitar IDs that already have a corresponding x_gear record."""
    gear = conn.get_model("x_gear")
    records = gear.search_read([("x_guitar_id", "!=", False)], ["x_guitar_id"])
    return {
        (r["x_guitar_id"][0] if isinstance(r["x_guitar_id"], (list, tuple)) else r["x_guitar_id"])
        for r in records
    }


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _m2o_id(value: Any) -> int | None:
    """Extract the integer id from a many2one field value (or None)."""
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int):
        return value
    return None


def _guitar_to_gear_vals(guitar: dict) -> dict[str, Any]:
    """Build x_gear creation values from an x_guitar record."""
    raw_status = guitar.get(_STATUS_FIELD) or "Watched"
    gear_status = _GEAR_STATUS_MAP.get(raw_status, "watching")
    is_not_interested = raw_status == "Not Interested"

    model_ref = guitar.get("x_studio_models")
    model_id = _m2o_id(model_ref)

    vals: dict[str, Any] = {
        "x_name": guitar.get("x_name", ""),
        "x_status": gear_status,
        "x_is_not_interested": is_not_interested,
        "x_guitar_id": guitar["id"],
    }
    if model_id:
        vals["x_model_id"] = model_id

    return vals


def _guitar_to_listing_vals(guitar: dict, gear_id: int) -> dict[str, Any]:
    """Build x_listing creation values from an x_guitar record."""
    raw_status = guitar.get(_STATUS_FIELD) or "Watched"
    listing_status = "acquired" if raw_status in _ACQUIRED_STATUSES else "active"

    currency_ref = guitar.get("x_studio_currency_id")
    currency_id = _m2o_id(currency_ref)

    vals: dict[str, Any] = {
        "x_name": guitar.get("x_name", ""),
        "x_gear_id": gear_id,
        "x_url": guitar.get("x_studio_url", ""),
        "x_platform": "reverb",
        "x_price": guitar.get("x_studio_value") or 0.0,
        "x_shipping": guitar.get("x_studio_shipping") or 0.0,
        "x_is_available": bool(guitar.get("x_studio_is_available")),
        "x_can_accept_offers": bool(guitar.get("x_studio_accept_offers")),
        "x_is_taxed": bool(guitar.get("x_studio_taxed")),
        "x_status": listing_status,
        "x_guitar_id": guitar["id"],
    }
    if currency_id:
        vals["x_currency_id"] = currency_id
    published = guitar.get("x_studio_published_at")
    if published:
        vals["x_published_at"] = published

    return vals


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compute_plan(conn) -> tuple[list[dict], set[int]]:
    """Compute which x_guitar records still need migration.

    Returns
    -------
    to_migrate : list[dict]
        x_guitar records not yet migrated (in id-ascending order).
    already_migrated : set[int]
        x_guitar ids that already have a corresponding x_gear.
    """
    logger.info("Fetching all x_guitar records…")
    all_guitars = _fetch_all_guitars(conn)
    logger.info("  {} x_guitar record(s) fetched", len(all_guitars))

    logger.info("Checking already-migrated records…")
    already_migrated = _fetch_already_migrated_guitar_ids(conn)
    logger.info("  {} x_guitar record(s) already migrated (will be skipped)", len(already_migrated))

    to_migrate = [g for g in all_guitars if g["id"] not in already_migrated]
    logger.info("  {} x_guitar record(s) to migrate", len(to_migrate))

    return to_migrate, already_migrated


def apply_plan(conn, to_migrate: list[dict], *, dry_run: bool) -> tuple[int, int]:
    """Create x_gear + x_listing records for each unmigrated x_guitar.

    Returns
    -------
    (gear_created, listing_created) : tuple[int, int]
    """
    gear_model = conn.get_model("x_gear")
    listing_model = conn.get_model("x_listing")

    gear_created = 0
    listing_created = 0

    for guitar in to_migrate:
        guitar_id = guitar["id"]
        guitar_name = guitar.get("x_name", f"id={guitar_id}")
        raw_status = guitar.get(_STATUS_FIELD) or "Watched"

        gear_vals = _guitar_to_gear_vals(guitar)

        if dry_run:
            logger.info(
                "[DRY-RUN] Would create x_gear for x_guitar id={} '{}' (status: {} → {})",
                guitar_id,
                guitar_name[:50],
                raw_status,
                gear_vals["x_status"],
            )
            gear_created += 1
            listing_created += 1
            continue

        gear_id = gear_model.create(gear_vals)
        logger.info(
            "Created x_gear id={} for x_guitar id={} '{}'",
            gear_id,
            guitar_id,
            guitar_name[:50],
        )
        gear_created += 1

        listing_vals = _guitar_to_listing_vals(guitar, gear_id)
        listing_id = listing_model.create(listing_vals)
        logger.debug("  → x_listing id={} (status={})", listing_id, listing_vals["x_status"])
        listing_created += 1

    return gear_created, listing_created


# ---------------------------------------------------------------------------
# Status back-fill
# ---------------------------------------------------------------------------


def fix_migrated_status(conn, *, dry_run: bool) -> int:
    """Back-fill x_status on gear/listing records where the field is unset.

    Targets records created before x_status existed as a field (x_status=False
    but x_guitar_id is set).  Returns the total number of records updated.
    """
    gear_model = conn.get_model("x_gear")
    listing_model = conn.get_model("x_listing")
    guitar_model = conn.get_model("x_guitar")

    updated = 0

    # ── x_gear ──────────────────────────────────────────────────────────────
    gear_records = gear_model.search_read(
        [("x_guitar_id", "!=", False), ("x_status", "=", False)],
        ["id", "x_guitar_id"],
    )
    if gear_records:
        guitar_ids = [_m2o_id(g["x_guitar_id"]) for g in gear_records]
        guitars = guitar_model.search_read([("id", "in", guitar_ids)], ["id", _STATUS_FIELD])
        guitar_by_id = {g["id"]: g for g in guitars}

        for gear in gear_records:
            guitar_id = _m2o_id(gear["x_guitar_id"])
            guitar = guitar_by_id.get(guitar_id)
            if guitar is None:
                continue
            raw_status = guitar.get(_STATUS_FIELD) or "Watched"
            gear_status = _GEAR_STATUS_MAP.get(raw_status, "watching")
            is_not_interested = raw_status == "Not Interested"
            if dry_run:
                logger.info(
                    "  [DRY-RUN] Would fix x_gear id={} x_status → {} (guitar: {})",
                    gear["id"],
                    gear_status,
                    raw_status,
                )
                updated += 1
                continue
            gear_model.write(
                [gear["id"]],
                {
                    "x_status": gear_status,
                    "x_is_not_interested": is_not_interested,
                },
            )
            logger.info("  Fixed x_gear id={} x_status → {}", gear["id"], gear_status)
            updated += 1

    # ── x_listing ────────────────────────────────────────────────────────────
    listing_records = listing_model.search_read(
        [("x_guitar_id", "!=", False), ("x_status", "=", False)],
        ["id", "x_guitar_id"],
    )
    if listing_records:
        guitar_ids = [_m2o_id(rec["x_guitar_id"]) for rec in listing_records]
        guitars = guitar_model.search_read([("id", "in", guitar_ids)], ["id", _STATUS_FIELD])
        guitar_by_id = {g["id"]: g for g in guitars}

        for listing in listing_records:
            guitar_id = _m2o_id(listing["x_guitar_id"])
            guitar = guitar_by_id.get(guitar_id)
            if guitar is None:
                continue
            raw_status = guitar.get(_STATUS_FIELD) or "Watched"
            listing_status = "acquired" if raw_status in _ACQUIRED_STATUSES else "active"
            if dry_run:
                logger.info(
                    "  [DRY-RUN] Would fix x_listing id={} x_status → {} (guitar: {})",
                    listing["id"],
                    listing_status,
                    raw_status,
                )
                updated += 1
                continue
            listing_model.write([listing["id"]], {"x_status": listing_status})
            logger.info("  Fixed x_listing id={} x_status → {}", listing["id"], listing_status)
            updated += 1

    return updated


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("migrate-guitar-to-gear-listing")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Migrate x_guitar records into x_gear + x_listing.

    Runs in dry-run mode by default.  Pass --apply to write changes to Odoo.
    Already-migrated records (x_gear.x_guitar_id is set) are skipped, making
    this safe to re-run after a partial failure.
    """
    conn = ctx.obj["conn"]

    to_migrate, already_migrated = compute_plan(conn)

    # ── Dry-run report ──────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== MIGRATION PLAN ===")
    logger.info("")
    logger.info("Already migrated : {}", len(already_migrated))
    logger.info("To migrate       : {}", len(to_migrate))
    logger.info("")

    dry_run = not apply

    # ── Status back-fill (always runs) ──────────────────────────────────────
    logger.info("=== status back-fill ===")
    fixed = fix_migrated_status(conn, dry_run=dry_run)
    if fixed:
        logger.info(
            "  {} record(s) with missing x_status {}.",
            fixed,
            "would be fixed" if dry_run else "fixed",
        )
    else:
        logger.info("  No records with missing x_status.")
    logger.info("")

    if not to_migrate:
        if not dry_run:
            logger.success("Nothing to migrate.")
        else:
            logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    # Status distribution
    from collections import Counter

    status_counts: Counter[str] = Counter(g.get(_STATUS_FIELD) or "Watched" for g in to_migrate)
    logger.info("Status breakdown:")
    for status, count in sorted(status_counts.items()):
        gear_status = _GEAR_STATUS_MAP.get(status, "watching")
        listing_status = "acquired" if status in _ACQUIRED_STATUSES else "active"
        logger.info(
            "  {:20s} {:4d}  → x_gear({}) + x_listing({})",
            status,
            count,
            gear_status,
            listing_status,
        )
    logger.info("")

    if dry_run:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        gear_created, listing_created = apply_plan(conn, to_migrate, dry_run=True)
        logger.info(
            "Would create: {} x_gear record(s), {} x_listing record(s)",
            gear_created,
            listing_created,
        )
        return

    # ── Apply ───────────────────────────────────────────────────────────────
    logger.info("Applying migration…")
    gear_created, listing_created = apply_plan(conn, to_migrate, dry_run=False)
    logger.success(
        "Done — created {} x_gear record(s) and {} x_listing record(s).",
        gear_created,
        listing_created,
    )
