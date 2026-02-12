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
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click
from loguru import logger

from odoo_connector import GUITAR_FIELDS, get_connection
from reverb_scraper import ReverbScraper

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
        cat_fields = ["x_studio_slug", "x_studio_default_shipping_price"]
        cat_records = cat_model.search_read([("id", "=", cat_id)], cat_fields)
        if cat_records:
            category_slug = cat_records[0].get("x_studio_slug") or None
            cat_ship = cat_records[0].get("x_studio_default_shipping_price")
            if cat_ship:
                default_shipping = float(cat_ship)

    return {
        "id": record["id"],
        "category_slug": category_slug,
        "default_shipping": default_shipping,
    }


def _fetch_guitars(conn, model_id: int) -> list[dict]:
    """Return all ``x_guitar`` records linked to *model_id*."""
    guitar = conn.get_model("x_guitar")
    return guitar.search_read(
        [("x_studio_models", "=", model_id)],
        GUITAR_FIELDS,
    )


def _fetch_all_models(conn) -> list[dict[str, Any]]:
    """Fetch every ``x_models`` record and resolve category / shipping info.

    Returns a list of dicts, each with the same shape as
    :func:`_find_model`:

    - ``id`` – model record ID
    - ``name`` – model display name
    - ``category_slug`` – Reverb category slug (or ``None``)
    - ``default_shipping`` – fallback shipping cost
    """
    models = conn.get_model("x_models")
    fields = ["x_name", "x_studio_reverb_category_id"]
    records = models.search_read([], fields)

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
        cat_fields = ["x_studio_slug", "x_studio_default_shipping_price"]
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
                cat_ship = cat_rec.get("x_studio_default_shipping_price")
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
) -> list[dict]:
    """Search Reverb for *query* and return deduplicated results.

    Args:
        query: Free-text search string.
        category: Reverb product-type slug (e.g. ``"electric-guitars"``).
                  ``None`` searches across all categories.
        default_shipping: Fallback shipping cost (from the Reverb category)
                          used when no rate is found for the target region.

    Searches ``state='all'`` to capture both live and sold listings.
    """
    shipping_str = f"{default_shipping:.2f}"

    async def _fetch() -> list[dict]:
        async with ReverbScraper(
            currency="CAD",
            shipping_region="CA",
            default_shipping=shipping_str,
        ) as scraper:
            return await scraper.search(query, category=category, state="all")

    raw = asyncio.run(_fetch())

    seen: set[str] = set()
    unique: list[dict] = []
    for r in raw:
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(r)

    logger.info("Reverb search '{}': {} unique listing(s)", query, len(unique))
    return unique


# ---------------------------------------------------------------------------
# Diff / compare
# ---------------------------------------------------------------------------


def _compute_changes(entry: dict, reverb: dict) -> dict[str, Any]:
    """Compare a single Odoo entry against scraped Reverb data.

    Returns a dict of ``{field_name: new_value}`` for every field that
    needs updating.  An empty dict means no changes.
    """
    changes: dict[str, Any] = {}

    sale_ended = reverb.get("sale_ended", False)
    price = float(reverb.get("price", 0) or 0)
    offers = reverb.get("offers_enabled", False)
    published_at = reverb.get("published_at", "")

    # Price (x_studio_value)
    if price > 0 and abs(price - entry.get("x_studio_value", 0)) > 0.01:
        changes["x_studio_value"] = price

    # Offers
    if offers != entry.get("x_studio_accept_offers"):
        changes["x_studio_accept_offers"] = offers

    # Published at
    if published_at:
        new_val = published_at + " 00:00:00"
        if entry.get("x_studio_published_at_1") != new_val:
            changes["x_studio_published_at_1"] = new_val

    # Availability
    if sale_ended and entry.get("x_studio_is_available") is True:
        changes["x_studio_is_available"] = False

    if not sale_ended:
        if entry.get("x_studio_is_available") is False:
            changes["x_studio_is_available"] = True

        # Only update shipping for live listings (Reverb returns None for ended)
        ship = reverb.get("shipping_price")
        if ship is not None:
            ship_f = float(ship)
            if abs(ship_f - entry.get("x_studio_shipping", 0)) > 0.01:
                changes["x_studio_shipping"] = ship_f

    return changes


