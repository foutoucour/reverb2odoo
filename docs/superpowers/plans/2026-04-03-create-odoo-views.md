# Create Odoo Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create list, form, and search views for `x_gear` and `x_listing` in Odoo, along with window actions and menu items, via a new `create-odoo-views` CLI command.

**Architecture:** A new `create_odoo_views.py` module follows the same dry-run / `--apply` / idempotent pattern as `create_odoo_schema.py`. Views are created via `ir.ui.view`, actions via `ir.actions.act_window`, and menus via `ir.ui.menu`. Each object is looked up by a stable external ID key before creation to ensure idempotency.

**Tech Stack:** Python 3.12+, odoolib (`conn.get_model()`), Click, loguru, pytest (unit tests with mock connections)

---

## Naming conventions (critical — getting these wrong causes silent failures)

- `ir.ui.view.model` field → underscored form for custom models: `"x_gear"`, `"x_listing"`
- `ir.actions.act_window.res_model` → same: `"x_gear"`, `"x_listing"`
- Standard Odoo model relations → dotted form: `"res.currency"`, `"res.partner"`
- View lookup key: `(model, type, name)` triple — use names like `"x_gear.list"`, `"x_gear.form"`, `"x_gear.search"`
- In Odoo 19 the list-view tag is `<list>` (not `<tree>`)

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `create_odoo_views.py` | **Create** | All view/action/menu creation logic + CLI |
| `tests/test_create_odoo_views.py` | **Create** | Unit tests for every helper and `create_views()` |
| `cli.py` | **Modify** | Import and register `create-odoo-views` command |
| `README.md` | **Modify** | Document the new command |

---

## Task 1: Core helpers — `get_view_id`, `ensure_view`

**Files:**
- Create: `create_odoo_views.py`
- Create: `tests/test_create_odoo_views.py`

- [ ] **Step 1: Write failing tests for `get_view_id` and `ensure_view`**

Create `tests/test_create_odoo_views.py`:

```python
"""Tests for create_odoo_views helpers."""

from unittest.mock import MagicMock

import pytest

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
        ir_view.create.assert_called_once_with({
            "name": "x_gear.list",
            "model": "x_gear",
            "type": "list",
            "arch": "<list/>",
        })

    def test_dry_run_skips_create(self):
        conn, ir_view = _make_conn([])
        ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=True)
        ir_view.create.assert_not_called()

    def test_dry_run_returns_existing_id(self):
        conn, ir_view = _make_conn([{"id": 7}])
        result = ensure_view(conn, "x_gear", "list", "x_gear.list", "<list/>", dry_run=True)
        assert result == 7
        ir_view.create.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_create_odoo_views.py -v
```

Expected: `ModuleNotFoundError: No module named 'create_odoo_views'`

- [ ] **Step 3: Implement `get_view_id` and `ensure_view`**

Create `create_odoo_views.py`:

```python
"""Create views, window actions, and menu items for x_gear and x_listing.

Usage (dry-run, default)::

    reverb2odoo create-odoo-views

Usage (apply changes)::

    reverb2odoo create-odoo-views --apply
"""

from __future__ import annotations

import click
from loguru import logger


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------


def get_view_id(conn, model: str, view_type: str, name: str) -> int | None:
    """Return the ir.ui.view id matching (model, type, name), or None."""
    ir_view = conn.get_model("ir.ui.view")
    results = ir_view.search_read(
        [("model", "=", model), ("type", "=", view_type), ("name", "=", name)],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_view(
    conn,
    model: str,
    view_type: str,
    name: str,
    arch: str,
    *,
    dry_run: bool,
) -> int | None:
    """Create an ir.ui.view if one with (model, type, name) does not exist.

    Returns the id (existing or new), or None in dry-run when missing.
    """
    existing_id = get_view_id(conn, model, view_type, name)
    if existing_id:
        logger.info("  View {} ({}) already exists (id={})", name, view_type, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create {} view: {}", view_type, name)
        return None

    ir_view = conn.get_model("ir.ui.view")
    new_id = ir_view.create({"name": name, "model": model, "type": view_type, "arch": arch})
    logger.success("  Created {} view: {} (id={})", view_type, name, new_id)
    return new_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_create_odoo_views.py::TestGetViewId tests/test_create_odoo_views.py::TestEnsureView -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add create_odoo_views.py tests/test_create_odoo_views.py
git commit -m "feat: add create_odoo_views skeleton with get_view_id and ensure_view"
```

