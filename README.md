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