def _reverb_to_odoo_vals(
    reverb: dict,
    model_id: int,
    default_shipping: float = DEFAULT_SHIPPING,
) -> dict[str, Any]:
    """Convert a scraped Reverb listing to Odoo field values for creation."""
    price = float(reverb.get("price", 0) or 0)
    ship = reverb.get("shipping_price")
    ship_f = float(ship) if ship is not None else default_shipping
    published = reverb.get("published_at", "")

    vals: dict[str, Any] = {
        "x_name": reverb.get("name", ""),
        "x_studio_url": reverb.get("url", ""),
        "x_studio_models": model_id,
        "x_studio_model_type": "Guitar",
        "x_studio_value": price,
        "x_studio_shipping": ship_f,
        "x_studio_is_available": not reverb.get("sale_ended", False),
        "x_studio_active": True,
        "x_studio_accept_offers": reverb.get("offers_enabled", False),
        "x_studio_taxed": False,
    }
    if published:
        vals["x_studio_published_at_1"] = published + " 00:00:00"

    return vals


def _build_report(
    reverb_results: list[dict],
    odoo_entries: list[dict],
    model_id: int,
    default_shipping: float = DEFAULT_SHIPPING,
) -> list[dict]:
    """Cross-reference Reverb search results against existing Odoo entries.

    Each item in the returned list has:

    - ``action``:  ``"create"`` | ``"update"`` | ``"ok"`` | ``"skip"``
    - ``reverb``:  the scraped Reverb dict
    - ``entry``:   the matching Odoo dict (or ``None`` for new)
    - ``changes``: field updates for ``"update"``
    - ``create_vals``: full values dict for ``"create"``
    - ``warnings``: list of informational strings
    """
    odoo_by_url: dict[str, dict] = {}
    for e in odoo_entries:
        odoo_by_url[_clean_url(e.get("x_studio_url", ""))] = e

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

        if existing:
            item["entry"] = existing
            item["changes"] = _compute_changes(existing, r)
            item["action"] = "update" if item["changes"] else "ok"
        else:
            item["create_vals"] = _reverb_to_odoo_vals(r, model_id, default_shipping)
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
    """Print a human-readable sync report.  Returns (update_count, create_count)."""
    sep = "=" * 100
    print(f"\n{sep}")
    print(f"{'#':<4} {'Action':<10} {'Price':<14} {'Name':<55} {'Info'}")
    print(sep)

    update_count = 0
    create_count = 0

    for i, item in enumerate(report, 1):
        r = item["reverb"]
        name = r.get("name", "")[:54]
        price = r.get("price_display", "")
        warnings = item["warnings"]
        warn_str = "; ".join(warnings) if warnings else ""

        if item["action"] == "create":
            create_count += 1
            print(f"{i:<4} {'+ NEW':<10} {price:<14} {name:<55} {warn_str}")
        elif item["action"] == "update":
            update_count += 1
            eid = item["entry"]["id"]
            print(f"{i:<4} {'~ UPD':<10} {price:<14} {name:<55} id={eid}  {warn_str}")
            for field, new_val in item["changes"].items():
                old_val = item["entry"].get(field, "—")
                print(f"{'':>4} {'':>10} {'':>14}   {field}: {old_val} → {new_val}")
        elif item["action"] == "ok":
            eid = item["entry"]["id"]
            print(f"{i:<4} {'✓ OK':<10} {price:<14} {name:<55} id={eid}  {warn_str}")
        else:
            print(f"{i:<4} {'⚠ SKIP':<10} {price:<14} {name:<55} {warn_str}")

    print(sep)
    skip_count = sum(1 for i in report if i["action"] == "skip")
    ok_count = len(report) - update_count - create_count - skip_count
    print(
        f"\n  Total: {len(report)}  |  Up to date: {ok_count}"
        f"  |  Update: {update_count}  |  New: {create_count}"
    )
    return update_count, create_count


