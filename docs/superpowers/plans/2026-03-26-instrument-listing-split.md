# Instrument / Listing Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `x_guitar` (which conflates a physical instrument with a sale listing) into `x_instrument` (the physical object you own) and `x_listing` (one record per platform per time it's listed for sale), enabling multi-platform listings, full sale history, and richer physical details.

**Architecture:** Migration scripts in `migrations/` use the existing `odoolib` XML-RPC connection to create new Odoo Studio custom models and migrate data. Each script is idempotent. The application code (`sync_model.py`, `validate_model.py`, `odoo_connector.py`) is updated last, after data migration is verified. Old `x_guitar` records are **not deleted** — they are archived and kept as a safety net until the new structure is validated in production.

**Tech Stack:** Python 3.13, odoolib (XML-RPC), uv, pytest, Odoo 17 (Odoo.com hosted)

> **Critical naming rule for implementors:** `conn.get_model(name)` for **data operations** (search_read, create, write) always takes the **underscored** form: `"x_instrument"`, `"x_listing"`, `"x_guitar"`. The **dotted** form (`"x.instrument"`, `"x.guitar"`) is used only when querying `ir.model` or `ir.model.fields` to inspect the schema. Getting this wrong causes a silent `False` result on searches with no error message.

---

## Follow-on Plans (out of scope here)

- **Plan B** `2026-03-26-price-observation.md` — `x_price_observation` model for time-aware market price tracking (replaces static bracket floats on `x_models`)
- **Plan C** `2026-03-26-instrument-types.md` — `instrument_type` on `x_models`, pedal/amp-specific fields, rename guitar-centric lookup tables

---

## New Model Structure

```
x_models          (unchanged — model catalog: brand, specs, reverb category)
  └─ x_instrument (new — the physical object: serial, condition, acquisition, keeper status)
       └─ x_listing (new — one per platform per listing event: URL, price, availability)
x_expense         (move many2one link from x_guitar → x_instrument)
```

### `x_instrument` fields

| Technical name           | Label                | Type      | Notes                                          |
|--------------------------|----------------------|-----------|------------------------------------------------|
| `x_name`                 | Description          | char      | e.g. "1989 Gibson Les Paul Classic"            |
| `x_model_id`             | Model                | many2one → x_models | replaces x_guitar.x_studio_models    |
| `x_serial_number`        | Serial Number        | char      |                                                |
| `x_year`                 | Year                 | integer   | manufacturing year                             |
| `x_condition`            | Condition            | selection | mint/excellent/good/fair/poor                  |
| `x_weight_lbs`           | Weight (lbs)         | float     | migrated from x_guitar.x_studio_float_field_1r5_1ifr9edfj |
| `x_nut_width_mm`         | Nut Width (mm)       | float     |                                                |
| `x_neck_profile`         | Neck Profile         | selection | C/U/D/V/asymmetric                             |
| `x_fretboard_radius_in`  | Fretboard Radius (in)| float     |                                                |
| `x_fret_count`           | Fret Count           | integer   |                                                |
| `x_fret_size`            | Fret Size            | selection | small/medium/medium-jumbo/jumbo/wide-fat       |
| `x_modifications`        | Modifications        | text      |                                                |
| `x_is_custom_build`      | Custom Build         | boolean   | migrated from x_guitar.x_studio_custom_build_1 |
| `x_custom_part_ids`      | Custom Parts         | many2many → x_custom_build_part | migrated from x_guitar.x_studio_parts |
| `x_acquisition_date`     | Acquired On          | date      |                                                |
| `x_acquisition_price`    | Acquisition Price    | float     |                                                |
| `x_acquisition_source`   | Acquisition Source   | selection | reverb/marketplace/kijiji/facebook/local/trade/other |
| `x_status`               | Status               | selection | in_collection/listed/sold/traded               |
| `x_is_keeper`            | Keeper               | boolean   |                                                |
| `x_sold_date`            | Sold On              | date      |                                                |
| `x_sold_price`           | Sold Price           | float     |                                                |
| `x_currency_id`          | Currency             | many2one → res.currency | migrated from x_guitar.x_studio_currency_id |
| `x_notes`                | Notes                | text      | migrated from x_guitar.x_studio_notes         |
| `x_guitar_id`            | Source Guitar        | many2one → x_guitar | migration traceability, archive-only |

### `x_listing` fields

| Technical name           | Label                | Type      | Notes                                          |
|--------------------------|----------------------|-----------|------------------------------------------------|
| `x_name`                 | Description          | char      | e.g. "Les Paul Classic on Reverb"              |
| `x_instrument_id`        | Instrument           | many2one → x_instrument | core FK                            |
| `x_platform`             | Platform             | selection | reverb/marketplace/kijiji/facebook/local/other |
| `x_url`                  | URL                  | char      | migrated from x_guitar.x_studio_url            |
| `x_status`               | Status               | selection | active/sold/cancelled/expired                  |
| `x_asking_price_ht`      | Price HT             | float     | migrated from x_guitar.x_studio_best_price_ht |
| `x_asking_price_ttc`     | Price TTC            | float     | migrated from x_guitar.x_studio_best_price     |
| `x_value_ht`             | Value HT             | float     | migrated from x_guitar.x_studio_value          |
| `x_shipping`             | Shipping             | float     | migrated from x_guitar.x_studio_shipping       |
| `x_taxed`                | Taxed                | boolean   | migrated from x_guitar.x_studio_taxed          |
| `x_accept_offers`        | Accept Offers        | boolean   | migrated from x_guitar.x_studio_accept_offers  |
| `x_published_at`         | Published At         | date      | migrated from x_guitar.x_studio_published_at   |
| `x_platform_fees`        | Platform Fees        | float     | migrated from x_guitar.x_studio_reverb_fees    |
| `x_reverb_category_id`   | Reverb Category      | many2one → x_reverb_category | migrated from x_guitar.x_studio_model_id_reverb_category_id |
| `x_currency_id`          | Currency             | many2one → res.currency |                                    |
| `x_tax_rate_id`          | Tax Rate             | many2one → x_tax | migrated from x_guitar.x_studio_final_tax_rate_id |
| `x_notes`                | Notes                | text      |                                                |
| `x_guitar_id`            | Source Guitar        | many2one → x_guitar | migration traceability, archive-only |

---

## File Map

