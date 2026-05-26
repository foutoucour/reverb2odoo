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
| `odoo://tags` | `x_weighted_tags` + `x_weighted_tag_groups` | Weighted tag catalog grouped by tag group, with scores and multiply factors |

### Resource templates (parameterized)

Fetch a single item by URI without invoking a tool:

| URI template | Returns |
|---|---|
| `odoo://model/{name}` | One x_models record (name or numeric id), with linked gear and listings |
| `odoo://brand/{name}` | One brand card with country, made_in, description, and linked models |
| `odoo://gear/{gear_id}` | One x_gear record with full listing history |
| `odoo://tag/{name}` | One x_weighted_tags record (name or numeric id) with its group and linked models |

### Tools

| Tool | Params | Returns |
|---|---|---|
| `search_gear` | `brand`, `model_type`, `status`, `intent` (all optional) | Filtered gear cards |
| `search_listings` | `brand`, `model_type`, `max_price`, `platform`, `status` (all optional) | Filtered listing cards sorted by score |
| `get_model` | `name_or_id` | Full model spec with all linked gear and listings |
| `get_gear` | `gear_id` | Single gear detail with scores, notes, and listing history |
| `get_brand` | `name` | Brand card with description and linked x_models |
| `get_tag` | `name_or_id` | Weighted tag detail: score, group multiply, and linked x_models |
| `missed_deals` | `days_lookback` (default 30) | Under-p25 active deals + closed/sold listings on wanna models you don't own |
| `recent_activity` | `days` (default 7) | New listings, sold listings, and gear updates in the window |
| `portfolio_summary` | — | Owned/sold totals, unrealized + realized P&L, by-brand and by-intent pivots |
| `pending_decisions` | — | Watching listings on wanna models that have not been triaged |
| `clear_cache` | — | Drop server-side caches (result, brand, connection) for fresh data |

### Prompts

Canned templates that chain multiple resources and tools:

| Prompt | Use case |
|---|---|
| `daily_check` | Watchlist + missed deals + pending decisions + recent activity in one report |
| `deal_hunt` | Focused hunt with `brand` and/or `model` args, ranked by value vs brackets |
| `portfolio_review` | Financial state of the collection with commentary and suggested actions |

### Caching

Resource renders and tool results are memoized in-process. Defaults:

- TTL — **300 seconds** (5 minutes). Override with `ODOO_MCP_CACHE_TTL_SECONDS`.
- LRU cap — **128 entries**. Override with `ODOO_MCP_CACHE_MAX_SIZE`.

The Odoo connection itself is also memoized with the same TTL. After editing
Odoo data and wanting fresh results immediately, call the `clear_cache` tool
or restart the server.

> **Defense in depth**: although every code path uses `search_read`, the
> Odoo credentials still technically permit writes. Create a dedicated
> read-only Odoo user for the MCP server's `.env` to enforce read-only
> at the Odoo side too.

### Running the MCP server

#### 1. Prerequisites

```bash
uv sync
```

The server requires four Odoo credentials. Provide them via **either** a
`.env` file in the project root (auto-loaded) **or** shell exports:

```bash
# .env (recommended for local use)
ODOO_HOSTNAME=https://yourinstance.odoo.com/odoo
ODOO_DATABASE=yourdb
ODOO_LOGIN=user@example.com
ODOO_PASSWORD=your-password

# Optional cache tuning
ODOO_MCP_CACHE_TTL_SECONDS=300   # default 5 min
ODOO_MCP_CACHE_MAX_SIZE=128      # default LRU cap
```

> **Tip**: create a dedicated read-only Odoo user and use those credentials.
> The code path is read-only, but the credentials themselves still allow
> writes — a read-only user closes that gap.

#### 2. Pick a run mode

##### Option A — Claude Desktop (typical)

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the server entry. If you have a `.env` file, the `env` block is optional:

```json
{
  "mcpServers": {
    "odoo-collection": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/reverb2odoo", "run", "odoo-mcp"],
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

Restart Claude Desktop. The server appears in the connector list and its
resources, tools, and prompts become available in chat.

##### Option B — Run manually in a terminal

Useful when you want to see server logs while debugging:

```bash
uv run odoo-mcp
```

The process talks MCP over stdio and waits for a client to connect — it
won't print anything until a request arrives. Stop it with `Ctrl-C`.

##### Option C — Interactive inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a
web UI that lets you browse every resource, call every tool, and see the raw
markdown output — perfect for a first smoke test:

```bash
npx @modelcontextprotocol/inspector uv run odoo-mcp
```

Open the printed URL, click **Connect**, then explore the **Resources**,
**Tools**, and **Prompts** tabs.

#### 3. Verify it works

The inspector is the fastest way:

1. Open **Resources** → click `odoo://watchlist` → confirm a markdown report
   appears with your wanna models.
2. Open **Tools** → call `portfolio_summary` (no args) → confirm a totals
   block returns.
3. Open **Prompts** → run `daily_check` → confirm the canned template loads.

If any call returns an Odoo error, your credentials or the Odoo schema is
the problem — not the server wiring.

#### 4. Daily use from Claude

In Claude Desktop chat:

- **Resources** — type `@` to autocomplete URIs like `@odoo://watchlist` or
  `@odoo://model/Les Paul Standard` to pull live markdown into context.
- **Tools** — ask in plain language; Claude picks the right tool ("what
  deals did I miss this week?" → `missed_deals`).
- **Prompts** — type `/daily_check`, `/deal_hunt`, or `/portfolio_review`
  to invoke a canned multi-step workflow.
- After editing Odoo and wanting fresh data immediately, ask Claude to call
  `clear_cache` (or restart the server).

#### 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Server starts but every call hangs | Bad `ODOO_HOSTNAME` (try with and without `/odoo` suffix) |
| `AccessDenied` or 401-style error | Wrong `ODOO_LOGIN` / `ODOO_PASSWORD`, or user lacks read access on `x_*` models |
| Empty `odoo://watchlist` | No models marked `x_studio_wanna=True` yet |
| Stale data after a sync run | Wait for TTL (default 5 min) or call `clear_cache` |
| `KeyError: 'ODOO_HOSTNAME'` | Env vars not set — check `.env` is at project root or pass `env` in the Claude config |

> **Read-only**: the MCP server never writes to Odoo. Every operation uses
> `search_read` only — no `write`, `create`, or `unlink` calls. It is safe
> to connect to a production instance.

> **Note**: `x_models` field names (especially computed score fields) should
> be verified against your live Odoo schema before first use. Run
> `conn.get_model("x_models").fields_get()` to inspect.

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
