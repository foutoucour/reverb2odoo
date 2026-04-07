"""
Search Reverb for a given guitar model, then update existing Odoo entries
and create new ones.

The Reverb category filter is resolved automatically from the model's
``x_studio_reverb_category_id`` field in Odoo (e.g. "electric-guitars",
"effects-and-pedals").  Use ``--category`` to override, or
``--no-category`` to search across all categories.

Use ``--all`` to sync every model in the database at once, with
multi-threaded Reverb searching.
"""

from __future__ import annotations

import asyncio
import base64
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import click
import httpx
from loguru import logger
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from odoo_connector import LISTING_FIELDS
from reverb_scraper import ReverbScraper

_console = Console()

#: Default shipping cost assumed when Reverb does not return one.
DEFAULT_SHIPPING = 250.0

#: Default number of worker threads for ``--all`` mode.
DEFAULT_WORKERS = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_url(url: str) -> str:
    """Strip query-string from a URL for comparison purposes."""
    return url.split("?")[0]


def _reverb_item_id(url: str) -> str | None:
    """Extract the leading numeric Reverb item ID from a listing URL.

    ``https://reverb.com/item/94370297-godin-…`` → ``"94370297"``

    Returns ``None`` for non-Reverb or non-item URLs.
    """
    p = urlparse(url)
    parts = p.path.strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "item":
        segment = parts[-1].split("-")[0]
        if segment.isdigit():
            return segment
    return None


def _download_image_base64(photo_url: str) -> str | None:
    """Download an image from *photo_url* and return base64-encoded bytes.

    Used to populate the ``x_studio_image`` field in Odoo with the first
    photo from a Reverb listing.

    Returns ``None`` if the URL is empty or the download fails.
    """
    if not photo_url:
        return None
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(photo_url)
            response.raise_for_status()
            return base64.b64encode(response.content).decode("ascii")
    except Exception as e:
        logger.warning("Failed to download image from {}: {}", photo_url, e)
        return None


def _find_entries_without_image(conn, entry_ids: list[int]) -> set[int]:
    """Return the subset of *entry_ids* that have no ``x_studio_image`` set.

    Uses a single Odoo query with a domain filter so that image binary data
    is never transferred over the wire.
    """
    if not entry_ids:
        return set()
    listing = conn.get_model("x_listing")
    no_img = listing.search_read(
        [("id", "in", entry_ids), ("x_studio_image", "=", False)],
        ["id"],
    )
    return {r["id"] for r in no_img}


def _find_model(conn, model_name: str) -> dict[str, Any]:
    """Look up an ``x_models`` record by *model_name*.

    Uses a case-insensitive search (``ilike``).  Also resolves the linked
    ``x_reverb_category`` slug so it can be used as the default Reverb
    search category.

    Returns
    -------
    dict
        ``{"id": int, "category_slug": str | None,
        "default_shipping": float}``

    Raises
    ------
    SystemExit
        If the model name is not found or matches more than one record.
    """
    models = conn.get_model("x_models")
    fields = ["x_name", "x_studio_reverb_category_id"]
    results = models.search_read([("x_name", "ilike", model_name)], fields)

    if not results:
        logger.error("No model found matching '{}'", model_name)
        sys.exit(1)

    # Prefer an exact (case-insensitive) match when several rows come back.
    exact = [r for r in results if r["x_name"].lower() == model_name.lower()]
    if len(exact) == 1:
        record = exact[0]
    elif len(results) == 1:
        record = results[0]
    else:
        names = ", ".join(f"{r['x_name']!r} (id={r['id']})" for r in results)
        logger.error("Ambiguous model name '{}' — matches: {}", model_name, names)
        sys.exit(1)

    # Resolve category slug & default shipping from the linked record.
    category_slug: str | None = None
    default_shipping: float = DEFAULT_SHIPPING
    cat_ref = record.get("x_studio_reverb_category_id")
    if cat_ref:
        cat_id = cat_ref[0] if isinstance(cat_ref, (list, tuple)) else cat_ref
        cat_model = conn.get_model("x_reverb_category")
        cat_fields = ["x_studio_slug", "x_studio_shipping_default_price"]
        cat_records = cat_model.search_read([("id", "=", cat_id)], cat_fields)
        if cat_records:
            category_slug = cat_records[0].get("x_studio_slug") or None
            cat_ship = cat_records[0].get("x_studio_shipping_default_price")
            if cat_ship:
                default_shipping = float(cat_ship)

    return {
        "id": record["id"],
        "category_slug": category_slug,
        "default_shipping": default_shipping,
    }