| File | Status | Responsibility |
|------|--------|---------------|
| `migrations/migrate_utils.py` | **Create** | Shared helpers: idempotent model/field creation, snapshot, logging |
| `migrations/000_snapshot.py` | **Create** | Save x_guitar record count + sample to JSON before touching anything |
| `migrations/001_cleanup_deleteme.py` | **Create** | Archive/remove fields labeled "deleteme" and known duplicate fields |
| `migrations/002_create_x_instrument.py` | **Create** | Create x_instrument model + all fields via ir.model / ir.model.fields |
| `migrations/003_create_x_listing.py` | **Create** | Create x_listing model + all fields |
| `migrations/004_migrate_data.py` | **Create** | Read x_guitar → write x_instrument + x_listing (1:1 at migration time) |
| `migrations/005_link_expenses.py` | **Create** | Update x_expense.x_studio_guitar many2one to point at x_instrument |
| `migrations/run_all.py` | **Create** | Orchestrator: run 000–005 in order, stop on first error |
| `tests/migrations/conftest.py` | **Create** | Shared Odoo connection fixture for migration tests |
| `tests/migrations/test_002_x_instrument.py` | **Create** | Verify x_instrument model + fields exist with correct types |
| `tests/migrations/test_003_x_listing.py` | **Create** | Verify x_listing model + fields exist with correct types |
| `tests/migrations/test_004_data.py` | **Create** | Verify counts + spot-check key field values after data migration |
| `odoo_connector.py` | **Modify** | Add INSTRUMENT_FIELDS, LISTING_FIELDS; keep GUITAR_FIELDS for rollback |
| `sync_model.py` | **Modify** | Write to x_listing + x_instrument instead of x_guitar |
| `validate_model.py` | **Modify** | Read x_listing records (platform=reverb, status=active) |
| `tests/test_sync_model.py` | **Modify** | Update mock field names to match new models |
| `tests/test_validate_model.py` | **Modify** | Update mock field names |

---

## Task 0 — Pre-migration snapshot

**Files:**
- Create: `migrations/migrate_utils.py`
- Create: `migrations/000_snapshot.py`

- [ ] **Step 1: Write the migration utils module**

```python
# migrations/migrate_utils.py
"""Shared helpers for idempotent Odoo model/field creation."""
from __future__ import annotations
import json
from pathlib import Path
from loguru import logger
import odoolib


def model_exists(conn: odoolib.main.Connection, model_name: str) -> bool:
    return bool(
        conn.get_model("ir.model").search_read(
            [("model", "=", model_name)], ["id"]
        )
    )


def field_exists(conn: odoolib.main.Connection, model_name: str, field_name: str) -> bool:
    return bool(
        conn.get_model("ir.model.fields").search_read(
            [("model", "=", model_name), ("name", "=", field_name)], ["id"]
        )
    )


def get_model_id(conn: odoolib.main.Connection, model_name: str) -> int:
    results = conn.get_model("ir.model").search_read(
        [("model", "=", model_name)], ["id"]
    )
    if not results:
        raise ValueError(f"Model {model_name!r} not found in Odoo")
    return results[0]["id"]


def ensure_model(conn: odoolib.main.Connection, technical_name: str, label: str) -> int:
    """Create the model if it doesn't exist. Returns model_id.

    The ir.model.access record is created without a group_id, which grants
    access to all users (Odoo treats no-group as global access for custom models).
    This matches how existing x_guitar / x_models were created via Odoo Studio
    on this instance. If Studio added explicit group restrictions to existing models,
    mirror those here by adding group_id to the ir.model.access.create call.
    To check: ir.model.access.search_read([("model_id.model","=","x.guitar")], ["group_id"])
    """
    if model_exists(conn, technical_name):
        logger.info("Model {} already exists, skipping creation", technical_name)
        return get_model_id(conn, technical_name)

    ir_model = conn.get_model("ir.model")
    model_id = ir_model.create({
        "name": label,
        "model": technical_name,
        "state": "manual",
    })
    # Grant full access to all internal users (no group_id = global)
    conn.get_model("ir.model.access").create({
        "name": f"{technical_name}_all",
        "model_id": model_id,
        "perm_read": True,
        "perm_write": True,
        "perm_create": True,
        "perm_unlink": True,
    })
    logger.success("Created model: {}", technical_name)
    return model_id


def ensure_field(
    conn: odoolib.main.Connection,
    model_name: str,
    model_id: int,
    name: str,
    label: str,
    ttype: str,
    **kwargs,
) -> None:
    """Create a field on a model if it doesn't exist. Idempotent."""
    if field_exists(conn, model_name, name):
        return
    conn.get_model("ir.model.fields").create({
        "model_id": model_id,
        "name": name,
        "field_description": label,
        "ttype": ttype,
        "state": "manual",
        **kwargs,
    })
    logger.debug("Created field {}.{}", model_name, name)


def save_snapshot(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))
    logger.info("Snapshot saved to {}", path)
```

- [ ] **Step 2: Write the snapshot script**

```python
# migrations/000_snapshot.py
"""Save a before-migration snapshot of x_guitar counts and sample records."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from migrate_utils import save_snapshot
from loguru import logger


def run(conn) -> None:
    guitar = conn.get_model("x_guitar")
    total = guitar.search_count([])
    active = guitar.search_count([("x_active", "=", True)])
    sample = guitar.search_read(
        [], ["x_name", "x_studio_url", "x_studio_models", "x_studio_value"], limit=5
    )

    snapshot = {
        "x_guitar_total": total,
        "x_guitar_active": active,
        "sample_records": sample,
    }

    save_snapshot(snapshot, Path(__file__).parent.parent / "migrations" / "snapshot.json")
    logger.success("Snapshot: {} total x_guitar records ({} active)", total, active)


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 3: Run the snapshot**

```bash
cd /Users/rieraj/__projects__/reverb2odoo
uv run python migrations/000_snapshot.py 2>&1
```

Expected output: `Snapshot: N total x_guitar records (M active)` and a `migrations/snapshot.json` file.

- [ ] **Step 4: Verify snapshot file**

```bash
cat migrations/snapshot.json | python -m json.tool | head -20
```

Expected: Valid JSON with `x_guitar_total`, `x_guitar_active`, and `sample_records`.

- [ ] **Step 5: Commit**

```bash
git add migrations/migrate_utils.py migrations/000_snapshot.py migrations/snapshot.json
git commit -m "feat: add migration utils and pre-migration snapshot"
```

---

## Task 1 — Cleanup deleteme fields

**Files:**
- Create: `migrations/001_cleanup_deleteme.py`

Context: the following fields are labeled "deleteme" in Odoo or are known duplicates:
- `x_models`: `x_studio_construction_score`, `x_studio_finish`, `x_studio_fretboard_1`, `x_studio_guitar_familly_ids`, `x_studio_guitar_neck_feel_id`, `x_studio_integer_field_4hq_1ifr6qi6p`, `x_studio_many2many_field_8av_1jivmqp92`
- `x_models`: `x_studio_rarity` (int) — duplicate of `x_studio_selection_field_5vd_1igkv87hm` (selection "Rarity")
- `x_guitar`: `x_studio_model`, `x_studio_model_sequence_score`

These are **archived** (set inactive) not hard-deleted, so Odoo retains the column.

- [ ] **Step 1: Write the cleanup script**

```python
# migrations/001_cleanup_deleteme.py
"""Archive (set inactive) known deleteme and duplicate fields."""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from loguru import logger

