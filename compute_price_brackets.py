"""Compute price brackets (p25 / p50 / p75) on x_models from x_listing data.

For each model, collects all x_listing prices via x_listing.x_model_id,
then writes three percentile fields back to x_models:

  x_price_p25   — 25th percentile (lower bound of "normal" range)
  x_price_p50   — median
  x_price_p75   — 75th percentile (upper bound of "normal" range)
  x_price_sample_size — number of listings used
  x_price_updated_at  — timestamp of last computation

Window strategy (sliding window with fallback):
  - Use listings published in the last 12 months if ≥ 5 exist.
  - Otherwise fall back to all historical listings.

Usage::

    reverb2odoo compute-price-brackets
    reverb2odoo compute-price-brackets --model "Gibson Les Paul Custom"

"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

import click
from loguru import logger

#: Minimum number of recent listings required to use the sliding window.
_MIN_RECENT = 5

#: Width of the sliding window in days.
_WINDOW_DAYS = 365


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _fetch_models(conn, *, model_name: str | None = None) -> list[dict]:
    """Return x_models records, optionally filtered by name."""
    x_models = conn.get_model("x_models")
    domain: list = []
    if model_name:
        domain = [("x_name", "ilike", model_name)]
    return x_models.search_read(domain, ["id", "x_name"], order="x_name asc")


def _fetch_listing_prices_for_model(conn, model_id: int) -> list[tuple[float, str | None]]:
    """Return (price, published_at) for all x_listing records linked to model_id."""
    listing = conn.get_model("x_listing")
    records = listing.search_read(
        [("x_model_id", "=", model_id), ("x_price", ">", 0)],
        ["x_price", "x_published_at"],
    )
    return [(float(r["x_price"]), r.get("x_published_at") or None) for r in records]


# ---------------------------------------------------------------------------
# Bracket computation
# ---------------------------------------------------------------------------


def _compute_brackets(
    prices_with_dates: list[tuple[float, str | None]],
) -> dict[str, Any] | None:
    """Compute p25/p50/p75 with the sliding-window-with-fallback strategy.

    Returns a dict with keys p25, p50, p75, sample_size, used_window,
    or None when there are no prices at all.
    """
    if not prices_with_dates:
        return None

    cutoff = datetime.now(tz=UTC) - timedelta(days=_WINDOW_DAYS)

    recent_prices: list[float] = []
    all_prices: list[float] = []

    for price, published_at in prices_with_dates:
        all_prices.append(price)
        if published_at:
            try:
                # Odoo returns datetimes as "YYYY-MM-DD HH:MM:SS"
                dt = datetime.strptime(published_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                if dt >= cutoff:
                    recent_prices.append(price)
            except ValueError:
                pass

    prices = recent_prices if len(recent_prices) >= _MIN_RECENT else all_prices
    used_window = prices is recent_prices

    if len(prices) < 2:
        # statistics.quantiles requires at least 2 data points
        if len(prices) == 1:
            p = prices[0]
            return {
                "p25": p,
                "p50": p,
                "p75": p,
                "sample_size": 1,
                "used_window": used_window,
            }
        return None

    p25, p50, p75 = statistics.quantiles(prices, n=4)
    return {
        "p25": round(p25, 2),
        "p50": round(p50, 2),
        "p75": round(p75, 2),
        "sample_size": len(prices),
        "used_window": used_window,
    }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run_computation(conn, *, model_name: str | None = None, dry_run: bool = False) -> None:
    """Compute and write price brackets for all (or one) x_models records."""
    models = _fetch_models(conn, model_name=model_name)

    if not models:
        logger.warning("No x_models records found.")
        return

    logger.info("Computing price brackets for {} model(s)…", len(models))

    x_models = conn.get_model("x_models")
    now_str = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    updated = 0
    skipped = 0

    for record in models:
        model_id = record["id"]
        name = record.get("x_name", f"id={model_id}")

        prices_with_dates = _fetch_listing_prices_for_model(conn, model_id)
        brackets = _compute_brackets(prices_with_dates)

        if brackets is None:
            logger.debug("  {} — no price data, skipping", name)
            skipped += 1
            continue

        window_label = f"last {_WINDOW_DAYS}d" if brackets["used_window"] else "all-time"
        logger.info(
            "  {} — p25={:.0f}  p50={:.0f}  p75={:.0f}  n={}  ({})",
            name[:50],
            brackets["p25"],
            brackets["p50"],
            brackets["p75"],
            brackets["sample_size"],
            window_label,
        )

        if not dry_run:
            x_models.write(
                [model_id],
                {
                    "x_price_p25": brackets["p25"],
                    "x_price_p50": brackets["p50"],
                    "x_price_p75": brackets["p75"],
                    "x_price_sample_size": brackets["sample_size"],
                    "x_price_updated_at": now_str,
                },
            )
            updated += 1

    logger.info("")
    if dry_run:
        logger.info(
            "[DRY RUN] Would update {} model(s), skip {} (no data).",
            len(models) - skipped,
            skipped,
        )
    else:
        logger.success(
            "Done — updated {} model(s), skipped {} (no data).",
            updated,
            skipped,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("compute-price-brackets")
@click.option(
    "--model",
    "model_name",
    default=None,
    help="Compute for a single model (ilike match). Defaults to all models.",
)
@click.option("--dry-run", is_flag=True, help="Preview results without writing to Odoo.")
@click.pass_context
def cli(ctx: click.Context, model_name: str | None, dry_run: bool) -> None:
    """Compute p25/p50/p75 price brackets on x_models from x_listing data.

    Uses a 12-month sliding window when ≥ 5 listings exist; falls back to
    all-time data otherwise.
    """
    conn = ctx.obj["conn"]
    run_computation(conn, model_name=model_name, dry_run=dry_run)
