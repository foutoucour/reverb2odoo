"""Tests for create_odoo_schema helpers."""

from unittest.mock import MagicMock

import pytest

from create_odoo_schema import (
    _GEAR_FIELDS,
    _GEAR_O2M_FIELD,
    _LISTING_FIELDS,
    _MODELS_PRICE_FIELDS,
    create_schema,
    ensure_field,
    get_field_id,
    get_model_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(ir_model_results=None, ir_fields_results=None):
    """Return a mock odoolib connection with configurable search_read responses."""
    conn = MagicMock()

    ir_model_mock = MagicMock()
    ir_model_mock.search_read.return_value = ir_model_results or []

    ir_fields_mock = MagicMock()
    ir_fields_mock.search_read.return_value = ir_fields_results or []

    def get_model_side_effect(name):
        if name == "ir.model":
            return ir_model_mock
        if name == "ir.model.fields":
            return ir_fields_mock
        return MagicMock()

    conn.get_model.side_effect = get_model_side_effect
    return conn, ir_model_mock, ir_fields_mock


# ---------------------------------------------------------------------------
# get_model_id
# ---------------------------------------------------------------------------


class TestGetModelId:
    def test_returns_id_when_found(self):
        conn, ir_model, _ = _make_conn(ir_model_results=[{"id": 42}])

        result = get_model_id(conn, "x_gear")

        assert result == 42
        ir_model.search_read.assert_called_once_with([("model", "=", "x_gear")], ["id"], limit=1)

    def test_returns_none_when_not_found(self):
        conn, ir_model, _ = _make_conn(ir_model_results=[])

        result = get_model_id(conn, "x_gear")

        assert result is None

    def test_passes_model_name_as_given(self):
        conn, ir_model, _ = _make_conn(ir_model_results=[{"id": 7}])

        get_model_id(conn, "x_listing")

        domain = ir_model.search_read.call_args[0][0]
        assert domain == [("model", "=", "x_listing")]


# ---------------------------------------------------------------------------
# get_field_id
# ---------------------------------------------------------------------------


class TestGetFieldId:
    def test_returns_id_when_found(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[{"id": 99}])

        result = get_field_id(conn, 42, "x_name")

        assert result == 99
        ir_fields.search_read.assert_called_once_with(
            [("model_id", "=", 42), ("name", "=", "x_name")], ["id"], limit=1
        )

    def test_returns_none_when_not_found(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])

        result = get_field_id(conn, 42, "x_name")

        assert result is None


# ---------------------------------------------------------------------------
# ensure_field
# ---------------------------------------------------------------------------


class TestEnsureField:
    def test_skips_when_field_exists(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[{"id": 5}])

        ensure_field(conn, 10, "x_gear", _GEAR_FIELDS[0], dry_run=False)

        ir_fields.create.assert_not_called()

    def test_creates_field_when_missing(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])
        char_field = {
            "name": "x_name",
            "field_description": "Gear Title",
            "ttype": "char",
            "required": True,
        }

        ensure_field(conn, 10, "x_gear", char_field, dry_run=False)

        ir_fields.create.assert_called_once_with(
            {
                **char_field,
                "model_id": 10,
                "state": "manual",
            }
        )

    def test_dry_run_skips_create(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])

        ensure_field(conn, 10, "x_gear", _GEAR_FIELDS[0], dry_run=True)

        ir_fields.create.assert_not_called()

    def test_creates_selection_field(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])
        sel_field = {
            "name": "x_status",
            "field_description": "Status",
            "ttype": "selection",
            "selection": "[('watching', 'Watching')]",
        }

        ensure_field(conn, 10, "x_gear", sel_field, dry_run=False)

        ir_fields.create.assert_called_once()
        created = ir_fields.create.call_args[0][0]
        assert created["ttype"] == "selection"
        assert "selection" in created

    def test_creates_many2one_field(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])
        m2o_field = {
            "name": "x_model_id",
            "field_description": "Model",
            "ttype": "many2one",
            "relation": "x_models",
        }

        ensure_field(conn, 10, "x_gear", m2o_field, dry_run=False)

        created = ir_fields.create.call_args[0][0]
        assert created["relation"] == "x_models"

    def test_required_m2o_has_restrict_ondelete(self):
        """Odoo 19 rejects required m2o with default set null ondelete policy."""
        x_gear_id_field = next(f for f in _LISTING_FIELDS if f["name"] == "x_gear_id")
        assert x_gear_id_field.get("required") is True
        assert x_gear_id_field.get("on_delete") == "restrict"

    def test_creates_one2many_field(self):
        conn, _, ir_fields = _make_conn(ir_fields_results=[])

        ensure_field(conn, 10, "x_gear", _GEAR_O2M_FIELD, dry_run=False)

        created = ir_fields.create.call_args[0][0]
        assert created["ttype"] == "one2many"
        assert created["relation"] == "x_listing"
        assert created["relation_field"] == "x_gear_id"


# ---------------------------------------------------------------------------
# create_schema — integration-style (all mocked)
# ---------------------------------------------------------------------------


