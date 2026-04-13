# reverb2odoo

[![CI](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml)
[![Daily Validation](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml)
[![Daily Sync (Wanna)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml)
[![Daily Price Brackets](https://github.com/foutoucour/reverb2odoo/actions/workflows/compute-price-brackets.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/compute-price-brackets.yml)

CLI tool to sync gear listings from [Reverb.com](https://reverb.com) into an [Odoo](https://www.odoo.com) database.
It searches the Reverb public API, compares results against existing Odoo records, and creates or updates entries as
needed. It also ships an **MCP server** that exposes the collection as live resources for Claude Desktop.

## Data model

| Model | Purpose |
|---|---|
| `x_listing` | Marketplace entry — one record per listing. Primary sync target. |
| `x_gear` | Physical item — one per guitar/pedal/amp. Owns the item lifecycle. |
| `x_models` | Gear model catalogue (brand, specs, Reverb category, price brackets p25/p50/p75). |
| `x_reverb_category` | Reverb category slugs and default shipping costs. |

`x_listing` drives the sync workflow. `x_gear` records are created manually in Odoo when a listing is acquired.

### x_gear status lifecycle

`owned` → `for_sale` → `sold`

### x_listing status lifecycle

**Buy side** (from sync): `watching` → `acquired` | `passed`

**Sell side** (created manually per platform): `for_sale` → `sold`

## MCP Server — Collection Source of Truth

The `odoo-mcp` server exposes your Odoo collection as live [MCP](https://modelcontextprotocol.io) resources for
Claude Desktop, replacing static markdown knowledge-base files with real-time queries.

### Resources

| URI | Source | Description |
|---|---|---|
| `odoo://collection` | `x_gear` (owned + for_sale) | Gear you own or are currently selling, with listing details |
| `odoo://watchlist` | `x_models` (wanna=True) | Models you want, with score-ranked watching listings and price brackets |
| `odoo://sold` | `x_gear` (sold) | Flip history with P&L per item |
| `odoo://brands` | `res.partner` + GitHub README | Brand catalog by category, enriched with construction details |
| `odoo://models` | `x_models` (all) | Full model catalog; highlights wanna=True models with no listings tracked |

### Tools

| Tool | Params | Returns |
|---|---|---|
| `search_gear` | `brand`, `model_type`, `status`, `intent` (all optional) | Filtered gear cards |
| `get_model` | `name_or_id` | Full model spec with all linked gear and listings |
| `get_gear` | `gear_id` | Single gear detail with scores, notes, and listing history |

### Claude Desktop setup

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "odoo-collection": {
      "command": "uv",
      "args": ["--directory", "/path/to/reverb2odoo", "run", "odoo-mcp"],
      "env": {
        "ODOO_HOSTNAME": "https://yourinstance.odoo.com/odoo",
        "ODOO_DATABASE": "yourdb",
        "ODOO_LOGIN": "user@example.com",
        "ODOO_PASSWORD": "your-password"
      }
    }
  }
}
```

Or use a `.env` file at the project root (same vars as the CLI) — the server loads it automatically.

### Running the server manually

```bash
uv run odoo-mcp
```

Use the [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to explore resources interactively:

```bash
npx @modelcontextprotocol/inspector uv run odoo-mcp
```

> **Note**: `x_models` field names (especially computed score fields) should be verified against your live Odoo
> schema before first use. Run `conn.get_model("x_models").fields_get()` to inspect.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- An Odoo instance with custom models `x_gear`, `x_listing`, `x_models`, `x_reverb_category` (create via Odoo Studio)

## Installation

```bash
uv sync
```

## Configuration

Set the following environment variables with your Odoo credentials:

```bash
export ODOO_HOSTNAME="https://myinstance.odoo.com/odoo"
export ODOO_DATABASE="mydb"
export ODOO_LOGIN="user@example.com"
export ODOO_PASSWORD="your-password"
```

You can also pass them as CLI options (`--odoo-hostname`, `--odoo-database`, `--odoo-login`, `--odoo-password`).

## Usage

All commands are exposed through a single CLI entry point:

```bash
uv run reverb2odoo --help
```

### `sync` — Search Reverb and sync into Odoo

Search Reverb for a gear model, then create new `x_listing` entries and update existing ones in Odoo.
Matching is done first by exact URL (query-string ignored), then by Reverb numeric item ID — so listings that were renamed on Reverb (slug changed) are updated in place rather than duplicated.

Sync **never creates `x_gear` records** — those are created manually in Odoo when a listing is acquired.

By default only **live** listings are searched. Pass `--include-sold` to also include sold/ended listings.

```bash
uv run reverb2odoo sync "Frank Brothers Arcane"
uv run reverb2odoo sync "Frank Brothers Arcane" --include-sold   # also include sold
uv run reverb2odoo sync --all --include-sold                     # all models, sold included
```

### `validate` — Refresh existing listings from Reverb

Starting from existing `x_listing` records that have a Reverb URL, fetch the current listing data and update fields
that have drifted (price, availability, shipping, etc.). Only updates existing records — never creates new ones.

By default **sold/ended** listings are skipped. Pass `--include-sold` to validate them as well (useful to mark stale entries as unavailable).

```bash
uv run reverb2odoo validate "Frank Brothers Arcane"
uv run reverb2odoo validate --all --include-sold   # also validate sold listings
```

### `set-default-currency` — Set CAD as the default currency on a model

Sets `CAD` as the default value for `x_studio_currency_id` on the given Odoo model.

```bash
uv run reverb2odoo set-default-currency x_gear
uv run reverb2odoo set-default-currency x_listing
```

## Testing

```bash
uv run pytest
```

Tests use [VCR.py](https://vcrpy.readthedocs.io/) (`pytest-recording`) to replay recorded HTTP cassettes so they run
without network access. To re-record cassettes:

```bash
uv run pytest --record-mode=once    # record missing cassettes
uv run pytest --record-mode=all     # re-record everything
```