---

## Task 2: Action and menu helpers — `ensure_action`, `ensure_menu`

**Files:**
- Modify: `create_odoo_views.py`
- Modify: `tests/test_create_odoo_views.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_create_odoo_views.py`:

```python
from create_odoo_views import ensure_action, ensure_menu, get_action_id, get_menu_id


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
        mocks["ir.actions.act_window"].create.assert_called_once_with({
            "name": "Gear",
            "res_model": "x_gear",
            "view_mode": "list,form",
            "type": "ir.actions.act_window",
        })

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
        mocks["ir.ui.menu"].create.assert_called_once_with({
            "name": "Gear Items",
            "parent_id": 5,
            "action": "ir.actions.act_window,77",
        })

    def test_dry_run_skips_create(self):
        conn, mocks = _make_multi_conn({"ir.ui.menu": []})
        ensure_menu(conn, "Gear", parent_id=None, action_id=None, dry_run=True)
        mocks["ir.ui.menu"].create.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_create_odoo_views.py -k "Action or Menu" -v
```

Expected: `ImportError` — `ensure_action`, `ensure_menu`, etc. not yet defined.

- [ ] **Step 3: Implement `get_action_id`, `ensure_action`, `get_menu_id`, `ensure_menu`**

Append to `create_odoo_views.py` (after `ensure_view`):

```python
# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------


def get_action_id(conn, name: str) -> int | None:
    """Return the ir.actions.act_window id with the given name, or None."""
    act = conn.get_model("ir.actions.act_window")
    results = act.search_read(
        [("name", "=", name), ("type", "=", "ir.actions.act_window")],
        ["id"],
        limit=1,
    )
    return results[0]["id"] if results else None


def ensure_action(
    conn,
    name: str,
    res_model: str,
    view_mode: str,
    *,
    dry_run: bool,
) -> int | None:
    """Create an ir.actions.act_window if one with *name* does not exist.

    Returns the id (existing or new), or None in dry-run when missing.
    """
    existing_id = get_action_id(conn, name)
    if existing_id:
        logger.info("  Action '{}' already exists (id={})", name, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create action: {}", name)
        return None

    act = conn.get_model("ir.actions.act_window")
    new_id = act.create({
        "name": name,
        "res_model": res_model,
        "view_mode": view_mode,
        "type": "ir.actions.act_window",
    })
    logger.success("  Created action: {} (id={})", name, new_id)
    return new_id


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------


def get_menu_id(conn, complete_name: str) -> int | None:
    """Return the ir.ui.menu id whose complete_name matches, or None.

    *complete_name* is the full slash-joined path displayed in Odoo's
    menu list (e.g. ``"Gear"`` or ``"Gear / Gear Items"``).
    """
    menu = conn.get_model("ir.ui.menu")
    results = menu.search_read(
        [("complete_name", "=", complete_name)], ["id"], limit=1
    )
    return results[0]["id"] if results else None


def ensure_menu(
    conn,
    name: str,
    *,
    parent_id: int | None,
    action_id: int | None,
    dry_run: bool,
    complete_name: str | None = None,
) -> int | None:
    """Create an ir.ui.menu entry if one matching *complete_name* does not exist.

    *complete_name* defaults to *name* when omitted (top-level menu).
    Returns the id (existing or new), or None in dry-run when missing.
    """
    lookup = complete_name or name
    existing_id = get_menu_id(conn, lookup)
    if existing_id:
        logger.info("  Menu '{}' already exists (id={})", lookup, existing_id)
        return existing_id

    if dry_run:
        logger.info("  [DRY-RUN] Would create menu: {}", lookup)
        return None

    vals: dict = {"name": name}
    if parent_id is not None:
        vals["parent_id"] = parent_id
    if action_id is not None:
        vals["action"] = f"ir.actions.act_window,{action_id}"

    menu = conn.get_model("ir.ui.menu")
    new_id = menu.create(vals)
    logger.success("  Created menu: {} (id={})", lookup, new_id)
    return new_id
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_create_odoo_views.py -v
```

