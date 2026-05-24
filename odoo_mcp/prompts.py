"""Canned MCP prompt templates.

Prompts teach Claude how to combine multiple resources and tools into a
coherent workflow without the user having to remember each tool name.
"""

from __future__ import annotations


def daily_check() -> str:
    """Daily-routine prompt: scan the collection state for action items."""
    return (
        "Run a daily check on my guitar collection. In one combined report:\n"
        "\n"
        "1. Read the `odoo://watchlist` resource — list any wanna=True model with a top-3 "
        "watching listing (score-sorted).\n"
        "2. Call the `missed_deals` tool (days_lookback=14) — surface anything that got away "
        "in the last two weeks and any sub-p25 active deal.\n"
        "3. Call the `pending_decisions` tool — list watching listings I haven't triaged.\n"
        "4. Call the `recent_activity` tool (days=7) — summarize new listings and sold "
        "listings in the last week.\n"
        "\n"
        "Format as one short markdown report with one bullet per item. Highlight anything "
        "that needs my attention today."
    )


def deal_hunt(brand: str = "", model: str = "") -> str:
    """Focused deal-hunt prompt for a specific brand or model."""
    target_parts: list[str] = []
    if brand:
        target_parts.append(f"brand `{brand}`")
    if model:
        target_parts.append(f"model `{model}`")
    target = " for " + " and ".join(target_parts) if target_parts else ""

    return (
        f"Hunt for deals{target}.\n"
        "\n"
        "1. Call the `search_listings` tool with the supplied filters and `status=watching`.\n"
        "2. For each result, compare price to the model's p25/p50/p75 brackets (use "
        "`get_model` if you need the spec).\n"
        "3. Rank by best value, return the top 5 with URLs.\n"
    )


def portfolio_review() -> str:
    """Portfolio review prompt: financial state of the collection."""
    return (
        "Give me a portfolio review.\n"
        "\n"
        "1. Call the `portfolio_summary` tool.\n"
        "2. Read the `odoo://sold` resource for the realized P&L breakdown.\n"
        "3. Comment on: largest unrealized gains, largest unrealized losses, brand "
        "concentration, flip vs keeper balance.\n"
        "4. Suggest one or two actions (e.g. consider selling X, double down on Y)."
    )