# (model_technical_name, field_name, reason)
FIELDS_TO_ARCHIVE = [
    # x_models
    ("x.models", "x_studio_construction_score", "deleteme"),
    ("x.models", "x_studio_finish", "replaced by x_studio_finish_ids"),
    ("x.models", "x_studio_fretboard_1", "deleteme"),
    ("x.models", "x_studio_guitar_familly_ids", "replaced by x_studio_family_ids"),
    ("x.models", "x_studio_guitar_neck_feel_id", "deleteme"),
    ("x.models", "x_studio_integer_field_4hq_1ifr6qi6p", "deleteme"),
    ("x.models", "x_studio_many2many_field_8av_1jivmqp92", "deleteme"),
    ("x.models", "x_studio_rarity", "duplicate of x_studio_selection_field_5vd_1igkv87hm"),
    # x_guitar
    ("x.guitar", "x_studio_model", "deleteme"),
    ("x.guitar", "x_studio_model_sequence_score", "deleteme"),
]


def run(conn) -> None:
    ir_fields = conn.get_model("ir.model.fields")
    archived = 0
    skipped = 0

    for model_dot, field_name, reason in FIELDS_TO_ARCHIVE:
        # Odoo stores the model name with dots, e.g. "x.models"
        results = ir_fields.search_read(
            [("model", "=", model_dot), ("name", "=", field_name)],
            ["id", "active"],
        )
        if not results:
            logger.debug("Field {}.{} not found — skipping", model_dot, field_name)
            skipped += 1
            continue
        fid = results[0]["id"]
        if not results[0].get("active", True):
            logger.debug("Field {}.{} already archived", model_dot, field_name)
            skipped += 1
            continue
        ir_fields.write([fid], {"active": False})
        logger.info("Archived {}.{} ({})", model_dot, field_name, reason)
        archived += 1

    logger.success("Cleanup done: {} archived, {} skipped", archived, skipped)


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 2: Run the cleanup**

```bash
uv run python migrations/001_cleanup_deleteme.py 2>&1
```

Expected: `Cleanup done: N archived, M skipped`

- [ ] **Step 3: Commit**

```bash
git add migrations/001_cleanup_deleteme.py
git commit -m "feat: cleanup deleteme and duplicate Odoo fields"
```

---

## Task 2 — Create `x_instrument`

**Files:**
- Create: `migrations/002_create_x_instrument.py`
- Create: `tests/migrations/conftest.py`
- Create: `tests/migrations/test_002_x_instrument.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/migrations/conftest.py
"""Shared fixtures for migration tests. Requires live ODOO_* env vars."""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from odoo_connector import get_connection


@pytest.fixture(scope="session")
def odoo_conn():
    """Return an authenticated Odoo connection using env vars."""
    return get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
```

```python
# tests/migrations/test_002_x_instrument.py
"""Verify x_instrument model and fields exist after migration 002."""
from __future__ import annotations

import pytest

# (field_name, expected_ttype)
EXPECTED_FIELDS = [
    ("x_name", "char"),
    ("x_model_id", "many2one"),
    ("x_serial_number", "char"),
    ("x_year", "integer"),
    ("x_condition", "selection"),
    ("x_weight_lbs", "float"),
    ("x_nut_width_mm", "float"),
    ("x_neck_profile", "selection"),
    ("x_fretboard_radius_in", "float"),
    ("x_fret_count", "integer"),
    ("x_fret_size", "selection"),
    ("x_modifications", "text"),
    ("x_is_custom_build", "boolean"),
    ("x_custom_part_ids", "many2many"),
    ("x_acquisition_date", "date"),
    ("x_acquisition_price", "float"),
    ("x_acquisition_source", "selection"),
    ("x_status", "selection"),
    ("x_is_keeper", "boolean"),
    ("x_sold_date", "date"),
    ("x_sold_price", "float"),
    ("x_currency_id", "many2one"),
    ("x_notes", "text"),
    ("x_guitar_id", "many2one"),
]


@pytest.mark.parametrize(
    "field_name, expected_ttype",
    [pytest.param(fn, tt, id=fn) for fn, tt in EXPECTED_FIELDS],
)
def test_x_instrument_field_exists(odoo_conn, field_name: str, expected_ttype: str) -> None:
    ir_fields = odoo_conn.get_model("ir.model.fields")
    results = ir_fields.search_read(
        [("model", "=", "x.instrument"), ("name", "=", field_name)],
        ["ttype"],
    )
    assert results, f"Field x_instrument.{field_name} does not exist"
    assert results[0]["ttype"] == expected_ttype, (
        f"x_instrument.{field_name}: expected {expected_ttype!r}, "
        f"got {results[0]['ttype']!r}"
    )


def test_x_instrument_model_exists(odoo_conn) -> None:
    ir_model = odoo_conn.get_model("ir.model")
    results = ir_model.search_read([("model", "=", "x.instrument")], ["id"])
    assert results, "x_instrument model does not exist in Odoo"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/migrations/test_002_x_instrument.py -v 2>&1
```

Expected: All tests FAIL with "x_instrument model does not exist"

- [ ] **Step 3: Write the migration script**

