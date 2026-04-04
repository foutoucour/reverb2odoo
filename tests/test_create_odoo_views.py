"""Tests for create_odoo_views helpers."""

from unittest.mock import MagicMock

from create_odoo_views import ensure_view, get_view_id


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
        ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=False)
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
