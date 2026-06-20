"""Tests for sync_model — Reverb API calls recorded via VCR cassettes."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from models import ListingRecord
from sync_model import (
    DEFAULT_SHIPPING,
    REWATCH_PRICE_DROP_THRESHOLD,
    _apply_updates,
    _build_report,
    _clean_url,
    _collect_sync_data,
    _compute_changes,
    _download_image_base64,
    _ebay_item_id,
    _fetch_all_models,
    _fetch_listings,
    _find_entries_without_image,
    _find_model,
    _is_brand_new,
    _listing_vals_from_scrape,
    _print_report,
    _reverb_item_id,
    _round_price,
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


# ── _reverb_item_id ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium",
            "94370297",
            id="standard-reverb-url",
        ),
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium?show_sold=true",
            "94370297",
            id="with-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/94370297",
            "94370297",
            id="no-slug",
        ),
        pytest.param("https://reverb.com/shop/some-shop", None, id="non-item-url"),
        pytest.param("", None, id="empty-string"),
        pytest.param(
            "https://reverb.com/item/abc-not-numeric",
            None,
            id="non-numeric-id",
        ),
    ],
)
def test_reverb_item_id(url: str, expected: str | None):
    assert _reverb_item_id(url) == expected


# ── _ebay_item_id ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://www.ebay.com/itm/123456789012",
            "123456789012",
            id="standard-ebay-url",
        ),
        pytest.param(
            "https://www.ebay.ca/itm/some-guitar/123456789012",
            "123456789012",
            id="with-slug",
        ),
        pytest.param(
            "https://www.ebay.com/itm/123456789012?var=456",
            "123456789012",
            id="with-query-string",
        ),
        pytest.param("https://reverb.com/item/1-g", None, id="non-ebay-url"),
        pytest.param("", None, id="empty-string"),
    ],
)
def test_ebay_item_id(url: str, expected: str | None):
    assert _ebay_item_id(url) == expected


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
        assert "--include-sold" in result.output

    def test_flags_only_no_model_no_all(self):
        result = self.runner.invoke(cli, ["--dry-run"])
        assert result.exit_code != 0

    def test_workers_invalid_type_rejected(self):
        result = self.runner.invoke(cli, ["--all", "--workers", "abc"])
        assert result.exit_code != 0

    def test_wanna_shown_in_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert "--wanna" in result.output


# ── _is_brand_new ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "condition, expected",
    [
        pytest.param("Brand New", True, id="exact-brand-new"),
        pytest.param("brand new", True, id="lowercase"),
        pytest.param("BRAND NEW", True, id="uppercase"),
        pytest.param("Excellent", False, id="excellent"),
        pytest.param("Very Good", False, id="very-good"),
        pytest.param("Mint", False, id="mint"),
        pytest.param("Good", False, id="good"),
        pytest.param("", False, id="empty-string"),
    ],
)
def test_is_brand_new(condition: str, expected: bool):
    assert _is_brand_new({"condition": condition}) == expected


def test_is_brand_new_missing_field():
    assert _is_brand_new({}) is False


# ── _round_price ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "price, expected",
    [
        pytest.param(0.0, 0.0, id="zero"),
        pytest.param(10.0, 10.0, id="exact-multiple"),
        pytest.param(8.0, 10.0, id="rounds-up"),
        pytest.param(11.0, 10.0, id="rounds-down"),
        pytest.param(16.0, 20.0, id="rounds-up-to-20"),
        pytest.param(15.0, 20.0, id="midpoint-banker-rounds-up-to-even"),
        pytest.param(5000.0, 5000.0, id="large-exact-multiple"),
    ],
)
def test_round_price(price: float, expected: float):
    assert _round_price(price) == expected


# ── _compute_changes ──────────────────────────────────────────────────────


class TestComputeChanges:
    """Unit tests for _compute_changes (pure logic, no I/O)."""

    def test_no_changes_when_identical(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_published_at": "2025-06-20 00:00:00",
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "published_at": "2025-06-20",
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        assert _compute_changes(ListingRecord.from_odoo(entry), reverb) == {}

    def test_price_change(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "4500.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_price"] == 4500.0

    def test_price_fx_noise_ignored(self):
        """Small price drift within $50 (CAD FX noise) should not trigger an update."""
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "4999.00",  # rounds to same $5000 bucket
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_price" not in changes

    def test_offers_toggled_off(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_can_accept_offers"] is False

    def test_sale_ended_marks_unavailable(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_is_available"] is False

    def test_sale_ended_does_not_update_shipping(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_shipping" not in changes

    def test_live_listing_updates_shipping(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "300.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_shipping"] == 300.0

    def test_published_at_not_updated_when_already_set(self):
        """published_at should not be overwritten once stored in Odoo."""
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_published_at": "2025-01-01 00:00:00",
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
            "published_at": "2025-06-20",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_published_at" not in changes

    def test_published_at_set_when_empty(self):
        """published_at should be populated when the Odoo field is empty."""
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_published_at": False,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
            "published_at": "2025-06-20",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_published_at"] == "2025-06-20 00:00:00"

    def test_relists_marks_available(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": False,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_is_available"] is True

    def test_passed_listing_reverts_to_watching_on_price_drop(self):
        entry = {
            "x_price": 5000.0,
            "x_status": "passed",
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "4000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_status"] == "watching"
        assert changes["x_price"] == 4000.0

    def test_passed_listing_stays_passed_on_currency_noise_drop(self):
        # A < REWATCH_PRICE_DROP_THRESHOLD drop (e.g. 2 %) is treated as conversion noise
        existing = 5000.0
        noise_drop = existing * (1 - REWATCH_PRICE_DROP_THRESHOLD / 2)  # half the threshold
        entry = {
            "x_price": existing,
            "x_status": "passed",
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": str(noise_drop),
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_status" not in changes

    def test_passed_listing_stays_passed_when_price_same(self):
        entry = {
            "x_price": 5000.0,
            "x_status": "passed",
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_status" not in changes

    def test_passed_listing_stays_passed_when_price_rises(self):
        entry = {
            "x_price": 5000.0,
            "x_status": "passed",
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "6000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_status" not in changes

    def test_watching_listing_unaffected_by_price_drop(self):
        entry = {
            "x_price": 5000.0,
            "x_status": "watching",
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "4000.00",
            "offers_enabled": True,
            "sale_ended": False,
            "shipping_price": "250.00",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_status" not in changes

    def test_already_unavailable_stays_unchanged(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": False,
            "x_shipping": 250.0,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": True,
            "sale_ended": True,
            "shipping_price": None,
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_is_available" not in changes

    def test_description_sets_notes_when_changed(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": False,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_studio_notes": "old description",
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
            "description": "new detailed description",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_studio_notes"] == "new detailed description"

    def test_description_unchanged_no_notes_update(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": False,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_studio_notes": "same description",
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
            "description": "same description",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_studio_notes" not in changes

    def test_empty_description_does_not_clear_notes(self):
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": False,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_studio_notes": "existing notes",
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
            "description": "",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_studio_notes" not in changes

    def test_odoo_false_notes_treated_as_empty(self):
        # Odoo XML-RPC returns False for unset fields, not "" or None
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": False,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_studio_notes": False,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
            "description": "some description",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert changes["x_studio_notes"] == "some description"

    def test_odoo_false_notes_with_same_description_no_update(self):
        # If Odoo has False and Reverb has empty description, no update
        entry = {
            "x_price": 5000.0,
            "x_can_accept_offers": False,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_studio_notes": False,
        }
        reverb = {
            "price": "5000.00",
            "offers_enabled": False,
            "sale_ended": False,
            "shipping_price": "250.00",
            "description": "",
        }
        changes = _compute_changes(ListingRecord.from_odoo(entry), reverb)
        assert "x_studio_notes" not in changes


# ── _listing_vals_from_scrape ─────────────────────────────────────────────


class TestListingValsFromScrape:
    """Unit tests for _listing_vals_from_scrape (pure logic, no I/O)."""

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
        vals = _listing_vals_from_scrape(reverb, model_id=42)

        assert vals["x_name"] == "Cool Guitar"
        assert vals["x_model_id"] == 42
        assert vals["x_status"] == "watching"
        assert vals["x_url"] == "https://reverb.com/item/123-cool-guitar"
        assert vals["x_platform"] == "reverb"
        assert vals["x_price"] == 5000.0
        assert vals["x_shipping"] == 200.0
        assert vals["x_is_available"] is True
        assert vals["x_can_accept_offers"] is True
        assert vals["x_is_taxed"] is False
        assert vals["x_published_at"] == "2025-06-20 00:00:00"
        assert "x_intent" not in vals
        assert "x_market_status" not in vals

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
        vals = _listing_vals_from_scrape(reverb, model_id=1)

        assert vals["x_is_available"] is False
        assert vals["x_shipping"] == DEFAULT_SHIPPING
        assert vals["x_can_accept_offers"] is False

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
        vals = _listing_vals_from_scrape(reverb, model_id=1, default_shipping=35.0)

        assert vals["x_shipping"] == 40.0  # _round_price(35) = 40

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
        vals = _listing_vals_from_scrape(reverb, model_id=1)
        assert "x_published_at" not in vals

    def test_description_included_in_vals(self):
        reverb = {
            "name": "Guitar",
            "url": "https://reverb.com/item/789-g",
            "price": "1000.00",
            "shipping_price": "100.00",
            "sale_ended": False,
            "offers_enabled": False,
            "published_at": "",
            "description": "Great condition, minor wear.",
        }
        vals = _listing_vals_from_scrape(reverb, model_id=1)
        assert vals["x_studio_notes"] == "Great condition, minor wear."

    def test_empty_description_not_included(self):
        reverb = {
            "name": "Guitar",
            "url": "https://reverb.com/item/789-g",
            "price": "1000.00",
            "shipping_price": "100.00",
            "sale_ended": False,
            "offers_enabled": False,
            "published_at": "",
            "description": "",
        }
        vals = _listing_vals_from_scrape(reverb, model_id=1)
        assert "x_studio_notes" not in vals


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

    def _make_odoo(self, url="https://reverb.com/item/1-g", **kwargs) -> ListingRecord:
        """Build a mock x_listing record."""
        base = {
            "id": 100,
            "x_name": "Guitar",
            "x_url": url,
            "x_price": 5000.0,
            "x_can_accept_offers": True,
            "x_is_available": True,
            "x_shipping": 250.0,
            "x_published_at": "2025-06-20 00:00:00",
        }
        base.update(kwargs)
        return ListingRecord.from_odoo(base)

    def test_new_listing_creates(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/999-new", condition="Excellent")
        ]
        odoo_entries = []

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "create"
        assert report[0]["create_vals"]["x_model_id"] == 42

    def test_brand_new_listing_skipped(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/999-new", condition="Brand New")
        ]
        odoo_entries = []

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "skip"
        assert any("brand new" in w for w in report[0]["warnings"])
        assert report[0]["create_vals"] == {}

    def test_brand_new_existing_still_updated(self):
        """A brand-new listing that already exists in Odoo should still be updated."""
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, condition="Brand New", price="4000.00")]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["changes"]["x_price"] == 4000.0

    def test_existing_up_to_date(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url)]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "ok"

    def test_slug_changed_matches_by_item_id(self):
        """When Reverb renames a listing the URL slug changes but item ID stays the same.
        The existing Odoo entry should be updated, not duplicated."""
        old_url = "https://reverb.com/item/9999-old-slug"
        new_url = "https://reverb.com/item/9999-new-slug"
        reverb_results = [self._make_reverb(url=new_url, price="4000.00")]
        odoo_entries = [self._make_odoo(url=old_url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["entry"] is not None

    def test_different_item_id_creates(self):
        """A genuinely new listing (different item ID) should still be created."""
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/8888-new-guitar", condition="Excellent")
        ]
        odoo_entries = [self._make_odoo(url="https://reverb.com/item/9999-old-guitar")]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "create"

    def test_existing_needs_update(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, price="4000.00")]
        odoo_entries = [self._make_odoo(url=url)]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["changes"]["x_price"] == 4000.0

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
            self._make_reverb(url="https://reverb.com/item/3-new", condition="Excellent"),
        ]
        odoo_entries = [
            self._make_odoo(url="https://reverb.com/item/1-g"),
            self._make_odoo(url="https://reverb.com/item/2-g", id=200),
        ]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        actions = [r["action"] for r in report]
        assert actions == ["ok", "update", "create"]

    def test_mixed_with_brand_new_skipped(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/1-g"),
            self._make_reverb(url="https://reverb.com/item/2-new", condition="Brand New"),
            self._make_reverb(url="https://reverb.com/item/3-used", condition="Very Good"),
        ]
        odoo_entries = [
            self._make_odoo(url="https://reverb.com/item/1-g"),
        ]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        actions = [r["action"] for r in report]
        assert actions == ["ok", "skip", "create"]

    def test_include_brand_new_creates_instead_of_skipping(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/2-new", condition="Brand New"),
        ]
        odoo_entries = []

        report = _build_report(reverb_results, odoo_entries, model_id=42, include_brand_new=True)

        assert len(report) == 1
        assert report[0]["action"] == "create"
        assert report[0]["create_vals"]["x_model_id"] == 42

    def test_cross_model_match_flags_other_model_id(self):
        """When the matched entry belongs to a different model, the report
        item should expose other_model_id and never include x_model_id in
        the change set."""
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, price="4000.00")]
        # Entry belongs to model 99, not the syncing model 42.
        odoo_entries = [
            self._make_odoo(url=url, x_model_id=[99, "Other Model"]),
        ]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["other_model_id"] == 99
        assert "x_model_id" not in report[0]["changes"]

    def test_same_model_match_other_model_id_is_none(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url)]
        odoo_entries = [self._make_odoo(url=url, x_model_id=[42, "Same"])]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert report[0]["other_model_id"] is None

    def test_new_listing_has_other_model_id_none(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/999-new", condition="Excellent"),
        ]
        report = _build_report(reverb_results, [], model_id=42)

        assert report[0]["action"] == "create"
        assert report[0]["other_model_id"] is None

    def test_cross_model_match_does_not_create(self):
        """If the URL already exists under another model, no create entry
        should be produced — the existing row is updated instead."""
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, condition="Excellent")]
        odoo_entries = [self._make_odoo(url=url, x_model_id=[99, "Other"])]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        actions = [r["action"] for r in report]
        assert "create" not in actions

    def test_duplicate_url_first_wins_and_warns(self):
        """If two existing entries share the same URL, the first one is
        kept and a WARNING is logged so the user can dedupe manually.

        We patch sync_model.logger.warning directly because the project
        uses loguru, which does not propagate to caplog by default.
        """
        url = "https://reverb.com/item/1-g"
        first = self._make_odoo(url=url, id=100)
        second = self._make_odoo(url=url, id=200)
        reverb_results = [self._make_reverb(url=url)]

        with patch("sync_model.logger.warning") as warn:
            report = _build_report(reverb_results, [first, second], model_id=42)

        assert report[0]["entry"].id == 100
        assert warn.called
        warn_args = " ".join(str(a) for call in warn.call_args_list for a in call.args)
        assert "100" in warn_args
        assert "200" in warn_args

    def test_ebay_item_id_match_on_slug_change(self):
        """An eBay listing whose URL slug changed is matched by numeric item id,
        not URL, so no duplicate create is produced."""
        old_url = "https://www.ebay.com/itm/old-slug/123456789012"
        new_url = "https://www.ebay.com/itm/new-slug/123456789012"
        odoo_entry = self._make_odoo(url=old_url, id=77)
        scrape_result = {
            "url": new_url,
            "name": "eBay Guitar",
            "price": "5000.00",
            "price_display": "USD 5,000",
            "offers_enabled": False,
            "sale_ended": False,
            "published_at": "2025-06-20",
            "shipping_price": "50.00",
            "ships_to_canada": True,
            "_ebay_item_id": "123456789012",
            "_platform": "ebay",
        }

        report = _build_report([scrape_result], [odoo_entry], model_id=42)

        assert len(report) == 1
        assert report[0]["action"] in ("ok", "update")
        assert report[0]["entry"].id == 77


# ── _print_report ─────────────────────────────────────────────────────────


class TestPrintReport:
    """Test _print_report return values."""

    def test_counts(self, capsys):
        report = [
            {
                "action": "ok",
                "reverb": {"name": "A", "price_display": "$1"},
                "entry": ListingRecord.from_odoo({"id": 1}),
                "changes": {},
                "warnings": [],
            },
            {
                "action": "update",
                "reverb": {"name": "B", "price_display": "$2"},
                "entry": ListingRecord.from_odoo({"id": 2, "x_price": 99}),
                "changes": {"x_price": 99},
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
                "entry": ListingRecord.from_odoo({"id": 1}),
                "changes": {},
                "warnings": [],
            },
        ]
        upd, crt = _print_report(report)
        assert upd == 0
        assert crt == 0

    def test_cross_model_hint_shown_in_info_column(self, capsys):
        report = [
            {
                "action": "update",
                "reverb": {"name": "G", "price_display": "$1"},
                "entry": ListingRecord.from_odoo(
                    {"id": 200, "x_price": 99, "x_model_id": [1155, "Grez Mendocino Jr"]}
                ),
                "changes": {"x_price": 99},
                "warnings": [],
                "other_model_id": 1155,
            },
        ]
        _print_report(report)
        out = capsys.readouterr().out
        # Hint must surface arrow prefix + model name + id.
        # Rich wraps the Info column under capsys's narrow default width,
        # so check the parts independently rather than as a contiguous
        # substring.
        assert "→ model:" in out
        assert "Grez Mendocino Jr" in out
        assert "1155" in out

    def test_no_hint_when_same_model(self, capsys):
        report = [
            {
                "action": "update",
                "reverb": {"name": "G", "price_display": "$1"},
                "entry": ListingRecord.from_odoo({"id": 200, "x_price": 99}),
                "changes": {"x_price": 99},
                "warnings": [],
                "other_model_id": None,
            },
        ]
        _print_report(report)
        out = capsys.readouterr().out
        assert "model:" not in out.lower()


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

    def _mock_conn(self, gear_create_return=777):
        conn = MagicMock()
        gear_mock = MagicMock()
        gear_mock.create.return_value = gear_create_return
        gear_mock.search_read.return_value = []  # no entries without image

        conn.get_model.return_value = gear_mock
        return conn, gear_mock

    def test_writes_updates(self):
        conn, gear_mock = self._mock_conn()
        report = [
            {
                "action": "update",
                "entry": ListingRecord.from_odoo({"id": 100}),
                "changes": {"x_price": 4000.0},
            },
            {"action": "ok", "entry": ListingRecord.from_odoo({"id": 200}), "changes": {}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 1
        assert crt == 0
        gear_mock.write.assert_called_once_with(100, {"x_price": 4000.0})

    def test_creates_new_entries(self):
        conn, gear_mock = self._mock_conn(gear_create_return=777)
        listing_vals = {
            "x_name": "New Guitar",
            "x_model_id": 42,
            "x_status": "watching",
            "x_url": "https://reverb.com/item/1-g",
            "x_platform": "reverb",
        }
        report = [
            {
                "action": "create",
                "create_vals": listing_vals,
                "reverb": {"photo_url": ""},
            },
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 0
        assert crt == 1
        gear_mock.create.assert_called_once_with(listing_vals)

    def test_skips_ok_entries(self):
        conn, gear_mock = self._mock_conn()
        report = [
            {"action": "ok", "entry": ListingRecord.from_odoo({"id": 1}), "changes": {}},
            {"action": "skip", "entry": None, "changes": {}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 0
        assert crt == 0
        gear_mock.create.assert_not_called()

    def test_mixed_updates_and_creates(self):
        conn, gear_mock = self._mock_conn(gear_create_return=100)
        gear_vals = {
            "x_name": "G",
            "x_model_id": 1,
            "x_status": "watching",
            "x_url": "u",
            "x_platform": "reverb",
        }
        report = [
            {
                "action": "update",
                "entry": ListingRecord.from_odoo({"id": 50}),
                "changes": {"x_price": 1.0},
            },
            {"action": "create", "create_vals": gear_vals, "reverb": {"photo_url": ""}},
            {"action": "ok", "entry": ListingRecord.from_odoo({"id": 200}), "changes": {}},
            {"action": "create", "create_vals": gear_vals, "reverb": {"photo_url": ""}},
        ]
        upd, crt = _apply_updates(conn, report)
        assert upd == 1
        assert crt == 2
        gear_mock.write.assert_called_once()
        assert gear_mock.create.call_count == 2


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


@pytest.mark.parametrize(
    "include_sold, expected_state",
    [
        pytest.param(False, "live", id="default-live-only"),
        pytest.param(True, "all", id="include-sold-all"),
    ],
)
def test_search_reverb_state_parameter(include_sold: bool, expected_state: str):
    """_search_reverb passes state='live' by default, 'all' with include_sold=True."""
    from unittest.mock import AsyncMock

    captured_states: list[str] = []

    async def fake_search(query, *, category=None, state="live", **kwargs):
        captured_states.append(state)
        return []

    mock_scraper = MagicMock()
    mock_scraper.search = fake_search
    mock_instance = MagicMock()
    mock_instance.__aenter__ = AsyncMock(return_value=mock_scraper)
    mock_instance.__aexit__ = AsyncMock(return_value=None)

    with patch("sync_model.ReverbScraper", return_value=mock_instance):
        _search_reverb("Test Model", include_sold=include_sold)

    assert captured_states == [expected_state]


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

    def test_wanna_only_filters_domain(self):
        """When wanna_only=True the search domain filters on x_studio_wanna."""
        conn = self._mock_conn(
            [
                {"id": 1, "x_name": "Wanted", "x_studio_reverb_category_id": False},
            ]
        )

        _fetch_all_models(conn, wanna_only=True)

        models_mock = conn.get_model("x_models")
        call_domain = models_mock.search_read.call_args[0][0]
        assert call_domain == [("x_studio_wanna", "=", True)]

    def test_wanna_only_false_uses_empty_domain(self):
        """Default (wanna_only=False) searches all models."""
        conn = self._mock_conn(
            [
                {"id": 1, "x_name": "Model A", "x_studio_reverb_category_id": False},
            ]
        )

        _fetch_all_models(conn, wanna_only=False)

        models_mock = conn.get_model("x_models")
        call_domain = models_mock.search_read.call_args[0][0]
        assert call_domain == []


# ── _collect_sync_data (mocked I/O) ──────────────────────────────────────


class TestCollectSyncData:
    """Unit tests for _collect_sync_data, the thread-safe collection phase."""

    def _mock_conn(self, guitar_entries=None):
        conn = MagicMock()
        guitar = MagicMock()
        guitar.search_read.return_value = guitar_entries or []
        conn.get_model.return_value = guitar
        return conn

    def _fake_platforms(self, reverb_return=None):
        """Build a PLATFORMS dict with a mock reverb function and a no-op ebay function."""
        fake_reverb = MagicMock(return_value=reverb_return or [])
        fake_ebay = MagicMock(return_value=[])
        return {"reverb": fake_reverb, "ebay": fake_ebay}

    def test_no_reverb_results_returns_empty(self):
        import sync_model

        conn = self._mock_conn()

        with patch.object(sync_model, "PLATFORMS", self._fake_platforms([])):
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
        import sync_model

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

        with patch.object(sync_model, "PLATFORMS", self._fake_platforms(reverb_results)):
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
        import sync_model

        with patch.object(sync_model, "PLATFORMS", self._fake_platforms([])):
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
        import sync_model

        conn = self._mock_conn()
        platforms = self._fake_platforms([])

        with patch.object(sync_model, "PLATFORMS", platforms):
            _collect_sync_data(
                conn,
                model_id=1,
                model_name="Model A",
                category_slug="electric-guitars",
                default_shipping=250.0,
                search_query="Custom Query",
                platforms=["reverb"],
            )

        platforms["reverb"].assert_called_once_with(
            "Custom Query",
            category="electric-guitars",
            default_shipping=250.0,
            include_sold=False,
        )

    def test_falls_back_to_model_name_for_query(self):
        import sync_model

        conn = self._mock_conn()
        platforms = self._fake_platforms([])

        with patch.object(sync_model, "PLATFORMS", platforms):
            _collect_sync_data(
                conn,
                model_id=1,
                model_name="Model A",
                category_slug=None,
                default_shipping=250.0,
                platforms=["reverb"],
            )

        platforms["reverb"].assert_called_once_with(
            "Model A",
            category=None,
            default_shipping=250.0,
            include_sold=False,
        )

    def test_passes_include_sold_to_search_reverb(self):
        import sync_model

        conn = self._mock_conn()
        platforms = self._fake_platforms([])

        with patch.object(sync_model, "PLATFORMS", platforms):
            _collect_sync_data(
                conn,
                model_id=1,
                model_name="Model A",
                category_slug=None,
                default_shipping=250.0,
                include_sold=True,
                platforms=["reverb"],
            )

        platforms["reverb"].assert_called_once_with(
            "Model A",
            category=None,
            default_shipping=250.0,
            include_sold=True,
        )

    def test_passes_url_candidates_to_fetch_listings(self):
        """URL candidates from results are forwarded to _fetch_listings
        as both raw and cleaned forms so the DB lookup is lossless."""
        import sync_model

        reverb_results = [
            {
                "url": "https://reverb.com/item/1-g?show_sold=true",
                "name": "G1",
                "price": "100.00",
                "price_display": "C$100",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
            {
                "url": "https://reverb.com/item/2-g",
                "name": "G2",
                "price": "200.00",
                "price_display": "C$200",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
        ]
        captured: dict = {}

        def fake_fetch_listings(conn, model_id, extra_urls=None):
            captured["model_id"] = model_id
            captured["extra_urls"] = list(extra_urls or [])
            return []

        with (
            patch.object(sync_model, "PLATFORMS", self._fake_platforms(reverb_results)),
            patch("sync_model._fetch_listings", side_effect=fake_fetch_listings),
        ):
            _collect_sync_data(
                MagicMock(),
                model_id=42,
                model_name="Test",
                category_slug=None,
                default_shipping=250.0,
            )

        assert captured["model_id"] == 42
        # Both the raw URL (with query string) and the cleaned URL should be present
        assert "https://reverb.com/item/1-g?show_sold=true" in captured["extra_urls"]
        assert "https://reverb.com/item/1-g" in captured["extra_urls"]
        assert "https://reverb.com/item/2-g" in captured["extra_urls"]

    def test_empty_url_candidates_when_results_lack_urls(self):
        """If results have empty/missing url fields, no URL candidates
        are forwarded — _fetch_listings receives an empty extra_urls list."""
        import sync_model

        reverb_results = [
            {
                "url": "",  # empty string
                "name": "G1",
                "price": "100.00",
                "price_display": "C$100",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
            {
                # url key entirely absent
                "name": "G2",
                "price": "200.00",
                "price_display": "C$200",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
        ]
        captured: dict = {}

        def fake_fetch_listings(conn, model_id, extra_urls=None):
            captured["extra_urls"] = list(extra_urls or [])
            return []

        with (
            patch.object(sync_model, "PLATFORMS", self._fake_platforms(reverb_results)),
            patch("sync_model._fetch_listings", side_effect=fake_fetch_listings),
        ):
            _collect_sync_data(
                MagicMock(),
                model_id=42,
                model_name="Test",
                category_slug=None,
                default_shipping=250.0,
            )

        assert captured["extra_urls"] == []

    def test_unknown_platform_skipped_with_warning(self):
        """An unknown platform name is skipped with a warning; valid
        platforms still run and their results are returned."""
        import sync_model

        reverb_results = [
            {
                "url": "https://reverb.com/item/1-g",
                "name": "Guitar",
                "price": "100.00",
                "price_display": "C$100",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            }
        ]

        with (
            patch.object(sync_model, "PLATFORMS", self._fake_platforms(reverb_results)),
            patch("sync_model._fetch_listings", return_value=[]),
            patch("sync_model.logger.warning") as warn,
        ):
            result = _collect_sync_data(
                MagicMock(),
                model_id=42,
                model_name="Test",
                category_slug=None,
                default_shipping=250.0,
                platforms=["reverb", "nonexistent"],
            )

        assert len(result["reverb_results"]) == 1
        assert warn.called
        warn_args = " ".join(str(a) for call in warn.call_args_list for a in call.args)
        assert "nonexistent" in warn_args


# ── _download_image_base64 ───────────────────────────────────────────────


class TestDownloadImageBase64:
    """Unit tests for _download_image_base64 (mocked HTTP)."""

    def test_returns_base64_on_success(self):
        fake_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_response = MagicMock()
        mock_response.content = fake_content
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("sync_model.httpx.Client", return_value=mock_client):
            result = _download_image_base64("https://images.reverb.com/photo.jpg")

        assert result is not None
        import base64

        assert base64.b64decode(result) == fake_content

    def test_returns_none_for_empty_url(self):
        assert _download_image_base64("") is None

    def test_returns_none_for_none_url(self):
        # photo_url can be None when not present in API response
        assert _download_image_base64(None) is None

    def test_returns_none_on_http_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=MagicMock()
        )

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("sync_model.httpx.Client", return_value=mock_client):
            result = _download_image_base64("https://images.reverb.com/missing.jpg")

        assert result is None

    def test_returns_none_on_connection_error(self):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = Exception("Connection refused")

        with patch("sync_model.httpx.Client", return_value=mock_client):
            result = _download_image_base64("https://images.reverb.com/photo.jpg")

        assert result is None


# ── _find_entries_without_image ──────────────────────────────────────────


class TestFindEntriesWithoutImage:
    """Unit tests for _find_entries_without_image."""

    def test_returns_ids_without_image(self):
        conn = MagicMock()
        listing = MagicMock()
        listing.search_read.return_value = [{"id": 100}, {"id": 300}]
        conn.get_model.return_value = listing

        result = _find_entries_without_image(conn, [100, 200, 300])

        assert result == {100, 300}
        conn.get_model.assert_called_once_with("x_listing")
        listing.search_read.assert_called_once_with(
            [("id", "in", [100, 200, 300]), ("x_studio_image", "=", False)],
            ["id"],
        )

    def test_empty_ids_returns_empty_set(self):
        conn = MagicMock()
        result = _find_entries_without_image(conn, [])
        assert result == set()
        conn.get_model.assert_not_called()

    def test_all_have_images(self):
        conn = MagicMock()
        guitar = MagicMock()
        guitar.search_read.return_value = []
        conn.get_model.return_value = guitar

        result = _find_entries_without_image(conn, [100, 200])
        assert result == set()


# ── _apply_updates (image handling) ──────────────────────────────────────


class TestApplyUpdatesImages:
    """Tests for image download behaviour in _apply_updates."""

    def _mock_conn(self, gear_create_return=777, listing_create_return=9999, no_image_ids=None):
        """Build a mock connection that handles x_gear and x_listing separately."""
        conn = MagicMock()
        gear_mock = MagicMock()
        gear_mock.create.return_value = gear_create_return
        listing_mock = MagicMock()
        listing_mock.create.return_value = listing_create_return

        def _listing_search_read(domain, fields, **kwargs):
            if fields == ["id"]:
                return [{"id": eid} for eid in (no_image_ids or [])]
            return []

        listing_mock.search_read.side_effect = _listing_search_read

        def _get_model(name):
            if name == "x_gear":
                return gear_mock
            return listing_mock

        conn.get_model.side_effect = _get_model
        return conn, gear_mock, listing_mock

    def _make_create_vals(self, name="Guitar", model_id=42):
        return {
            "x_name": name,
            "x_model_id": model_id,
            "x_status": "watching",
            "x_url": "https://reverb.com/item/1-g",
            "x_platform": "reverb",
        }

    def test_create_downloads_image(self):
        conn, gear_mock, listing_mock = self._mock_conn(
            gear_create_return=777, listing_create_return=500
        )
        report = [
            {
                "action": "create",
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg", "name": "G"},
                "create_vals": self._make_create_vals(),
            },
        ]

        with patch("sync_model._download_image_base64", return_value="FAKEBASE64") as mock_dl:
            upd, crt = _apply_updates(conn, report)

        assert crt == 1
        mock_dl.assert_called_once_with("https://img.reverb.com/photo.jpg")
        # The listing create call should include the image
        call_vals = listing_mock.create.call_args[0][0]
        assert call_vals["x_studio_image"] == "FAKEBASE64"

    def test_create_without_photo_url(self):
        conn, gear_mock, listing_mock = self._mock_conn(listing_create_return=500)
        report = [
            {
                "action": "create",
                "reverb": {"photo_url": "", "name": "G"},
                "create_vals": self._make_create_vals(),
            },
        ]

        with patch("sync_model._download_image_base64", return_value=None):
            upd, crt = _apply_updates(conn, report)

        assert crt == 1
        call_vals = listing_mock.create.call_args[0][0]
        assert "x_studio_image" not in call_vals

    def test_create_image_download_fails_gracefully(self):
        conn, gear_mock, listing_mock = self._mock_conn(listing_create_return=500)
        report = [
            {
                "action": "create",
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg", "name": "G"},
                "create_vals": self._make_create_vals(),
            },
        ]

        with patch("sync_model._download_image_base64", return_value=None):
            upd, crt = _apply_updates(conn, report)

        # Entry should still be created, just without image
        assert crt == 1
        call_vals = listing_mock.create.call_args[0][0]
        assert "x_studio_image" not in call_vals

    def test_update_downloads_image_when_missing(self):
        conn, gear_mock, listing_mock = self._mock_conn(no_image_ids=[100])
        report = [
            {
                "action": "update",
                "entry": ListingRecord.from_odoo({"id": 100}),
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg"},
                "changes": {"x_price": 4000.0},
            },
        ]

        with patch("sync_model._download_image_base64", return_value="IMGDATA"):
            upd, crt = _apply_updates(conn, report)

        assert upd == 1
        call_args = listing_mock.write.call_args[0]
        assert call_args[0] == 100
        assert call_args[1]["x_price"] == 4000.0
        assert call_args[1]["x_studio_image"] == "IMGDATA"

    def test_update_skips_image_when_already_present(self):
        # no_image_ids is empty → entry 100 already has an image
        conn, gear_mock, listing_mock = self._mock_conn(no_image_ids=[])
        report = [
            {
                "action": "update",
                "entry": ListingRecord.from_odoo({"id": 100}),
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg"},
                "changes": {"x_price": 4000.0},
            },
        ]

        with patch("sync_model._download_image_base64") as mock_dl:
            upd, crt = _apply_updates(conn, report)

        assert upd == 1
        mock_dl.assert_not_called()
        call_args = listing_mock.write.call_args[0]
        assert "x_studio_image" not in call_args[1]

    def test_does_not_mutate_original_create_vals(self):
        conn, gear_mock, listing_mock = self._mock_conn(listing_create_return=500)
        original_vals = self._make_create_vals()
        report = [
            {
                "action": "create",
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg", "name": "G"},
                "create_vals": original_vals,
            },
        ]

        with patch("sync_model._download_image_base64", return_value="IMG"):
            _apply_updates(conn, report)

        # The original dict should not be mutated
        assert "x_studio_image" not in original_vals

    def test_does_not_mutate_original_changes(self):
        conn, gear_mock, listing_mock = self._mock_conn(no_image_ids=[100])
        original_changes = {"x_price": 4000.0}
        report = [
            {
                "action": "update",
                "entry": ListingRecord.from_odoo({"id": 100}),
                "reverb": {"photo_url": "https://img.reverb.com/photo.jpg"},
                "changes": original_changes,
            },
        ]

        with patch("sync_model._download_image_base64", return_value="IMG"):
            _apply_updates(conn, report)

        # The original dict should not be mutated
        assert "x_studio_image" not in original_changes


# ── _fetch_listings (mocked Odoo) ────────────────────────────────────────


class TestFetchListings:
    """Unit tests for _fetch_listings (cross-model URL lookup)."""

    def _mock_conn(self, listing_rows=None):
        conn = MagicMock()
        listing = MagicMock()
        listing.search_read.return_value = listing_rows or []
        conn.get_model.return_value = listing
        return conn, listing

    def test_no_extra_urls_uses_model_only_domain(self):
        conn, listing = self._mock_conn()
        _fetch_listings(conn, model_id=42)

        call_domain = listing.search_read.call_args[0][0]
        # Old behaviour: a plain ('x_model_id', '=', 42) domain.
        assert call_domain == [("x_model_id", "=", 42)]

    def test_extra_urls_unions_with_model_domain(self):
        conn, listing = self._mock_conn()
        urls = ["https://reverb.com/item/1-g", "https://reverb.com/item/2-g"]
        _fetch_listings(conn, model_id=42, extra_urls=urls)

        call_domain = listing.search_read.call_args[0][0]
        # OR(model_id=42, x_url in [...])  →  ['|', term1, term2]
        assert call_domain[0] == "|"
        assert ("x_model_id", "=", 42) in call_domain
        url_clause = next(t for t in call_domain if isinstance(t, tuple) and t[0] == "x_url")
        assert url_clause[1] == "in"
        assert set(url_clause[2]) == set(urls)

    def test_empty_extra_urls_still_uses_model_only_domain(self):
        conn, listing = self._mock_conn()
        _fetch_listings(conn, model_id=42, extra_urls=[])

        call_domain = listing.search_read.call_args[0][0]
        assert call_domain == [("x_model_id", "=", 42)]

    def test_returns_listing_records(self):
        conn, listing = self._mock_conn(
            listing_rows=[
                {"id": 1, "x_url": "https://reverb.com/item/1-g", "x_model_id": [42, "M"]},
            ]
        )
        result = _fetch_listings(conn, model_id=42)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].x_url == "https://reverb.com/item/1-g"
        assert result[0].x_model_id == (42, "M")

    def test_returns_cross_model_listing_records(self):
        conn, listing = self._mock_conn(
            listing_rows=[
                {"id": 1, "x_url": "https://reverb.com/item/1-g", "x_model_id": [42, "Mine"]},
                {"id": 2, "x_url": "https://reverb.com/item/2-g", "x_model_id": [99, "Other"]},
            ]
        )
        result = _fetch_listings(
            conn,
            model_id=42,
            extra_urls=["https://reverb.com/item/2-g"],
        )

        # The cross-model row's x_model_id must survive round-trip so the
        # caller can detect that the listing belongs to a different model.
        assert len(result) == 2
        by_id = {r.id: r for r in result}
        assert by_id[1].x_model_id == (42, "Mine")
        assert by_id[2].x_model_id == (99, "Other")


# ── PLATFORMS registry ────────────────────────────────────────────────────


def test_platforms_registry_has_reverb_and_ebay():
    from sync_model import PLATFORMS

    assert set(PLATFORMS.keys()) == {"reverb", "ebay"}
    assert callable(PLATFORMS["reverb"])
    assert callable(PLATFORMS["ebay"])


def test_listing_vals_from_scrape_tags_platform():
    from sync_model import _listing_vals_from_scrape

    scrape = {
        "url": "https://www.ebay.com/itm/123",
        "name": "Test eBay Listing",
        "price": "100.00",
        "shipping_price": "20.00",
        "sale_ended": False,
        "offers_enabled": False,
        "description": "",
        "published_at": "",
    }
    vals = _listing_vals_from_scrape(scrape, model_id=42, default_shipping=250.0, platform="ebay")
    assert vals["x_platform"] == "ebay"
    assert vals["x_url"] == "https://www.ebay.com/itm/123"
    assert vals["x_model_id"] == 42


def test_listing_vals_from_scrape_reverb_unchanged():
    from sync_model import _listing_vals_from_scrape

    scrape = {
        "url": "https://reverb.com/item/123-foo",
        "name": "Reverb Listing",
        "price": "100.00",
        "shipping_price": "20.00",
        "sale_ended": False,
        "offers_enabled": True,
        "description": "",
        "published_at": "2026-06-01",
    }
    vals = _listing_vals_from_scrape(scrape, model_id=42, default_shipping=250.0, platform="reverb")
    assert vals["x_platform"] == "reverb"
    assert vals["x_can_accept_offers"] is True


# ── _collect_sync_data platform routing ──────────────────────────────────


def test_collect_sync_data_runs_only_selected_platforms(monkeypatch):
    """`platforms=["reverb"]` must NOT invoke the eBay search at all."""
    from unittest.mock import MagicMock

    import sync_model

    fake_reverb = MagicMock(
        return_value=[
            {
                "url": "https://reverb.com/item/1-foo",
                "name": "Reverb 1",
                "price": "100",
                "sale_ended": False,
                "shipping_price": "10",
                "_platform": "reverb",
            }
        ]
    )
    fake_ebay = MagicMock(return_value=[])

    monkeypatch.setattr(sync_model, "PLATFORMS", {"reverb": fake_reverb, "ebay": fake_ebay})

    fake_conn = MagicMock()
    fake_listing = MagicMock()
    fake_listing.search_read.return_value = []
    fake_conn.get_model.return_value = fake_listing

    data = sync_model._collect_sync_data(
        fake_conn,
        model_id=1,
        model_name="Test",
        category_slug=None,
        default_shipping=250.0,
        platforms=["reverb"],
    )

    fake_reverb.assert_called_once()
    fake_ebay.assert_not_called()
    assert len(data["reverb_results"]) == 1


def test_collect_sync_data_runs_all_platforms_by_default(monkeypatch):
    from unittest.mock import MagicMock

    import sync_model

    fake_reverb = MagicMock(return_value=[])
    fake_ebay = MagicMock(return_value=[])
    monkeypatch.setattr(sync_model, "PLATFORMS", {"reverb": fake_reverb, "ebay": fake_ebay})

    fake_conn = MagicMock()
    fake_listing = MagicMock()
    fake_listing.search_read.return_value = []
    fake_conn.get_model.return_value = fake_listing

    sync_model._collect_sync_data(
        fake_conn,
        model_id=1,
        model_name="Test",
        category_slug=None,
        default_shipping=250.0,
        platforms=["reverb", "ebay"],
    )

    fake_reverb.assert_called_once()
    fake_ebay.assert_called_once()


def test_resolve_platforms_ebay_without_credentials_raises(monkeypatch):
    """Direct check: the platform filter resolution raises when ebay creds missing."""
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    from ebay_scraper import EbayAuth, EbayAuthError

    with pytest.raises(EbayAuthError, match="EBAY_CLIENT_ID"):
        EbayAuth.from_env()
