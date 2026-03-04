# reverb2odoo

[![CI](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml)
[![Daily Validation](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml)
[![Daily Sync (Wanna)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml)

CLI tool to sync guitar listings from [Reverb.com](https://reverb.com) into an [Odoo](https://www.odoo.com) database. It
searches the Reverb public API, compares results against existing Odoo records, and creates or updates entries as
needed.

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

Starting from existing Odoo records that have a Reverb URL, fetch the current listing data and update fields that have
drifted (price, availability, shipping, etc.).

### `gpt-files` — Generate ChatGPT knowledge-base files

Reads every model from the Odoo `x_models` catalogue and writes two RAG-optimised markdown files for use as a custom GPT
knowledge base:

| File                         | Content                                         |
|------------------------------|-------------------------------------------------|
| `gpt-files/models_gibson.md` | Gibson, Gibson Custom Shop, and Epiphone Guitars models |
| `gpt-files/models_others.md` | All other brands                                |

```bash
uv run reverb2odoo gpt-files
# custom output paths:
uv run reverb2odoo gpt-files --gibson-file path/to/gibson.md --other-file path/to/other.md
```

Each model is rendered as a `###` section sorted alphabetically by name:

```markdown
### Les Paul Standard 50s

- brand: Gibson
- Model type: Guitar
- construction: set-neck + Solid body
- neckFeel: slim
- scale: 24.75
- finish: Nitrocellulose Lacquer
- fretboard: Rosewood
- web page: https://www.gibson.com/...
- notes: Classic Les Paul with vintage-spec pickups and a chunky 50s neck profile.
```

**Field sources:**

| Field          | Odoo field                     | Notes                             |
|----------------|--------------------------------|-----------------------------------|
| `brand`        | `x_studio_partner_id`          | many2one display name (res.partner) |
| `Model type`   | `x_studio_model_type`          | selection string                  |
| `construction` | `x_studio_guitar_familly_ids`  | many2many names joined with ` + ` |
| `neckFeel`     | `x_studio_guitar_neck_feel_id` | many2one display name             |
| `scale`        | `x_studio_scale`               | selection string                  |
| `finish`       | `x_studio_finish`              | many2one display name             |
| `fretboard`    | `x_studio_fretboard_1`         | many2one display name             |
| `web page`     | `x_studio_web_page_1`          | plain text URL                    |
| `notes`        | `x_studio_notes`               | HTML stripped to plain text       |

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
