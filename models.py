"""Pydantic source-of-truth for Odoo records consumed by reverb2odoo.

One class per Odoo model (``x_gear``, ``x_listing``, ``x_models``). Field
names mirror the live Odoo schema verbatim, including Studio quirks such as
``x_studio_lsting_ids`` (the ``i`` is genuinely missing in Odoo).

Each class is the single source of truth for:

1.  The field list passed to ``search_read`` — via :meth:`odoo_fields`.
2.  Typed access to a returned row — via :meth:`from_odoo`.

Both the local CLI scripts and the ``odoo_mcp`` server import these classes.
When a field is added/renamed, update the class once; both sides stay in
sync. A schema-drift test (``tests/test_models.py``) verifies every declared
field exists in live Odoo.
"""

from __future__ import annotations

from typing import Annotated, Any, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict

# ---------------------------------------------------------------------------
# Odoo value coercers
# ---------------------------------------------------------------------------


def _coerce_m2o(value: Any) -> tuple[int, str] | None:
    """Odoo returns ``False`` for an empty many2one, or ``[id, "Display"]``
    for a set value. Normalise to ``None`` or ``(id, name)``.
    """
    if value is False or value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (int(value[0]), str(value[1]))
    return None


def _coerce_id_list(value: Any) -> list[int]:
    """Odoo returns ``False`` for empty one2many/many2many, or ``[id, id, ...]``."""
    if value is False or value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [int(v) for v in value]
    return []


def _coerce_optional_str(value: Any) -> str | None:
    """Odoo returns ``False`` for an empty char/text/selection. Normalise to ``None``."""
    if value is False or value is None or value == "":
        return None
    return str(value)


def _coerce_optional_float(value: Any) -> float | None:
    if value is False or value is None:
        return None
    return float(value)


def _coerce_optional_int(value: Any) -> int | None:
    if value is False or value is None:
        return None
    return int(value)


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


OdooM2O = Annotated[tuple[int, str] | None, BeforeValidator(_coerce_m2o)]
OdooIds = Annotated[list[int], BeforeValidator(_coerce_id_list)]
OdooStr = Annotated[str | None, BeforeValidator(_coerce_optional_str)]
OdooFloat = Annotated[float | None, BeforeValidator(_coerce_optional_float)]
OdooInt = Annotated[int | None, BeforeValidator(_coerce_optional_int)]
OdooBool = Annotated[bool | None, BeforeValidator(_coerce_optional_bool)]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class OdooRecord(BaseModel):
    """Base for typed Odoo records.

    Subclasses declare fields with verbatim Odoo names. Two class methods
    drive every interaction with Odoo:

    - :meth:`odoo_fields` — list passed to ``search_read``.
    - :meth:`from_odoo` — parse a single row dict into a typed instance.
    """

    model_config = ConfigDict(extra="ignore", frozen=False)

    #: Odoo always returns a non-zero id for real records. A default of 0 lets
    #: test fixtures and placeholder records skip the field without a verbose
    #: ``id=0`` everywhere.
    id: int = 0

    @classmethod
    def odoo_fields(cls) -> list[str]:
        """Return the field list for ``search_read``."""
        return list(cls.model_fields.keys())

    @classmethod
    def from_odoo(cls, row: dict[str, Any]) -> Self:
        """Parse a row returned by ``search_read`` into a typed instance."""
        return cls.model_validate(row)


# ---------------------------------------------------------------------------
# x_gear — physical items (one per guitar / pedal / amp)
# ---------------------------------------------------------------------------


class GearRecord(OdooRecord):
    """A single physical item tracked in the collection.

    Field names are verbatim ``x_gear`` Odoo column names. ``x_studio_*``
    fields are Studio-defined. Note the genuine Studio typo
    ``x_studio_lsting_ids`` (missing the second ``i``).
    """

    x_name: OdooStr = None
    x_model_id: OdooM2O = None
    x_status: OdooStr = None
    x_intent: OdooStr = None
    x_serial_number: OdooStr = None
    x_active: OdooBool = None

    # Condition is split into "acquiring" (state when bought) and "current"
    # (state right now). The MCP previously asked for a non-existent
    # ``x_condition`` field; both real fields are surfaced here.
    x_studio_acquiring_condition: OdooStr = None
    x_studio_current_condition: OdooStr = None

    # Money + notes
    x_studio_acquiring_price: OdooFloat = None
    x_studio_total_expenses: OdooFloat = None
    x_studio_currency_id: OdooM2O = None
    x_studio_notes: OdooStr = None
    x_studio_acquiring_date: OdooStr = None
    x_studio_production_year: OdooInt = None

    # Materials & finish
    x_studio_body_material: OdooStr = None
    x_studio_top_cap_material: OdooStr = None
    x_studio_body_finish: OdooStr = None
    x_studio_neck_material: OdooStr = None
    x_studio_neck_finish: OdooStr = None
    x_studio_fretboard_material: OdooStr = None

    # Pickups
    x_studio_acquiring_bridge_pickup_id_1: OdooM2O = None
    x_studio_acquiring_neck_pickup_id: OdooM2O = None
    x_studio_acquiring_pickup_ids: OdooIds = []
    x_studio_current_bridge_pickup_id: OdooM2O = None
    x_studio_current_neck_pickup_id: OdooM2O = None
    x_studio_current_pickup_ids: OdooIds = []

    # Dimensions
    x_studio_scale_length: OdooFloat = None
    x_studio_scale_length_imperial: OdooStr = None
    x_studio_scale_radius: OdooFloat = None
    x_studio_scale_radius_imperial: OdooStr = None
    x_studio_nut_width: OdooFloat = None
    x_studio_nut_width_imperial: OdooFloat = None
    x_studio_thickness_first_fret: OdooFloat = None
    x_studio_thickness_first_fret_imperial: OdooFloat = None
    x_studio_thickness_twelfth_fret: OdooFloat = None
    x_studio_thickness_twelfth_fret_imperial: OdooFloat = None
    x_studio_weight: OdooFloat = None
    x_studio_weight_imperial: OdooFloat = None

    # Denormalised references
    x_studio_model_name: OdooStr = None
    x_studio_model_id_brand_id: OdooM2O = None
    x_studio_model_reverb_category_related_id: OdooM2O = None
    x_studio_image: OdooStr = None  # base64 binary as returned by Odoo

    # Linked listings — note the Studio typo ``lsting`` not ``listing``.
    x_studio_lsting_ids: OdooIds = []


