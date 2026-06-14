"""Tests for KitRecord and KitPartRecord in models.py."""

from __future__ import annotations

import pytest

from models import KitPartRecord, KitRecord

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