class TestCreateSchema:
    def _make_full_conn(self, gear_id=10, listing_id=20, models_id=100):
        """Build a mock connection. Pass None to simulate a missing model."""
        conn = MagicMock()

        ir_model_mock = MagicMock()

        def ir_model_search(domain, fields, limit=None):
            model_name = domain[0][2]
            if model_name == "x_gear":
                return [{"id": gear_id}] if gear_id else []
            if model_name == "x_listing":
                return [{"id": listing_id}] if listing_id else []
            if model_name == "x_models":
                return [{"id": models_id}] if models_id else []
            return []

        ir_model_mock.search_read.side_effect = ir_model_search

        ir_fields_mock = MagicMock()
        ir_fields_mock.search_read.return_value = []

        def get_model_side_effect(name):
            if name == "ir.model":
                return ir_model_mock
            if name == "ir.model.fields":
                return ir_fields_mock
            return MagicMock()

        conn.get_model.side_effect = get_model_side_effect
        return conn, ir_model_mock, ir_fields_mock

    def test_dry_run_creates_nothing(self):
        conn, _, ir_fields = self._make_full_conn()

        create_schema(conn, dry_run=True)

        ir_fields.create.assert_not_called()

    def test_aborts_when_gear_missing(self):
        conn, _, ir_fields = self._make_full_conn(gear_id=None)

        create_schema(conn, dry_run=False)

        ir_fields.create.assert_not_called()

    def test_aborts_when_listing_missing(self):
        conn, _, ir_fields = self._make_full_conn(listing_id=None)

        create_schema(conn, dry_run=False)

        # No x_listing or x_gear.x_listing_ids fields created
        created_names = [c[0][0]["name"] for c in ir_fields.create.call_args_list]
        assert "x_gear_id" not in created_names
        assert "x_listing_ids" not in created_names

    def test_total_fields_created(self):
        """All fields from all three models are created when everything exists."""
        conn, _, ir_fields = self._make_full_conn()

        create_schema(conn, dry_run=False)

        expected = len(_GEAR_FIELDS) + 1 + len(_LISTING_FIELDS) + len(_MODELS_PRICE_FIELDS)
        assert ir_fields.create.call_count == expected

    def test_o2m_field_created_after_listing(self):
        """x_listing_ids must be created after x_listing.x_gear_id exists."""
        conn, _, ir_fields = self._make_full_conn()
        creation_order = []

        def track_create(vals):
            creation_order.append(vals["name"])

        ir_fields.create.side_effect = track_create

        create_schema(conn, dry_run=False)

        gear_id_pos = creation_order.index("x_gear_id")
        listing_ids_pos = creation_order.index("x_listing_ids")
        assert gear_id_pos < listing_ids_pos

    def test_price_bracket_fields_added_to_x_models(self):
        conn, _, ir_fields = self._make_full_conn(models_id=100)
        created_fields = []

        def track_create(vals):
            created_fields.append(vals["name"])

        ir_fields.create.side_effect = track_create

        create_schema(conn, dry_run=False)

        expected_bracket_fields = {f["name"] for f in _MODELS_PRICE_FIELDS}
        assert expected_bracket_fields.issubset(set(created_fields))

    def test_missing_x_models_skips_price_brackets(self):
        conn, _, ir_fields = self._make_full_conn(models_id=None)

        create_schema(conn, dry_run=False)

        created_field_names = [c[0][0]["name"] for c in ir_fields.create.call_args_list]
        bracket_names = {f["name"] for f in _MODELS_PRICE_FIELDS}
        assert not bracket_names.intersection(set(created_field_names))


# ---------------------------------------------------------------------------
# Schema constant sanity checks
# ---------------------------------------------------------------------------


class TestSchemaConstants:
    def test_all_fields_have_required_keys(self):
        for field in _GEAR_FIELDS + _LISTING_FIELDS + _MODELS_PRICE_FIELDS + [_GEAR_O2M_FIELD]:
            assert "name" in field
            assert "ttype" in field
            assert "field_description" in field

    @pytest.mark.parametrize(
        "field",
        [pytest.param(f, id=f["name"]) for f in _GEAR_FIELDS if f["ttype"] == "many2one"],
    )
    def test_gear_m2o_fields_have_underscored_relation(self, field):
        assert "." not in field["relation"], (
            f"x_gear.{field['name']}: relation must use underscored form, got {field['relation']!r}"
        )

    @pytest.mark.parametrize(
        "field",
        [
            pytest.param(f, id=f["name"])
            for f in _LISTING_FIELDS
            if f["ttype"] == "many2one" and not f["relation"].startswith("res.")
        ],
    )
    def test_listing_custom_m2o_fields_have_underscored_relation(self, field):
        assert "." not in field["relation"], (
            f"x_listing.{field['name']}: custom relation must use underscored form, "
            f"got {field['relation']!r}"
        )

    def test_listing_currency_id_uses_dotted_relation(self):
        currency_field = next(f for f in _LISTING_FIELDS if f["name"] == "x_currency_id")
        assert currency_field["relation"] == "res.currency"

    def test_price_bracket_field_names(self):
        names = {f["name"] for f in _MODELS_PRICE_FIELDS}
        assert names == {
            "x_price_p25",
            "x_price_p50",
            "x_price_p75",
            "x_price_sample_size",
            "x_price_updated_at",
        }
