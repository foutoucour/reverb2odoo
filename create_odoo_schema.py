"""Add custom fields to x_gear, x_listing, and x_models.

Models must already exist (create them via Odoo Studio first).
This script only adds the application-specific fields that Studio
would not create automatically.

Idempotent: already-existing fields are silently skipped.

Usage (dry-run, default)::

    reverb2odoo add-model-fields

Usage (apply changes)::

    reverb2odoo add-model-fields --apply
"""

from __future__ import annotations

import click
from loguru import logger

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

#: Fields to add to x_listing (marketplace entry — primary sync record).
#: x_currency_id must be created before x_price / x_shipping (monetary dependency).
_LISTING_FIELDS: list[dict] = [
    {
        "name": "x_name",
        "field_description": "Listing Title",
        "ttype": "char",
        "required": True,
    },
    {
        "name": "x_model_id",
        "field_description": "Model",
        "ttype": "many2one",
        "relation": "x_models",
    },
    {
        "name": "x_url",
        "field_description": "URL",
        "ttype": "char",
    },
    {
        "name": "x_platform",
        "field_description": "Platform",
        "ttype": "selection",
        "selection": (
            "[('reverb', 'Reverb'), ('marketplace', 'Marketplace'),"
            " ('kijiji', 'Kijiji'), ('other', 'Other')]"
        ),
    },
    {
        "name": "x_currency_id",
        "field_description": "Currency",
        "ttype": "many2one",
        "relation": "res.currency",
    },
    {
        "name": "x_price",
        "field_description": "Price",
        "ttype": "monetary",
        "currency_field": "x_currency_id",
    },
    {
        "name": "x_shipping",
        "field_description": "Shipping",
        "ttype": "monetary",
        "currency_field": "x_currency_id",
    },
    {
        "name": "x_condition",
        "field_description": "Condition",
        "ttype": "selection",
        "selection": (
            "[('mint', 'Mint'), ('excellent', 'Excellent'), ('very_good', 'Very Good'),"
            " ('good', 'Good'), ('fair', 'Fair'), ('poor', 'Poor')]"
        ),
    },
    {
        "name": "x_status",
        "field_description": "Status",
        "ttype": "selection",
        "required": True,
        "selection": (
            "[('watching', 'Watching'), ('acquired', 'Acquired'), ('passed', 'Passed'),"
            " ('closed', 'Closed'), ('for_sale', 'For Sale'), ('sold', 'Sold')]"
        ),
    },
    {
        "name": "x_is_available",
        "field_description": "Is Available",
        "ttype": "boolean",
    },
    {
        "name": "x_can_accept_offers",
        "field_description": "Can Accept Offers",
        "ttype": "boolean",
    },
    {
        "name": "x_is_taxed",
        "field_description": "Is Taxed",
        "ttype": "boolean",
    },
    {
        "name": "x_published_at",
        "field_description": "Published At",
        "ttype": "datetime",
    },
    {
        "name": "x_gear_id",
        "field_description": "Gear",
        "ttype": "many2one",
        "relation": "x_gear",
    },
    {
        "name": "x_guitar_id",
        "field_description": "Source Guitar",
        "ttype": "many2one",
        "relation": "x_guitar",
    },
]

#: Fields to add to x_gear (physical item — created only on acquisition).
_GEAR_FIELDS: list[dict] = [
    {
        "name": "x_name",
        "field_description": "Gear Name",
        "ttype": "char",
        "required": True,
    },
    {
        "name": "x_model_id",
        "field_description": "Model",
        "ttype": "many2one",
        "relation": "x_models",
    },
    {
        "name": "x_intent",
        "field_description": "Intent",
        "ttype": "selection",
        "selection": "[('flip', 'Flip'), ('keeper', 'Keeper'), ('unknown', 'Unknown')]",
    },
    {
        "name": "x_condition",
        "field_description": "Condition",
        "ttype": "char",
    },
    {
        "name": "x_status",
        "field_description": "Status",
        "ttype": "selection",
        "required": True,
        "selection": "[('owned', 'Owned'), ('sold', 'Sold')]",
    },
    {
        "name": "x_serial_number",
        "field_description": "Serial Number",
        "ttype": "char",
    },
    {
        "name": "x_neck_profile",
        "field_description": "Neck Profile",
        "ttype": "char",
    },
]

