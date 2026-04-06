"""Migrate x_guitar records into x_listing (and x_gear for owned items).

Each x_guitar record produces:
  - one ``x_listing`` record  (always — the marketplace entry)
  - one ``x_gear`` record     (only when the item was bought — Bought / For Sale / Sold)

Status mapping from ``x_studio_selection_field_7tf_1igs0n52h``:

  Watched        → x_listing(status=watching)
  Not Interested → x_listing(status=passed)
  Bought         → x_listing(status=acquired) + x_gear(status=owned)
  For Sale       → x_listing(status=acquired) + x_gear(status=owned)
  Sold           → x_listing(status=acquired) + x_gear(status=sold)
  (anything else) → x_listing(status=watching)

Skip logic: an x_guitar is skipped when an x_listing with the same URL already
exists, making the command safe to re-run after a partial failure.

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

#: x_guitar status values that require an x_gear record (item was acquired).
_OWNED_STATUSES = {"Bought", "For Sale", "Sold"}

#: x_guitar status → x_listing status
_LISTING_STATUS_MAP: dict[str, str] = {
    "Watched": "watching",
    "Not Interested": "passed",
    "Bought": "acquired",
    "For Sale": "acquired",
    "Sold": "acquired",
}

#: x_guitar status → x_gear status (only for _OWNED_STATUSES)
_GEAR_STATUS_MAP: dict[str, str] = {
    "Bought": "owned",
    "For Sale": "owned",
    "Sold": "sold",
}


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _fetch_all_guitars(conn) -> list[dict]:
    """Fetch all x_guitar records with migration-relevant fields."""
    guitar = conn.get_model("x_guitar")
    fields = GUITAR_FIELDS + [_STATUS_FIELD]
    return guitar.search_read([], fields, order="id asc")


def _fetch_existing_listing_urls(conn) -> set[str]:
    """Return all URLs already present in x_listing."""
    listing = conn.get_model("x_listing")
    records = listing.search_read([("x_url", "!=", False)], ["x_url"])
    return {r["x_url"] for r in records if r.get("x_url")}


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


def _guitar_to_listing_vals(guitar: dict) -> dict[str, Any]:
    """Build x_listing creation values from an x_guitar record."""
    raw_status = guitar.get(_STATUS_FIELD) or "Watched"
    listing_status = _LISTING_STATUS_MAP.get(raw_status, "watching")

    currency_ref = guitar.get("x_studio_currency_id")
    currency_id = _m2o_id(currency_ref)

    model_ref = guitar.get("x_studio_models")
    model_id = _m2o_id(model_ref)

    vals: dict[str, Any] = {
        "x_name": guitar.get("x_name", ""),
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
    if model_id:
        vals["x_model_id"] = model_id
    if currency_id:
        vals["x_currency_id"] = currency_id
    published = guitar.get("x_studio_published_at")
    if published:
        vals["x_published_at"] = published

    return vals


def _guitar_to_gear_vals(guitar: dict) -> dict[str, Any]:
    """Build x_gear creation values from an x_guitar record (owned items only)."""
    raw_status = guitar.get(_STATUS_FIELD) or "Watched"
    gear_status = _GEAR_STATUS_MAP[raw_status]  # caller must check _OWNED_STATUSES

    model_ref = guitar.get("x_studio_models")
    model_id = _m2o_id(model_ref)

    vals: dict[str, Any] = {
        "x_name": guitar.get("x_name", ""),
        "x_status": gear_status,
        "x_intent": "unknown",
    }
    if model_id:
        vals["x_model_id"] = model_id

    return vals


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compute_plan(conn) -> tuple[list[dict], int]:
    """Compute which x_guitar records still need migration.

    Returns
    -------
    to_migrate : list[dict]
        x_guitar records whose URL is not yet in x_listing.
    already_migrated : int
        Count of x_guitar records already present in x_listing (by URL).
    """
    logger.info("Fetching all x_guitar records…")
    all_guitars = _fetch_all_guitars(conn)
    logger.info("  {} x_guitar record(s) fetched", len(all_guitars))

    logger.info("Fetching existing x_listing URLs…")
    existing_urls = _fetch_existing_listing_urls(conn)
    logger.info("  {} x_listing URL(s) already present", len(existing_urls))

    to_migrate = []
    already_migrated = 0
    for g in all_guitars:
        url = g.get("x_studio_url", "")
        if url and url in existing_urls:
            already_migrated += 1
        else:
            to_migrate.append(g)

    logger.info("  {} x_guitar record(s) to migrate", len(to_migrate))
    logger.info("  {} x_guitar record(s) already migrated (will be skipped)", already_migrated)
    return to_migrate, already_migrated


def apply_plan(conn, to_migrate: list[dict], *, dry_run: bool) -> tuple[int, int]:
    """Create x_listing (and x_gear for owned items) for each unmigrated x_guitar.

    Returns
    -------
    (listing_created, gear_created) : tuple[int, int]
    """
    listing_model = conn.get_model("x_listing")
    gear_model = conn.get_model("x_gear")

    listing_created = 0
    gear_created = 0

    for guitar in to_migrate:
        guitar_id = guitar["id"]
        guitar_name = guitar.get("x_name", f"id={guitar_id}")
        raw_status = guitar.get(_STATUS_FIELD) or "Watched"
        needs_gear = raw_status in _OWNED_STATUSES

        listing_vals = _guitar_to_listing_vals(guitar)

        if dry_run:
            gear_note = f" + x_gear(status={_GEAR_STATUS_MAP[raw_status]})" if needs_gear else ""
            logger.info(
                "[DRY-RUN] x_guitar id={} '{}' → x_listing(status={}){}",
                guitar_id,
                guitar_name[:50],
                listing_vals["x_status"],
                gear_note,
            )
            listing_created += 1
            if needs_gear:
                gear_created += 1
            continue

        listing_id = listing_model.create(listing_vals)
        logger.info(
            "Created x_listing id={} (status={}) for x_guitar id={} '{}'",
            listing_id,
            listing_vals["x_status"],
            guitar_id,
            guitar_name[:50],
        )
        listing_created += 1

        if needs_gear:
            gear_vals = _guitar_to_gear_vals(guitar)
            gear_vals["x_listing_ids"] = [(4, listing_id)]  # link listing to gear
            gear_id = gear_model.create(gear_vals)
            listing_model.write([listing_id], {"x_gear_id": gear_id})
            logger.debug("  → x_gear id={} (status={})", gear_id, gear_vals["x_status"])
            gear_created += 1

    return listing_created, gear_created


# ---------------------------------------------------------------------------
# Back-fill helpers
# ---------------------------------------------------------------------------


def backfill_guitar_id(conn, *, dry_run: bool) -> int:
    """Set x_guitar_id on x_listing records that were migrated before the field existed.

    Matches listings to guitars by URL (x_listing.x_url == x_guitar.x_studio_url).
    Records that already have x_guitar_id set are skipped.

    Returns the number of listings updated (or that would be updated in dry-run).
    """
    listing_model = conn.get_model("x_listing")
    guitar_model = conn.get_model("x_guitar")

    missing = listing_model.search_read(
        [("x_guitar_id", "=", False), ("x_url", "!=", False)],
        ["id", "x_url"],
    )
    if not missing:
        logger.success("All x_listing records already have x_guitar_id set.")
        return 0

    logger.info("{} x_listing record(s) missing x_guitar_id", len(missing))

    guitars = guitar_model.search_read([("x_studio_url", "!=", False)], ["id", "x_studio_url"])
    url_to_guitar_id: dict[str, int] = {r["x_studio_url"]: r["id"] for r in guitars}

    updated = 0
    unmatched = 0
    for record in missing:
        guitar_id = url_to_guitar_id.get(record["x_url"])
        if guitar_id is None:
            logger.warning(
                "  No x_guitar match for x_listing id={} url={}", record["id"], record["x_url"]
            )
            unmatched += 1
            continue

        if dry_run:
            logger.info(
                "  [DRY-RUN] Would set x_listing id={}.x_guitar_id = {}", record["id"], guitar_id
            )
        else:
            listing_model.write([record["id"]], {"x_guitar_id": guitar_id})
            logger.debug("  x_listing id={} → x_guitar_id={}", record["id"], guitar_id)

        updated += 1

    if unmatched:
        logger.warning("{} listing(s) had no matching x_guitar (URL not found)", unmatched)

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
    """Migrate x_guitar records into x_listing (and x_gear for owned items).

    Runs in dry-run mode by default.  Pass --apply to write changes to Odoo.
    Records whose URL already exists in x_listing are skipped, making this
    safe to re-run after a partial failure.
    """
    conn = ctx.obj["conn"]

    to_migrate, already_migrated = compute_plan(conn)

    logger.info("")
    logger.info("=== MIGRATION PLAN ===")
    logger.info("Already migrated : {}", already_migrated)
    logger.info("To migrate       : {}", len(to_migrate))
    logger.info("")

    if not to_migrate:
        logger.success("Nothing to migrate.")
        return

    # Status breakdown
    from collections import Counter

    status_counts: Counter[str] = Counter(g.get(_STATUS_FIELD) or "Watched" for g in to_migrate)
    logger.info("Status breakdown:")
    for status, count in sorted(status_counts.items()):
        listing_status = _LISTING_STATUS_MAP.get(status, "watching")
        gear_note = (
            f" + x_gear(status={_GEAR_STATUS_MAP[status]})" if status in _OWNED_STATUSES else ""
        )
        logger.info(
            "  {:20s} {:4d}  → x_listing(status={}){}",
            status,
            count,
            listing_status,
            gear_note,
        )
    logger.info("")

    dry_run = not apply

    if dry_run:
        logger.info("[DRY-RUN] No changes written.  Pass --apply to apply.")

    listing_created, gear_created = apply_plan(conn, to_migrate, dry_run=dry_run)

    if dry_run:
        logger.info(
            "Would create: {} x_listing record(s), {} x_gear record(s)",
            listing_created,
            gear_created,
        )
    else:
        logger.success(
            "Done — created {} x_listing record(s) and {} x_gear record(s).",
            listing_created,
            gear_created,
        )


@click.command("backfill-guitar-id")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def backfill_guitar_id_cli(ctx: click.Context, apply: bool) -> None:
    """Back-fill x_guitar_id on x_listing records migrated before the field existed.

    Matches listings to their source x_guitar by URL.  Records that already
    have x_guitar_id set are skipped.

    Runs in dry-run mode by default; pass --apply to write to Odoo.
    """
    conn = ctx.obj["conn"]
    dry_run = not apply

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written.  Pass --apply to apply.")

    updated = backfill_guitar_id(conn, dry_run=dry_run)

    if dry_run:
        logger.info("[DRY-RUN] Would update {} x_listing record(s).", updated)
    else:
        logger.success("Updated {} x_listing record(s).", updated)
