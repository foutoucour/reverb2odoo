"""
Find duplicate ``x_guitar`` records in Odoo.

Two records are considered **exact duplicates** when their URLs resolve to the
same base URL (query-string stripped).

Two records are **same-ID duplicates** when they share the same Reverb numeric
item ID but have a different URL slug (listing renamed/relisted on Reverb).
"""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlparse, urlunparse

import click
from loguru import logger
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

_console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_url(url: str) -> str:
    """Strip query-string and fragment from *url*."""
    if not url:
        return ""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


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


def _pick_keeper(group: list[dict]) -> dict:
    """Return the record to keep from a duplicate group.

    Priority (descending):

    1. active **and** available
    2. active only
    3. lowest Odoo ID (oldest record)
    """

    def _sort_key(r: dict) -> tuple[int, int, int]:
        active = 0 if r.get("x_studio_active") else 1
        available = 0 if r.get("x_studio_is_available") else 1
        return (active, available, r["id"])

    return min(group, key=_sort_key)


# ---------------------------------------------------------------------------
# Detection logic
# ---------------------------------------------------------------------------


def _find_exact_url_dupes(records: list[dict]) -> list[list[dict]]:
    """Return groups of records sharing the same base URL."""
    by_url: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        bu = _base_url(r.get("x_studio_url") or "")
        if bu:
            by_url[bu].append(r)
    return [grp for grp in by_url.values() if len(grp) > 1]


def _find_same_item_id_dupes(records: list[dict]) -> list[list[dict]]:
    """Return groups sharing the same Reverb numeric item ID but different URLs.

    Records that are already caught by exact-URL deduplication are excluded.
    """
    by_id: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        url = r.get("x_studio_url") or ""
        item_id = _reverb_item_id(url)
        if item_id:
            by_id[item_id].append(r)

    groups = [grp for grp in by_id.values() if len(grp) > 1]

    # Only keep groups where not all records share the exact same base URL
    # (those are already covered by the exact-URL check).
    filtered = []
    for grp in groups:
        base_urls = {_base_url(r.get("x_studio_url") or "") for r in grp}
        if len(base_urls) > 1:
            filtered.append(grp)
    return filtered


def _ids_to_delete(groups: list[list[dict]]) -> list[int]:
    """Return the Odoo IDs to delete across all duplicate groups."""
    ids: list[int] = []
    for grp in groups:
        keeper_id = _pick_keeper(grp)["id"]
        ids.extend(r["id"] for r in grp if r["id"] != keeper_id)
    return ids


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _status_label(r: dict) -> str:
    avail = "avail" if r.get("x_studio_is_available") else "sold"
    active = "active" if r.get("x_studio_active") else "archived"
    return f"{avail}/{active}"


def _print_exact_dupes(groups: list[list[dict]]) -> None:
    _console.print()
    _console.rule(f"[bold red]EXACT URL DUPLICATES[/bold red]  ({len(groups)} group(s))")

    if not groups:
        _console.print("  [green]None found.[/green]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold", highlight=False)
    table.add_column("Odoo ID", style="dim", width=8, justify="right")
    table.add_column("Name")
    table.add_column("Status", width=14)
    table.add_column("Base URL", style="dim")

    for grp in groups:
        bu = _base_url(grp[0].get("x_studio_url") or "")
        keeper_id = _pick_keeper(grp)["id"]
        for r in grp:
            if r["id"] == keeper_id:
                marker = "[bold green]KEEP[/bold green]"
            else:
                marker = "[bold red] DEL[/bold red]"
            table.add_row(
                str(r["id"]),
                f"{marker}  {escape(r.get('x_name') or '')}",
                f"[dim]{_status_label(r)}[/dim]",
                escape(bu) if r["id"] == keeper_id else "",
            )
        table.add_section()

    _console.print(table)


