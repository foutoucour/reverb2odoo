# Design: Reverb MCP Server

**Date**: 2026-04-12
**Status**: Approved

## Goal

An MCP server that lets Claude Desktop search Reverb.com for guitar listings and fetch individual listings by URL. Works alongside the existing `odoo-mcp` server — Claude bridges the two by pulling price brackets from Odoo and comparing against Reverb results.

## Use Cases

1. **Search by model** — "Find me listings for a Gibson Les Paul Custom 54 Black Beauty" → Claude searches Reverb, then compares prices against `x_models` p25/p50/p75 brackets from the Odoo MCP.
2. **Score a URL** — "Is this listing a good deal?" + Reverb URL → Claude fetches the listing, compares price against Odoo brackets.

Scoring is done by Claude in context — the Reverb MCP returns raw data, the Odoo MCP provides brackets. No direct connection between the two servers.

## Architecture

```
reverb_mcp/
  __init__.py
  server.py          # FastMCP "reverb-search", registers resource + tools
  scraper.py         # thin sync wrapper: runs ReverbScraper coroutines via asyncio.run()
  category_cache.py  # fetch_categories() result, cached in memory for server lifetime
```

Lives alongside `odoo_mcp/` in the same repo. New entry point added to `pyproject.toml`:
```
reverb-mcp = "reverb_mcp.server:main"
```

**No new dependencies** — `httpx` and `mcp` are already present.  
**No credentials** — Reverb public API requires no auth for search and fetch.  
**Read-only** — no mutations; same constraint as `odoo_mcp/`.

### Async bridging

`ReverbScraper` is async; FastMCP tools are sync. `scraper.py` wraps each call in `asyncio.run()` so tool functions stay simple synchronous functions.

## Resource

### `reverb://categories`

Fetched once on first access via `ReverbScraper.fetch_categories()`, cached for the server lifetime (slugs are stable). Returns a markdown list of `slug — display name` pairs. Claude uses this to pick a valid category before calling `search_listings`.

## Tools

### `search_listings(query, category?, condition?, ships_to?)`

| Param | Type | Default | Notes |
|---|---|---|---|
| `query` | `str` | required | e.g. `"Gibson Les Paul Custom"` |
| `category` | `str` | `""` | Reverb slug e.g. `"electric-guitars"` |
| `condition` | `str` | `""` | `"excellent"`, `"good"`, `"fair"`, `"poor"`, `"non-functioning"` |
| `ships_to` | `str` | `"CA"` | ISO country code, defaults to Canada |

- Calls `ReverbScraper.search()` with `state="live"`, `per_page=50`, `max_pages=1`
- Results sorted by price ascending (cheapest first)
- Returns markdown cards:

```
- **{title}** — {price} {currency} + {shipping} shipping
  Condition: {condition} | Published: {date}
  {url}
```

### `fetch_listing(url)`

Takes a single Reverb URL, returns a full normalised listing as markdown: title, price, shipping, condition, published date, description excerpt, URL.

## Claude Desktop Setup

Two servers registered side by side in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-collection": { "...": "existing config" },
    "reverb-search": {
      "command": "uv",
      "args": ["--directory", "/path/to/reverb2odoo", "run", "reverb-mcp"]
    }
  }
}
```

No env vars needed for the Reverb server.

## What's Out of Scope

- Automatic sweeping of all wanna=True models (search is one model at a time)
- Writing to Odoo (creating `x_listing` records) — that stays in the CLI `sync` command
- Auth or saved searches