def _fetch_listings(conn, model_id: int) -> list[dict]:
    """Return all ``x_listing`` records linked to *model_id*."""
    listing = conn.get_model("x_listing")
    return listing.search_read([("x_model_id", "=", model_id)], LISTING_FIELDS)


def _fetch_all_models(conn, *, wanna_only: bool = False) -> list[dict[str, Any]]:
    """Fetch every ``x_models`` record and resolve category / shipping info.

    Parameters
    ----------
    conn
        Odoo XML-RPC connection wrapper.
    wanna_only : bool
        When *True*, only return models whose ``x_studio_wanna`` field is
        set.  This lets you sync just the models you have flagged as
        "wanted" in Odoo.

    Returns a list of dicts, each with the same shape as
    :func:`_find_model`:

    - ``id`` – model record ID
    - ``name`` – model display name
    - ``category_slug`` – Reverb category slug (or ``None``)
    - ``default_shipping`` – fallback shipping cost
    """
    models = conn.get_model("x_models")
    fields = ["x_name", "x_studio_reverb_category_id"]
    domain: list = [("x_studio_wanna", "=", True)] if wanna_only else []
    records = models.search_read(domain, fields)

    if not records:
        logger.warning("No models found in Odoo.")
        return []

    # Collect all referenced category IDs for a single bulk fetch.
    cat_ids: set[int] = set()
    for rec in records:
        cat_ref = rec.get("x_studio_reverb_category_id")
        if cat_ref:
            cat_ids.add(cat_ref[0] if isinstance(cat_ref, (list, tuple)) else cat_ref)

    cat_map: dict[int, dict] = {}
    if cat_ids:
        cat_model = conn.get_model("x_reverb_category")
        cat_fields = ["x_studio_slug", "x_studio_shipping_default_price"]
        cat_records = cat_model.search_read([("id", "in", list(cat_ids))], cat_fields)
        for c in cat_records:
            cat_map[c["id"]] = c

    result: list[dict[str, Any]] = []
    for rec in records:
        category_slug: str | None = None
        default_shipping: float = DEFAULT_SHIPPING

        cat_ref = rec.get("x_studio_reverb_category_id")
        if cat_ref:
            cat_id = cat_ref[0] if isinstance(cat_ref, (list, tuple)) else cat_ref
            cat_rec = cat_map.get(cat_id)
            if cat_rec:
                category_slug = cat_rec.get("x_studio_slug") or None
                cat_ship = cat_rec.get("x_studio_shipping_default_price")
                if cat_ship:
                    default_shipping = float(cat_ship)

        result.append(
            {
                "id": rec["id"],
                "name": rec.get("x_name", ""),
                "category_slug": category_slug,
                "default_shipping": default_shipping,
            }
        )

    logger.info("Found {} model(s) in Odoo", len(result))
    return result


# ---------------------------------------------------------------------------
# Reverb search
# ---------------------------------------------------------------------------


def _search_reverb(
    query: str,
    *,
    category: str | None = None,
    default_shipping: float = DEFAULT_SHIPPING,
    include_sold: bool = False,
) -> list[dict]:
    """Search Reverb for *query* and return deduplicated results.

    Args:
        query: Free-text search string.
        category: Reverb product-type slug (e.g. ``"electric-guitars"``).
                  ``None`` searches across all categories.
        default_shipping: Fallback shipping cost (from the Reverb category)
                          used when no rate is found for the target region.
        include_sold: When *True*, searches ``state='all'`` to capture both
                      live and sold listings.  Defaults to live-only.
    """
    shipping_str = f"{default_shipping:.2f}"
    state = "all" if include_sold else "live"

    async def _fetch() -> list[dict]:
        async with ReverbScraper(
            currency="CAD",
            shipping_region="CA",
            default_shipping=shipping_str,
        ) as scraper:
            return await scraper.search(query, category=category, state=state)

    raw = asyncio.run(_fetch())

    seen: set[str] = set()
    unique: list[dict] = []
    for r in raw:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    logger.debug("Reverb search '{}': {} unique listing(s)", query, len(unique))
    return unique


