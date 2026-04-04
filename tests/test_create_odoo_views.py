"""Tests for create_odoo_views helpers."""

from unittest.mock import MagicMock

from create_odoo_views import (
    create_gear_views,
    create_listing_views,
    create_views,
    ensure_action,
    ensure_menu,
    ensure_view,
    get_action_id,
    get_menu_id,
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


def _make_multi_conn(model_map: dict):
    """Build a mock conn where get_model returns different mocks per model name."""
    conn = MagicMock()
    mocks = {name: MagicMock() for name in model_map}
    for name, results in model_map.items():
        mocks[name].search_read.return_value = results
    conn.get_model.side_effect = lambda name: mocks.get(name, MagicMock())
    return conn, mocks


class TestGetActionId:
    def test_returns_id_when_found(self):
        conn, mocks = _make_multi_conn({"ir.actions.act_window": [{"id": 5}]})
        result = get_action_id(conn, "Gear")
        assert result == 5
        mocks["ir.actions.act_window"].search_read.assert_called_once_with(
            [("name", "=", "Gear"), ("type", "=", "ir.actions.act_window")],
            ["id"],
            limit=1,
        )

    def test_returns_none_when_not_found(self):
        conn, mocks = _make_multi_conn({"ir.actions.act_window": []})
        result = get_action_id(conn, "Gear")
        assert result is None


class TestEnsureAction:
    def test_skips_when_exists(self):
        conn, mocks = _make_multi_conn({"ir.actions.act_window": [{"id": 3}]})
        ensure_action(conn, "Gear", "x_gear", "list,form", dry_run=False)
        mocks["ir.actions.act_window"].create.assert_not_called()

    def test_creates_when_missing(self):
        conn, mocks = _make_multi_conn({"ir.actions.act_window": []})
        mocks["ir.actions.act_window"].create.return_value = 77
        result = ensure_action(conn, "Gear", "x_gear", "list,form", dry_run=False)
        assert result == 77
        mocks["ir.actions.act_window"].create.assert_called_once_with(
            {
                "name": "Gear",
                "res_model": "x_gear",
                "view_mode": "list,form",
                "type": "ir.actions.act_window",
            }
        )

    def test_dry_run_skips_create(self):
        conn, mocks = _make_multi_conn({"ir.actions.act_window": []})
        ensure_action(conn, "Gear", "x_gear", "list,form", dry_run=True)
        mocks["ir.actions.act_window"].create.assert_not_called()


class TestGetMenuId:
    def test_returns_id_when_found(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": [{"id": 8}]})
        result = get_menu_id(conn, "Gear")
        assert result == 8
        mocks["ir.ui.menu"].search_read.assert_called_once_with(
            [("complete_name", "=", "Gear")], ["id"], limit=1
        )

    def test_returns_none_when_not_found(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": []})
        result = get_menu_id(conn, "Gear")
        assert result is None


class TestEnsureMenu:
    def test_skips_when_exists(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": [{"id": 2}]})
        ensure_menu(conn, "Gear", parent_id=None, action_id=None, dry_run=False)
        mocks["ir.ui.menu"].create.assert_not_called()

    def test_creates_top_level_menu(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": []})
        mocks["ir.ui.menu"].create.return_value = 11
        result = ensure_menu(conn, "Gear", parent_id=None, action_id=None, dry_run=False)
        assert result == 11
        mocks["ir.ui.menu"].create.assert_called_once_with({"name": "Gear"})

    def test_creates_submenu_with_parent_and_action(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": []})
        mocks["ir.ui.menu"].create.return_value = 12
        ensure_menu(conn, "Gear Items", parent_id=5, action_id=77, dry_run=False)
        mocks["ir.ui.menu"].create.assert_called_once_with(
            {
                "name": "Gear Items",
                "parent_id": 5,
                "action": "ir.actions.act_window,77",
            }
        )

    def test_dry_run_skips_create(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": []})
        ensure_menu(conn, "Gear", parent_id=None, action_id=None, dry_run=True)
        mocks["ir.ui.menu"].create.assert_not_called()


class TestCreateGearViews:
    def _make_conn(self):
        """Mock conn: all lookups return empty (nothing pre-exists)."""
        conn = MagicMock()
        ir_view = MagicMock()
        ir_view.search_read.return_value = []
        conn.get_model.return_value = ir_view
        return conn, ir_view

    def test_dry_run_creates_nothing(self):
        conn, ir_view = self._make_conn()
        create_gear_views(conn, dry_run=True)
        ir_view.create.assert_not_called()

    def test_creates_three_views(self):
        conn, ir_view = self._make_conn()
        create_gear_views(conn, dry_run=False)
        assert ir_view.create.call_count == 3

    def test_view_names(self):
        conn, ir_view = self._make_conn()
        create_gear_views(conn, dry_run=False)
        created_names = {c[0][0]["name"] for c in ir_view.create.call_args_list}
        assert created_names == {"x_gear.list", "x_gear.form", "x_gear.search"}

    def test_view_model_is_x_gear(self):
        conn, ir_view = self._make_conn()
        create_gear_views(conn, dry_run=False)
        for call in ir_view.create.call_args_list:
            assert call[0][0]["model"] == "x_gear"

    def test_skips_existing_views(self):
        conn, ir_view = self._make_conn()
        ir_view.search_read.return_value = [{"id": 1}]  # all views exist
        create_gear_views(conn, dry_run=False)
        ir_view.create.assert_not_called()


class TestCreateListingViews:
    def _make_conn(self):
        conn = MagicMock()
        ir_view = MagicMock()
        ir_view.search_read.return_value = []
        conn.get_model.return_value = ir_view
        return conn, ir_view

    def test_dry_run_creates_nothing(self):
        conn, ir_view = self._make_conn()
        create_listing_views(conn, dry_run=True)
        ir_view.create.assert_not_called()

    def test_creates_three_views(self):
        conn, ir_view = self._make_conn()
        create_listing_views(conn, dry_run=False)
        assert ir_view.create.call_count == 3

    def test_view_names(self):
        conn, ir_view = self._make_conn()
        create_listing_views(conn, dry_run=False)
        created_names = {c[0][0]["name"] for c in ir_view.create.call_args_list}
        assert created_names == {"x_listing.list", "x_listing.form", "x_listing.search"}

    def test_view_model_is_x_listing(self):
        conn, ir_view = self._make_conn()
        create_listing_views(conn, dry_run=False)
        for call in ir_view.create.call_args_list:
            assert call[0][0]["model"] == "x_listing"

    def test_skips_existing_views(self):
        conn, ir_view = self._make_conn()
        ir_view.search_read.return_value = [{"id": 1}]  # all views exist
        create_listing_views(conn, dry_run=False)
        ir_view.create.assert_not_called()


class TestCreateViews:
    def test_dry_run_creates_nothing(self):
        created = []
        conn = MagicMock()
        conn.get_model.side_effect = lambda name: _make_no_create_mock(created)
        create_views(conn, dry_run=True)
        assert created == []

    def test_creates_six_views_two_actions_three_menus(self):
        """
        6 views (3 gear + 3 listing), 2 actions (gear + listing),
        3 menus (Gear top-level, Gear Items submenu, Listings submenu).
        """
        view_creates = []
        action_creates = []
        menu_creates = []

        conn = MagicMock()
        counter = [0]

        def make_mock(model_name):
            m = MagicMock()
            m.search_read.return_value = []

            def side(vals):
                counter[0] += 1
                if model_name == "ir.ui.view":
                    view_creates.append(vals)
                elif model_name == "ir.actions.act_window":
                    action_creates.append(vals)
                elif model_name == "ir.ui.menu":
                    menu_creates.append(vals)
                return counter[0]

            m.create.side_effect = side
            return m

        conn.get_model.side_effect = make_mock

        create_views(conn, dry_run=False)

        assert len(view_creates) == 6
        assert len(action_creates) == 2
        assert len(menu_creates) == 3


def _make_no_create_mock(created_list):
    m = MagicMock()
    m.search_read.return_value = []
    m.create.side_effect = lambda vals: created_list.append(vals) or 1
    return m
