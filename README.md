# reverb2odoo

[![CI](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml)
[![Daily Validation](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml)
[![Weekly Sync](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync.yml)
[![Daily Sync (Wanna)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml)

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

Search Reverb for a guitar model, then create new entries and update existing ones in Odoo.

### `validate` — Refresh existing entries from Reverb

Starting from existing Odoo records that have a Reverb URL, fetch the current listing data and update fields that have drifted (price, availability, shipping, etc.).


## Testing

```bash
uv run pytest
```

Tests use [VCR.py](https://vcrpy.readthedocs.io/) (`pytest-recording`) to replay recorded HTTP cassettes so they run without network access. To re-record cassettes:

```bash
uv run pytest --record-mode=once    # record missing cassettes
uv run pytest --record-mode=all     # re-record everything
```