# ---------------------------------------------------------------------------
# Diff / compare
# ---------------------------------------------------------------------------


def _compute_changes(entry: dict, reverb: dict) -> dict[str, Any]:
    """Compare a single Odoo x_listing entry against scraped Reverb data.

    Returns a dict of ``{field_name: new_value}`` for every field that
    needs updating.  An empty dict means no changes.
    """
    changes: dict[str, Any] = {}

    sale_ended = reverb.get("sale_ended", False)
    price = float(reverb.get("price", 0) or 0)
    offers = reverb.get("offers_enabled", False)
    published_at = reverb.get("published_at", "")

    # Name
    reverb_name = reverb.get("name", "")
    if reverb_name and reverb_name != entry.get("x_name", ""):
        changes["x_name"] = reverb_name

    # Price — compare rounded to absorb CAD/USD conversion noise
    if price > 0 and _round_price(price) != _round_price(entry.get("x_price", 0)):
        changes["x_price"] = _round_price(price)

    # Offers
    if offers != entry.get("x_can_accept_offers"):
        changes["x_can_accept_offers"] = offers

    # Published at — only set if not already stored
    if published_at and not entry.get("x_published_at"):
        changes["x_published_at"] = published_at + " 00:00:00"

    # Availability
    if sale_ended and entry.get("x_is_available") is True:
        changes["x_is_available"] = False

    if not sale_ended:
        if entry.get("x_is_available") is False:
            changes["x_is_available"] = True

        # Only update shipping for live listings (Reverb returns None for ended)
        ship = reverb.get("shipping_price")
        if ship is not None:
            ship_f = float(ship)
            if _round_price(ship_f) != _round_price(entry.get("x_shipping", 0)):
                changes["x_shipping"] = _round_price(ship_f)

    return changes


def _reverb_to_listing_vals(
    reverb: dict,
    model_id: int,
    default_shipping: float = DEFAULT_SHIPPING,
) -> dict[str, Any]:
    """Build x_listing creation values from a scraped Reverb listing."""
    price = float(reverb.get("price", 0) or 0)
    ship = reverb.get("shipping_price")
    ship_f = float(ship) if ship is not None else default_shipping
    published = reverb.get("published_at", "")

    vals: dict[str, Any] = {
        "x_name": reverb.get("name", ""),
        "x_model_id": model_id,
        "x_status": "watching",
        "x_url": reverb.get("url", ""),
        "x_platform": "reverb",
        "x_price": _round_price(price),
        "x_shipping": _round_price(ship_f),
        "x_is_available": not reverb.get("sale_ended", False),
        "x_can_accept_offers": reverb.get("offers_enabled", False),
        "x_is_taxed": False,
    }
    if published:
        vals["x_published_at"] = published + " 00:00:00"

    return vals


def _round_price(price: float) -> float:
    """Round *price* to the nearest $10 to absorb currency-conversion noise."""
    return round(price / 10) * 10


def _is_brand_new(reverb: dict) -> bool:
    """Return *True* if the Reverb listing is labelled "Brand New"."""
    return reverb.get("condition", "").lower() == "brand new"