Expected: all tests pass (no failures)

- [ ] **Step 5: Commit**

```bash
git add create_odoo_views.py tests/test_create_odoo_views.py
git commit -m "feat: add action and menu helpers to create_odoo_views"
```

---

## Task 3: x_gear views

**Files:**
- Modify: `create_odoo_views.py`
- Modify: `tests/test_create_odoo_views.py`

- [ ] **Step 1: Write failing test for `create_gear_views`**

Append to `tests/test_create_odoo_views.py`:

```python
from create_odoo_views import create_gear_views


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
        # list + form + search = 3 ir.ui.view.create calls
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_create_odoo_views.py::TestCreateGearViews -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `_GEAR_VIEWS` constant and `create_gear_views`**

Append to `create_odoo_views.py` (after the menu helpers):

```python
# ---------------------------------------------------------------------------
# x_gear view definitions
# ---------------------------------------------------------------------------

_GEAR_LIST_ARCH = """\
<list string="Gear">
  <field name="x_name"/>
  <field name="x_model_id"/>
  <field name="x_status"/>
  <field name="x_condition"/>
  <field name="x_intent"/>
  <field name="x_is_not_interested"/>
</list>"""

_GEAR_FORM_ARCH = """\
<form string="Gear">
  <sheet>
    <field name="x_image" widget="image" class="oe_avatar" options="{'preview_image': 'x_image'}"/>
    <group>
      <group>
        <field name="x_name"/>
        <field name="x_model_id"/>
        <field name="x_status"/>
      </group>
      <group>
        <field name="x_condition"/>
        <field name="x_intent"/>
        <field name="x_is_not_interested"/>
        <field name="x_guitar_id"/>
      </group>
    </group>
    <notebook>
      <page string="Listings">
        <field name="x_listing_ids">
          <list>
            <field name="x_name"/>
            <field name="x_platform"/>
            <field name="x_price"/>
            <field name="x_currency_id"/>
            <field name="x_status"/>
            <field name="x_is_available"/>
          </list>
        </field>
      </page>
    </notebook>
  </sheet>
</form>"""

_GEAR_SEARCH_ARCH = """\
<search string="Gear">
  <field name="x_name"/>
  <field name="x_model_id"/>
  <filter string="Watching" name="watching" domain="[('x_status', '=', 'watching')]"/>
  <filter string="Owned" name="owned" domain="[('x_status', '=', 'owned')]"/>
  <filter string="Closed" name="closed" domain="[('x_status', '=', 'closed')]"/>
  <separator/>
  <filter string="Not Interested" name="not_interested" domain="[('x_is_not_interested', '=', True)]"/>
  <group expand="0" string="Group By">
    <filter string="Status" name="group_status" context="{'group_by': 'x_status'}"/>
    <filter string="Model" name="group_model" context="{'group_by': 'x_model_id'}"/>
  </group>
</search>"""

_GEAR_VIEWS: list[tuple[str, str, str]] = [
    ("list",   "x_gear.list",   _GEAR_LIST_ARCH),
    ("form",   "x_gear.form",   _GEAR_FORM_ARCH),
    ("search", "x_gear.search", _GEAR_SEARCH_ARCH),
]


def create_gear_views(conn, *, dry_run: bool) -> None:
    """Create list, form, and search views for x_gear."""
    for view_type, name, arch in _GEAR_VIEWS:
        ensure_view(conn, "x_gear", view_type, name, arch, dry_run=dry_run)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_create_odoo_views.py::TestCreateGearViews -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add create_odoo_views.py tests/test_create_odoo_views.py