```python
# migrations/002_create_x_instrument.py
"""Create the x_instrument custom model in Odoo Studio."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from migrate_utils import ensure_model, ensure_field
from loguru import logger


def run(conn) -> None:
    mid = ensure_model(conn, "x.instrument", "Instrument")

    # Core identity
    ensure_field(conn, "x.instrument", mid, "x_name", "Description", "char",
                 required=True)
    ensure_field(conn, "x.instrument", mid, "x_model_id", "Model", "many2one",
                 relation="x.models")
    ensure_field(conn, "x.instrument", mid, "x_serial_number", "Serial Number", "char")
    ensure_field(conn, "x.instrument", mid, "x_year", "Year", "integer")
    ensure_field(conn, "x.instrument", mid, "x_condition", "Condition", "selection",
                 selection=json.dumps([
                     ["mint", "Mint"], ["excellent", "Excellent"],
                     ["good", "Good"], ["fair", "Fair"], ["poor", "Poor"],
                 ]))

    # Physical dimensions
    ensure_field(conn, "x.instrument", mid, "x_weight_lbs", "Weight (lbs)", "float")
    ensure_field(conn, "x.instrument", mid, "x_nut_width_mm", "Nut Width (mm)", "float")
    ensure_field(conn, "x.instrument", mid, "x_neck_profile", "Neck Profile", "selection",
                 selection=json.dumps([
                     ["C", "C"], ["U", "U"], ["D", "D"], ["V", "V"],
                     ["asymmetric", "Asymmetric"],
                 ]))
    ensure_field(conn, "x.instrument", mid, "x_fretboard_radius_in",
                 "Fretboard Radius (in)", "float")
    ensure_field(conn, "x.instrument", mid, "x_fret_count", "Fret Count", "integer")
    ensure_field(conn, "x.instrument", mid, "x_fret_size", "Fret Size", "selection",
                 selection=json.dumps([
                     ["small", "Small"], ["medium", "Medium"],
                     ["medium_jumbo", "Medium Jumbo"],
                     ["jumbo", "Jumbo"], ["wide_fat", "Wide/Fat"],
                 ]))
    ensure_field(conn, "x.instrument", mid, "x_modifications", "Modifications", "text")

    # Custom build
    ensure_field(conn, "x.instrument", mid, "x_is_custom_build", "Custom Build", "boolean")
    ensure_field(conn, "x.instrument", mid, "x_custom_part_ids", "Custom Parts",
                 "many2many", relation="x.custom_build_part")

    # Acquisition
    ensure_field(conn, "x.instrument", mid, "x_acquisition_date", "Acquired On", "date")
    ensure_field(conn, "x.instrument", mid, "x_acquisition_price",
                 "Acquisition Price", "float")
    ensure_field(conn, "x.instrument", mid, "x_acquisition_source",
                 "Acquisition Source", "selection",
                 selection=json.dumps([
                     ["reverb", "Reverb"], ["marketplace", "Facebook Marketplace"],
                     ["kijiji", "Kijiji"], ["facebook", "Facebook"],
                     ["local", "Local"], ["trade", "Trade"], ["other", "Other"],
                 ]))

    # Collection status
    ensure_field(conn, "x.instrument", mid, "x_status", "Status", "selection",
                 selection=json.dumps([
                     ["in_collection", "In Collection"], ["listed", "Listed"],
                     ["sold", "Sold"], ["traded", "Traded"],
                 ]),
                 default="in_collection")
    ensure_field(conn, "x.instrument", mid, "x_is_keeper", "Keeper", "boolean")
    ensure_field(conn, "x.instrument", mid, "x_sold_date", "Sold On", "date")
    ensure_field(conn, "x.instrument", mid, "x_sold_price", "Sold Price", "float")

    # Financial
    ensure_field(conn, "x.instrument", mid, "x_currency_id", "Currency", "many2one",
                 relation="res.currency")
    ensure_field(conn, "x.instrument", mid, "x_notes", "Notes", "text")

    # Migration traceability — link back to source x_guitar record
    ensure_field(conn, "x.instrument", mid, "x_guitar_id", "Source Guitar (archive)",
                 "many2one", relation="x.guitar")

    logger.success("x_instrument model ready")


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 4: Run the migration**

```bash
uv run python migrations/002_create_x_instrument.py 2>&1
```

Expected: `x_instrument model ready`

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/migrations/test_002_x_instrument.py -v 2>&1
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add migrations/002_create_x_instrument.py \
        tests/migrations/conftest.py \
        tests/migrations/test_002_x_instrument.py
git commit -m "feat: create x_instrument Odoo model with physical and acquisition fields"
```

---

## Task 3 — Create `x_listing`

**Files:**
- Create: `migrations/003_create_x_listing.py`
- Create: `tests/migrations/test_003_x_listing.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/migrations/test_003_x_listing.py
"""Verify x_listing model and fields exist after migration 003."""
from __future__ import annotations
import pytest

EXPECTED_FIELDS = [
    ("x_name", "char"),
    ("x_instrument_id", "many2one"),
    ("x_platform", "selection"),
    ("x_url", "char"),
    ("x_status", "selection"),
    ("x_asking_price_ht", "float"),
    ("x_asking_price_ttc", "float"),
    ("x_value_ht", "float"),
    ("x_shipping", "float"),
    ("x_taxed", "boolean"),
    ("x_accept_offers", "boolean"),
    ("x_published_at", "date"),
    ("x_platform_fees", "float"),
    ("x_reverb_category_id", "many2one"),
    ("x_currency_id", "many2one"),
    ("x_tax_rate_id", "many2one"),
    ("x_notes", "text"),
    ("x_guitar_id", "many2one"),
]


@pytest.mark.parametrize(
    "field_name, expected_ttype",
    [pytest.param(fn, tt, id=fn) for fn, tt in EXPECTED_FIELDS],
)
def test_x_listing_field_exists(odoo_conn, field_name: str, expected_ttype: str) -> None:
    ir_fields = odoo_conn.get_model("ir.model.fields")
    results = ir_fields.search_read(
        [("model", "=", "x.listing"), ("name", "=", field_name)],
        ["ttype"],
    )
    assert results, f"Field x_listing.{field_name} does not exist"
    assert results[0]["ttype"] == expected_ttype


def test_x_listing_model_exists(odoo_conn) -> None:
    ir_model = odoo_conn.get_model("ir.model")
    results = ir_model.search_read([("model", "=", "x.listing")], ["id"])
    assert results, "x_listing model does not exist in Odoo"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/migrations/test_003_x_listing.py -v 2>&1
```

Expected: All FAIL.

- [ ] **Step 3: Write the migration script**

