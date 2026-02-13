"""Tests for validate_model — Odoo→Reverb validation / sanitization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from sync_model import _fetch_all_models
from validate_model import (
    _apply_validation_updates,
    _build_validation_report,
    _collect_model_data,
    _is_reverb_url,
    _print_validation_report,
    _scrape_reverb_urls,
    cli,
)

# ── _is_reverb_url ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/12345-guitar",
            True,
            id="valid-reverb-url",
        ),
        pytest.param(
            "https://reverb.com/item/99999-some-listing?show_sold=true",
            True,
            id="reverb-url-with-query-string",
        ),
        pytest.param(
            "https://other-site.com/item/12345",
            False,
            id="non-reverb-url",
        ),
        pytest.param("", False, id="empty-string"),
        pytest.param(
            "https://reverb.com/shop/cool-guitars",
            False,
            id="reverb-non-item-url",
        ),
    ],
)
def test_is_reverb_url(url: str, expected: bool):
    assert _is_reverb_url(url) == expected


# ── CLI (Click) ──────────────────────────────────────────────────────────


class TestValidateCli:
    """Tests for the Click-based validate CLI."""

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
        assert "--workers" in result.output

    def test_flags_only_no_model_no_all(self):
        result = self.runner.invoke(cli, ["--dry-run"])
        assert result.exit_code != 0

    def test_workers_invalid_type_rejected(self):
        result = self.runner.invoke(cli, ["--all", "--workers", "abc"])
        assert result.exit_code != 0


# ── _build_validation_report ─────────────────────────────────────────────


class TestBuildValidationReport:
    """Unit tests for _build_validation_report (pure logic, no I/O)."""

    def _make_entry(self, url="https://reverb.com/item/1-g", **kwargs):
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

    def _make_reverb(self, **kwargs):
        base = {
            "url": "https://reverb.com/item/1-g",
            "name": "Guitar",
            "price": "5000.00",
            "price_display": "C$5,000",
            "offers_enabled": True,
            "sale_ended": False,
            "published_at": "2025-06-20",
            "shipping_price": "250.00",
            "ships_to_canada": True,
            "status": "Live",
        }
        base.update(kwargs)
        return base

    def test_up_to_date_entry(self):
        url = "https://reverb.com/item/1-g"
        entries = [self._make_entry(url=url)]
        reverb_data = {url: self._make_reverb()}

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 1
        assert report[0]["action"] == "ok"
        assert report[0]["changes"] == {}

    def test_entry_needs_update(self):
        url = "https://reverb.com/item/1-g"
        entries = [self._make_entry(url=url)]
        reverb_data = {url: self._make_reverb(price="4000.00")}

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["changes"]["x_studio_value"] == 4000.0

    def test_non_reverb_url_skipped(self):
        entries = [self._make_entry(url="https://other-site.com/guitar")]
        reverb_data = {}

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 1
        assert report[0]["action"] == "skip"
        assert "non-Reverb URL" in report[0]["warnings"][0]

    def test_missing_reverb_data_skipped(self):
        url = "https://reverb.com/item/999-missing"
        entries = [self._make_entry(url=url)]
        reverb_data = {}  # URL not in scraped data

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 1
        assert report[0]["action"] == "skip"
        assert "not found in scraped data" in report[0]["warnings"][0]

    def test_reverb_api_error_skipped(self):
        url = "https://reverb.com/item/1-g"
        entries = [self._make_entry(url=url)]
        reverb_data = {url: {"url": url, "error": "API error: timeout"}}

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 1
        assert report[0]["action"] == "skip"
        assert "Reverb API error" in report[0]["warnings"][0]

    def test_sold_listing_warns(self):
        url = "https://reverb.com/item/1-g"
        entries = [self._make_entry(url=url)]
        reverb_data = {
            url: self._make_reverb(
                sale_ended=True,
                status="Sold",
                shipping_price=None,
            )
        }

        report = _build_validation_report(entries, reverb_data)

        assert any("status: Sold" in w for w in report[0]["warnings"])

    def test_no_ship_to_canada_warns(self):
        url = "https://reverb.com/item/1-g"
        entries = [self._make_entry(url=url)]
        reverb_data = {url: self._make_reverb(ships_to_canada=False)}

        report = _build_validation_report(entries, reverb_data)

        assert any("does NOT ship to Canada" in w for w in report[0]["warnings"])

    def test_mixed_entries(self):
        url1 = "https://reverb.com/item/1-g"
        url2 = "https://reverb.com/item/2-g"
        url3 = "https://other.com/guitar"
        entries = [
            self._make_entry(url=url1, id=100),
            self._make_entry(url=url2, id=200),
            self._make_entry(url=url3, id=300),
        ]
        reverb_data = {
            url1: self._make_reverb(),
            url2: self._make_reverb(price="3000.00"),
        }

        report = _build_validation_report(entries, reverb_data)

        assert len(report) == 3
        assert report[0]["action"] == "ok"
        assert report[1]["action"] == "update"
        assert report[2]["action"] == "skip"

    def test_reverb_dict_attached_to_report_item(self):
        url = "https://reverb.com/item/1-g"
        reverb = self._make_reverb()
        entries = [self._make_entry(url=url)]
        reverb_data = {url: reverb}

        report = _build_validation_report(entries, reverb_data)

        assert report[0]["reverb"] is reverb

    def test_skip_has_no_reverb_attached(self):
        entries = [self._make_entry(url="https://other.com/guitar")]
        report = _build_validation_report(entries, {})

        assert report[0]["reverb"] is None


# ── _print_validation_report ─────────────────────────────────────────────


class TestPrintValidationReport:
    """Test _print_validation_report return values."""

    def test_counts_updates(self, capsys):
        report = [
            {
                "action": "ok",
                "entry": {"id": 1, "x_name": "A"},
                "reverb": {"price_display": "$1"},
                "changes": {},
                "warnings": [],
            },
            {
                "action": "update",
                "entry": {"id": 2, "x_name": "B"},
                "reverb": {"price_display": "$2"},
                "changes": {"x_studio_value": 99},
                "warnings": [],
            },
            {
                "action": "skip",
                "entry": {"id": 3, "x_name": "C"},
                "reverb": None,
                "changes": {},
                "warnings": ["non-Reverb URL — skipped"],
            },
        ]
        update_count = _print_validation_report(report)
        assert update_count == 1

    def test_all_ok_returns_zero(self, capsys):
        report = [
            {
                "action": "ok",
                "entry": {"id": 1, "x_name": "A"},
                "reverb": {"price_display": "$1"},
                "changes": {},
                "warnings": [],
            },
        ]
        update_count = _print_validation_report(report)
        assert update_count == 0

    def test_empty_report(self, capsys):
        assert _print_validation_report([]) == 0


# ── _apply_validation_updates (mocked Odoo) ──────────────────────────────


class TestApplyValidationUpdates:
    """Unit tests for _apply_validation_updates with mocked Odoo connection."""

    def _mock_conn(self):
        conn = MagicMock()
        model = MagicMock()
        conn.get_model.return_value = model
        return conn, model

    def test_writes_updates(self):
        conn, model = self._mock_conn()
        report = [
            {
                "action": "update",
                "entry": {"id": 100},
                "changes": {"x_studio_value": 4000.0},
            },
            {"action": "ok", "entry": {"id": 200}, "changes": {}},
        ]
        updated = _apply_validation_updates(conn, report)
        assert updated == 1
        model.write.assert_called_once_with(100, {"x_studio_value": 4000.0})

    def test_skips_ok_and_skip_entries(self):
        conn, model = self._mock_conn()
        report = [
            {"action": "ok", "entry": {"id": 1}, "changes": {}},
            {"action": "skip", "entry": {"id": 2}, "changes": {}},
        ]
        updated = _apply_validation_updates(conn, report)
        assert updated == 0
        model.write.assert_not_called()

    def test_multiple_updates(self):
        conn, model = self._mock_conn()
        report = [
            {
                "action": "update",
                "entry": {"id": 100},
                "changes": {"x_studio_value": 4000.0},
            },
            {
                "action": "update",
                "entry": {"id": 200},
                "changes": {"x_studio_is_available": False},
            },
            {"action": "ok", "entry": {"id": 300}, "changes": {}},
        ]
        updated = _apply_validation_updates(conn, report)
        assert updated == 2
        assert model.write.call_count == 2


# ── _scrape_reverb_urls (mocked scraper) ─────────────────────────────────


class TestScrapeReverbUrls:
    """Unit tests for _scrape_reverb_urls with mocked ReverbScraper."""

    async def test_scrapes_reverb_urls_only(self):
        entries = [
            {"x_studio_url": "https://reverb.com/item/1-guitar"},
            {"x_studio_url": "https://other.com/guitar"},
            {"x_studio_url": "https://reverb.com/item/2-bass"},
        ]

        mock_results = [
            {"url": "https://reverb.com/item/1-guitar", "name": "Guitar"},
            {"url": "https://reverb.com/item/2-bass", "name": "Bass"},
        ]

        mock_scraper = AsyncMock()
        mock_scraper.extract_many.return_value = mock_results

        with patch("validate_model.ReverbScraper") as MockCls:
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_scraper
            MockCls.return_value = mock_instance
            result = await _scrape_reverb_urls(entries)

        assert len(result) == 2
        assert "https://reverb.com/item/1-guitar" in result
        assert "https://reverb.com/item/2-bass" in result
        assert "https://other.com/guitar" not in result

    async def test_empty_entries_returns_empty(self):
        result = await _scrape_reverb_urls([])
        assert result == {}

    async def test_no_reverb_urls_returns_empty(self):
        entries = [
            {"x_studio_url": "https://other.com/guitar"},
            {"x_studio_url": ""},
        ]
        result = await _scrape_reverb_urls(entries)
        assert result == {}


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
        assert result[0]["default_shipping"] == 250.0

    def test_empty_database_returns_empty(self):
        conn = self._mock_conn([])
        result = _fetch_all_models(conn)
        assert result == []

    def test_mixed_with_and_without_category(self):
        conn = self._mock_conn(
            [
                {
                    "id": 1,
                    "x_name": "With Cat",
                    "x_studio_reverb_category_id": [10, "Guitars"],
                },
                {
                    "id": 2,
                    "x_name": "Without Cat",
                    "x_studio_reverb_category_id": False,
                },
            ],
            cat_records=[
                {
                    "id": 10,
                    "x_studio_slug": "electric-guitars",
                    "x_studio_shipping_default_price": 300.0,
                },
            ],
        )
        result = _fetch_all_models(conn)

        assert result[0]["category_slug"] == "electric-guitars"
        assert result[0]["default_shipping"] == 300.0
        assert result[1]["category_slug"] is None
        assert result[1]["default_shipping"] == 250.0

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

        # x_reverb_category search_read should be called exactly once.
        cat_mock = conn.get_model("x_reverb_category")
        assert cat_mock.search_read.call_count == 1

        # The domain should use 'in' with both category IDs.
        call_domain = cat_mock.search_read.call_args[0][0]
        assert call_domain[0][0] == "id"
        assert call_domain[0][1] == "in"
        assert set(call_domain[0][2]) == {10, 20}


# ── _collect_model_data (mocked I/O) ─────────────────────────────────────


class TestCollectModelData:
    """Unit tests for _collect_model_data, the thread-safe collection phase."""

    def _mock_conn(self, guitar_entries=None):
        conn = MagicMock()
        guitar = MagicMock()
        guitar.search_read.return_value = guitar_entries or []
        conn.get_model.return_value = guitar
        return conn

    async def test_no_entries_returns_empty_result(self):
        conn = self._mock_conn(guitar_entries=[])

        result = await _collect_model_data(
            conn, model_id=1, model_name="Test", default_shipping=250.0
        )

        assert result["model_id"] == 1
        assert result["model_name"] == "Test"
        assert result["entries"] == []
        assert result["reverb_data"] == {}
        assert result["report"] == []
        assert result["update_count"] == 0

    async def test_collects_entries_and_scrapes(self):
        url = "https://reverb.com/item/1-guitar"
        entries = [
            {
                "id": 100,
                "x_name": "Guitar",
                "x_studio_url": url,
                "x_studio_value": 5000.0,
                "x_studio_accept_offers": True,
                "x_studio_is_available": True,
                "x_studio_shipping": 250.0,
                "x_studio_published_at_1": "2025-06-20 00:00:00",
            }
        ]
        reverb_result = {
            url: {
                "url": url,
                "name": "Guitar",
                "price": "4000.00",
                "price_display": "C$4,000",
                "offers_enabled": True,
                "sale_ended": False,
                "published_at": "2025-06-20",
                "shipping_price": "250.00",
                "ships_to_canada": True,
                "status": "Live",
            }
        }

        conn = self._mock_conn(guitar_entries=entries)

        with patch(
            "validate_model._scrape_reverb_urls",
            new_callable=AsyncMock,
            return_value=reverb_result,
        ):
            result = await _collect_model_data(
                conn, model_id=1, model_name="Test", default_shipping=250.0
            )

        assert len(result["entries"]) == 1
        assert url in result["reverb_data"]
        assert len(result["report"]) == 1
        assert result["update_count"] == 1  # price changed 5000 → 4000

    async def test_echoes_back_model_metadata(self):
        conn = self._mock_conn(guitar_entries=[])

        result = await _collect_model_data(
            conn, model_id=42, model_name="My Model", default_shipping=99.0
        )

        assert result["model_id"] == 42
        assert result["model_name"] == "My Model"
        assert result["default_shipping"] == 99.0
