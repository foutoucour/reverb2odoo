"""Schema-drift test for the pydantic Odoo records.

Asserts that every field declared on :class:`GearRecord`,
:class:`ListingRecord`, and :class:`ModelsRecord` actually exists in the live
Odoo schema.

The live schema is captured as a static JSON snapshot in
``tests/fixtures/odoo_fields_snapshot.json``. Regenerate the snapshot whenever
Studio fields are added or renamed:

.. code-block:: bash

    set -a && source .env && set +a
    uv run python tests/fixtures/regenerate_snapshot.py

Then commit the updated JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from models import (
    GearRecord,
    ListingRecord,
    ModelsRecord,
    OdooRecord,
    WeightedTagGroupRecord,
    WeightedTagRecord,
)

_SNAPSHOT_PATH = Path(__file__).parent / "fixtures" / "odoo_fields_snapshot.json"


def _load_snapshot() -> dict[str, list[str]]:
    """Load the captured Odoo field snapshot from disk."""
    return json.loads(_SNAPSHOT_PATH.read_text())


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
    ],
)
def test_pydantic_fields_exist_in_odoo(record_cls: type[OdooRecord], odoo_model: str) -> None:
    """Every field declared on the pydantic class must exist in live Odoo."""
    snapshot = _load_snapshot()
    live_fields = set(snapshot[odoo_model])
    declared = set(record_cls.odoo_fields())

    missing = declared - live_fields
    assert not missing, (
        f"{record_cls.__name__} declares fields that are not in live Odoo "
        f"({odoo_model}): {sorted(missing)}. "
        f"Either rename the pydantic field to match Odoo, or remove it, or "
        f"add the field in Odoo Studio and regenerate the snapshot."
    )


def test_snapshot_covers_all_three_models() -> None:
    """Make sure the fixture covers every model the pydantic layer declares."""
    snapshot = _load_snapshot()
    assert set(snapshot.keys()) == {
        "x_gear",
        "x_listing",
        "x_models",
        "x_weighted_tags",
        "x_weighted_tag_groups",
    }
    for model, fields in snapshot.items():
        assert fields, f"Snapshot for {model} is empty — regenerate"
