# Kit Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `KitRecord` and `KitPartRecord` pydantic models and extend the schema drift
infrastructure so kit builds can be tracked in Odoo as `x_kit` / `x_kit_part` records.

**Architecture:** Two new pydantic classes follow the existing `OdooRecord` pattern in
`models.py`. The schema drift test and snapshot regeneration script are extended to cover the
new Odoo models. Odoo Studio setup (creating `x_kit`, `x_kit_part`, and extending the
`x_models` / `x_listing` selections) is a manual step — the code side is gated behind it.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, odoolib, uv

---

## Files touched

| Action | File |
|--------|------|
| Modify | `models.py` |
| Create | `tests/test_kit_models.py` |
| Modify | `tests/test_models.py` |
| Modify | `tests/fixtures/regenerate_snapshot.py` |
| Update | `tests/fixtures/odoo_fields_snapshot.json` *(after Odoo Studio step)* |

---

## Task 1: Write failing pydantic parsing tests

**Files:**
- Create: `tests/test_kit_models.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for KitRecord and KitPartRecord in models.py."""

from __future__ import annotations

import pytest

from models import KitRecord, KitPartRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kit_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "TV Yellow Korina Explorer",
        "x_status": "idea",
        "x_studio_notes": False,
        "x_gear_id": False,
        "x_kit_part_ids": False,
    }
    base.update(overrides)
    return base


def _kit_part_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 5,
        "x_kit_id": [1, "TV Yellow Korina Explorer"],
        "x_listing_id": [42, "Gotoh SD91 Tuners"],
        "x_quantity": 1,
        "x_studio_status": "ordered",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# KitRecord
# ---------------------------------------------------------------------------


def test_kit_record_parses_full_row() -> None:
    row = _kit_dict(
        x_status="building",
        x_studio_notes="Korina slab · Nitro TV Yellow",
        x_gear_id=[13, "TV Yellow Xplo P90"],
        x_kit_part_ids=[5, 6, 7],
    )
    kit = KitRecord.from_odoo(row)
    assert kit.id == 1
    assert kit.x_name == "TV Yellow Korina Explorer"
    assert kit.x_status == "building"
    assert kit.x_studio_notes == "Korina slab · Nitro TV Yellow"
    assert kit.x_gear_id == (13, "TV Yellow Xplo P90")
    assert kit.x_kit_part_ids == [5, 6, 7]


@pytest.mark.parametrize(
    "field, value",
    [
        pytest.param("x_name", False, id="name-false-to-none"),
        pytest.param("x_status", False, id="status-false-to-none"),
        pytest.param("x_studio_notes", False, id="notes-false-to-none"),
        pytest.param("x_gear_id", False, id="gear-id-false-to-none"),
    ],
)
def test_kit_record_coerces_false_to_none(field: str, value: object) -> None:
    kit = KitRecord.from_odoo(_kit_dict(**{field: value}))
    assert getattr(kit, field) is None


def test_kit_record_coerces_false_part_ids_to_empty_list() -> None:
    kit = KitRecord.from_odoo(_kit_dict(x_kit_part_ids=False))
    assert kit.x_kit_part_ids == []


def test_kit_record_odoo_fields() -> None:
    fields = KitRecord.odoo_fields()
    assert "id" in fields
    assert "x_name" in fields
    assert "x_status" in fields
    assert "x_studio_notes" in fields
    assert "x_gear_id" in fields
    assert "x_kit_part_ids" in fields


# ---------------------------------------------------------------------------
# KitPartRecord
# ---------------------------------------------------------------------------


def test_kit_part_record_parses_full_row() -> None:
    part = KitPartRecord.from_odoo(_kit_part_dict())
    assert part.id == 5
    assert part.x_kit_id == (1, "TV Yellow Korina Explorer")
    assert part.x_listing_id == (42, "Gotoh SD91 Tuners")
    assert part.x_quantity == 1
    assert part.x_studio_status == "ordered"


@pytest.mark.parametrize(
    "field, value",
    [
        pytest.param("x_kit_id", False, id="kit-id-false-to-none"),
        pytest.param("x_listing_id", False, id="listing-id-false-to-none"),
        pytest.param("x_quantity", False, id="quantity-false-to-none"),
        pytest.param("x_studio_status", False, id="status-false-to-none"),
    ],
)
def test_kit_part_record_coerces_false_to_none(field: str, value: object) -> None:
    part = KitPartRecord.from_odoo(_kit_part_dict(**{field: value}))
    assert getattr(part, field) is None


def test_kit_part_record_odoo_fields() -> None:
    fields = KitPartRecord.odoo_fields()
    assert "id" in fields
    assert "x_kit_id" in fields
    assert "x_listing_id" in fields
    assert "x_quantity" in fields
    assert "x_studio_status" in fields
```

