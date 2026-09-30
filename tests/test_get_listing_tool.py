"""Tests for odoo_mcp/tools/get_listing.py."""

from unittest.mock import MagicMock

import pytest

from models import ListingRecord
from odoo_mcp.tools.get_listing import _render_listing_header, run


def _listing_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 100,
        "x_name": "Les Paul Standard listing",
        "x_model_id": [10, "Les Paul Standard"],
        "x_gear_id": [1, "2021 Gibson Les Paul Standard"],
        "x_platform": "reverb",
        "x_status": "watching",
        "x_price": 2500.0,
        "x_currency_id": [1, "CAD"],
        "x_studio_is_candidate": True,
        "x_studio_model_id_wanna": True,
        "x_studio_model_id_too_expensive": False,
    }
    base.update(overrides)
    return base


def _make_conn(rows: list[dict]) -> MagicMock:
    conn = MagicMock()
    conn.get_model.return_value.search_read.return_value = rows
    return conn


# ---------------------------------------------------------------------------
# _render_listing_header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, expected, absent",
    [
        pytest.param(
            {},
            ["# Les Paul Standard listing", "(id=10)", "**Gear**: 2021 Gibson Les Paul Standard"],
            None,
            id="with-gear",
        ),
        pytest.param({"x_gear_id": False}, ["(id=10)"], "**Gear**", id="without-gear"),
        pytest.param({"x_name": False}, ["# (unnamed)"], None, id="unnamed"),
    ],
)
def test_render_listing_header(overrides: dict, expected: list[str], absent: str | None) -> None:
    result = _render_listing_header(ListingRecord.from_odoo(_listing_dict(**overrides)))
    for fragment in expected:
        assert fragment in result
    if absent:
        assert absent not in result


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def test_run_returns_not_found_for_unknown_id() -> None:
    conn = _make_conn([])
    assert run(conn, 999) == "No listing found with id: **999**"


def test_run_queries_x_listing_including_archived() -> None:
    conn = _make_conn([_listing_dict()])
    run(conn, 100)
    conn.get_model.assert_called_with("x_listing")
    domain = conn.get_model.return_value.search_read.call_args[0][0]
    assert ("id", "=", 100) in domain
    assert ("x_active", "in", [True, False]) in domain


def test_run_renders_header_and_detail() -> None:
    conn = _make_conn([_listing_dict()])
    result = run(conn, 100)
    assert "# Les Paul Standard listing" in result
    assert "### Listing id=100 [watching] on reverb" in result
    assert "**Candidate**: yes" in result
    assert "**Model too expensive**: no" in result