git commit -m "feat: add x_gear views to create_odoo_views"
```

---

## Task 4: x_listing views

**Files:**
- Modify: `create_odoo_views.py`
- Modify: `tests/test_create_odoo_views.py`

- [ ] **Step 1: Write failing test for `create_listing_views`**

Append to `tests/test_create_odoo_views.py`:

```python
from create_odoo_views import create_listing_views


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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_create_odoo_views.py::TestCreateListingViews -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `_LISTING_VIEWS` constant and `create_listing_views`**

Append to `create_odoo_views.py`:

```python
# ---------------------------------------------------------------------------
# x_listing view definitions
# ---------------------------------------------------------------------------

_LISTING_LIST_ARCH = """\
<list string="Listings">
  <field name="x_name"/>
  <field name="x_gear_id"/>
  <field name="x_platform"/>
  <field name="x_price"/>
  <field name="x_currency_id"/>
  <field name="x_status"/>
  <field name="x_is_available"/>
  <field name="x_published_at"/>
</list>"""

_LISTING_FORM_ARCH = """\
<form string="Listing">
  <sheet>
    <field name="x_image" widget="image" class="oe_avatar" options="{'preview_image': 'x_image'}"/>
    <group>
      <group>
        <field name="x_name"/>
        <field name="x_gear_id"/>
        <field name="x_url" widget="url"/>
        <field name="x_platform"/>
        <field name="x_status"/>
        <field name="x_published_at"/>
        <field name="x_guitar_id"/>
      </group>
      <group>
        <field name="x_price"/>
        <field name="x_currency_id"/>
        <field name="x_shipping"/>
        <field name="x_is_available"/>
        <field name="x_can_accept_offers"/>
        <field name="x_is_taxed"/>
        <field name="x_is_too_expensive"/>
      </group>
    </group>
  </sheet>
</form>"""

_LISTING_SEARCH_ARCH = """\
<search string="Listings">
  <field name="x_name"/>
  <field name="x_gear_id"/>
  <filter string="Active" name="active" domain="[('x_status', '=', 'active')]"/>
  <filter string="Acquired" name="acquired" domain="[('x_status', '=', 'acquired')]"/>
  <filter string="Passed" name="passed" domain="[('x_status', '=', 'passed')]"/>
  <separator/>
  <filter string="Available" name="available" domain="[('x_is_available', '=', True)]"/>
  <filter string="Reverb" name="platform_reverb" domain="[('x_platform', '=', 'reverb')]"/>
  <group expand="0" string="Group By">
    <filter string="Status" name="group_status" context="{'group_by': 'x_status'}"/>
    <filter string="Platform" name="group_platform" context="{'group_by': 'x_platform'}"/>
    <filter string="Gear" name="group_gear" context="{'group_by': 'x_gear_id'}"/>
  </group>
</search>"""

_LISTING_VIEWS: list[tuple[str, str, str]] = [
    ("list",   "x_listing.list",   _LISTING_LIST_ARCH),
    ("form",   "x_listing.form",   _LISTING_FORM_ARCH),
    ("search", "x_listing.search", _LISTING_SEARCH_ARCH),
]


def create_listing_views(conn, *, dry_run: bool) -> None:
    """Create list, form, and search views for x_listing."""
    for view_type, name, arch in _LISTING_VIEWS:
        ensure_view(conn, "x_listing", view_type, name, arch, dry_run=dry_run)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_create_odoo_views.py::TestCreateListingViews -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add create_odoo_views.py tests/test_create_odoo_views.py
git commit -m "feat: add x_listing views to create_odoo_views"
```

---

## Task 5: Actions, menus, and `create_views` orchestrator

**Files:**
- Modify: `create_odoo_views.py`
- Modify: `tests/test_create_odoo_views.py`

- [ ] **Step 1: Write failing test for `create_views`**

Append to `tests/test_create_odoo_views.py`:

```python
from create_odoo_views import create_views


class TestCreateViews:
    def _make_conn(self):
        """Conn where nothing pre-exists; create() returns sequential ints."""
        conn = MagicMock()
        counter = [0]

        def make_mock():
            m = MagicMock()
            m.search_read.return_value = []
            def create_side(vals):
                counter[0] += 1
                return counter[0]
            m.create.side_effect = create_side
            return m

        conn.get_model.side_effect = lambda _: make_mock()
        return conn

    def test_dry_run_creates_nothing(self):
        conn = self._make_conn()
        created = []
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_create_odoo_views.py::TestCreateViews -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement `create_views` orchestrator and CLI**

Append to `create_odoo_views.py`:

```python
# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

