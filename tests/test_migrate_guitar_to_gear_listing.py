"""Tests for migrate_guitar_to_gear_listing."""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from migrate_guitar_to_gear_listing import (
    _STATUS_FIELD,
    _fetch_all_guitars,
    _fetch_existing_listing_urls,
    _guitar_to_gear_vals,
    _guitar_to_listing_vals,
    apply_plan,
    backfill_guitar_id,
    backfill_guitar_id_cli,
    cli,
    compute_plan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_guitar(
    id: int = 1,
    name: str = "Les Paul Standard",
    url: str = "https://reverb.com/item/123-les-paul",
    status: str = "Watched",
    price: float = 2000.0,
    shipping: float = 100.0,
    model_id: int | None = 42,
    currency_id: int | None = 5,
    published_at: str = "2024-01-15",
    is_available: bool = True,
    accept_offers: bool = False,
    taxed: bool = False,
) -> dict:
    return {
        "id": id,
        "x_name": name,
        "x_studio_url": url,
        _STATUS_FIELD: status,
        "x_studio_value": price,
        "x_studio_shipping": shipping,
        "x_studio_models": [model_id, "Some Model"] if model_id else False,
        "x_studio_currency_id": [currency_id, "CAD"] if currency_id else False,
        "x_studio_published_at": published_at,
        "x_studio_is_available": is_available,
        "x_studio_accept_offers": accept_offers,
        "x_studio_taxed": taxed,
    }


def _make_conn(guitars=None, existing_urls=None):
    """Build a mock connection for migration tests."""
    conn = MagicMock()

    guitar_mock = MagicMock()
    guitar_mock.search_read.return_value = guitars or []

    listing_mock = MagicMock()
    listing_mock.search_read.return_value = (
        [{"x_url": u} for u in existing_urls] if existing_urls else []
    )
    listing_mock.create.return_value = 500

    gear_mock = MagicMock()
    gear_mock.create.return_value = 999

    def get_model(name):
        if name == "x_guitar":
            return guitar_mock
        if name == "x_listing":
            return listing_mock
        if name == "x_gear":
            return gear_mock
        return MagicMock()

    conn.get_model.side_effect = get_model
    return conn, guitar_mock, listing_mock, gear_mock


# ---------------------------------------------------------------------------
# _guitar_to_listing_vals
# ---------------------------------------------------------------------------


class TestGuitarToListingVals:
    def test_watched_maps_to_watching(self):
        guitar = _make_guitar(status="Watched")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "watching"

    def test_not_interested_maps_to_passed(self):
        guitar = _make_guitar(status="Not Interested")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "passed"

    def test_bought_maps_to_acquired(self):
        guitar = _make_guitar(status="Bought")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "acquired"

    def test_for_sale_maps_to_acquired(self):
        guitar = _make_guitar(status="For Sale")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "acquired"

    def test_sold_maps_to_acquired(self):
        guitar = _make_guitar(status="Sold")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "acquired"

    def test_basic_fields_mapped(self):
        guitar = _make_guitar(
            name="LP Standard",
            url="https://reverb.com/item/1-lp",
            price=2500.0,
            shipping=150.0,
            is_available=True,
            accept_offers=True,
            taxed=True,
        )
        vals = _guitar_to_listing_vals(guitar)

        assert vals["x_name"] == "LP Standard"
        assert vals["x_url"] == "https://reverb.com/item/1-lp"
        assert vals["x_platform"] == "reverb"
        assert vals["x_price"] == 2500.0
        assert vals["x_shipping"] == 150.0
        assert vals["x_is_available"] is True
        assert vals["x_can_accept_offers"] is True
        assert vals["x_is_taxed"] is True
        assert vals["x_guitar_id"] == 1  # default id from _make_guitar

    def test_guitar_id_always_set(self):
        guitar = _make_guitar(id=99)
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_guitar_id"] == 99

    def test_model_id_extracted(self):
        guitar = _make_guitar(model_id=42)
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_model_id"] == 42

    def test_missing_model_id_omitted(self):
        guitar = _make_guitar(model_id=None)
        vals = _guitar_to_listing_vals(guitar)
        assert "x_model_id" not in vals

    def test_currency_id_extracted(self):
        guitar = _make_guitar(currency_id=5)
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_currency_id"] == 5

    def test_missing_currency_omitted(self):
        guitar = _make_guitar(currency_id=None)
        vals = _guitar_to_listing_vals(guitar)
        assert "x_currency_id" not in vals

    def test_published_at_included(self):
        guitar = _make_guitar(published_at="2024-03-10")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_published_at"] == "2024-03-10"

    def test_missing_published_at_omitted(self):
        guitar = _make_guitar(published_at="")
        vals = _guitar_to_listing_vals(guitar)
        assert "x_published_at" not in vals

    def test_unknown_status_defaults_to_watching(self):
        guitar = _make_guitar(status="Alien Status")
        vals = _guitar_to_listing_vals(guitar)
        assert vals["x_status"] == "watching"


# ---------------------------------------------------------------------------
# _guitar_to_gear_vals
# ---------------------------------------------------------------------------


class TestGuitarToGearVals:
    def test_bought_maps_to_owned(self):
        guitar = _make_guitar(status="Bought")
        vals = _guitar_to_gear_vals(guitar)
        assert vals["x_status"] == "owned"

    def test_for_sale_maps_to_owned(self):
        guitar = _make_guitar(status="For Sale")
        vals = _guitar_to_gear_vals(guitar)
        assert vals["x_status"] == "owned"

    def test_sold_maps_to_sold(self):
        guitar = _make_guitar(status="Sold")
        vals = _guitar_to_gear_vals(guitar)
        assert vals["x_status"] == "sold"

    def test_name_and_model_included(self):
        guitar = _make_guitar(name="LP Custom", model_id=7, status="Bought")
        vals = _guitar_to_gear_vals(guitar)
        assert vals["x_name"] == "LP Custom"
        assert vals["x_model_id"] == 7
        assert vals["x_intent"] == "unknown"

    def test_missing_model_id_omitted(self):
        guitar = _make_guitar(model_id=None, status="Bought")
        vals = _guitar_to_gear_vals(guitar)
        assert "x_model_id" not in vals

    def test_no_marketplace_fields(self):
        guitar = _make_guitar(status="Bought")
        vals = _guitar_to_gear_vals(guitar)
        assert "x_url" not in vals
        assert "x_price" not in vals
        assert "x_platform" not in vals


# ---------------------------------------------------------------------------
# _fetch_all_guitars
# ---------------------------------------------------------------------------


class TestFetchAllGuitars:
    def test_fetches_from_x_guitar(self):
        conn, guitar_mock, _, _ = _make_conn(guitars=[{"id": 1}])
        result = _fetch_all_guitars(conn)
        assert result == [{"id": 1}]
        conn.get_model.assert_called_with("x_guitar")

    def test_orders_by_id_asc(self):
        conn, guitar_mock, _, _ = _make_conn()
        _fetch_all_guitars(conn)
        call_kwargs = guitar_mock.search_read.call_args
        assert call_kwargs[1].get("order") == "id asc" or "id asc" in call_kwargs[0]


# ---------------------------------------------------------------------------
# _fetch_existing_listing_urls
# ---------------------------------------------------------------------------


class TestFetchExistingListingUrls:
    def test_returns_url_set(self):
        conn, _, listing_mock, _ = _make_conn(
            existing_urls=[
                "https://reverb.com/item/1-g",
                "https://reverb.com/item/2-g",
            ]
        )
        result = _fetch_existing_listing_urls(conn)
        assert result == {
            "https://reverb.com/item/1-g",
            "https://reverb.com/item/2-g",
        }

    def test_empty_when_no_listings(self):
        conn, _, listing_mock, _ = _make_conn(existing_urls=[])
        result = _fetch_existing_listing_urls(conn)
        assert result == set()


# ---------------------------------------------------------------------------
# compute_plan
# ---------------------------------------------------------------------------


class TestComputePlan:
    def test_all_guitars_migrated_when_no_existing_listings(self):
        guitars = [_make_guitar(id=1), _make_guitar(id=2, url="https://reverb.com/item/2-g")]
        conn, _, _, _ = _make_conn(guitars=guitars, existing_urls=[])

        to_migrate, already_migrated = compute_plan(conn)

        assert len(to_migrate) == 2
        assert already_migrated == 0

    def test_skips_guitars_with_existing_url(self):
        url = "https://reverb.com/item/1-lp"
        guitars = [
            _make_guitar(id=1, url=url),
            _make_guitar(id=2, url="https://reverb.com/item/2-g"),
        ]
        conn, _, _, _ = _make_conn(guitars=guitars, existing_urls=[url])

        to_migrate, already_migrated = compute_plan(conn)

        assert len(to_migrate) == 1
        assert to_migrate[0]["id"] == 2
        assert already_migrated == 1

    def test_empty_url_not_skipped(self):
        """Guitars without a URL are always included (can't match by URL)."""
        guitar = _make_guitar(id=1, url="")
        conn, _, _, _ = _make_conn(guitars=[guitar], existing_urls=[])

        to_migrate, _ = compute_plan(conn)

        assert len(to_migrate) == 1


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    def test_creates_listing_for_watched(self):
        conn, _, listing_mock, gear_mock = _make_conn()
        guitars = [_make_guitar(status="Watched")]

        listing_created, gear_created = apply_plan(conn, guitars, dry_run=False)

        assert listing_created == 1
        assert gear_created == 0
        listing_mock.create.assert_called_once()
        gear_mock.create.assert_not_called()

    def test_creates_listing_for_not_interested(self):
        conn, _, listing_mock, gear_mock = _make_conn()
        guitars = [_make_guitar(status="Not Interested")]

        listing_created, gear_created = apply_plan(conn, guitars, dry_run=False)

        assert listing_created == 1
        assert gear_created == 0
        gear_mock.create.assert_not_called()

    def test_creates_listing_and_gear_for_bought(self):
        conn, _, listing_mock, gear_mock = _make_conn()
        listing_mock.create.return_value = 500
        gear_mock.create.return_value = 999
        guitars = [_make_guitar(status="Bought")]

        listing_created, gear_created = apply_plan(conn, guitars, dry_run=False)

        assert listing_created == 1
        assert gear_created == 1
        listing_mock.create.assert_called_once()
        gear_mock.create.assert_called_once()

    def test_gear_linked_to_listing(self):
        conn, _, listing_mock, gear_mock = _make_conn()
        listing_mock.create.return_value = 500
        gear_mock.create.return_value = 999
        guitars = [_make_guitar(status="Bought")]

        apply_plan(conn, guitars, dry_run=False)

        # x_listing.x_gear_id set after gear created
        listing_mock.write.assert_called_once_with([500], {"x_gear_id": 999})
        # x_gear created with listing linked via x_listing_ids
        gear_vals = gear_mock.create.call_args[0][0]
        assert gear_vals["x_listing_ids"] == [(4, 500)]

    @pytest.mark.parametrize(
        "status, expected_gear_status",
        [
            pytest.param("Bought", "owned", id="bought"),
            pytest.param("For Sale", "owned", id="for-sale"),
            pytest.param("Sold", "sold", id="sold"),
        ],
    )
    def test_gear_status_mapping(self, status, expected_gear_status):
        conn, _, listing_mock, gear_mock = _make_conn()
        guitars = [_make_guitar(status=status)]

        apply_plan(conn, guitars, dry_run=False)

        gear_vals = gear_mock.create.call_args[0][0]
        assert gear_vals["x_status"] == expected_gear_status

    def test_dry_run_creates_nothing(self):
        conn, _, listing_mock, gear_mock = _make_conn()
        guitars = [_make_guitar(status="Bought"), _make_guitar(id=2, status="Watched")]

        listing_created, gear_created = apply_plan(conn, guitars, dry_run=True)

        listing_mock.create.assert_not_called()
        gear_mock.create.assert_not_called()
        assert listing_created == 2
        assert gear_created == 1

    def test_listing_status_set_correctly(self):
        conn, _, listing_mock, _ = _make_conn()
        guitars = [_make_guitar(status="Not Interested")]

        apply_plan(conn, guitars, dry_run=False)

        vals = listing_mock.create.call_args[0][0]
        assert vals["x_status"] == "passed"

    def test_empty_list_creates_nothing(self):
        conn, _, listing_mock, gear_mock = _make_conn()

        listing_created, gear_created = apply_plan(conn, [], dry_run=False)

        assert listing_created == 0
        assert gear_created == 0
        listing_mock.create.assert_not_called()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestMigrateCli:
    runner = CliRunner()

    def _invoke(self, args, conn):
        return self.runner.invoke(cli, args, obj={"conn": conn})

    def test_dry_run_default(self):
        conn, _, listing_mock, gear_mock = _make_conn(guitars=[_make_guitar()], existing_urls=[])
        result = self._invoke([], conn)
        assert result.exit_code == 0
        listing_mock.create.assert_not_called()

    def test_apply_creates_records(self):
        conn, _, listing_mock, gear_mock = _make_conn(
            guitars=[_make_guitar(status="Watched")], existing_urls=[]
        )
        result = self._invoke(["--apply"], conn)
        assert result.exit_code == 0
        listing_mock.create.assert_called_once()

    def test_nothing_to_migrate(self):
        url = "https://reverb.com/item/1-lp"
        conn, _, listing_mock, gear_mock = _make_conn(
            guitars=[_make_guitar(url=url)], existing_urls=[url]
        )
        result = self._invoke(["--apply"], conn)
        assert result.exit_code == 0
        listing_mock.create.assert_not_called()
        gear_mock.create.assert_not_called()

    def test_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--apply" in result.output


# ---------------------------------------------------------------------------
# backfill_guitar_id
# ---------------------------------------------------------------------------


def _make_backfill_conn(missing_listings=None, guitars=None):
    """Build a mock connection for backfill tests."""
    conn = MagicMock()

    listing_mock = MagicMock()
    listing_mock.search_read.return_value = missing_listings or []

    guitar_mock = MagicMock()
    guitar_mock.search_read.return_value = guitars or []

    def get_model(name):
        if name == "x_listing":
            return listing_mock
        if name == "x_guitar":
            return guitar_mock
        return MagicMock()

    conn.get_model.side_effect = get_model
    return conn, listing_mock, guitar_mock


class TestBackfillGuitarId:
    def test_nothing_to_do_when_all_set(self):
        conn, listing_mock, _ = _make_backfill_conn(missing_listings=[])
        result = backfill_guitar_id(conn, dry_run=False)
        assert result == 0
        listing_mock.write.assert_not_called()

    def test_matches_by_url_and_writes(self):
        url = "https://reverb.com/item/1-lp"
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[{"id": 10, "x_url": url}],
            guitars=[{"id": 42, "x_studio_url": url}],
        )
        result = backfill_guitar_id(conn, dry_run=False)
        assert result == 1
        listing_mock.write.assert_called_once_with([10], {"x_guitar_id": 42})

    def test_dry_run_does_not_write(self):
        url = "https://reverb.com/item/1-lp"
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[{"id": 10, "x_url": url}],
            guitars=[{"id": 42, "x_studio_url": url}],
        )
        result = backfill_guitar_id(conn, dry_run=True)
        assert result == 1
        listing_mock.write.assert_not_called()

    def test_unmatched_url_is_skipped(self):
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[{"id": 10, "x_url": "https://reverb.com/item/1-lp"}],
            guitars=[{"id": 42, "x_studio_url": "https://reverb.com/item/99-other"}],
        )
        result = backfill_guitar_id(conn, dry_run=False)
        assert result == 0
        listing_mock.write.assert_not_called()

    def test_multiple_listings_matched(self):
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[
                {"id": 10, "x_url": "https://reverb.com/item/1-a"},
                {"id": 11, "x_url": "https://reverb.com/item/2-b"},
            ],
            guitars=[
                {"id": 1, "x_studio_url": "https://reverb.com/item/1-a"},
                {"id": 2, "x_studio_url": "https://reverb.com/item/2-b"},
            ],
        )
        result = backfill_guitar_id(conn, dry_run=False)
        assert result == 2
        assert listing_mock.write.call_count == 2


class TestBackfillGuitarIdCli:
    runner = CliRunner()

    def _invoke(self, args, conn):
        return self.runner.invoke(backfill_guitar_id_cli, args, obj={"conn": conn})

    def test_dry_run_default_does_not_write(self):
        url = "https://reverb.com/item/1-lp"
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[{"id": 10, "x_url": url}],
            guitars=[{"id": 42, "x_studio_url": url}],
        )
        result = self._invoke([], conn)
        assert result.exit_code == 0
        listing_mock.write.assert_not_called()

    def test_apply_writes(self):
        url = "https://reverb.com/item/1-lp"
        conn, listing_mock, _ = _make_backfill_conn(
            missing_listings=[{"id": 10, "x_url": url}],
            guitars=[{"id": 42, "x_studio_url": url}],
        )
        result = self._invoke(["--apply"], conn)
        assert result.exit_code == 0
        listing_mock.write.assert_called_once_with([10], {"x_guitar_id": 42})
