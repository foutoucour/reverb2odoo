"""
Validate and sanitize existing Odoo guitar entries against live Reverb data.

For each guitar entry linked to a model in Odoo that has a Reverb URL,
fetch the current listing data from Reverb and update Odoo where needed.

Unlike ``sync_model.py`` (which *searches* Reverb and creates new entries),
this command starts from the **existing Odoo records** and refreshes them.

Use ``--all`` to validate every model in the database at once.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import click
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

from reverb_scraper import ReverbScraper
from sync_model import (
    DEFAULT_SHIPPING,
    _compute_changes,
    _download_image_base64,
    _fetch_all_models,
    _fetch_guitars,
    _find_entries_without_image,
    _find_model,
)

_console = Console()

REVERB_DOMAIN = "reverb.com/item/"

#: Default number of worker threads for ``--all`` mode.
DEFAULT_WORKERS = 4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_reverb_url(url: str) -> bool:
    """Return *True* if *url* points to a Reverb item listing."""
    return REVERB_DOMAIN in url


# ---------------------------------------------------------------------------
# Reverb scraping
# ---------------------------------------------------------------------------


async def _scrape_reverb_urls(
    entries: list[dict],
    *,
    default_shipping: float = DEFAULT_SHIPPING,
) -> dict[str, dict]:
    """Scrape current Reverb data for every Reverb URL in *entries*.

    Uses :meth:`ReverbScraper.extract_many` for concurrent fetching.

    Returns a dict mapping URL → scraped data dict.
    """
    urls: list[str] = []
    for entry in entries:
        url = entry.get("x_studio_url", "")
        if _is_reverb_url(url):
            urls.append(url)

    if not urls:
        return {}

    shipping_str = f"{default_shipping:.2f}"

    async with ReverbScraper(
        currency="CAD",
        shipping_region="CA",
        default_shipping=shipping_str,
    ) as scraper:
        results_list = await scraper.extract_many(urls)

    results: dict[str, dict] = {}
    for url, data in zip(urls, results_list, strict=True):
        results[url] = data

    return results


# ---------------------------------------------------------------------------
# Diff / report
# ---------------------------------------------------------------------------


def _build_validation_report(
    entries: list[dict],
    reverb_data: dict[str, dict],
) -> list[dict]:
    """Build a validation report comparing Odoo entries against Reverb data.

    Each item in the returned list has:

    - ``entry``:    the Odoo record dict
    - ``reverb``:   the scraped Reverb dict (or ``None``)
    - ``changes``:  field updates needed
    - ``warnings``: list of informational strings
    - ``action``:   ``"update"`` | ``"ok"`` | ``"skip"``
    """
    report: list[dict] = []

    for entry in entries:
        url = entry.get("x_studio_url", "")
        item: dict[str, Any] = {
            "entry": entry,
            "reverb": None,
            "changes": {},
            "warnings": [],
            "action": "skip",
        }

        if not _is_reverb_url(url):
            item["warnings"].append("non-Reverb URL — skipped")
            report.append(item)
            continue

        reverb = reverb_data.get(url)
        if not reverb:
            item["warnings"].append("URL not found in scraped data")
            report.append(item)
            continue
        if "error" in reverb:
            item["warnings"].append(f"Reverb API error: {reverb['error']}")
            report.append(item)
            continue

        item["reverb"] = reverb

        # Skip ended / sold listings — nothing to update
        if reverb.get("sale_ended"):
            item["warnings"].append(f"status: {reverb.get('status', 'ended/sold')}")
            report.append(item)
            continue

        item["changes"] = _compute_changes(entry, reverb)
        item["action"] = "update" if item["changes"] else "ok"

        # Informational warnings
        if reverb.get("ships_to_canada") is False:
            item["warnings"].append("does NOT ship to Canada")

        report.append(item)

    return report


def _print_validation_report(report: list[dict]) -> int:
    """Print a rich validation report table.

    Returns the number of entries that need updating.
    """
    from rich.table import Table

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold", highlight=False)
    table.add_column("ID", style="dim", width=8, justify="right")
    table.add_column("Name")
    table.add_column("Price", width=14)
    table.add_column("Status")

    update_count = 0
    for item in report:
        entry = item["entry"]
        eid = str(entry["id"])
        name = escape(entry.get("x_name", "")[:54])
        reverb = item.get("reverb") or {}
        price = escape(reverb.get("price_display", "") or "")
        changes = item["changes"]
        warnings = item["warnings"]

        if item["action"] == "skip":
            warn_str = escape("; ".join(warnings)) if warnings else ""
            table.add_row(eid, name, price, f"[dim]⚠ {warn_str}[/dim]")
        elif changes:
            update_count += 1
            warn_str = escape(f"  (⚠ {'; '.join(warnings)})") if warnings else ""
            table.add_row(eid, name, price, f"[bold yellow]~ NEEDS UPDATE[/bold yellow]{warn_str}")
            for field, new_val in changes.items():
                old_val = entry.get(field, "—")
                diff = (
                    f"  [dim]{escape(field)}:[/dim]"
                    f" {escape(str(old_val))} [dim]→[/dim] [bold]{escape(str(new_val))}[/bold]"
                )
                table.add_row("", "", "", diff)
        else:
            pass  # counted in summary; not shown to reduce noise

    _console.print()
    _console.print(table)
    skip_count = sum(1 for item in report if item["action"] == "skip")
    ok_count = len(report) - update_count - skip_count
    _console.print(
        f"  Total: [bold]{len(report)}[/bold]"
        f"  Up to date: [green]{ok_count}[/green]"
        f"  Need update: [yellow]{update_count}[/yellow]"
        f"  Skipped: [dim]{skip_count}[/dim]"
    )
    return update_count


# ---------------------------------------------------------------------------
# Write to Odoo
# ---------------------------------------------------------------------------


def _apply_validation_updates(conn, report: list[dict]) -> list[dict]:
    """Write validation changes back to Odoo.

    Only updates existing records (no creates).  When an entry being
    updated has no ``x_studio_image``, the first Reverb listing photo is
    downloaded and included in the update.

    Returns a list of dicts with ``id``, ``name``, and ``fields`` (list of
    changed field names) for each updated record.
    """
    guitar = conn.get_model("x_guitar")

    # Pre-check: which entries being updated lack an image?
    update_ids = [item["entry"]["id"] for item in report if item["action"] == "update"]
    ids_without_image = _find_entries_without_image(conn, update_ids)

    updated_items: list[dict] = []

    for item in report:
        if item["action"] != "update":
            continue
        changes = item["changes"]
        if not changes:
            continue

        eid = item["entry"]["id"]
        changes = dict(changes)

        # Download image if the entry has no image yet
        if eid in ids_without_image:
            photo_url = (item.get("reverb") or {}).get("photo_url", "")
            image_b64 = _download_image_base64(photo_url)
            if image_b64:
                changes["x_studio_image"] = image_b64
                logger.info("  ↳ downloaded image for id={}", eid)

        # Log changes without the (potentially huge) image blob
        log_changes = {k: v for k, v in changes.items() if k != "x_studio_image"}
        logger.info("Updating id={}: {}", eid, log_changes)
        guitar.write(eid, changes)
        updated_items.append(
            {
                "id": eid,
                "name": item["entry"].get("x_name", ""),
                "fields": list(log_changes.keys()),
            }
        )

    return updated_items


def _print_updated_summary(updated_items: list[dict]) -> None:
    """Print a compact list of all records that were updated."""
    if not updated_items:
        return
    _console.print()
    _console.print(f"  [bold]Updated {len(updated_items)} record(s):[/bold]")
    for item in updated_items:
        fields_str = ", ".join(item["fields"])
        _console.print(
            f"    [dim]{item['id']}[/dim]  {escape(item['name'])}  [dim]({fields_str})[/dim]"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _collect_model_data(
    conn,
    *,
    model_id: int,
    model_name: str,
    default_shipping: float,
) -> dict[str, Any]:
    """Fetch Odoo entries and scrape Reverb for a single model.

    This is the **I/O-heavy** phase.

    Returns a dict with keys:

    - ``model_id``, ``model_name``, ``default_shipping`` – echo back inputs
    - ``entries``  – Odoo guitar records for the model
    - ``reverb_data`` – URL → scraped Reverb dict
    - ``report`` – validation report list
    - ``update_count`` – number of entries that need updating
    """
    logger.debug("[{}] Fetching Odoo entries…", model_name)
    entries = _fetch_guitars(conn, model_id)
    logger.debug("[{}] Found {} guitar entries", model_name, len(entries))

    if not entries:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "default_shipping": default_shipping,
            "entries": [],
            "reverb_data": {},
            "report": [],
            "update_count": 0,
        }

    reverb_count = sum(1 for e in entries if _is_reverb_url(e.get("x_studio_url", "")))
    logger.debug("[{}] Scraping {} Reverb URL(s)…", model_name, reverb_count)
    reverb_data = await _scrape_reverb_urls(entries, default_shipping=default_shipping)
    logger.debug("[{}] Scraped {} Reverb listing(s)", model_name, len(reverb_data))

    report = _build_validation_report(entries, reverb_data)
    update_count = sum(1 for item in report if item["action"] == "update")

    return {
        "model_id": model_id,
        "model_name": model_name,
        "default_shipping": default_shipping,
        "entries": entries,
        "reverb_data": reverb_data,
        "report": report,
        "update_count": update_count,
    }


def _validate_single_model(
    conn,
    *,
    model_id: int,
    model_name: str,
    default_shipping: float,
    dry_run: bool,
    auto_yes: bool,
) -> int:
    """Validate one model's guitar entries against Reverb.

    Returns the number of records updated (0 in dry-run mode).
    """
    logger.info("Resolved model '{}' → x_models id={}", model_name, model_id)
    logger.info("Default shipping: C${:.2f}", default_shipping)

    data = asyncio.run(
        _collect_model_data(
            conn,
            model_id=model_id,
            model_name=model_name,
            default_shipping=default_shipping,
        )
    )

    if not data["entries"]:
        logger.warning("No entries to validate — nothing to do.")
        return 0

    update_count = _print_validation_report(data["report"])

    if update_count == 0:
        logger.success("Everything is up to date — nothing to do.")
        return 0

    if dry_run:
        logger.info("Dry-run mode — no changes written to Odoo.")
        return 0

    # Confirm & apply -----------------------------------------------------------
    if not auto_yes:
        click.confirm(
            f"\n  Apply {update_count} update(s) to Odoo?",
            abort=True,
        )

    updated_items = _apply_validation_updates(conn, data["report"])
    _print_updated_summary(updated_items)
    logger.success("Updated {} record(s) in Odoo.", len(updated_items))
    return len(updated_items)


@click.command("validate")
@click.argument("model_name", required=False, default=None)
@click.option("--all", "all_models", is_flag=True, help="Validate every model in the database.")
@click.option("--dry-run", is_flag=True, help="Preview changes without writing to Odoo.")
@click.option("--yes", "-y", "auto_yes", is_flag=True, help="Skip confirmation prompts.")
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
    dry_run: bool,
    auto_yes: bool,
    workers: int,
) -> None:
    """Validate existing Odoo entries against live Reverb data.

    MODEL_NAME is the guitar model to validate (e.g. "Frank Brothers Arcane").
    Use --all to validate every model in the database at once.
    """
    if not all_models and not model_name:
        raise click.UsageError("Provide a MODEL_NAME or use --all.")

    conn = ctx.obj["conn"]

    # --all: validate every model in the database (multi-threaded) -------------
    if all_models:
        all_model_info = _fetch_all_models(conn)
        if not all_model_info:
            logger.warning("No models found — nothing to do.")
            return

        n_workers = min(workers, len(all_model_info))
        logger.info(
            "Validating {} model(s) with {} worker thread(s)…",
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
                f"[cyan]Scraping Reverb data[/cyan] ({n_workers} workers)…",
                total=len(all_model_info),
            )
            with ThreadPoolExecutor(max_workers=n_workers) as pool:
                future_to_idx = {
                    pool.submit(
                        asyncio.run,
                        _collect_model_data(
                            conn,
                            model_id=mi["id"],
                            model_name=mi["name"],
                            default_shipping=mi["default_shipping"],
                        ),
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
                            "entries": [],
                            "reverb_data": {},
                            "report": [],
                            "update_count": 0,
                        }
                    progress.advance(task)

        # Phase 2 — print reports & apply updates sequentially -----------------
        total_updated = 0
        for i, data in enumerate(collected, 1):
            update_count = data["update_count"]

            # Compact one-liner for models with nothing to do
            if not data["entries"] or update_count == 0:
                if not data["entries"]:
                    note = "[dim]no entries[/dim]"
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

            update_count = _print_validation_report(data["report"])

            if dry_run:
                logger.info("Dry-run mode — no changes written to Odoo.")
                continue

            if not auto_yes:
                click.confirm(
                    f"\n  Apply {update_count} update(s) to Odoo?",
                    abort=True,
                )

            updated_items = _apply_validation_updates(conn, data["report"])
            _print_updated_summary(updated_items)
            logger.success("Updated {} record(s) in Odoo.", len(updated_items))
            total_updated += len(updated_items)

        logger.success("All models validated — {} record(s) updated total.", total_updated)
        return

    # Single model -------------------------------------------------------------
    assert model_name is not None  # guaranteed by validation above
    model_info = _find_model(conn, model_name)

    _validate_single_model(
        conn,
        model_id=model_info["id"],
        model_name=model_name,
        default_shipping=model_info["default_shipping"],
        dry_run=dry_run,
        auto_yes=auto_yes,
    )


if __name__ == "__main__":
    cli()