def _build_report(
    reverb_results: list[dict],
    odoo_entries: list[dict],
    model_id: int,
    default_shipping: float = DEFAULT_SHIPPING,
    *,
    include_brand_new: bool = False,
) -> list[dict]:
    """Cross-reference Reverb search results against existing Odoo entries.

    Each item in the returned list has:

    - ``action``:  ``"create"`` | ``"update"`` | ``"ok"`` | ``"skip"``
    - ``reverb``:  the scraped Reverb dict
    - ``entry``:   the matching Odoo dict (or ``None`` for new)
    - ``changes``: field updates for ``"update"``
    - ``create_vals``: full values dict for ``"create"``
    - ``warnings``: list of informational strings

    Brand-new listings that do not already exist in Odoo are skipped by
    default.  Pass ``include_brand_new=True`` to create them as well.
    """
    odoo_by_url: dict[str, dict] = {}
    odoo_by_item_id: dict[str, dict] = {}
    for e in odoo_entries:
        clean = _clean_url(e.get("x_url", ""))
        odoo_by_url[clean] = e
        item_id = _reverb_item_id(clean)
        if item_id:
            odoo_by_item_id[item_id] = e

    report: list[dict] = []

    for r in reverb_results:
        url = r.get("url", "")
        item: dict[str, Any] = {
            "reverb": r,
            "entry": None,
            "changes": {},
            "create_vals": {},
            "warnings": [],
            "action": "skip",
        }

        if "error" in r:
            item["warnings"].append(f"Reverb API error: {r['error']}")
            report.append(item)
            continue

        existing = odoo_by_url.get(_clean_url(url))
        if not existing:
            item_id = _reverb_item_id(url)
            if item_id:
                existing = odoo_by_item_id.get(item_id)

        if existing:
            item["entry"] = existing
            item["changes"] = _compute_changes(existing, r)
            item["action"] = "update" if item["changes"] else "ok"
        elif _is_brand_new(r) and not include_brand_new:
            item["action"] = "skip"
            item["warnings"].append("skipped: brand new")
        else:
            item["create_vals"] = _reverb_to_listing_vals(r, model_id, default_shipping)
            item["action"] = "create"

        # Informational warnings
        if r.get("sale_ended"):
            item["warnings"].append(f"status: {r.get('status', 'ended/sold')}")
        if r.get("ships_to_canada") is False and not r.get("sale_ended"):
            item["warnings"].append("does NOT ship to Canada")

        report.append(item)

    return report


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _print_report(report: list[dict]) -> tuple[int, int]:
    """Print a rich sync report table.  Returns (update_count, create_count)."""
    from rich.table import Table

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold", highlight=False)
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Action", width=9)
    table.add_column("Price", width=14)
    table.add_column("Name")
    table.add_column("Info", style="dim")

    update_count = 0
    create_count = 0

    for i, item in enumerate(report, 1):
        r = item["reverb"]
        name = escape(r.get("name", "")[:54])
        price = escape(r.get("price_display", "") or "")
        warnings = item["warnings"]
        warn_str = escape("; ".join(warnings)) if warnings else ""

        if item["action"] == "create":
            create_count += 1
            table.add_row(str(i), "[bold green]+ NEW[/bold green]", price, name, warn_str)
        elif item["action"] == "update":
            update_count += 1
            eid = item["entry"]["id"]
            info = escape(f"id={eid}  {warn_str}".strip())
            table.add_row(str(i), "[bold yellow]~ UPD[/bold yellow]", price, name, info)
            for field, new_val in item["changes"].items():
                old_val = item["entry"].get(field, "—")
                diff = (
                    f"  [dim]{escape(field)}:[/dim]"
                    f" {escape(str(old_val))} [dim]→[/dim] [bold]{escape(str(new_val))}[/bold]"
                )
                table.add_row("", "", "", diff, "")
        elif item["action"] == "ok":
            pass  # counted in summary; not shown to reduce noise
        else:
            table.add_row(str(i), "[dim]⚠ SKIP[/dim]", price, name, warn_str)

    _console.print()
    _console.print(table)
    skip_count = sum(1 for item in report if item["action"] == "skip")
    ok_count = len(report) - update_count - create_count - skip_count
    _console.print(
        f"  Total: [bold]{len(report)}[/bold]"
        f"  Up to date: [green]{ok_count}[/green]"
        f"  Update: [yellow]{update_count}[/yellow]"
        f"  New: [bold green]{create_count}[/bold green]"
    )
    return update_count, create_count


