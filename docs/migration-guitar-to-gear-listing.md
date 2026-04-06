# Migration: x_guitar → x_gear + x_listing

## Why

`x_guitar` was doing two jobs at once:

- Representing a **physical item** (a specific guitar, pedal, or amp you own or track)
- Representing a **marketplace listing** (a URL, price, and availability on Reverb)

This made it impossible to associate multiple listings with the same physical item, caused confusing ownership state
tracking, and blocked fair price bracket computation across all listing history for a model.

## What changed

| Before                                        | After                                                  |
|-----------------------------------------------|--------------------------------------------------------|
| One `x_guitar` record per listing URL         | `x_gear` = one physical item (permanent)               |
| Duplicate gear → duplicate `x_guitar` records | `x_listing` = one marketplace entry, many per gear     |
| Single status field mixing intent + ownership | `x_gear.x_status` tracks physical lifecycle            |
| Price comparison done manually                | `x_models` p25/p50/p75 brackets computed automatically |

---

## New schema

### `x_gear` — physical item

| Field                 | Type                   | Notes                                             |
|-----------------------|------------------------|---------------------------------------------------|
| `x_name`              | char                   | gear title                                        |
| `x_model_id`          | many2one → `x_models`  |                                                   |
| `x_condition`         | selection              | mint / excellent / very_good / good / fair / poor |
| `x_intent`            | selection              | flip / keeper / unknown                           |
| `x_status`            | selection              | **watching** / **owned** / **closed**             |
| `x_is_not_interested` | boolean                | this specific item is out (defect, wrong color…)  |
| `x_image`             | image                  |                                                   |
| `x_guitar_id`         | many2one → `x_guitar`  | migration traceability, null for new records      |
| `x_listing_ids`       | one2many → `x_listing` | all marketplace entries for this item             |

**Status semantics:**

- `watching` — tracking it, don't own it yet
- `owned` — physically have it (maps from Bought or For Sale)
- `closed` — no longer in possession (maps from Sold)

`x_is_not_interested` can be set on any status (e.g., you're still watching a model for price data but would never buy
this specific item due to a defect).

**Model-level cascade:** if `x_models.x_studio_wanna = False`, all linked `x_gear` records are implicitly uninteresting
regardless of their own flag.

---

### `x_listing` — marketplace entry

| Field                 | Type                      | Notes                                               |
|-----------------------|---------------------------|-----------------------------------------------------|
| `x_name`              | char                      | listing title                                       |
| `x_gear_id`           | many2one → `x_gear`       | required                                            |
| `x_url`               | char                      | marketplace URL                                     |
| `x_platform`          | selection                 | reverb / marketplace / craigslist / other           |
| `x_price`             | float                     | listing price                                       |
| `x_currency_id`       | many2one → `res.currency` |                                                     |
| `x_shipping`          | float                     | shipping cost                                       |
| `x_status`            | selection                 | **active** / **acquired** / **passed** / **closed** |
| `x_is_too_expensive`  | boolean                   | explicit "passed because of price" flag             |
| `x_is_available`      | boolean                   | live on marketplace                                 |
| `x_can_accept_offers` | boolean                   |                                                     |
| `x_is_taxed`          | boolean                   |                                                     |
| `x_published_at`      | datetime                  |                                                     |
| `x_image`             | image                     | listing photo                                       |
| `x_guitar_id`         | many2one → `x_guitar`     | migration traceability, null for new records        |

**Direction inference:** buy-side vs sell-side is inferred from `x_gear.x_status` — no explicit field needed:

