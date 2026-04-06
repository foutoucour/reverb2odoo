# reverb2odoo

[![CI](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/ci.yml)
[![Daily Validation](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/validate.yml)
[![Daily Sync (Wanna)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml/badge.svg)](https://github.com/foutoucour/reverb2odoo/actions/workflows/sync-wanna.yml)

CLI tool to sync gear listings from [Reverb.com](https://reverb.com) into an [Odoo](https://www.odoo.com) database. It
searches the Reverb public API, compares results against existing Odoo records, and creates or updates entries as
needed.

## Data model

| Model | Purpose |
|---|---|
| `x_listing` | Marketplace entry — one record per Reverb listing. Primary sync target. |
| `x_gear` | Physical item — created only when a listing is acquired (~20 records vs thousands). Holds serial number, neck profile, and other physical details. |
| `x_models` | Gear model catalogue (brand, specs, Reverb category, price brackets). |
| `x_reverb_category` | Reverb category slugs and default shipping costs. |

`x_listing` drives the workflow: the `sync` command creates and updates listing records. `x_gear` records are created
manually in Odoo when you mark a listing as acquired.

### x_listing status lifecycle

**Buy side** (from sync): `watching` → `acquired` | `passed` | `closed`

**Sell side** (created manually per platform): `for_sale` → `sold` | `closed`

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

### `dedup` — Find and remove duplicate listings (legacy)

Scans all `x_guitar` records and reports duplicates in two categories:

| Category | Description |
|---|---|
| **Exact URL duplicates** | Records sharing the same URL (query-string ignored) |
| **Same Reverb item ID** | Records with the same numeric item ID but a different URL slug (listing renamed/relisted on Reverb) |

In each group the record to keep is chosen by priority: active+available first, then lowest Odoo ID.

```bash
uv run reverb2odoo dedup                   # report only
uv run reverb2odoo dedup --delete          # prompt before deleting each duplicate
uv run reverb2odoo dedup --delete --yes    # delete all duplicates without prompting
```

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

### `add-model-fields` — Add custom fields to x_gear, x_listing, and x_models

Adds application-specific fields to models that must already exist in Odoo.
Create `x_gear` and `x_listing` via **Odoo Studio** first (in that order — `x_listing.x_gear_id`
references `x_gear`). Studio handles model initialisation, default views, and menu wiring. Then
run this command to add the fields Studio would not create automatically.

Fields added to `x_listing`: `x_name`, `x_model_id`, `x_url`, `x_platform`, `x_currency_id`,
`x_price`, `x_shipping`, `x_condition`, `x_status`, `x_is_available`, `x_can_accept_offers`,
`x_is_taxed`, `x_published_at`, `x_gear_id`.

Fields added to `x_gear`: `x_name`, `x_model_id`, `x_intent`, `x_condition`, `x_status`,
`x_serial_number`, `x_neck_profile`.

Also adds five price bracket fields (`x_price_p25`, `x_price_p50`,
`x_price_p75`, `x_price_sample_size`, `x_price_updated_at`) to `x_models`.

Idempotent: already-existing fields are silently skipped.

```bash
uv run reverb2odoo add-model-fields           # dry-run (default)
uv run reverb2odoo add-model-fields --apply   # write to Odoo
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
