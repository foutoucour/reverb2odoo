"""Tests for create_odoo_views helpers."""

from unittest.mock import MagicMock

from create_odoo_views import (
    create_gear_views,
    create_listing_views,
    create_views,
    ensure_view,
    get_view_id,
)


def _make_conn(ir_view_results=None):
    conn = MagicMock()
    ir_view = MagicMock()
    ir_view.search_read.return_value = ir_view_results or []
    conn.get_model.return_value = ir_view
    return conn, ir_view


class TestGetViewId:
    def test_returns_id_when_found(self):
        conn, ir_view = _make_conn([{"id": 42}])
        result = get_view_id(conn, "x_gear", "list", "x_gear.list")
        assert result == 42
        ir_view.search_read.assert_called_once_with(
            [("model", "=", "x_gear"), ("type", "=", "list"), ("name", "=", "x_gear.list")],
            ["id"],
            limit=1,
        )

    def test_returns_none_when_not_found(self):
        conn, ir_view = _make_conn([])
        result = get_view_id(conn, "x_gear", "list", "x_gear.list")
        assert result is None


class TestEnsureView:
    def test_skips_create_when_view_exists(self):
        conn, ir_view = _make_conn([{"id": 10}])
        ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=False)
        ir_view.create.assert_not_called()

    def test_creates_view_when_missing(self):
        conn, ir_view = _make_conn([])
        ir_view.create.return_value = 99
        result = ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=False)
        assert result == 99
        ir_view.create.assert_called_once_with(
            {
                "name": "x_gear.list",
                "model": "x_gear",
                "type": "list",
                "arch": "<list/>",
            }
        )

    def test_dry_run_skips_create(self):
        conn, ir_view = _make_conn([])
        ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=True)
        ir_view.create.assert_not_called()

    def test_dry_run_returns_existing_id(self):
        conn, ir_view = _make_conn([{"id": 7}])
        result = ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=True)
        assert result == 7
        ir_view.create.assert_not_called()


class TestCreateGearViews:
    def test_dry_run_creates_nothing(self):
        conn, ir_view = _make_conn()
        create_gear_views(conn, dry_run=True)
        ir_view.create.assert_not_called()

    def test_creates_three_views(self):
        conn, ir_view = _make_conn()
        create_gear_views(conn, dry_run=False)
        assert ir_view.create.call_count == 3

    def test_view_names(self):
        conn, ir_view = _make_conn()
        create_gear_views(conn, dry_run=False)
        created_names = {c[0][0]["name"] for c in ir_view.create.call_args_list}
        assert created_names == {"x_gear.list", "x_gear.form", "x_gear.search"}

    def test_view_model_is_x_gear(self):
        conn, ir_view = _make_conn()
        create_gear_views(conn, dry_run=False)
        for call in ir_view.create.call_args_list:
            assert call[0][0]["model"] == "x_gear"

    def test_skips_existing_views(self):
        conn, ir_view = _make_conn()
        ir_view.search_read.return_value = [{"id": 1}]  # all views exist
        create_gear_views(conn, dry_run=False)
        ir_view.create.assert_not_called()


class TestCreateListingViews:
    def test_dry_run_creates_nothing(self):
        conn, ir_view = _make_conn()
        create_listing_views(conn, dry_run=True)
        ir_view.create.assert_not_called()

    def test_creates_three_views(self):
        conn, ir_view = _make_conn()
        create_listing_views(conn, dry_run=False)
        assert ir_view.create.call_count == 3

    def test_view_names(self):
        conn, ir_view = _make_conn()
        create_listing_views(conn, dry_run=False)
        created_names = {c[0][0]["name"] for c in ir_view.create.call_args_list}
        assert created_names == {"x_listing.list", "x_listing.form", "x_listing.search"}

    def test_view_model_is_x_listing(self):
        conn, ir_view = _make_conn()
        create_listing_views(conn, dry_run=False)
        for call in ir_view.create.call_args_list:
            assert call[0][0]["model"] == "x_listing"

    def test_skips_existing_views(self):
        conn, ir_view = _make_conn()
        ir_view.search_read.return_value = [{"id": 1}]  # all views exist
        create_listing_views(conn, dry_run=False)
        ir_view.create.assert_not_called()


class TestCreateViews:
    def test_dry_run_creates_nothing(self):
        conn, ir_view = _make_conn()
        create_views(conn, dry_run=True)
        ir_view.create.assert_not_called()

    def test_creates_six_views(self):
        """3 gear views + 3 listing views."""
        conn, ir_view = _make_conn()
        create_views(conn, dry_run=False)
        assert ir_view.create.call_count == 6