```python
# migrations/003_create_x_listing.py
"""Create the x_listing custom model in Odoo Studio."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from migrate_utils import ensure_model, ensure_field
from loguru import logger


def run(conn) -> None:
    mid = ensure_model(conn, "x.listing", "Listing")

    ensure_field(conn, "x.listing", mid, "x_name", "Description", "char",
                 required=True)
    ensure_field(conn, "x.listing", mid, "x_instrument_id", "Instrument", "many2one",
                 relation="x.instrument", required=True)
    ensure_field(conn, "x.listing", mid, "x_platform", "Platform", "selection",
                 selection=json.dumps([
                     ["reverb", "Reverb"], ["marketplace", "Facebook Marketplace"],
                     ["kijiji", "Kijiji"], ["facebook", "Facebook"],
                     ["local", "Local"], ["other", "Other"],
                 ]),
                 default="reverb")
    ensure_field(conn, "x.listing", mid, "x_url", "URL", "char")
    ensure_field(conn, "x.listing", mid, "x_status", "Status", "selection",
                 selection=json.dumps([
                     ["active", "Active"], ["sold", "Sold"],
                     ["cancelled", "Cancelled"], ["expired", "Expired"],
                 ]),
                 default="active")
    ensure_field(conn, "x.listing", mid, "x_asking_price_ht", "Price HT", "float")
    ensure_field(conn, "x.listing", mid, "x_asking_price_ttc", "Price TTC", "float")
    ensure_field(conn, "x.listing", mid, "x_value_ht", "Value HT", "float")
    ensure_field(conn, "x.listing", mid, "x_shipping", "Shipping", "float")
    ensure_field(conn, "x.listing", mid, "x_taxed", "Taxed", "boolean")
    ensure_field(conn, "x.listing", mid, "x_accept_offers", "Accept Offers", "boolean")
    ensure_field(conn, "x.listing", mid, "x_published_at", "Published At", "date")
    ensure_field(conn, "x.listing", mid, "x_platform_fees", "Platform Fees", "float")
    ensure_field(conn, "x.listing", mid, "x_reverb_category_id", "Reverb Category",
                 "many2one", relation="x.reverb_category")
    ensure_field(conn, "x.listing", mid, "x_currency_id", "Currency", "many2one",
                 relation="res.currency")
    ensure_field(conn, "x.listing", mid, "x_tax_rate_id", "Tax Rate", "many2one",
                 relation="x.tax")
    ensure_field(conn, "x.listing", mid, "x_notes", "Notes", "text")

    # Migration traceability
    ensure_field(conn, "x.listing", mid, "x_guitar_id", "Source Guitar (archive)",
                 "many2one", relation="x.guitar")

    logger.success("x_listing model ready")


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 4: Run the migration and then the test**

```bash
uv run python migrations/003_create_x_listing.py 2>&1
uv run pytest tests/migrations/test_003_x_listing.py -v 2>&1
```

Expected: migration succeeds, all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add migrations/003_create_x_listing.py tests/migrations/test_003_x_listing.py
git commit -m "feat: create x_listing Odoo model for per-platform sale listings"
```

---

## Task 4 — Migrate data: x_guitar → x_instrument + x_listing

**Files:**
- Create: `migrations/004_migrate_data.py`
- Create: `tests/migrations/test_004_data.py`

> **IMPORTANT:** Run `000_snapshot.py` before this step if you haven't already. This migration is idempotent (it checks `x_guitar_id` on x_instrument before creating). Still: take a backup if your Odoo plan allows it.

- [ ] **Step 1: Write the failing data test (pre-migration state)**

```python
# tests/migrations/test_004_data.py
"""Verify data integrity after migration 004: x_guitar → x_instrument + x_listing."""
from __future__ import annotations
import json
from pathlib import Path
import pytest


SNAPSHOT_PATH = Path(__file__).parent.parent.parent / "migrations" / "snapshot.json"


@pytest.fixture(scope="module")
def snapshot() -> dict:
    assert SNAPSHOT_PATH.exists(), f"Run 000_snapshot.py first: {SNAPSHOT_PATH}"
    return json.loads(SNAPSHOT_PATH.read_text())


def test_instrument_count_matches_guitar_count(odoo_conn, snapshot) -> None:
    """Every x_guitar must have exactly one x_instrument after migration."""
    expected = snapshot["x_guitar_total"]
    actual = odoo_conn.get_model("x_instrument").search_count([])
    assert actual == expected, (
        f"x_instrument count ({actual}) != x_guitar count at snapshot ({expected})"
    )


def test_listing_count_matches_guitar_count(odoo_conn, snapshot) -> None:
    """Every x_guitar must have exactly one x_listing after migration."""
    expected = snapshot["x_guitar_total"]
    actual = odoo_conn.get_model("x_listing").search_count([])
    assert actual == expected


def test_all_listings_linked_to_instrument(odoo_conn) -> None:
    """No x_listing should have a null x_instrument_id."""
    unlinked = odoo_conn.get_model("x_listing").search_count(
        [("x_instrument_id", "=", False)]
    )
    assert unlinked == 0, f"{unlinked} listings have no x_instrument_id"


def test_all_instruments_linked_to_model(odoo_conn) -> None:
    """No x_instrument should have a null x_model_id."""
    unlinked = odoo_conn.get_model("x_instrument").search_count(
        [("x_model_id", "=", False)]
    )
    assert unlinked == 0, f"{unlinked} instruments have no x_model_id"


def test_url_migrated_correctly(odoo_conn, snapshot) -> None:
    """Spot-check: first sample record's URL appears on its x_listing."""
    sample = snapshot["sample_records"]
    if not sample:
        pytest.skip("No sample records in snapshot")

    first = sample[0]
    guitar_name = first["x_name"]

    # Find the x_listing migrated from this guitar
    listings = odoo_conn.get_model("x_listing").search_read(
        [("x_guitar_id.x_name", "=", guitar_name)],
        ["x_url", "x_guitar_id"],
        limit=1,
    )
    assert listings, f"No x_listing found for guitar {guitar_name!r}"
    # URL should match (or be empty if the guitar had no URL)
    original_url = first.get("x_studio_url") or ""
    assert listings[0]["x_url"] == original_url
```

- [ ] **Step 2: Run the test to verify it fails (migration not done yet)**

```bash
uv run pytest tests/migrations/test_004_data.py -v 2>&1
```

Expected: `test_instrument_count_matches_guitar_count` FAIL with count 0 != N.

- [ ] **Step 3: Write the data migration script**