def _print_same_id_dupes(groups: list[list[dict]]) -> None:
    _console.print()
    _console.rule(
        f"[bold yellow]SAME REVERB ITEM ID — DIFFERENT URL[/bold yellow]  ({len(groups)} group(s))"
    )

    if not groups:
        _console.print("  [green]None found.[/green]")
        return

    table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold", highlight=False)
    table.add_column("Odoo ID", style="dim", width=8, justify="right")
    table.add_column("Name")
    table.add_column("Status", width=14)
    table.add_column("URL", style="dim")

    for grp in groups:
        keeper_id = _pick_keeper(grp)["id"]
        for r in grp:
            if r["id"] == keeper_id:
                marker = "[bold green]KEEP[/bold green]"
            else:
                marker = "[bold red] DEL[/bold red]"
            table.add_row(
                str(r["id"]),
                f"{marker}  {escape(r.get('x_name') or '')}",
                f"[dim]{_status_label(r)}[/dim]",
                escape(r.get("x_studio_url") or ""),
            )
        table.add_section()

    _console.print(table)


# ---------------------------------------------------------------------------
# Write to Odoo
# ---------------------------------------------------------------------------


def _delete_records(conn, ids: list[int]) -> int:
    """Delete x_guitar records by ID. Returns the number of deleted records."""
    if not ids:
        return 0
    guitar = conn.get_model("x_guitar")
    guitar.unlink(ids)
    return len(ids)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("dedup")
@click.option("--delete", "do_delete", is_flag=True, help="Delete duplicate records from Odoo.")
@click.option("--yes", "-y", "auto_yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def cli(ctx: click.Context, do_delete: bool, auto_yes: bool) -> None:
    """Find duplicate x_guitar records in Odoo.

    Reports two categories:

    \b
    1. Exact URL duplicates — same URL (query-string ignored).
    2. Same Reverb item ID  — URL slug changed (relisted / renamed).

    Use --delete to remove duplicates. In each group the record that is
    active+available is kept; ties are broken by lowest Odoo ID.
    """
    conn = ctx.obj["conn"]
    guitar = conn.get_model("x_guitar")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=_console,
    ) as progress:
        progress.add_task("Fetching x_guitar records from Odoo…", total=None)
        records: list[dict] = guitar.search_read(
            [],
            ["id", "x_name", "x_studio_url", "x_studio_is_available", "x_studio_active"],
            limit=0,
        )

    logger.info("Fetched {} record(s).", len(records))

    exact_groups = _find_exact_url_dupes(records)
    same_id_groups = _find_same_item_id_dupes(records)

    _print_exact_dupes(exact_groups)
    _print_same_id_dupes(same_id_groups)

    total_exact = sum(len(g) for g in exact_groups) - len(exact_groups)
    total_same_id = sum(len(g) for g in same_id_groups) - len(same_id_groups)
    total_to_delete = total_exact + total_same_id

    _console.print()
    _console.print(
        f"  Summary — "
        f"exact URL dupes: [bold red]{total_exact}[/bold red]  |  "
        f"same-ID dupes: [bold yellow]{total_same_id}[/bold yellow]"
    )

    if not do_delete or total_to_delete == 0:
        return

    total_deleted = 0
    for grp in exact_groups + same_id_groups:
        keeper = _pick_keeper(grp)
        to_delete = [r for r in grp if r["id"] != keeper["id"]]
        for r in to_delete:
            if not auto_yes:
                _console.print(
                    f"\n  [bold]KEEP[/bold]  id={keeper['id']}"
                    f"  {escape(keeper.get('x_name') or '')}  "
                    f"[dim]{_status_label(keeper)}[/dim]\n"
                    f"        [dim]{escape(keeper.get('x_studio_url') or '')}[/dim]\n"
                    f"  [bold red] DEL[/bold red]  id={r['id']}  {escape(r.get('x_name') or '')}  "
                    f"[dim]{_status_label(r)}[/dim]\n"
                    f"        [dim]{escape(r.get('x_studio_url') or '')}[/dim]"
                )
                confirmed = click.confirm("  Delete?", default=False)
                if not confirmed:
                    continue
            total_deleted += _delete_records(conn, [r["id"]])
            logger.success("Deleted id={}.", r["id"])

    logger.success("Deleted {} duplicate record(s) total.", total_deleted)


if __name__ == "__main__":
    cli()