#: Display name for the top-level "Gear" menu entry.
_MENU_ROOT_NAME = "Gear"
#: complete_name used to look up the root menu (top-level → same as name).
_MENU_ROOT_COMPLETE = "Gear"


def create_views(conn, *, dry_run: bool) -> None:
    """Create all views, actions, and menus for x_gear and x_listing.

    Execution order:
    1. x_gear views (list, form, search)
    2. x_listing views (list, form, search)
    3. Window actions for both models
    4. Top-level "Gear" menu + two sub-menus
    """
    # ── Views ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== x_gear views ===")
    create_gear_views(conn, dry_run=dry_run)

    logger.info("")
    logger.info("=== x_listing views ===")
    create_listing_views(conn, dry_run=dry_run)

    # ── Actions ──────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== window actions ===")
    gear_action_id = ensure_action(conn, "Gear Items", "x_gear", "list,form", dry_run=dry_run)
    listing_action_id = ensure_action(conn, "Listings", "x_listing", "list,form", dry_run=dry_run)

    # ── Menus ────────────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=== menus ===")
    root_id = ensure_menu(
        conn,
        _MENU_ROOT_NAME,
        parent_id=None,
        action_id=None,
        dry_run=dry_run,
        complete_name=_MENU_ROOT_COMPLETE,
    )
    ensure_menu(
        conn,
        "Gear Items",
        parent_id=root_id,
        action_id=gear_action_id,
        dry_run=dry_run,
        complete_name=f"{_MENU_ROOT_COMPLETE} / Gear Items",
    )
    ensure_menu(
        conn,
        "Listings",
        parent_id=root_id,
        action_id=listing_action_id,
        dry_run=dry_run,
        complete_name=f"{_MENU_ROOT_COMPLETE} / Listings",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("create-odoo-views")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Create views, actions, and menus for x_gear and x_listing.

    Creates list/form/search views, window actions, and a top-level
    'Gear' menu with 'Gear Items' and 'Listings' sub-entries.

    Runs in dry-run mode by default; pass --apply to write to Odoo.
    Idempotent: existing views, actions, and menus are skipped.
    """
    conn = ctx.obj["conn"]
    dry_run = not apply

    if dry_run:
        logger.info("[DRY-RUN] No changes will be written.  Pass --apply to apply.")

    create_views(conn, dry_run=dry_run)

    logger.info("")
    if dry_run:
        logger.info("[DRY-RUN] Done.  Run with --apply to create the views.")
    else:
        logger.success("View creation complete.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_create_odoo_views.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add create_odoo_views.py tests/test_create_odoo_views.py
git commit -m "feat: add create_views orchestrator and CLI to create_odoo_views"
```

---

## Task 6: Wire up CLI, update README, run full suite

**Files:**
- Modify: `cli.py`
- Modify: `README.md`

- [ ] **Step 1: Register command in `cli.py`**

In `cli.py`, add after the `create_odoo_schema` import line:

```python
from create_odoo_views import cli as create_odoo_views_cmd
```

And after `main.add_command(create_odoo_schema_cmd)`:

```python
main.add_command(create_odoo_views_cmd)
```

- [ ] **Step 2: Add README section**

In `README.md`, after the `create-odoo-schema` section, add:

```markdown
### `create-odoo-views` — Create views and menus for x_gear and x_listing

Creates list, form, and search views for both models, two window actions,
and a top-level **Gear** menu with **Gear Items** and **Listings** sub-entries.

Run after `create-odoo-schema` (schema must exist before views can reference fields).
Idempotent: already-existing views, actions, and menus are skipped.

```bash
uv run reverb2odoo create-odoo-views           # dry-run (default)
uv run reverb2odoo create-odoo-views --apply   # write to Odoo
```
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest
```

Expected: all tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add cli.py README.md
git commit -m "feat: register create-odoo-views command and document it"
```