```python
# migrations/004_migrate_data.py
"""
Migrate every x_guitar record to one x_instrument + one x_listing.

Idempotent: skips guitars that already have an x_instrument linked
via x_guitar_id.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from loguru import logger

GUITAR_FIELDS = [
    "id", "x_name", "x_active",
    # Physical (instrument)
    "x_studio_float_field_1r5_1ifr9edfj",  # weight
    "x_studio_custom_build_1",
    "x_studio_parts",
    "x_studio_notes",
    "x_studio_currency_id",
    # Model link
    "x_studio_models",
    # Listing
    "x_studio_url",
    "x_studio_best_price",
    "x_studio_best_price_ht",
    "x_studio_value",
    "x_studio_shipping",
    "x_studio_taxed",
    "x_studio_accept_offers",
    "x_studio_published_at",
    "x_studio_reverb_fees",
    "x_studio_model_id_reverb_category_id",
    "x_studio_final_tax_rate_id",
    "x_studio_is_available",
]

BATCH = 100


def _resolve_id(val) -> int | None:
    """Extract int id from an Odoo many2one value (could be [id, name] or id or False).

    Returns None when the field is unset (False in Odoo). Pass None values directly
    to Odoo write/create calls — Odoo treats None and False identically for many2one
    fields (clears the field).
    """
    if not val:
        return None
    if isinstance(val, (list, tuple)):
        return val[0]
    return val


def run(conn) -> None:
    guitar_model = conn.get_model("x_guitar")
    instrument_model = conn.get_model("x_instrument")
    listing_model = conn.get_model("x_listing")

    # Build a set of already-migrated guitar IDs
    already = instrument_model.search_read(
        [("x_guitar_id", "!=", False)], ["x_guitar_id"]
    )
    migrated_guitar_ids = {_resolve_id(r["x_guitar_id"]) for r in already}
    logger.info("{} guitars already migrated, skipping", len(migrated_guitar_ids))

    # Fetch all guitars in batches
    offset = 0
    created_instruments = 0
    created_listings = 0

    while True:
        guitars = guitar_model.search_read([], GUITAR_FIELDS, limit=BATCH, offset=offset)
        if not guitars:
            break

        for g in guitars:
            gid = g["id"]
            if gid in migrated_guitar_ids:
                continue

            # --- Create x_instrument ---
            instrument_vals = {
                "x_name": g.get("x_name") or "Unknown",
                "x_guitar_id": gid,
                # Status: if the guitar is active (has a listing), it's "listed";
                # otherwise assume "in_collection" — user can correct later.
                "x_status": "listed" if g.get("x_active") else "in_collection",
            }
            model_id_val = _resolve_id(g.get("x_studio_models"))
            if model_id_val:
                instrument_vals["x_model_id"] = model_id_val
            # NOTE: if x_studio_models is unset, x_model_id will be null.
            # This is expected for a small number of guitars with no model linked.
            # See Known Limitations section.
            if g.get("x_studio_float_field_1r5_1ifr9edfj"):
                instrument_vals["x_weight_lbs"] = g["x_studio_float_field_1r5_1ifr9edfj"]
            if g.get("x_studio_custom_build_1"):
                instrument_vals["x_is_custom_build"] = True
            if g.get("x_studio_parts"):
                instrument_vals["x_custom_part_ids"] = [[6, 0, g["x_studio_parts"]]]
            if g.get("x_studio_notes"):
                instrument_vals["x_notes"] = g["x_studio_notes"]
            if g.get("x_studio_currency_id"):
                instrument_vals["x_currency_id"] = _resolve_id(g["x_studio_currency_id"])

            instrument_id = instrument_model.create(instrument_vals)
            created_instruments += 1

            # --- Create x_listing ---
            listing_vals = {
                "x_name": g.get("x_name") or "Unknown",
                "x_instrument_id": instrument_id,
                "x_guitar_id": gid,
                "x_platform": "reverb",  # all existing records are from Reverb
                "x_url": g.get("x_studio_url") or "",
                "x_status": "active" if g.get("x_studio_is_available") else "cancelled",
            }
            for src, dst in [
                ("x_studio_best_price",      "x_asking_price_ttc"),
                ("x_studio_best_price_ht",   "x_asking_price_ht"),
                ("x_studio_value",           "x_value_ht"),
                ("x_studio_shipping",        "x_shipping"),
                ("x_studio_taxed",           "x_taxed"),
                ("x_studio_accept_offers",   "x_accept_offers"),
                ("x_studio_reverb_fees",     "x_platform_fees"),
            ]:
                val = g.get(src)
                if val is not None and val is not False:
                    listing_vals[dst] = val
            if g.get("x_studio_published_at"):
                listing_vals["x_published_at"] = g["x_studio_published_at"]
            if g.get("x_studio_model_id_reverb_category_id"):
                listing_vals["x_reverb_category_id"] = _resolve_id(
                    g["x_studio_model_id_reverb_category_id"]
                )
            if g.get("x_studio_final_tax_rate_id"):
                listing_vals["x_tax_rate_id"] = _resolve_id(g["x_studio_final_tax_rate_id"])
            if g.get("x_studio_currency_id"):
                listing_vals["x_currency_id"] = _resolve_id(g["x_studio_currency_id"])

            listing_model.create(listing_vals)
            created_listings += 1

        offset += BATCH
        logger.info("Progress: offset={}, created {} instruments, {} listings so far",
                    offset, created_instruments, created_listings)

    logger.success(
        "Migration done: {} x_instrument + {} x_listing created",
        created_instruments, created_listings,
    )


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 4: Run the migration (dry-run first: check connection, then run)**

```bash
uv run python migrations/004_migrate_data.py 2>&1
```

Expected: `Migration done: N x_instrument + N x_listing created`

- [ ] **Step 5: Run the data tests**

```bash
uv run pytest tests/migrations/test_004_data.py -v 2>&1
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add migrations/004_migrate_data.py tests/migrations/test_004_data.py
git commit -m "feat: migrate x_guitar data to x_instrument and x_listing (1:1)"
```

---

## Task 5 — Migrate expense links

**Files:**
- Create: `migrations/005_link_expenses.py`

`x_expense.x_studio_guitar` is a many2one pointing at `x_guitar`. After the migration each `x_guitar` has exactly one `x_instrument`. Update expenses to point at the instrument.

- [ ] **Step 1: Write the migration**

```python
# migrations/005_link_expenses.py
"""
Update x_expense.x_studio_guitar → x_studio_instrument_id.

Adds a new many2one field x_studio_instrument_id to x_expense,
then fills it using the x_guitar_id traceability field on x_instrument.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from migrate_utils import ensure_field, get_model_id
from loguru import logger


def run(conn) -> None:
    # 1. Add x_studio_instrument_id field to x_expense
    expense_model_id = get_model_id(conn, "x.expense")
    ensure_field(
        conn, "x.expense", expense_model_id,
        "x_studio_instrument_id", "Instrument", "many2one",
        relation="x.instrument",
    )

    # 2. For each expense that has x_studio_guitar set, find the matching
    #    x_instrument (via x_guitar_id) and fill x_studio_instrument_id.
    expense = conn.get_model("x_expense")
    instrument = conn.get_model("x_instrument")

    # Only process expenses that have NOT yet been linked to an instrument
    # (makes this script idempotent — safe to re-run).
    expenses = expense.search_read(
        [("x_studio_guitar", "!=", False), ("x_studio_instrument_id", "=", False)],
        ["id", "x_studio_guitar"],
    )
    logger.info("{} expenses to relink", len(expenses))

    updated = 0
    skipped = 0
    for exp in expenses:
        guitar_id = exp["x_studio_guitar"]
        if isinstance(guitar_id, (list, tuple)):
            guitar_id = guitar_id[0]

        instruments = instrument.search_read(
            [("x_guitar_id", "=", guitar_id)], ["id"], limit=1
        )
        if not instruments:
            logger.warning("No instrument found for guitar id={}, skipping expense id={}",
                           guitar_id, exp["id"])
            skipped += 1
            continue

        expense.write([exp["id"]], {"x_studio_instrument_id": instruments[0]["id"]})
        updated += 1

    logger.success("Expenses relinked: {} updated, {} skipped", updated, skipped)


if __name__ == "__main__":
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    run(conn)
```

- [ ] **Step 2: Run**

```bash
uv run python migrations/005_link_expenses.py 2>&1
```

Expected: `Expenses relinked: N updated, 0 skipped`

- [ ] **Step 3: Commit**

```bash
git add migrations/005_link_expenses.py
git commit -m "feat: relink x_expense from x_guitar to x_instrument"
```

---

## Task 6 — Orchestrator script

**Files:**
- Create: `migrations/run_all.py`

- [ ] **Step 1: Write the orchestrator**

```python
# migrations/run_all.py
"""Run all migrations in order. Stops on first failure."""
from __future__ import annotations
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from odoo_connector import get_connection
from loguru import logger

STEPS = [
    "migrations.000_snapshot",
    "migrations.001_cleanup_deleteme",
    "migrations.002_create_x_instrument",
    "migrations.003_create_x_listing",
    "migrations.004_migrate_data",
    "migrations.005_link_expenses",
]


def main() -> None:
    conn = get_connection(
        os.environ["ODOO_HOSTNAME"],
        os.environ["ODOO_DATABASE"],
        os.environ["ODOO_LOGIN"],
        os.environ["ODOO_PASSWORD"],
    )
    for step in STEPS:
        logger.info("Running {}…", step)
        mod = importlib.import_module(step)
        mod.run(conn)
        logger.success("✓ {}", step)
    logger.success("All migrations complete.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add migrations/run_all.py
git commit -m "feat: add migration orchestrator run_all.py"
```

---

## Task 7 — Update application code: `odoo_connector.py`

**Files:**
- Modify: `odoo_connector.py`

- [ ] **Step 1: Add the new field lists without removing GUITAR_FIELDS**

In `odoo_connector.py`, after the existing `GUITAR_FIELDS` list, add:

```python
#: Fields for x_instrument lookups.
INSTRUMENT_FIELDS: list[str] = [
    "x_name",
    "x_model_id",
    "x_serial_number",
    "x_year",
    "x_condition",
    "x_weight_lbs",
    "x_status",
    "x_is_keeper",
    "x_acquisition_date",
    "x_acquisition_price",
    "x_acquisition_source",
    "x_sold_date",
    "x_sold_price",
    "x_currency_id",
    "x_notes",
]

#: Fields for x_listing lookups.
LISTING_FIELDS: list[str] = [
    "x_name",
    "x_instrument_id",
    "x_platform",
    "x_url",
    "x_status",
    "x_asking_price_ht",
    "x_asking_price_ttc",
    "x_value_ht",
    "x_shipping",
    "x_taxed",
    "x_accept_offers",
    "x_published_at",
    "x_platform_fees",
    "x_reverb_category_id",
    "x_currency_id",
    "x_tax_rate_id",
]
```

Also add `find_listing_by_url` (searches `x_listing` by URL) and keep `find_guitar_by_url` as-is (do not remove — validate_model and sync_model currently import it; it will be replaced in Tasks 8–9).

Add after the existing `GUITAR_FIELDS` block:

```python
def find_listing_by_url(
    conn: odoolib.main.Connection,
    url: str,
    fields: list[str] | None = None,
) -> dict | None:
    """Look up a single x_listing record by its listing URL.

    Mirrors the logic of find_guitar_by_url but searches x_listing.
    NOTE: conn.get_model() uses the underscored form "x_listing".
    """
    if fields is None:
        fields = LISTING_FIELDS

    # Use underscored form for data operations
    model = conn.get_model("x_listing")

    results = model.search_read([("x_url", "=", url)], fields, limit=1)
    if results:
        logger.success("Exact URL match in x_listing → id={}", results[0]["id"])
        return results[0]

    item_id = _extract_reverb_item_id(url)
    if item_id:
        results = model.search_read(
            [("x_url", "ilike", item_id)], fields, limit=1
        )
        if results:
            logger.success("Partial URL match in x_listing (item {}) → id={}", item_id, results[0]["id"])
            return results[0]

    logger.warning("No x_listing record found for URL: {}", url)
    return None
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
uv run pytest tests/test_odoo_connector.py -v 2>&1
```

Expected: All existing tests PASS (GUITAR_FIELDS still exists, so nothing breaks).

- [ ] **Step 3: Commit**

```bash
git add odoo_connector.py
git commit -m "feat: add INSTRUMENT_FIELDS and LISTING_FIELDS to odoo_connector"
```

---

## Task 8 — Update `sync_model.py`

**Files:**
- Modify: `sync_model.py`
- Modify: `tests/test_sync_model.py`

The sync command currently:
1. Searches Reverb for a model name
2. Finds/creates `x_guitar` records

After this task it will:
1. Search Reverb for a model name
2. Find/create `x_listing` records (platform=reverb)
3. Create an `x_instrument` if the listing is new (1 instrument per new listing — the user will manually consolidate duplicates later)

- [ ] **Step 1: Locate all x_guitar references in sync_model.py**

```bash
grep -n "x_guitar\|GUITAR_FIELDS\|x_studio_url\|x_studio_value\|x_studio_models" sync_model.py
```

Note every line number. These are your edit targets.

- [ ] **Step 2: Replace `_fetch_guitars` with `_fetch_listings`**

Replace the `_fetch_guitars` function (currently uses `x_guitar` and `GUITAR_FIELDS`) with:

```python
def _fetch_listings(conn, model_id: int) -> list[dict]:
    """Return all active x_listing records linked to instruments of *model_id*."""
    listing = conn.get_model("x_listing")
    return listing.search_read(
        [
            ("x_instrument_id.x_model_id", "=", model_id),
            ("x_platform", "=", "reverb"),
        ],
        LISTING_FIELDS,
    )
```

Update all callers of `_fetch_guitars` to `_fetch_listings`.

- [ ] **Step 3: Replace `_compute_changes` field names**

`_compute_changes` currently references `x_studio_value`, `x_studio_accept_offers`, `x_studio_url`, `x_studio_is_available`, `x_name`. Update to the new field names:

```python
# Old → New
x_studio_value         → x_value_ht
x_studio_accept_offers → x_accept_offers
x_studio_url           → x_url
# x_name stays the same

# x_studio_is_available (bool) is the most important field — it marks a sold listing.
# In x_listing this becomes x_status (selection).
# Change the comparison logic from:
#   changes["x_studio_is_available"] = is_available
# To:
#   new_status = "active" if is_available else "sold"
#   if new_status != entry.get("x_status"):
#       changes["x_status"] = new_status
```

> **get_model() reminder:** All `conn.get_model()` calls in `sync_model.py` must use the underscored form: `"x_listing"`, `"x_instrument"`, `"x_models"`. Never the dotted form — that is only for `ir.model` schema queries.

- [ ] **Step 4: Replace the create-new-entry logic**

When a Reverb listing URL is not found in x_listing, the sync currently creates one `x_guitar`. Replace with: create one `x_instrument` + one `x_listing`:

```python
def _create_instrument_and_listing(
    conn,
    reverb: dict,
    model_id: int,
    default_shipping: float,
    image_b64: str | None,
) -> int:
    """Create an x_instrument + x_listing for a new Reverb listing."""
    instrument_model = conn.get_model("x_instrument")
    listing_model = conn.get_model("x_listing")

    name = reverb.get("name", "Unknown")

    instrument_id = instrument_model.create({
        "x_name": name,
        "x_model_id": model_id,
        "x_status": "listed",
    })

    listing_vals = {
        "x_name": name,
        "x_instrument_id": instrument_id,
        "x_platform": "reverb",
        "x_url": _clean_url(reverb.get("url", "")),
        "x_status": "active",
        "x_value_ht": _round_price(float(reverb.get("price", 0) or 0)),
        "x_shipping": float(reverb.get("shipping", 0) or default_shipping),
        "x_accept_offers": reverb.get("offers_enabled", False),
        "x_published_at": reverb.get("published_at", "")[:10] or False,
        "x_platform_fees": float(reverb.get("reverb_fee", 0) or 0),
    }
    listing_id = listing_model.create(listing_vals)
    return listing_id
```

- [ ] **Step 5: Update tests to match new field names**

In `tests/test_sync_model.py`, find every reference to `x_studio_*` fields in mock data and update them to the new names. Also update any `x_guitar` model references to `x.listing`.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_sync_model.py -v 2>&1
```

Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat: sync_model writes to x_instrument + x_listing instead of x_guitar"
```

---

## Task 9 — Update `validate_model.py`

**Files:**
- Modify: `validate_model.py`
- Modify: `tests/test_validate_model.py`

The validate command currently reads `x_guitar` records by model and refreshes them from Reverb. After this task it reads `x_listing` records (platform=reverb, status=active).

- [ ] **Step 1: Replace `_fetch_guitars` import with `_fetch_listings`**

`validate_model.py` imports `_fetch_guitars` from `sync_model`. Replace with `_fetch_listings`.

- [ ] **Step 2: Update field references in validate_model.py**

Same substitutions as Task 8 Step 3. Also update the write calls:

```python
# Old
guitar_model.write([entry_id], changes)
# New
listing_model = conn.get_model("x_listing")
listing_model.write([listing_id], changes)
```

- [ ] **Step 3: Update the "find entry by URL" call**

Replace:
```python
existing = find_guitar_by_url(conn, url)
```
With:
```python
from odoo_connector import find_listing_by_url
existing = find_listing_by_url(conn, url)
```

- [ ] **Step 4: Update tests and run**

```bash
uv run pytest tests/test_validate_model.py -v 2>&1
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add validate_model.py tests/test_validate_model.py
git commit -m "feat: validate_model reads/writes x_listing instead of x_guitar"
```

---

## Task 10 — Full test suite + verification

- [ ] **Step 1: Run the entire test suite**

```bash
uv run pytest -v 2>&1
```

Expected: All tests PASS. Note any failures and fix before continuing.

- [ ] **Step 2: Smoke test sync**

```bash
# Sync one well-known model to verify end-to-end flow
uv run python cli.py sync "Les Paul Classic" --dry-run 2>&1
```

Expected: Finds Reverb listings, matches against x_listing records, reports changes — no errors.

- [ ] **Step 3: Smoke test validate**

```bash
uv run python cli.py validate --all --dry-run 2>&1
```

Expected: Reads x_listing records, fetches Reverb data, reports changes — no errors.

- [ ] **Step 4: Verify counts in Odoo**

```bash
uv run python -c "
import os, sys
sys.path.insert(0, '.')
from odoo_connector import get_connection
conn = get_connection(os.environ['ODOO_HOSTNAME'], os.environ['ODOO_DATABASE'],
                      os.environ['ODOO_LOGIN'], os.environ['ODOO_PASSWORD'])
import json
snap = json.loads(open('migrations/snapshot.json').read())
instr = conn.get_model('x_instrument').search_count([])
lst = conn.get_model('x_listing').search_count([])
gtr = conn.get_model('x_guitar').search_count([])
print(f'x_guitar (original): {gtr}  (snapshot was {snap[\"x_guitar_total\"]})')
print(f'x_instrument: {instr}')
print(f'x_listing: {lst}')
" 2>&1
```

Expected: `x_instrument` and `x_listing` counts both equal the `x_guitar` count from the snapshot.

- [ ] **Step 5: Final commit**

```bash
git add migrations/snapshot.json odoo_connector.py sync_model.py validate_model.py \
        tests/test_sync_model.py tests/test_validate_model.py
git commit -m "chore: post-migration verification — instrument/listing split complete"
```

---

## Rollback Plan

The old `x_guitar` records are **never deleted**. If anything goes wrong:

1. Revert the application code to the old `x_guitar` references (the `GUITAR_FIELDS` constant is kept in `odoo_connector.py`).
2. The `x_instrument` and `x_listing` models can be archived in Odoo Studio without data loss.
3. The `x_guitar_id` field on `x_instrument` and `x_listing` provides a full traceability link back to the original `x_guitar` record.

Once you are confident the new structure works in production (after ~2 weeks of normal use), archive `x_guitar` via `ir.model` and clean up the `x_guitar_id` traceability fields.

---

## Known limitations at end of this plan

- **`dedup_model.py` is not updated** — it still references `x_guitar` directly. This is intentional: dedup logic operates on existing `x_guitar` records which are kept as an archive. Update `dedup_model.py` in a follow-on task once `x_guitar` is formally archived.
- **Guitars with no `x_studio_models` value** will produce `x_instrument` records with a null `x_model_id`. This is a data quality issue in the source, not a migration bug. Run `x_instrument.search_count([("x_model_id", "=", False)])` after migration to see the count; fix manually in Odoo. Do not treat `test_all_instruments_linked_to_model` as a hard blocker if the number is small and known.

- All migrated listings have `x_platform = "reverb"` — Marketplace / Kijiji records will need manual correction in Odoo after migration (the old `x_models.x_studio_kijiji` / `x_studio_facebook_1` / `x_studio_ebay_1` URLs are the source).
- `x_instrument.x_status` defaults to `"listed"` for active records and `"in_collection"` for archived ones — the user will need to manually mark sold instruments as `"sold"` and set `x_is_keeper` on keepers.
- `x_instrument.x_acquisition_date` and `x_instrument.x_acquisition_price` are empty — no source data exists for these.
- Scoring fields on `x_guitar` (`x_studio_score`, `x_studio_final_score`, etc.) are **not migrated** — they will need to be recreated as computed fields on `x_listing` in a follow-on task.