# ---------------------------------------------------------------------------
# Write to Odoo
# ---------------------------------------------------------------------------


def _apply_updates(conn, report: list[dict]) -> tuple[int, int]:
    """Write changes (updates + creates) to Odoo.

    Returns (updated, created).
    """
    guitar = conn.get_model("x_guitar")
    updated = 0
    created = 0

    for item in report:
        if item["action"] == "update":
            eid = item["entry"]["id"]
            logger.info("Updating id={}: {}", eid, item["changes"])
            guitar.write(eid, item["changes"])
            updated += 1
        elif item["action"] == "create":
            vals = item["create_vals"]
            logger.info("Creating: {}", vals.get("x_name", "")[:50])
            new_id = guitar.create(vals)
            logger.success("  → created id={}", new_id)
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
    logger.info("[{}] Searching Reverb for '{}'…", model_name, query)
    reverb_results = _search_reverb(
        query,
        category=category_slug,
        default_shipping=default_shipping,
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

    logger.info("[{}] Fetching existing Odoo entries…", model_name)
    odoo_entries = _fetch_guitars(conn, model_id)
    logger.info("[{}] Found {} existing entries", model_name, len(odoo_entries))

    report = _build_report(reverb_results, odoo_entries, model_id, default_shipping)
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
@click.option("--dry-run", is_flag=True, help="Preview changes without writing to Odoo.")
@click.option("--yes", "-y", "auto_yes", is_flag=True, help="Skip confirmation prompts.")
@click.option(
    "--workers",
    type=int,
    default=DEFAULT_WORKERS,
    show_default=True,
    help="Number of worker threads for --all mode.",
)
def cli(
    model_name: str | None,
    all_models: bool,
    search_query: str | None,
    category: str | None,
    no_category: bool,
    dry_run: bool,
    auto_yes: bool,
    workers: int,
) -> None:
    """Search Reverb for MODEL_NAME, then update/create entries in Odoo.

    MODEL_NAME is the guitar model to sync (e.g. "Frank Brothers Arcane").
    Use --all to sync every model in the database at once.
    """
    if not all_models and not model_name:
        raise click.UsageError("Provide a MODEL_NAME or use --all.")

    # Resolve category: --no-category → None, --category X → X, else → from DB
    if no_category:
        effective_category: Any = None
    elif category is not None:
        effective_category = category
    else:
        effective_category = _CATEGORY_FROM_DB

    conn = get_connection()

    # --all: sync every model in the database (multi-threaded) -----------------
    if all_models:
        all_model_info = _fetch_all_models(conn)
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
                ): idx
                for idx, mi in enumerate(all_model_info)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    collected[idx] = future.result()
                except Exception:
                    mi = all_model_info[idx]
                    logger.exception(
                        "Error collecting data for '{}' (id={})",
                        mi["name"],
                        mi["id"],
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

        # Phase 2 — print reports & apply updates sequentially -----------------
        total_updated = 0
        total_created = 0
        for i, data in enumerate(collected, 1):
            sep = "━" * 100
            logger.info(
                "\n{}\n  [{}/{}]  Model: '{}' (id={})\n{}",
                sep,
                i,
                len(collected),
                data["model_name"],
                data["model_id"],
                sep,
            )

            if not data["report"]:
                logger.warning("No Reverb results — nothing to do.")
                continue

            update_count, create_count = _print_report(data["report"])
            total_actions = update_count + create_count

            if total_actions == 0:
                logger.success("Everything is up to date — nothing to do.")
                continue

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
