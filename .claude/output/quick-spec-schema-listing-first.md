# Quick Spec: Schema — Listing-first, gear-on-acquisition

**Date**: 2026-04-04
**Scope**: 5 files modified, 3 components (schema, connector, sync/validate)

## Context

New data model: `x_listing` is the primary record (created on every Reverb sync).
`x_gear` is only created on acquisition (~20 records vs 4000+).
Database wiped clean — no migration needed.

## Odoo Studio constraints (do not create these — they already exist)
- **Image** → `x_studio_image` (already created by Studio). Do NOT create another image field.
- **Monetary fields** → `x_price` and `x_shipping` must use `ttype: monetary`, paired with `x_currency_id`.

## Tasks

### 1. Redefine schema constants — `create_odoo_schema.py`
- **Files**: `create_odoo_schema.py` (modify)
- **What**: Replace `_GEAR_FIELDS` with two lists — `_LISTING_FIELDS` (marketplace fields) and `_GEAR_FIELDS` (physical item fields only). Update `create_schema()` to provision both `x_listing` and `x_gear` models.

**`_LISTING_FIELDS`** (on `x_listing`):
- `x_name` (char) — listing title
- `x_model_id` (many2one → `x_models`) — gear model
- `x_url` (char) — marketplace URL
- `x_platform` (selection: reverb|marketplace|kijiji|other)
- `x_price` (monetary, currency_field=`x_currency_id`) — final price only
- `x_currency_id` (many2one → `res.currency`)
- `x_shipping` (monetary, currency_field=`x_currency_id`)
- `x_condition` (selection: mint|excellent|good|fair|poor)
- `x_status` (selection: watching|acquired|passed|closed|for_sale|sold)
- `x_is_available` (boolean)
- `x_can_accept_offers` (boolean)
- `x_is_taxed` (boolean)
- `x_published_at` (datetime)
- `x_gear_id` (many2one → `x_gear`) — null while watching, set on acquisition
- ~~image~~ — use `x_studio_image` (Studio-managed, not provisioned here)

**`_GEAR_FIELDS`** (on `x_gear`, physical item only):
- `x_name` (char)
- `x_model_id` (many2one → `x_models`)
- `x_intent` (selection: flip|keeper|unknown)
- `x_condition` (char) — condition at time of purchase
- `x_status` (selection: owned|sold)
- `x_serial_number` (char)
- `x_neck_profile` (char)

- **Acceptance**:
  - Given `--apply`, when run, then all `_LISTING_FIELDS` created on `x_listing` and `_GEAR_FIELDS` created on `x_gear`
  - Given field already exists, when run, then no create call made (idempotent)
  - Given dry-run (default), when run, then no writes to Odoo

### 2. Update field constants and lookups — `odoo_connector.py`
- **Files**: `odoo_connector.py` (modify)
- **What**: Replace `GEAR_FIELDS` with `LISTING_FIELDS` (all x_listing read fields, including `x_status` and `x_studio_image`). Add slim `GEAR_FIELDS`. Rename `find_gear_by_url` → `find_listing_by_url`, update it to search `x_listing`.

`LISTING_FIELDS` must include: `id`, `x_name`, `x_model_id`, `x_url`, `x_platform`, `x_price`, `x_currency_id`, `x_shipping`, `x_condition`, `x_status`, `x_is_available`, `x_can_accept_offers`, `x_is_taxed`, `x_published_at`, `x_gear_id`, `x_studio_image`

- **Acceptance**:
  - Given a Reverb URL, when `find_listing_by_url(conn, url)` called, then searches `x_listing` by `x_url` or Reverb item ID
  - Given `LISTING_FIELDS`, then contains all fields needed by sync and validate

### 3. Rewire sync to target `x_listing` — `sync_model.py`
- **Files**: `sync_model.py` (modify)
- **What**: All creates and updates target `x_listing` instead of `x_gear`. Rename internal helpers (`_fetch_gear` → `_fetch_listings`, `_reverb_to_gear_vals` → `_reverb_to_listing_vals`). Remove any `x_gear` creation logic — sync never creates `x_gear`. Replace `x_status` references with `x_status` where applicable.

- **Acceptance**:
  - Given a Reverb search result not in Odoo, when sync applied, then `x_listing` record created, no `x_gear` record created
  - Given existing `x_listing`, when price changes, then `x_listing.x_price` updated
  - Given `--dry-run`, when run, then no writes

### 4. Rewire validate to target `x_listing` — `validate_model.py`
- **Files**: `validate_model.py` (modify)
- **What**: Replace all `x_gear` references with `x_listing`. Update `_collect_model_data`, `_validate_single_model`, and `_apply_validation_updates` to read/write `x_listing`. Replace `x_status` with `x_status`.

- **Acceptance**:
  - Given an existing `x_listing` with a stale price, when validate applied, then `x_listing.x_price` updated
  - Given `--dry-run`, when run, then report printed but no writes

### 5. Update all tests
- **Files**: `tests/test_create_odoo_schema.py`, `tests/test_sync_model.py`, `tests/test_validate_model.py`, `tests/test_odoo_connector.py` (modify)
- **What**: Update mocks and assertions to reflect `x_listing` as primary record. Remove tests asserting `x_gear` creation during sync. Add tests asserting `x_listing` creation. Update field name references (`x_status` → `x_status`).
- **Acceptance**:
  - `uv run pytest` passes with no failures

## Testing Strategy
- **Unit**: mock-based tests for each helper (field creation, listing creation, change detection)
- **Manual**: run `reverb2odoo add-model-fields --apply` against dev Odoo, verify fields appear in Studio on both models

## Dependencies
- `x_gear` and `x_listing` models already created in Odoo Studio (done)
- `x_gear` was created before `x_listing` in Studio (x_listing.x_gear_id reference is valid)

## Notes
- `x_price` = final price only — no asking price field
- `x_status` stages must be configured in Studio Kanban for each model (watching/acquired/passed/closed/for_sale/sold for x_listing; owned/sold for x_gear)
- `x_studio_image` already present on both models — no image field creation needed
- Legacy `GUITAR_FIELDS` / `x_guitar` references left untouched
- Sell flow: create one `x_listing` per platform manually; winning listing → stage `sold`; others → stage `closed`
- P&L query: `sold_listing.x_price − acquired_listing.x_price`
