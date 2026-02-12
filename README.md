# reverb2odoo

CLI tool to sync guitar listings from [Reverb.com](https://reverb.com) into an [Odoo](https://www.odoo.com) database. It searches the Reverb public API, compares results against existing Odoo records, and creates or updates entries as needed.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended package manager)
- An Odoo instance with custom models (`x_guitar`, `x_models`, `x_reverb_category`)

## Installation

```bash
uv sync
```

## Configuration

Create an `env.yml` file at the project root with your Odoo credentials:

```yaml
---
odoo:
  hostname: "https://myinstance.odoo.com/odoo"
  database: "mydb"
  login: "user@example.com"
  password: "your-password"
```

The connector infers protocol (`jsonrpcs` / `jsonrpc`) and port (`443` / `8069`) from the hostname URL scheme.

## Usage

All commands are exposed through a single CLI entry point:

```bash
uv run reverb2odoo --help
```

### `sync` — Search Reverb and sync into Odoo

Search Reverb for a guitar model, then create new entries and update existing ones in Odoo.

```bash
# Sync a single model
uv run reverb2odoo sync "Frank Brothers Arcane"

# Preview changes without writing (dry-run)
uv run reverb2odoo sync "Godin Stadium HT" --dry-run

# Sync every model in the database at once
uv run reverb2odoo sync --all --yes

# Override the Reverb search query
uv run reverb2odoo sync "ES-335" --search "Gibson ES-335 1963"

# Override the Reverb category filter
uv run reverb2odoo sync "Strymon Timeline" --category "effects-and-pedals"

# Search across all Reverb categories (ignore DB default)
uv run reverb2odoo sync "Frank Brothers Arcane" --no-category
```

Options:

| Flag | Description |
|---|---|
| `--all` | Sync every model in the database (multi-threaded) |
| `--search TEXT` | Override the Reverb search query |
| `--category TEXT` | Override the Reverb category slug |
| `--no-category` | Search across all Reverb categories |
| `--dry-run` | Preview changes without writing to Odoo |
| `--yes / -y` | Skip confirmation prompts |
| `--workers N` | Number of worker threads for `--all` mode (default: 4) |

### `validate` — Refresh existing entries from Reverb

Starting from existing Odoo records that have a Reverb URL, fetch the current listing data and update fields that have drifted (price, availability, shipping, etc.).

```bash
# Validate a single model
uv run reverb2odoo validate "Frank Brothers Arcane"

# Validate everything
uv run reverb2odoo validate --all --dry-run
```

Options:

| Flag | Description |
|---|---|
| `--all` | Validate every model in the database |
| `--dry-run` | Preview changes without writing to Odoo |
| `--yes / -y` | Skip confirmation prompts |
| `--workers N` | Number of worker threads for `--all` mode (default: 4) |

### `sync-categories` — Import Reverb categories into Odoo

Fetch the full flat category list from the Reverb API and create any categories that don't already exist in Odoo.

```bash
uv run reverb2odoo sync-categories
uv run reverb2odoo sync-categories --dry-run
```

## Architecture

| Module | Role |
|---|---|
| `cli.py` | Unified Click entry point assembling all sub-commands |
| `reverb_scraper.py` | Async HTTP client for the Reverb public API (search, single listing, categories) |
| `sync_model.py` | `sync` command — search Reverb, diff against Odoo, create/update records |
| `validate_model.py` | `validate` command — refresh existing Odoo records from live Reverb data |
| `sync_categories.py` | `sync-categories` command — import Reverb category tree into Odoo |
| `odoo_connector.py` | Odoo connection helper using `odoo-client-lib` + record lookup utilities |

## Data extracted from Reverb

Each listing is normalised into a dict with the following fields:

| Field | Description |
|---|---|
| `url` | Reverb listing URL |
| `name` | Listing title |
| `make` / `model` | Brand and model |
| `finish` / `year` | Finish and year |
| `price` / `currency` | Price amount and currency (CAD by default) |
| `condition` | Listing condition (e.g. "Excellent", "Mint") |
| `status` / `sale_ended` | Sale status and whether it has ended |
| `shipping_price` / `ships_to_canada` | Shipping cost to Canada and availability |
| `offers_enabled` | Whether the seller accepts offers |
| `created_at` / `published_at` | Listing dates (YYYY-MM-DD) |
| `seller` / `location` | Seller shop name and display location |
| `description` | Plain-text description (HTML stripped) |
| `views` / `watchers` | Listing stats |
| `categories` | Category path list |
| `photo_url` | Main photo URL |

## Testing

```bash
uv run pytest
```

Tests use [VCR.py](https://vcrpy.readthedocs.io/) (`pytest-recording`) to replay recorded HTTP cassettes so they run without network access. To re-record cassettes:

```bash
uv run pytest --record-mode=once    # record missing cassettes
uv run pytest --record-mode=all     # re-record everything
```

## Dependencies

| Package | Purpose |
|---|---|
| `httpx` | Async HTTP client for the Reverb API |
| `click` | CLI framework |
| `loguru` | Structured logging |
| `odoo-client-lib` | XML-RPC / JSON-RPC connector for Odoo |
| `pyyaml` | Parse `env.yml` configuration |
| `uritemplate` | RFC 6570 URI template expansion |
