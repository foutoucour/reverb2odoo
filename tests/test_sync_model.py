"""Tests for sync_model — Reverb API calls recorded via VCR cassettes."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from sync_model import (
    DEFAULT_SHIPPING,
    _apply_updates,
    _build_report,
    _clean_url,
    _collect_sync_data,
    _compute_changes,
    _fetch_all_models,
    _find_model,
    _print_report,
    _reverb_to_odoo_vals,
    _search_reverb,
    cli,
)

# ── _clean_url ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/12345-guitar",
            "https://reverb.com/item/12345-guitar",
            id="no-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/12345-guitar?show_sold=true",
            "https://reverb.com/item/12345-guitar",
            id="strip-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/12345-guitar?a=1&b=2",
            "https://reverb.com/item/12345-guitar",
            id="strip-multiple-params",
        ),
        pytest.param("", "", id="empty-string"),
    ],
)
def test_clean_url(url: str, expected: str):
    assert _clean_url(url) == expected


# ── CLI (Click) ───────────────────────────────────────────────────────────


class TestSyncCli:
    """Tests for the Click-based sync CLI."""

    runner = CliRunner()

    def test_no_args_shows_error(self):
        result = self.runner.invoke(cli, [])
        assert result.exit_code != 0
        assert "MODEL_NAME" in result.output or "Usage" in result.output

    def test_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "MODEL_NAME" in result.output
        assert "--all" in result.output
        assert "--dry-run" in result.output

    def test_flags_only_no_model_no_all(self):
        result = self.runner.invoke(cli, ["--dry-run"])
        assert result.exit_code != 0

    def test_workers_invalid_type_rejected(self):
        result = self.runner.invoke(cli, ["--all", "--workers", "abc"])
        assert result.exit_code != 0


# ── _compute_changes ──────────────────────────────────────────────────────


class TestComputeChanges:
    """Unit tests for _compute_changes (pure logic, no I/O)."""

    def test_no_changes_when_identical(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_published_at_1": "2025-06-20 00:00:00",
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "published_at": "2025-06-20",
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        assert _compute_changes(entry, reverb) == {}

    def test_price_change(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "4500.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_value"] == 4500.0

    def test_offers_toggled_off(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_accept_offers"] is False

    def test_sale_ended_marks_unavailable(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_is_available"] is False

    def test_sale_ended_does_not_update_shipping(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(entry, reverb)
        assert "x_studio_shipping" not in changes

    def test_live_listing_updates_shipping(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "300.00",
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_shipping"] == 300.0

    def test_published_at_update(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
            "x_studio_published_at_1": "2025-01-01 00:00:00",
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
            "published_at": "2025-06-20",
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_published_at_1"] == "2025-06-20 00:00:00"

    def test_relists_marks_available(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": False,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(entry, reverb)
        assert changes["x_studio_is_available"] is True

    def test_already_unavailable_stays_unchanged(self):
        entry = {
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": False,
            "x_studio_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(entry, reverb)
        assert "x_studio_is_available" not in changes


# ── _reverb_to_odoo_vals ──────────────────────────────────────────────────


class TestReverbToOdooVals:
    """Unit tests for _reverb_to_odoo_vals (pure logic, no I/O)."""

    def test_basic_conversion(self):
        reverb = {
            "name": "Cool Guitar",
            "url": "https://reverb.com/item/123-cool-guitar",
            "price": "5000.00",
            "shipping_price": "200.00",
            "sale_ended": False,
            "offers_enabled": True,
            "published_at": "2025-06-20",
        }
        vals = _reverb_to_odoo_vals(reverb, model_id=42)

        assert vals["x_name"] == "Cool Guitar"
        assert vals["x_studio_url"] == "https://reverb.com/item/123-cool-guitar"
        assert vals["x_studio_models"] == 42
        assert vals["x_studio_model_type"] == "Guitar"
        assert vals["x_studio_value"] == 5000.0
        assert vals["x_studio_shipping"] == 200.0
        assert vals["x_studio_is_available"] is True
        assert vals["x_studio_active"] is True
        assert vals["x_studio_accept_offers"] is True
        assert vals["x_studio_taxed"] is False
        assert vals["x_studio_published_at_1"] == "2025-06-20 00:00:00"

    def test_sold_listing_uses_default_shipping(self):
        reverb = {
            "name": "Sold Guitar",
            "url": "https://reverb.com/item/456-sold",
            "price": "3000.00",
            "shipping_price": None,
            "sale_ended": True,
            "offers_enabled": False,
            "published_at": "2025-01-01",
        }
        vals = _reverb_to_odoo_vals(reverb, model_id=10)

        assert vals["x_studio_is_available"] is False
        assert vals["x_studio_shipping"] == DEFAULT_SHIPPING
        assert vals["x_studio_accept_offers"] is False

    def test_sold_listing_uses_category_shipping(self):
        reverb = {
            "name": "Sold Pedal",
            "url": "https://reverb.com/item/789-sold-pedal",
            "price": "200.00",
            "shipping_price": None,
            "sale_ended": True,
            "offers_enabled": False,
            "published_at": "2025-03-10",
        }
        vals = _reverb_to_odoo_vals(reverb, model_id=10, default_shipping=35.0)

        assert vals["x_studio_shipping"] == 35.0

    def test_missing_published_at(self):
        reverb = {
            "name": "Guitar",
            "url": "https://reverb.com/item/789-g",
            "price": "1000.00",
            "shipping_price": "100.00",
            "sale_ended": False,
            "offers_enabled": False,
            "published_at": "",
        }
        vals = _reverb_to_odoo_vals(reverb, model_id=1)
        assert "x_studio_published_at_1" not in vals


# ── _build_report ─────────────────────────────────────────────────────────


class TestBuildReport:
    """Unit tests for _build_report (pure logic, no I/O)."""

    def _make_reverb(self, url="https://reverb.com/item/1-g", **kwargs):
        base = {
            "url": url,
            "name": "Guitar",
            "price": "5000.00",
            "price_display": "C$5,000",
            "offers_enabled": True,
            "sale_ended": False,
            "published_at": "2025-06-20",
            "shipping_price": "250.00",
            "ships_to_canada": True,
        }
        base.update(kwargs)
        return base

    def _make_odoo(self, url="https://reverb.com/item/1-g", **kwargs):
        base = {
            "id": 100,
            "x_name": "Guitar",
            "x_studio_url": url,
            "x_studio_value": 5000.0,
            "x_studio_accept_offers": True,
            "x_studio_is_available": True,
            "x_studio_shipping": 250.0,
            "x_studio_published_at_1": "2025-06-20 00:00:00",
        }
        base.update(kwargs)
        return base

    def test_new_listing_creates(self):
        reverb_results = [self._make_reverb(url="https://reverb.com/item/999-new")]
        odoo_entries = []

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "create"
        assert report[0]["create_vals"]["x_studio_models"] == 42

    def test_existing_up_to_date(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url)]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "ok"

    def test_existing_needs_update(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, price="4000.00")]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["changes"]["x_studio_value"] == 4000.0

    def test_url_query_string_stripped_for_matching(self):
        reverb_results = [self._make_reverb(url="https://reverb.com/item/1-g")]
        odoo_entries = [self._make_odoo(url="https://reverb.com/item/1-g?show_sold=true")]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert report[0]["action"] == "ok"

    def test_error_result_skipped(self):
        reverb_results = [{"url": "https://reverb.com/item/1-g", "error": "timeout"}]
        odoo_entries = []

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "skip"
        assert "Reverb API error" in report[0]["warnings"][0]

    def test_sold_listing_warns(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [
            self._make_reverb(
                url=url,
                sale_ended=True,
                status="Sold",
                shipping_price=None,
            )
        ]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert any("status: Sold" in w for w in report[0]["warnings"])

    def test_no_ship_to_canada_warns(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, ships_to_canada=False)]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert any("does NOT ship to Canada" in w for w in report[0]["warnings"])

    def test_mixed_create_update_ok(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/1-g"),
            self._make_reverb(url="https://reverb.com/item/2-g", price="999.00"),
            self._make_reverb(url="https://reverb.com/item/3-new"),
        ]
        odoo_entries = [
            self._make_odoo(url="https://reverb.com/item/1-g"),
            self._make_odoo(url="https://reverb.com/item/2-g", id=200),
        ]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        actions = [r["action"] for r in report]
        assert actions == ["ok", "update", "create"]


# ── _print_report ─────────────────────────────────────────────────────────


class TestPrintReport:
    """Test _print_report return values."""

    def test_counts(self, capsys):
        report = [
            {
                "action": "ok",
                "reverb": {"name": "A", "price_display": "$1"},
                "entry": {"id": 1},
                "changes": {},
                "warnings": [],
            },
            {
                "action": "update",
                "reverb": {"name": "B", "price_display": "$2"},
                "entry": {"id": 2},
                "changes": {"x_studio_value": 99},
                "warnings": [],
            },
            {
                "action": "create",
                "reverb": {"name": "C", "price_display": "$3"},
                "entry": None,
                "create_vals": {},
                "changes": {},
                "warnings": [],
            },
            {
                "action": "create",
                "reverb": {"name": "D", "price_display": "$4"},
                "entry": None,
                "create_vals": {},
                "changes": {},
                "warnings": [],
            },
        ]
        upd, crt = _print_report(report)
        assert upd == 1
        assert crt == 2

    def test_all_ok_returns_zeros(self, capsys):
        report = [
            {
                "action": "ok",
                "reverb": {"name": "A", "price_display": "$1"},
                "entry": {"id": 1},
                "changes": {},
                "warnings": [],
            },
        ]
        upd, crt = _print_report(report)
        assert upd == 0
        assert crt == 0


# ── _find_model (mocked Odoo) ─────────────────────────────────────────────


class TestFindModel:
    """Unit tests for _find_model with mocked Odoo connection."""

    def _mock_conn(self, model_results, cat_results=None):
        """Build a mock connection.

        *model_results* is returned by the ``x_models`` search_read.
        *cat_results* (optional) is returned by the ``x_reverb_category``
        search_read when resolving the category slug.
        """
        conn = MagicMock()
        models_mock = MagicMock()
        models_mock.search_read.return_value = model_results

        cat_mock = MagicMock()
        cat_mock.search_read.return_value = cat_results or []

        def _get_model(name):
            if name == "x_reverb_category":
                return cat_mock
            return models_mock

        conn.get_model.side_effect = _get_model
        return conn

    def test_exact_match_with_category(self):
        conn = self._mock_conn(
            [
                {
                    "id": 234,
                    "x_name": "Frank Brothers Arcane",
                    "x_studio_reverb_category_id": [110, "Electric Guitars"],
                }
            ],
            cat_results=[
                {
                    "id": 110,
                    "x_studio_slug": "electric-guitars",
                    "x_studio_shipping_default_price": 250.0,
                }
            ],
        )
        result = _find_model(conn, "Frank Brothers Arcane")
        assert result == {
            "id": 234,
            "category_slug": "electric-guitars",
            "default_shipping": 250.0,
        }

    def test_exact_match_no_category(self):
        conn = self._mock_conn(
            [{"id": 234, "x_name": "Frank Brothers Arcane", "x_studio_reverb_category_id": False}],
        )
        result = _find_model(conn, "Frank Brothers Arcane")
        assert result == {"id": 234, "category_slug": None, "default_shipping": DEFAULT_SHIPPING}

    def test_case_insensitive_match(self):
        conn = self._mock_conn(
            [{"id": 234, "x_name": "Frank Brothers Arcane", "x_studio_reverb_category_id": False}],
        )
        result = _find_model(conn, "frank brothers arcane")
        assert result["id"] == 234

    def test_single_partial_match(self):
        conn = self._mock_conn(
            [{"id": 10, "x_name": "Some Model", "x_studio_reverb_category_id": False}],
        )
        result = _find_model(conn, "Some")
        assert result["id"] == 10

    def test_no_match_exits(self):
        conn = self._mock_conn([])
        with pytest.raises(SystemExit):
            _find_model(conn, "Nonexistent")

    def test_ambiguous_match_exits(self):
        conn = self._mock_conn(
            [
                {"id": 1, "x_name": "Foo Bar", "x_studio_reverb_category_id": False},
                {"id": 2, "x_name": "Foo Baz", "x_studio_reverb_category_id": False},
            ]
        )
        with pytest.raises(SystemExit):
            _find_model(conn, "Foo")

    def test_ambiguous_prefers_exact(self):
        conn = self._mock_conn(
            [
                {
                    "id": 1,
                    "x_name": "Arcade",
                    "x_studio_reverb_category_id": [109, "Effects and Pedals"],
                },
                {"id": 2, "x_name": "Arcade One", "x_studio_reverb_category_id": False},
            ],
            cat_results=[
                {
                    "id": 109,
                    "x_studio_slug": "effects-and-pedals",
                    "x_studio_shipping_default_price": 35.0,
                }
            ],
        )
        result = _find_model(conn, "Arcade")
        assert result == {
            "id": 1,
            "category_slug": "effects-and-pedals",
            "default_shipping": 35.0,
        }


# ── _apply_updates (mocked Odoo) ─────────────────────────────────────────


class TestApplyUpdates:
    """Unit tests for _apply_updates with mocked Odoo connection."""

    def _mock_conn(self, create_return=9999):
        conn = MagicMock()
        model = MagicMock()
        model.create.return_value = create_return
        conn.get_model.return_value = model
        return conn, model

    def test_writes_updates(self):
        conn, model = self._mock_conn()
        report = [
            {"action": "update", "entry": {"id": 100}, "changes": {"x_studio_value": 4000.0}},
            {"action": "ok", "entry": {"id": 200}, "changes": {}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 1
        assert crt == 0
        model.write.assert_called_once_with(100, {"x_studio_value": 4000.0})

    def test_creates_new_entries(self):
        conn, model = self._mock_conn(create_return=1904)
        vals = {"x_name": "New Guitar", "x_studio_models": 42}
        report = [
            {"action": "create", "create_vals": vals},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 0
        assert crt == 1
        model.create.assert_called_once_with(vals)

    def test_skips_ok_entries(self):
        conn, model = self._mock_conn()
        report = [
            {"action": "ok", "entry": {"id": 1}, "changes": {}},
            {"action": "skip", "entry": None, "changes": {}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 0
        assert crt == 0
        model.write.assert_not_called()
        model.create.assert_not_called()

    def test_mixed_updates_and_creates(self):
        conn, model = self._mock_conn(create_return=2000)
        report = [
            {"action": "update", "entry": {"id": 100}, "changes": {"x_studio_value": 1.0}},
            {"action": "create", "create_vals": {"x_name": "G1"}},
            {"action": "ok", "entry": {"id": 200}, "changes": {}},
            {"action": "create", "create_vals": {"x_name": "G2"}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 1
        assert crt == 2
        model.write.assert_called_once()
        assert model.create.call_count == 2


# ── _search_reverb (VCR cassette) ────────────────────────────────────────


@pytest.mark.vcr
def test_search_reverb_returns_results():
    """Search for a known model returns non-empty deduplicated results."""
    results = _search_reverb("Frank Brothers Arcade")
    assert len(results) > 0
    # All results should have a URL
    for r in results:
        assert r.get("url"), "Every result must have a URL"


@pytest.mark.vcr
def test_search_reverb_deduplicates():
    """Results are deduplicated by URL."""
    results = _search_reverb("Frank Brothers Arcade")
    urls = [r["url"] for r in results]
    assert len(urls) == len(set(urls)), "Duplicate URLs found"


@pytest.mark.vcr
def test_search_reverb_result_fields():
    """Each result has the expected fields from the scraper."""
    results = _search_reverb("Frank Brothers Arcade")
    assert len(results) > 0

    expected_keys = {
        "url",
        "name",
        "price",
        "price_display",
        "currency",
        "sale_ended",
        "offers_enabled",
        "shipping_price",
    }
    for r in results:
        missing = expected_keys - set(r.keys())
        assert not missing, f"Missing keys: {missing}"


@pytest.mark.vcr
def test_search_reverb_empty_query():
    """A nonsense query returns an empty list."""
    results = _search_reverb("xyznonexistent987654321qqq")
    assert results == []


# ── _fetch_all_models (mocked Odoo) ──────────────────────────────────────


class TestFetchAllModels:
    """Unit tests for _fetch_all_models with mocked Odoo connection."""

    def _mock_conn(self, model_records, cat_records=None):
        conn = MagicMock()
        models_mock = MagicMock()
        models_mock.search_read.return_value = model_records

        cat_mock = MagicMock()
        cat_mock.search_read.return_value = cat_records or []

        def _get_model(name):
            if name == "x_reverb_category":
                return cat_mock
            return models_mock

        conn.get_model.side_effect = _get_model
        return conn

    def test_returns_all_models(self):
        conn = self._mock_conn(
            [
                {"id": 1, "x_name": "Model A", "x_studio_reverb_category_id": False},
                {"id": 2, "x_name": "Model B", "x_studio_reverb_category_id": False},
            ]
        )
        result = _fetch_all_models(conn)

        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Model A"
        assert result[1]["id"] == 2
        assert result[1]["name"] == "Model B"

    def test_resolves_categories_in_bulk(self):
        conn = self._mock_conn(
            [
                {
                    "id": 1,
                    "x_name": "Guitar Model",
                    "x_studio_reverb_category_id": [10, "Electric Guitars"],
                },
                {
                    "id": 2,
                    "x_name": "Pedal Model",
                    "x_studio_reverb_category_id": [20, "Effects"],
                },
            ],
            cat_records=[
                {
                    "id": 10,
                    "x_studio_slug": "electric-guitars",
                    "x_studio_shipping_default_price": 250.0,
                },
                {
                    "id": 20,
                    "x_studio_slug": "effects-and-pedals",
                    "x_studio_shipping_default_price": 35.0,
                },
            ],
        )
        result = _fetch_all_models(conn)

        assert len(result) == 2
        assert result[0]["category_slug"] == "electric-guitars"
        assert result[0]["default_shipping"] == 250.0
        assert result[1]["category_slug"] == "effects-and-pedals"
        assert result[1]["default_shipping"] == 35.0

    def test_no_category_uses_defaults(self):
        conn = self._mock_conn(
            [{"id": 1, "x_name": "Model A", "x_studio_reverb_category_id": False}]
        )
        result = _fetch_all_models(conn)

        assert len(result) == 1
        assert result[0]["category_slug"] is None
        assert result[0]["default_shipping"] == DEFAULT_SHIPPING

    def test_empty_database_returns_empty(self):
        conn = self._mock_conn([])
        result = _fetch_all_models(conn)
        assert result == []

    def test_bulk_fetches_categories_once(self):
        """Verify categories are fetched with a single ``in`` query."""
        conn = self._mock_conn(
            [
                {
                    "id": 1,
                    "x_name": "A",
                    "x_studio_reverb_category_id": [10, "Guitars"],
                },
                {
                    "id": 2,
                    "x_name": "B",
                    "x_studio_reverb_category_id": [10, "Guitars"],
                },
                {
                    "id": 3,
                    "x_name": "C",
                    "x_studio_reverb_category_id": [20, "Pedals"],
                },
            ],
            cat_records=[
                {"id": 10, "x_studio_slug": "guitars", "x_studio_shipping_default_price": 250.0},
                {"id": 20, "x_studio_slug": "pedals", "x_studio_shipping_default_price": 35.0},
            ],
        )

        _fetch_all_models(conn)

        cat_mock = conn.get_model("x_reverb_category")
        assert cat_mock.search_read.call_count == 1

        call_domain = cat_mock.search_read.call_args[0][0]
        assert call_domain[0][0] == "id"
        assert call_domain[0][1] == "in"
        assert set(call_domain[0][2]) == {10, 20}


# ── _collect_sync_data (mocked I/O) ──────────────────────────────────────


class TestCollectSyncData:
    """Unit tests for _collect_sync_data, the thread-safe collection phase."""

    def _mock_conn(self, guitar_entries=None):
        conn = MagicMock()
        guitar = MagicMock()
        guitar.search_read.return_value = guitar_entries or []
        conn.get_model.return_value = guitar
        return conn

    def test_no_reverb_results_returns_empty(self):
        conn = self._mock_conn()

        with patch("sync_model._search_reverb", return_value=[]):
            result = _collect_sync_data(
                conn,
                model_id=1,
                model_name="Test",
                category_slug="electric-guitars",
                default_shipping=250.0,
            )

        assert result["model_id"] == 1
        assert result["model_name"] == "Test"
        assert result["reverb_results"] == []
        assert result["odoo_entries"] == []
        assert result["report"] == []
        assert result["update_count"] == 0
        assert result["create_count"] == 0

    def test_collects_results_and_builds_report(self):
        url = "https://reverb.com/item/1-guitar"
        reverb_results = [
            {
                "url": url,
                "name": "Guitar",
                "price": "5000.00",
                "price_display": "C$5,000",
                "offers_enabled": True,
                "sale_ended": False,
                "published_at": "2025-06-20",
                "shipping_price": "250.00",
                "ships_to_canada": True,
            }
        ]

        conn = self._mock_conn(guitar_entries=[])

        with patch("sync_model._search_reverb", return_value=reverb_results):
            result = _collect_sync_data(
                conn,
                model_id=42,
                model_name="Test",
                category_slug="electric-guitars",
                default_shipping=250.0,
            )

        assert len(result["reverb_results"]) == 1
        assert len(result["report"]) == 1
        assert result["create_count"] == 1  # new listing → create

    def test_echoes_back_model_metadata(self):
        with patch("sync_model._search_reverb", return_value=[]):
            result = _collect_sync_data(
                MagicMock(),
                model_id=42,
                model_name="My Model",
                category_slug=None,
                default_shipping=99.0,
            )

        assert result["model_id"] == 42
        assert result["model_name"] == "My Model"
        assert result["default_shipping"] == 99.0

    def test_uses_search_query_override(self):
        conn = self._mock_conn()

        with patch("sync_model._search_reverb", return_value=[]) as mock_search:
            _collect_sync_data(
                conn,
                model_id=1,
                model_name="Model A",
                category_slug="electric-guitars",
                default_shipping=250.0,
                search_query="Custom Query",
            )

        mock_search.assert_called_once_with(
            "Custom Query",
            category="electric-guitars",
            default_shipping=250.0,
        )

    def test_falls_back_to_model_name_for_query(self):
        conn = self._mock_conn()

        with patch("sync_model._search_reverb", return_value=[]) as mock_search:
            _collect_sync_data(
                conn,
                model_id=1,
                model_name="Model A",
                category_slug=None,
                default_shipping=250.0,
            )

        mock_search.assert_called_once_with(
            "Model A",
            category=None,
            default_shipping=250.0,
        )