# ---------------------------------------------------------------------------
# Write to Odoo
# ---------------------------------------------------------------------------


def _apply_updates(conn, report: list[dict]) -> tuple[int, int]:
    """Write changes (updates + creates) to Odoo.

    For **creates**, an ``x_listing`` record is created with all marketplace
    fields.  The first Reverb listing photo is downloaded and stored in
    ``x_listing.x_studio_image``.

    For **updates**, the ``x_listing`` record is updated directly.  The image
    is only downloaded when the existing record has no image yet.

    Returns (updated, created).
    """
    listing_model = conn.get_model("x_listing")

    # Pre-check: which listing entries being updated lack an image?
    update_ids = [item["entry"]["id"] for item in report if item["action"] == "update"]
    ids_without_image = _find_entries_without_image(conn, update_ids)

    updated = 0
    created = 0

    for item in report:
        if item["action"] == "update":
            eid = item["entry"]["id"]
            changes = dict(item["changes"])

            # Download image if the listing has no image yet
            if eid in ids_without_image:
                photo_url = item.get("reverb", {}).get("photo_url", "")
                image_b64 = _download_image_base64(photo_url)
                if image_b64:
                    changes["x_studio_image"] = image_b64
                    logger.info("  ↳ downloaded image for listing id={}", eid)

            # Log changes without the (potentially huge) image blob
            log_changes = {k: v for k, v in changes.items() if k != "x_studio_image"}
            logger.info("Updating listing id={}: {}", eid, log_changes)
            listing_model.write(eid, changes)
            updated += 1

        elif item["action"] == "create":
            listing_vals = dict(item["create_vals"])

            # Download image
            photo_url = item.get("reverb", {}).get("photo_url", "")
            image_b64 = _download_image_base64(photo_url)
            if image_b64:
                listing_vals["x_studio_image"] = image_b64

            listing_id = listing_model.create(listing_vals)
            if image_b64:
                logger.info("  ↳ downloaded image for listing id={}", listing_id)
            logger.success(
                "Created listing id={}: {}", listing_id, listing_vals.get("x_name", "")[:50]
            )
            created += 1

    return updated, created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


#: Sentinel indicating the user did not pass ``--category`` or
#: ``--no-category``, so we should use the value from the database.
_CATEGORY_FROM_DB = object()


def _collect_sync_data(
    conn,
    *,
    model_id: int,
    model_name: str,
    category_slug: str | None,
    default_shipping: float,
    search_query: str | None = None,
    include_brand_new: bool = False,
    include_sold: bool = False,
) -> dict[str, Any]:
    """Search Reverb and fetch Odoo entries for a single model.

    This is the **I/O-heavy** phase and is safe to run inside a thread.

    Returns a dict with keys:

    - ``model_id``, ``model_name``, ``default_shipping`` – echo back inputs
    - ``reverb_results`` – deduplicated Reverb search results
    - ``odoo_entries`` – existing Odoo guitar records
    - ``report`` – cross-reference report list
    - ``update_count``, ``create_count`` – action tallies
    """
    query = search_query or model_name
    logger.debug("[{}] Searching Reverb for '{}'…", model_name, query)
    reverb_results = _search_reverb(
        query,
        category=category_slug,
        default_shipping=default_shipping,
        include_sold=include_sold,
    )

    if not reverb_results:
        logger.warning("[{}] No Reverb results for '{}'", model_name, query)
        return {
            "model_id": model_id,
            "model_name": model_name,
            "default_shipping": default_shipping,
            "reverb_results": [],
            "odoo_entries": [],
            "report": [],
            "update_count": 0,
            "create_count": 0,
        }

    logger.debug("[{}] Fetching existing Odoo listing records…", model_name)
    odoo_entries = _fetch_listings(conn, model_id)
    logger.debug("[{}] Found {} existing listing records", model_name, len(odoo_entries))

    report = _build_report(
        reverb_results,
        odoo_entries,
        model_id,
        default_shipping,
        include_brand_new=include_brand_new,
    )
    update_count = sum(1 for item in report if item["action"] == "update")
    create_count = sum(1 for item in report if item["action"] == "create")

    return {
        "model_id": model_id,
        "model_name": model_name,
        "default_shipping": default_shipping,
        "reverb_results": reverb_results,
        "odoo_entries": odoo_entries,
        "report": report,
        "update_count": update_count,
        "create_count": create_count,
    }