- gear is `watching` → listings are buy-side (you're considering buying)
- gear is `owned` or `closed` → listings include the acquisition event (`status=acquired`) and any sell-side postings

**Listing status semantics:**

- `active` — currently live on a marketplace
- `acquired` — you bought it (the buy-side listing that led to ownership)
- `passed` — you consciously decided not to pursue (set `x_is_too_expensive` if price was the reason)
- `closed` — listing disappeared externally (expired, removed by seller)

---

### `x_models` — price brackets (new fields)

| Field                 | Type     | Notes                                         |
|-----------------------|----------|-----------------------------------------------|
| `x_price_p25`         | float    | 25th percentile — lower bound of normal range |
| `x_price_p50`         | float    | median — fair market value reference          |
| `x_price_p75`         | float    | 75th percentile — upper bound of normal range |
| `x_price_sample_size` | integer  | number of listings used in computation        |
| `x_price_updated_at`  | datetime | last computation timestamp                    |

**Computation rules:**

- Source: all `x_listing` records linked via `x_gear.x_model_id`
- Window: last 12 months if ≥ 5 listings exist; otherwise all-time fallback
- One bracket per model (no condition segmentation)
- p25/p50/p75 via `statistics.quantiles` — robust to outliers by design

---

## Status mapping (x_guitar → x_gear + x_listing)

| `x_guitar` status | `x_gear.x_status` | `x_listing.x_status`              | Notes                                       |
|-------------------|-------------------|-----------------------------------|---------------------------------------------|
| Watched           | watching          | active (or closed if unavailable) |                                             |
| Not Interested    | watching          | active/closed                     | `x_is_not_interested = True` on x_gear      |
| Bought            | owned             | acquired                          |                                             |
| For Sale          | owned             | acquired                          | sell-side listings must be created manually |
| Sold              | closed            | acquired                          |                                             |

The source status field on `x_guitar` is `x_studio_selection_field_7tf_1igs0n52h`.

---

## Migration scripts

### Step 1 — Create Odoo models (manual, in Odoo Studio)

Create `x_gear` and `x_listing` with all fields listed above.
Add the five price bracket fields to `x_models`.
See `docs/migration-studio-checklist.md` for the field-by-field checklist.

### Step 2 — Run the migration

```bash
# Preview (no writes)
reverb2odoo migrate-guitar-to-gear-listing

# Apply
reverb2odoo migrate-guitar-to-gear-listing --apply
```

The script is **idempotent**: records where `x_gear.x_guitar_id` is already set are skipped.
Safe to re-run after a partial failure.

### Step 3 — Validate

```bash
reverb2odoo validate-migration
```

Checks performed:

| # | Check                | What it verifies                                                |
|---|----------------------|-----------------------------------------------------------------|
| 1 | Coverage             | Every `x_guitar` has a corresponding `x_gear`                   |
| 2 | Listing link         | Every migrated `x_gear` has at least one `x_listing`            |
| 3 | Status mapping       | `x_gear.x_status` matches expected value for source status      |
| 4 | Not-interested flag  | "Not Interested" x_guitar → `x_gear.x_is_not_interested = True` |
| 5 | Listing field values | `x_url` and `x_platform` populated on all migrated listings     |
| 6 | Orphan listings      | No `x_listing` with `x_gear_id = False`                         |
| 7 | Price brackets       | Models with ≥5 listings have brackets computed                  |

Exits with code 1 if any check fails.

### Step 4 — Compute price brackets

```bash
# Preview
reverb2odoo compute-price-brackets --dry-run

# Apply
reverb2odoo compute-price-brackets
```

Re-run whenever significant new listing data has been added.

---

## Code changes

| File                                | Change                                                                          |
|-------------------------------------|---------------------------------------------------------------------------------|
| `odoo_connector.py`                 | Added `GEAR_FIELDS`, `LISTING_FIELDS`, `find_listing_by_url()`                  |
| `sync_model.py`                     | Targets `x_gear` + `x_listing`; `_fetch_listings()` replaces `_fetch_guitars()` |
| `validate_model.py`                 | Targets `x_listing` instead of `x_guitar`                                       |
| `migrate_guitar_to_gear_listing.py` | **New** — migration script                                                      |
| `compute_price_brackets.py`         | **New** — price bracket computation                                             |
| `validate_migration.py`             | **New** — post-migration validation                                             |
| `cli.py`                            | Registers 3 new commands                                                        |

---

## Backward compatibility

`x_guitar` records and the `GUITAR_FIELDS` constant in `odoo_connector.py` are kept during the transition period. Once
migration is validated and the sync/validate commands are confirmed working against the new models, `x_guitar` can be
archived or removed in a future cleanup step.
