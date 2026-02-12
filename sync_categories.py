"""
Sync Reverb categories into the ``x_reverb_category`` Odoo model.

Fetches the full flat category list from the Reverb API and creates any
categories that don't already exist in Odoo.  Existing categories (matched
by ``x_name``) are left untouched.
"""

from __future__ import annotations

import asyncio

import click
from loguru import logger

from odoo_connector import get_connection, search_read_all
from reverb_scraper import ReverbScraper

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CATEGORY_MODEL = "x_reverb_category"


def _make_slug(cat: dict) -> str:
    """Build a unique slug for a Reverb category.

    Root-level categories (where ``slug == root_slug``) keep their plain
    slug (e.g. ``"accessories"``).  Subcategories get a composite slug
    ``"root_slug/slug"`` (e.g. ``"acoustic-guitars/12-string"``) to
    guarantee uniqueness across root categories.
    """
    slug = cat.get("slug", "")
    root_slug = cat.get("root_slug", "")
    if slug == root_slug or not root_slug:
        return slug
    return f"{root_slug}/{slug}"


def _fetch_reverb_categories() -> list[dict]:
    """Fetch all categories from the Reverb API (sync wrapper)."""

    async def _fetch() -> list[dict]:
        async with ReverbScraper() as scraper:
            return await scraper.fetch_categories()

    return asyncio.run(_fetch())


def _fetch_existing(conn) -> dict[str, dict]:
    """Return existing Odoo categories keyed by ``x_name``."""
    records = search_read_all(
        conn,
        CATEGORY_MODEL,
        fields=["x_name", "x_studio_slug", "x_active"],
    )
    return {r["x_name"]: r for r in records}


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def sync_categories(*, dry_run: bool = False) -> int:
    """Fetch Reverb categories and create missing ones in Odoo.

    Returns the number of categories created.
    """
    # 1. Fetch from Reverb ------------------------------------------------------
    reverb_cats = _fetch_reverb_categories()
    if not reverb_cats:
        logger.error("No categories returned from Reverb — aborting.")
        return 0

    logger.info("Reverb categories fetched: {}", len(reverb_cats))

    # 2. Fetch existing Odoo records --------------------------------------------
    conn = get_connection()
    existing = _fetch_existing(conn)
    logger.info("Existing Odoo categories: {}", len(existing))

    # 3. Determine which categories to create -----------------------------------
    to_create: list[dict] = []
    for cat in reverb_cats:
        full_name = cat.get("full_name", "")
        if not full_name:
            continue
        if full_name in existing:
            continue
        to_create.append(cat)

    if not to_create:
        logger.success("All {} categories already exist — nothing to do.", len(reverb_cats))
        return 0

    logger.info("Categories to create: {}", len(to_create))

    if dry_run:
        for cat in to_create:
            logger.info(
                "  [DRY-RUN] would create: {} (slug: {})", cat["full_name"], _make_slug(cat)
            )
        return 0

    # 4. Create missing categories ----------------------------------------------
    model = conn.get_model(CATEGORY_MODEL)
    created = 0

    for i, cat in enumerate(to_create, 1):
        vals = {
            "x_name": cat["full_name"],
            "x_studio_slug": _make_slug(cat),
            "x_active": True,
        }
        try:
            new_id = model.create(vals)
            created += 1
            logger.debug(
                "  [{}/{}] Created id={}: {}",
                i,
                len(to_create),
                new_id,
                cat["full_name"],
            )
        except Exception as e:
            logger.error("  Failed to create '{}': {}", cat["full_name"], e)

    logger.success("Done — created {} / {} categories.", created, len(to_create))
    return created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("sync-categories")
@click.option("--dry-run", is_flag=True, help="Preview changes without writing to Odoo.")
def cli(dry_run: bool) -> None:
    """Sync Reverb categories into Odoo.

    Fetches the full flat category list from the Reverb API and creates
    any categories that don't already exist in the Odoo database.
    """
    sync_categories(dry_run=dry_run)


if __name__ == "__main__":
    cli()
