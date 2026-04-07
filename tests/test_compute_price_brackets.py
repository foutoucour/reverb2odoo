"""Tests for compute_price_brackets._compute_brackets() and supporting helpers."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from compute_price_brackets import (
    _MIN_RECENT,
    _compute_brackets,
    _fetch_listing_prices_for_model,
    _fetch_models,
    run_computation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _recent_date(days_ago: int = 30) -> str:
    """Return an Odoo-formatted datetime string within the sliding window."""
    dt = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _old_date(days_ago: int = 400) -> str:
    """Return an Odoo-formatted datetime string outside the sliding window."""
    dt = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# _compute_brackets — empty / single-price edge cases
# ---------------------------------------------------------------------------


class TestComputeBracketsEdgeCases:
    def test_empty_input_returns_none(self):
        assert _compute_brackets([]) is None

    def test_single_price_no_date_returns_same_value_for_all_percentiles(self):
        result = _compute_brackets([(500.0, None)])
        assert result is not None
        assert result["p25"] == 500.0
        assert result["p50"] == 500.0
        assert result["p75"] == 500.0
        assert result["sample_size"] == 1

    def test_single_price_with_recent_date_returns_same_value_for_all_percentiles(self):
        result = _compute_brackets([(500.0, _recent_date())])
        assert result is not None
        assert result["p25"] == 500.0
        assert result["p50"] == 500.0
        assert result["p75"] == 500.0
        assert result["sample_size"] == 1


# ---------------------------------------------------------------------------
# _compute_brackets — window selection
# ---------------------------------------------------------------------------


class TestComputeBracketsWindowSelection:
    def test_uses_recent_window_when_enough_recent_prices(self):
        recent_prices = [(float(p), _recent_date()) for p in range(100, 100 + _MIN_RECENT)]
        old_prices = [(9999.0, _old_date())]
        result = _compute_brackets(recent_prices + old_prices)
        assert result is not None
        assert result["used_window"] is True
        # 9999 (old outlier) should not affect the result
        assert result["p75"] < 9999.0

    def test_falls_back_to_all_time_when_too_few_recent_prices(self):
        recent_prices = [(float(p), _recent_date()) for p in range(100, 100 + _MIN_RECENT - 1)]
        old_prices = [(float(p), _old_date()) for p in range(200, 210)]
        result = _compute_brackets(recent_prices + old_prices)
        assert result is not None
        assert result["used_window"] is False

    def test_falls_back_to_all_time_when_no_dates(self):
        prices = [(float(p), None) for p in range(100, 110)]
        result = _compute_brackets(prices)
        assert result is not None
        assert result["used_window"] is False

    def test_malformed_date_string_is_skipped_gracefully(self):
        prices = [
            (100.0, "not-a-date"),
            (200.0, "also-bad"),
            (300.0, None),
        ]
        # Should not raise; falls back to all-time
        result = _compute_brackets(prices)
        assert result is not None
        assert result["used_window"] is False
        assert result["sample_size"] == 3

    def test_exactly_min_recent_prices_uses_window(self):
        recent_prices = [(float(p), _recent_date()) for p in range(100, 100 + _MIN_RECENT)]
        result = _compute_brackets(recent_prices)
        assert result is not None
        assert result["used_window"] is True

    def test_one_fewer_than_min_recent_uses_all_time(self):
        recent_prices = [(float(p), _recent_date()) for p in range(100, 100 + _MIN_RECENT - 1)]
        result = _compute_brackets(recent_prices)
        assert result is not None
        assert result["used_window"] is False


# ---------------------------------------------------------------------------
# _compute_brackets — percentile correctness
# ---------------------------------------------------------------------------


class TestComputeBracketsPercentiles:
    @pytest.mark.parametrize(
        "prices, expected_p50",
        [
            pytest.param([100.0, 200.0, 300.0, 400.0], 250.0, id="four-symmetric-prices"),
            pytest.param(
                [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 80.0, 100.0], 45.0, id="eight-prices"
            ),
        ],
    )
    def test_percentile_values(self, prices: list[float], expected_p50: float):
        data = [(p, None) for p in prices]
        result = _compute_brackets(data)
        assert result is not None
        assert result["p25"] <= result["p50"] <= result["p75"]
        assert result["p50"] == expected_p50

    def test_sample_size_reflects_chosen_window(self):
        recent_prices = [(float(p), _recent_date()) for p in range(100, 100 + _MIN_RECENT)]
        old_prices = [(9999.0, _old_date()), (9998.0, _old_date())]
        result = _compute_brackets(recent_prices + old_prices)
        assert result is not None
        assert result["used_window"] is True
        assert result["sample_size"] == _MIN_RECENT

    def test_all_time_sample_size(self):
        prices = [(float(p), None) for p in range(10)]
        result = _compute_brackets(prices)
        assert result is not None
        assert result["sample_size"] == 10


# ---------------------------------------------------------------------------
# _fetch_models — includes id field
# ---------------------------------------------------------------------------


class TestFetchModels:
    def test_returns_id_in_requested_fields(self):
        conn = MagicMock()
        x_models_mock = MagicMock()
        x_models_mock.search_read.return_value = [{"id": 1, "x_name": "LP Standard"}]
        conn.get_model.return_value = x_models_mock

        _fetch_models(conn)

        call_args = x_models_mock.search_read.call_args
        fields = call_args[0][1]
        assert "id" in fields
        assert "x_name" in fields

    def test_filters_by_model_name_when_provided(self):
        conn = MagicMock()
        x_models_mock = MagicMock()
        x_models_mock.search_read.return_value = []
        conn.get_model.return_value = x_models_mock

        _fetch_models(conn, model_name="Les Paul")

        call_args = x_models_mock.search_read.call_args
        domain = call_args[0][0]
        assert domain == [("x_name", "ilike", "Les Paul")]

    def test_empty_domain_when_no_filter(self):
        conn = MagicMock()
        x_models_mock = MagicMock()
        x_models_mock.search_read.return_value = []
        conn.get_model.return_value = x_models_mock

        _fetch_models(conn)

        call_args = x_models_mock.search_read.call_args
        domain = call_args[0][0]
        assert domain == []


# ---------------------------------------------------------------------------
# _fetch_listing_prices_for_model — uses x_price field
# ---------------------------------------------------------------------------


class TestFetchListingPricesForModel:
    def test_uses_x_price_field(self):
        conn = MagicMock()
        listing_mock = MagicMock()
        listing_mock.search_read.return_value = [
            {"x_price": 1500.0, "x_published_at": "2024-01-01 00:00:00"},
        ]
        conn.get_model.return_value = listing_mock

        result = _fetch_listing_prices_for_model(conn, model_id=1)

        call_args = listing_mock.search_read.call_args
        domain = call_args[0][0]
        fields = call_args[0][1]

        assert ("x_price", ">", 0) in domain
        assert "x_price" in fields
        assert "x_studio_taxed_price" not in fields
        assert result == [(1500.0, "2024-01-01 00:00:00")]

    def test_missing_published_at_returns_none(self):
        conn = MagicMock()
        listing_mock = MagicMock()
        listing_mock.search_read.return_value = [{"x_price": 800.0}]
        conn.get_model.return_value = listing_mock

        result = _fetch_listing_prices_for_model(conn, model_id=1)

        assert result == [(800.0, None)]


# ---------------------------------------------------------------------------
# run_computation — integration (mocked Odoo)
# ---------------------------------------------------------------------------


class TestRunComputation:
    def _make_conn(self, models, prices_by_model_id):
        conn = MagicMock()
        x_models_mock = MagicMock()
        x_models_mock.search_read.return_value = models

        listing_mock = MagicMock()

        def _listing_search_read(domain, fields, **kwargs):
            model_id = next((v for field, _op, v in domain if field == "x_model_id"), None)
            return [
                {"x_price": p, "x_published_at": d} for p, d in prices_by_model_id.get(model_id, [])
            ]

        listing_mock.search_read.side_effect = _listing_search_read

        def get_model(name):
            if name == "x_models":
                return x_models_mock
            if name == "x_listing":
                return listing_mock
            return MagicMock()

        conn.get_model.side_effect = get_model
        return conn, x_models_mock

    def test_skips_models_with_no_price_data(self):
        conn, x_models_mock = self._make_conn(
            models=[{"id": 1, "x_name": "LP Standard"}],
            prices_by_model_id={},
        )
        run_computation(conn)
        x_models_mock.write.assert_not_called()

    def test_writes_brackets_when_data_available(self):
        prices = [(float(p), None) for p in range(100, 110)]
        conn, x_models_mock = self._make_conn(
            models=[{"id": 1, "x_name": "LP Standard"}],
            prices_by_model_id={1: prices},
        )
        run_computation(conn)
        x_models_mock.write.assert_called_once()
        write_vals = x_models_mock.write.call_args[0][1]
        assert "x_price_p25" in write_vals
        assert "x_price_p50" in write_vals
        assert "x_price_p75" in write_vals
        assert "x_price_sample_size" in write_vals
        assert "x_price_updated_at" in write_vals

    def test_dry_run_does_not_write(self):
        prices = [(float(p), None) for p in range(100, 110)]
        conn, x_models_mock = self._make_conn(
            models=[{"id": 1, "x_name": "LP Standard"}],
            prices_by_model_id={1: prices},
        )
        run_computation(conn, dry_run=True)
        x_models_mock.write.assert_not_called()

    def test_no_models_logs_warning_and_returns(self):
        conn, x_models_mock = self._make_conn(models=[], prices_by_model_id={})
        run_computation(conn)
        x_models_mock.write.assert_not_called()