#: Price bracket fields to add to the existing x_models model.
_MODELS_PRICE_FIELDS: list[dict] = [
    {
        "name": "x_price_p25",
        "field_description": "Price P25",
        "ttype": "float",
    },
    {
        "name": "x_price_p50",
        "field_description": "Price P50 (Median)",
        "ttype": "float",
    },
    {
        "name": "x_price_p75",
        "field_description": "Price P75",
        "ttype": "float",
    },
    {
        "name": "x_price_sample_size",
        "field_description": "Price Sample Size",
        "ttype": "integer",
    },
    {
        "name": "x_price_updated_at",
        "field_description": "Price Updated At",
        "ttype": "datetime",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_model_id(conn, model_name: str) -> int | None:
    """Return the ir.model id for *model_name*, or None if not found."""
    ir_model = conn.get_model("ir.model")
    results = ir_model.search_read([("model", "=", model_name)], ["id"], limit=1)
    return results[0]["id"] if results else None


def get_field_id(conn, model_id: int, field_name: str) -> int | None:
    """Return the ir.model.fields id for *field_name* on *model_id*, or None."""
    ir_fields = conn.get_model("ir.model.fields")
    results = ir_fields.search_read(
        [("model_id", "=", model_id), ("name", "=", field_name)],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_field(
    conn,
    model_id: int,
    api_name: str,
    field_def: dict,
    *,
    dry_run: bool,
) -> None:
    """Create *field_def* on *model_id* if it does not already exist."""
    field_name = field_def["name"]
    if get_field_id(conn, model_id, field_name):
        logger.info("    Field {}.{} already exists", api_name, field_name)
        return

    if dry_run:
        logger.info(
            "    [DRY-RUN] Would create field {}.{} ({})",
            api_name,
            field_name,
            field_def["ttype"],
        )
        return

    ir_fields = conn.get_model("ir.model.fields")
    ir_fields.create({**field_def, "model_id": model_id, "state": "manual"})
    logger.success("    Created field {}.{} ({})", api_name, field_name, field_def["ttype"])


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def create_schema(conn, *, dry_run: bool) -> None:
    """Add fields to x_gear, x_listing, and x_models.

    Models must already exist — create them via Odoo Studio first.

    Execution order:
    1. x_gear fields (physical item — no x_listing dependency).
    2. x_listing fields (marketplace entry — x_gear_id references x_gear).
    3. x_models price bracket fields.
    """
    # ── x_gear ──────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== x_gear fields ===")
    gear_model_id = get_model_id(conn, "x_gear")
    if gear_model_id is None:
        logger.error("x_gear not found — create it via Odoo Studio first")
        return
    for field_def in _GEAR_FIELDS:
        ensure_field(conn, gear_model_id, "x_gear", field_def, dry_run=dry_run)

    # ── x_listing ────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== x_listing fields ===")
    listing_model_id = get_model_id(conn, "x_listing")
    if listing_model_id is None:
        logger.error("x_listing not found — create it via Odoo Studio first")
        return
    for field_def in _LISTING_FIELDS:
        ensure_field(conn, listing_model_id, "x_listing", field_def, dry_run=dry_run)

    # ── x_models price bracket fields ────────────────────────────────────────
    logger.info("")
    logger.info("=== x_models price bracket fields ===")
    models_model_id = get_model_id(conn, "x_models")
    if models_model_id is None:
        logger.error("x_models not found — skipping price bracket fields")
        return
    for field_def in _MODELS_PRICE_FIELDS:
        ensure_field(conn, models_model_id, "x_models", field_def, dry_run=dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("add-model-fields")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Add custom fields to x_gear, x_listing, and x_models.

    Requires x_gear and x_listing to already exist (create them via Odoo Studio first).
    Fields that already exist are skipped.

    Runs in dry-run mode by default; pass --apply to write to Odoo.
    """
    conn = ctx.obj["conn"]
    dry_run = not apply

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written.  Pass --apply to apply.")

    create_schema(conn, dry_run=dry_run)

    logger.info("")
    if dry_run:
        logger.info("[DRY-RUN] Done.  Run with --apply to add the fields.")
    else:
        logger.success("Field creation complete.")