@click.command("sync")
@click.argument("model_name", required=False, default=None)
@click.option("--all", "all_models", is_flag=True, help="Sync every model in the database.")
@click.option("--search", "search_query", default=None, help="Override the Reverb search query.")
@click.option(
    "--category",
    default=None,
    help="Reverb category slug override (e.g. 'electric-guitars').",
)
@click.option(
    "--no-category",
    "no_category",
    is_flag=True,
    help="Search across all Reverb categories.",
)
@click.option(
    "--include-brand-new",
    "include_brand_new",
    is_flag=True,
    help="Also create brand-new listings (skipped by default).",
)
@click.option(
    "--include-sold",
    "include_sold",
    is_flag=True,
    help="Include sold/ended listings in the Reverb search (default: live only).",
)
@click.option("--dry-run", is_flag=True, help="Preview changes without writing to Odoo.")
@click.option("--yes", "-y", "auto_yes", is_flag=True, help="Skip confirmation prompts.")
@click.option(
    "--wanna",
    is_flag=True,
    help="Only sync models flagged as 'wanna' (x_studio_wanna) in Odoo. Implies --all.",
)
@click.option(
    "--workers",
    type=int,
    default=DEFAULT_WORKERS,
    show_default=True,
    help="Number of worker threads for --all mode.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    model_name: str | None,
    all_models: bool,
    search_query: str | None,
    category: str | None,
    no_category: bool,
    include_brand_new: bool,
    include_sold: bool,
    dry_run: bool,
    auto_yes: bool,
    wanna: bool,
    workers: int,
) -> None:
    """Search Reverb for MODEL_NAME, then update/create entries in Odoo.

    MODEL_NAME is the guitar model to sync (e.g. "Frank Brothers Arcane").
    Use --all to sync every model in the database at once.
    """
    # --wanna implies --all
    if wanna:
        all_models = True

    if not all_models and not model_name:
        raise click.UsageError("Provide a MODEL_NAME or use --all.")

    # Resolve category: --no-category → None, --category X → X, else → from DB
    if no_category:
        effective_category: Any = None
    elif category is not None:
        effective_category = category
    else:
        effective_category = _CATEGORY_FROM_DB

    conn = ctx.obj["conn"]

    # --all: sync every model in the database (multi-threaded) -----------------
    if all_models:
        all_model_info = _fetch_all_models(conn, wanna_only=wanna)
        if not all_model_info:
            logger.warning("No models found — nothing to do.")
            return

        n_workers = min(workers, len(all_model_info))
        logger.info(
            "Syncing {} model(s) with {} worker thread(s)…",
            len(all_model_info),
            n_workers,
        )

        # Phase 1 — collect data in parallel (I/O-heavy) ----------------------
        collected: list[dict[str, Any]] = [{}] * len(all_model_info)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=_console,
        ) as progress:
            task = progress.add_task(
                f"[cyan]Fetching Reverb data[/cyan] ({n_workers} workers)…",
                total=len(all_model_info),
            )
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                future_to_idx = {
                    pool.submit(
                        _collect_sync_data,
                        conn,
                        model_id=mi["id"],
                        model_name=mi["name"],
                        category_slug=mi["category_slug"],
                        default_shipping=mi["default_shipping"],
                        search_query=search_query,
                        include_brand_new=include_brand_new,
                        include_sold=include_sold,
                    ): idx
                    for idx, mi in enumerate(all_model_info)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        collected[idx] = future.result()
                    # catch all to avoid crashing the whole batch
                    # It is hard to predict what might go wrong in the scraping phase,
                    # and we want to continue processing other models even if one fails.
                    except Exception:  # noqa
                        mi = all_model_info[idx]
                        _console.print(
                            f"  [bold red]✗[/bold red] [red]Error collecting data for"
                            f" '{escape(mi['name'])}' (id={mi['id']})[/red]"
                        )
                        collected[idx] = {
                            "model_id": mi["id"],
                            "model_name": mi["name"],
                            "default_shipping": mi["default_shipping"],
                            "reverb_results": [],
                            "odoo_entries": [],
                            "report": [],
                            "update_count": 0,
                            "create_count": 0,
                        }
                    progress.advance(task)

        # Phase 2 — print reports & apply updates sequentially -----------------
        total_updated = 0
        total_created = 0
        for i, data in enumerate(collected, 1):
            total_actions = data["update_count"] + data["create_count"]

            # Compact one-liner for models with nothing to do
            if not data["report"] or total_actions == 0:
                if not data["report"]:
                    note = "[dim]no Reverb results[/dim]"
                else:
                    ok_count = sum(1 for item in data["report"] if item["action"] == "ok")
                    note = f"[dim]{ok_count} listing(s) up to date[/dim]"
                _console.print(
                    f"  [dim][{i}/{len(collected)}][/dim]  {escape(data['model_name'])}"
                    f"  [green]✓[/green]  {note}"
                )
                continue

            _console.print()
            _console.rule(
                f"[bold]\\[{i}/{len(collected)}][/bold]  {escape(data['model_name'])}"
                f"  [dim](id={data['model_id']})[/dim]"
            )

            update_count, create_count = _print_report(data["report"])
            total_actions = update_count + create_count

            if dry_run:
                logger.info("Dry-run mode — no changes written to Odoo.")
                continue

            if not auto_yes:
                click.confirm(
                    f"\n  Apply {update_count} update(s) and {create_count} create(s) to Odoo?",
                    abort=True,
                )

            upd, crt = _apply_updates(conn, data["report"])
            logger.success("Done — updated: {}  |  created: {}", upd, crt)
            total_updated += upd
            total_created += crt

        logger.success(
            "All models synced — updated: {}  |  created: {} total.",
            total_updated,
            total_created,
        )
        return

    # Single model -------------------------------------------------------------
    assert model_name is not None  # guaranteed by validation above

    # 1. Connect & resolve model ------------------------------------------------
    model_info = _find_model(conn, model_name)
    model_id = model_info["id"]
    logger.info("Resolved model '{}' → x_models id={}", model_name, model_id)

    # 2. Resolve category & default shipping ------------------------------------
    default_shipping = model_info["default_shipping"]
    if effective_category is _CATEGORY_FROM_DB:
        resolved_category = model_info["category_slug"]
        if resolved_category:
            logger.info("Category from database: {}", resolved_category)
        else:
            logger.warning("No Reverb category set on model — searching all categories")
    else:
        resolved_category = effective_category
        if resolved_category:
            logger.info("Category override: {}", resolved_category)

    logger.info("Default shipping: C${:.2f}", default_shipping)

    # 3. Collect data (search Reverb + fetch Odoo) ------------------------------
    data = _collect_sync_data(
        conn,
        model_id=model_id,
        model_name=model_name,
        category_slug=resolved_category,
        default_shipping=default_shipping,
        search_query=search_query,
        include_brand_new=include_brand_new,
        include_sold=include_sold,
    )

    if not data["reverb_results"]:
        logger.warning("No Reverb results for '{}' — nothing to do.", search_query or model_name)
        return

    # 4. Compare ----------------------------------------------------------------
    update_count, create_count = _print_report(data["report"])

    total_actions = update_count + create_count
    if total_actions == 0:
        logger.success("Everything is up to date — nothing to do.")
        return

    if dry_run:
        logger.info("Dry-run mode — no changes written to Odoo.")
        return

    # 5. Confirm & apply --------------------------------------------------------
    if not auto_yes:
        click.confirm(
            f"\n  Apply {update_count} update(s) and {create_count} create(s) to Odoo?",
            abort=True,
        )

    upd, crt = _apply_updates(conn, data["report"])
    logger.success("Done — updated: {}  |  created: {}", upd, crt)


if __name__ == "__main__":
    cli()