# ---------------------------------------------------------------------------
# x_listing — marketplace entries (many per gear)
# ---------------------------------------------------------------------------


class ListingRecord(OdooRecord):
    """A single marketplace listing tracked against a gear model."""

    x_name: OdooStr = None
    x_url: OdooStr = None
    x_platform: OdooStr = None
    x_status: OdooStr = None
    x_condition: OdooStr = None
    x_published_at: OdooStr = None

    x_price: OdooFloat = None
    x_shipping: OdooFloat = None
    x_currency_id: OdooM2O = None

    x_is_available: OdooBool = None
    x_can_accept_offers: OdooBool = None
    x_is_taxed: OdooBool = None
    x_active: OdooBool = None

    x_model_id: OdooM2O = None
    x_gear_id: OdooM2O = None

    x_studio_image: OdooStr = None
    x_studio_notes: OdooStr = None
    x_studio_listing_score: OdooFloat = None
    x_studio_price_score: OdooFloat = None

    # Triage flag — used by pending_decisions as a proxy for the now-defunct
    # ``x_is_too_expensive`` schema design.
    x_studio_is_candidate: OdooBool = None


# ---------------------------------------------------------------------------
# x_models — gear catalogue (one per make/model variant)
# ---------------------------------------------------------------------------


class ModelsRecord(OdooRecord):
    """An entry in the gear catalogue (a specific make/model variant)."""

    x_name: OdooStr = None
    x_active: OdooBool = None

    x_studio_partner_id: OdooM2O = None
    x_studio_model_type: OdooStr = None
    x_studio_wanna: OdooBool = None
    x_studio_notes: OdooStr = None
    x_studio_image: OdooStr = None

    # Body / construction
    x_studio_guitar_familly_ids: OdooIds = []
    x_studio_guitar_neck_feel_id: OdooM2O = None
    x_studio_scale: OdooStr = None
    x_studio_finish: OdooM2O = None
    x_studio_fretboard_1: OdooM2O = None

    # Pricing — sliding-window percentiles computed by compute_price_brackets.
    # The MCP previously asked for non-existent ``x_studio_p25/p50/p75``.
    x_price_p25: OdooFloat = None
    x_price_p50: OdooFloat = None
    x_price_p75: OdooFloat = None
    x_price_sample_size: OdooInt = None
    x_price_updated_at: OdooStr = None

    x_studio_reverb_category_id: OdooM2O = None

    # Weighted tagging — tags carry a score, grouped under tag groups that
    # carry a multiply factor; x_studio_weighted_score is the computed result.
    x_studio_weighted_tag_ids: OdooIds = []
    x_studio_weighted_score: OdooInt = None


# ---------------------------------------------------------------------------
# x_weighted_tags — individual tag (score + group + linked models)
# ---------------------------------------------------------------------------


class WeightedTagRecord(OdooRecord):
    """A single weighted tag applied to one or more ``x_models``."""

    x_name: OdooStr = None
    x_active: OdooBool = None
    x_studio_score: OdooInt = None
    x_studio_weighted_tag_group_id: OdooM2O = None
    x_studio_model_ids: OdooIds = []


# ---------------------------------------------------------------------------
# x_weighted_tag_groups — group of tags with a shared multiply factor
# ---------------------------------------------------------------------------


class WeightedTagGroupRecord(OdooRecord):
    """A group of weighted tags. ``x_studio_multiply`` scales all member tag scores."""

    x_name: OdooStr = None
    x_active: OdooBool = None
    x_studio_multiply: OdooFloat = None