- [ ] **Step 2: Run to confirm ImportError (models not defined yet)**

```bash
uv run pytest tests/test_kit_models.py -v
```

Expected: `ImportError: cannot import name 'KitRecord' from 'models'`

---

## Task 2: Add KitRecord and KitPartRecord to models.py

**Files:**
- Modify: `models.py`

- [ ] **Step 1: Add KitRecord after WeightedTagGroupRecord**

Open `models.py` and append after the `WeightedTagGroupRecord` class (after line 293):

```python
# ---------------------------------------------------------------------------
# x_kit — build projects (one per kit build, idea through done)
# ---------------------------------------------------------------------------


class KitRecord(OdooRecord):
    """A kit build project tracked from idea through completion.

    Mirrors the x_listing → x_gear pattern: the kit is the build log;
    x_gear_id points to the finished instrument when status reaches 'done'.
    """

    x_name: OdooStr = None
    x_status: OdooStr = None
    x_studio_notes: OdooStr = None
    x_gear_id: OdooM2O = None
    x_kit_part_ids: OdooIds = []


# ---------------------------------------------------------------------------
# x_kit_part — part line items joining a kit to a listing
# ---------------------------------------------------------------------------


class KitPartRecord(OdooRecord):
    """A single part in a kit build.

    Links an x_kit to an x_listing (platform = supplier slug, model_type = parts).
    Quantity and order status live here; price, URL, and supplier come from the listing.
    """

    x_kit_id: OdooM2O = None
    x_listing_id: OdooM2O = None
    x_quantity: OdooInt = None
    x_studio_status: OdooStr = None
```

- [ ] **Step 2: Run the parsing tests**

```bash
uv run pytest tests/test_kit_models.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest
```

Expected: all existing tests still pass (no regressions).

- [ ] **Step 4: Commit**

```bash
git add models.py tests/test_kit_models.py
git commit -m "feat(models): add KitRecord and KitPartRecord pydantic models"
```

---

## Task 3: Extend schema drift test and snapshot script

**Files:**
- Modify: `tests/test_models.py`
- Modify: `tests/fixtures/regenerate_snapshot.py`

- [ ] **Step 1: Add KitRecord and KitPartRecord to the test_models.py imports**

In `tests/test_models.py`, update the import block (currently lines 26–33):

```python
from models import (
    GearRecord,
    KitPartRecord,
    KitRecord,
    ListingRecord,
    ModelsRecord,
    OdooRecord,
    WeightedTagGroupRecord,
    WeightedTagRecord,
)
```

- [ ] **Step 2: Add parametrize entries for x_kit and x_kit_part**

In `tests/test_models.py`, extend the `@pytest.mark.parametrize` list (currently lines 44–55)
to add two new entries at the end:

```python
@pytest.mark.parametrize(
    "record_cls, odoo_model",
    [
        pytest.param(GearRecord, "x_gear", id="x_gear"),
        pytest.param(ListingRecord, "x_listing", id="x_listing"),
        pytest.param(ModelsRecord, "x_models", id="x_models"),
        pytest.param(WeightedTagRecord, "x_weighted_tags", id="x_weighted_tags"),
        pytest.param(
            WeightedTagGroupRecord,
            "x_weighted_tag_groups",
            id="x_weighted_tag_groups",
        ),
        pytest.param(KitRecord, "x_kit", id="x_kit"),
        pytest.param(KitPartRecord, "x_kit_part", id="x_kit_part"),
    ],
)
```

- [ ] **Step 3: Update the snapshot coverage assertion**

In `tests/test_models.py`, update `test_snapshot_covers_all_three_models` (currently line 72)
to expect the two new Odoo models:

```python
def test_snapshot_covers_all_three_models() -> None:
    """Make sure the fixture covers every model the pydantic layer declares."""
    snapshot = _load_snapshot()
    assert set(snapshot.keys()) == {
        "x_gear",
        "x_listing",
        "x_models",
        "x_weighted_tags",
        "x_weighted_tag_groups",
        "x_kit",
        "x_kit_part",
    }
    for model, fields in snapshot.items():
        assert fields, f"Snapshot for {model} is empty — regenerate"
```

- [ ] **Step 4: Add x_kit and x_kit_part to regenerate_snapshot.py**

In `tests/fixtures/regenerate_snapshot.py`, update `_MODELS` (currently line 32):

```python
_MODELS = (
    "x_gear",
    "x_listing",
    "x_models",
    "x_weighted_tags",
    "x_weighted_tag_groups",
    "x_kit",
    "x_kit_part",
)
```

- [ ] **Step 5: Run the schema drift test to confirm expected failures**

```bash
uv run pytest tests/test_models.py -v
```

Expected failures (snapshot does not yet contain x_kit or x_kit_part — that's correct until
Odoo Studio creates the models):

```
FAILED tests/test_models.py::test_pydantic_fields_exist_in_odoo[x_kit]
FAILED tests/test_models.py::test_pydantic_fields_exist_in_odoo[x_kit_part]
FAILED tests/test_models.py::test_snapshot_covers_all_three_models
```

All other parametrize entries must still pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_models.py tests/fixtures/regenerate_snapshot.py
git commit -m "test(models): extend schema drift test to cover x_kit and x_kit_part"
```

---

## Task 4: Odoo Studio setup (manual)

> This task is performed in the Odoo UI, not in code. Complete it before Task 5.

- [ ] **Step 1: Extend x_models.x_studio_model_type selection**

In Odoo Studio → `x_models` → field `x_studio_model_type`: add selection value `parts`.

- [ ] **Step 2: Create the x_kit model in Odoo Studio**

Create a new custom model named `x_kit` with these fields:

| Field name | Type | Notes |
|---|---|---|
| `x_name` | Char | Name — set as the display name field |
| `x_status` | Selection | Values: `idea`, `planning`, `sourcing`, `building`, `done` |
| `x_studio_notes` | Html | Vision / build log |
| `x_gear_id` | Many2one → `x_gear` | Set when done |
| `x_kit_part_ids` | One2many → `x_kit_part` (inverse of `x_kit_id`) | Parts list |

- [ ] **Step 3: Create the x_kit_part model in Odoo Studio**

Create a new custom model named `x_kit_part` with these fields:

| Field name | Type | Notes |
|---|---|---|
| `x_kit_id` | Many2one → `x_kit` | Parent kit |
| `x_listing_id` | Many2one → `x_listing` | Part offer (supplier + price + URL) |
| `x_quantity` | Integer | Default: 1 |
| `x_studio_status` | Selection | Values: `wanted`, `ordered`, `received` |

---

## Task 5: Regenerate snapshot and verify

> Requires: Task 4 complete and `.env` loaded with Odoo credentials.

- [ ] **Step 1: Load environment and regenerate the snapshot**

```bash
set -a && source .env && set +a
uv run python tests/fixtures/regenerate_snapshot.py
```

Expected output:

```
Wrote tests/fixtures/odoo_fields_snapshot.json
  x_gear: N fields
  x_listing: N fields
  x_models: N fields
  x_weighted_tags: N fields
  x_weighted_tag_groups: N fields
  x_kit: 5+ fields
  x_kit_part: 4+ fields
```

- [ ] **Step 2: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests pass, including:

```
PASSED tests/test_models.py::test_pydantic_fields_exist_in_odoo[x_kit]
PASSED tests/test_models.py::test_pydantic_fields_exist_in_odoo[x_kit_part]
PASSED tests/test_models.py::test_snapshot_covers_all_three_models
PASSED tests/test_kit_models.py::...  (all kit model parsing tests)
```

- [ ] **Step 3: Commit snapshot**

```bash
git add tests/fixtures/odoo_fields_snapshot.json
git commit -m "chore: regenerate Odoo fields snapshot with x_kit and x_kit_part"
```
