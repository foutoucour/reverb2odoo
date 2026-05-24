"""Tests for odoo_mcp/tools/pending_decisions.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.tools.pending_decisions import _is_untriaged, run

# ── _is_untriaged ─────────────────────────────────────────────────────────────


def _base_listing(**overrides: object) -> dict:
    base: dict = {
        "x_is_too_expensive": False,
        "x_gear_id": False,
        "x_studio_notes": False,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "listing, expected",
    [
        pytest.param(_base_listing(), True, id="clean-listing-is-untriaged"),
        pytest.param(_base_listing(x_is_too_expensive=True), False, id="too-expensive-is-triaged"),
        pytest.param(_base_listing(x_gear_id=[5, "Foo"]), False, id="linked-gear-is-triaged"),
        pytest.param(_base_listing(x_studio_notes="checked"), False, id="notes-is-triaged"),
        pytest.param(_base_listing(x_studio_notes="   "), True, id="whitespace-notes-untriaged"),
    ],
)
def test_is_untriaged(listing: dict, expected: bool) -> None:
    assert _is_untriaged(listing) is expected


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(
    *,
    wanna_models: list[dict] | None = None,
    listings: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    models_proxy = MagicMock()
    listing_proxy = MagicMock()

    models_proxy.search_read.return_value = wanna_models or []
    listing_proxy.search_read.return_value = listings or []

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        return listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_no_wanna_models_returns_notice() -> None:
    conn = _make_conn(wanna_models=[])
    result = run(conn)
    assert "No models marked `wanna=True`" in result


def test_run_inbox_zero_when_no_pending() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_wanna": True,
        "x_studio_p50": 2200.0,
    }
    triaged = {
        "id": 100,
        "x_model_id": [10, "Les Paul"],
        "x_status": "watching",
        "x_price": 1800.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_condition": "excellent",
        "x_published_at": "2026-05-01",
        "x_url": "",
        "x_studio_listing_score": 80,
        "x_studio_price_score": 75,
        "x_studio_notes": False,
        "x_is_too_expensive": True,  # triaged
        "x_gear_id": False,
    }
    conn = _make_conn(wanna_models=[model], listings=[triaged])
    result = run(conn)
    assert "Inbox zero" in result


def test_run_lists_pending_with_model_and_brand() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_wanna": True,
        "x_studio_p50": 2200.0,
    }
    pending = {
        "id": 100,
        "x_model_id": [10, "Les Paul"],
        "x_status": "watching",
        "x_price": 1800.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_condition": "excellent",
        "x_published_at": "2026-05-01",
        "x_url": "https://reverb.com/item/abc",
        "x_studio_listing_score": 80,
        "x_studio_price_score": 75,
        "x_studio_notes": False,
        "x_is_too_expensive": False,
        "x_gear_id": False,
    }
    conn = _make_conn(wanna_models=[model], listings=[pending])
    result = run(conn)
    assert "Les Paul" in result
    assert "Gibson" in result
    assert "1800.0 CAD" in result


def test_run_sorts_by_listing_score_desc() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_wanna": True,
        "x_studio_p50": 2200.0,
    }

    def _listing(**kw: object) -> dict:
        base = {
            "id": kw.get("id", 1),
            "x_model_id": [10, "Les Paul"],
            "x_status": "watching",
            "x_price": kw.get("price", 1800.0),
            "x_currency_id": [1, "CAD"],
            "x_platform": "reverb",
            "x_condition": "excellent",
            "x_published_at": "2026-05-01",
            "x_url": f"https://reverb.com/item/{kw.get('id', 1)}",
            "x_studio_listing_score": kw.get("score", 0),
            "x_studio_price_score": 0,
            "x_studio_notes": False,
            "x_is_too_expensive": False,
            "x_gear_id": False,
        }
        return base

    low = _listing(id=1, score=50)
    high = _listing(id=2, score=90)
    conn = _make_conn(wanna_models=[model], listings=[low, high])
    result = run(conn)
    # high score listing's URL should appear before low score's URL
    assert result.index("/item/2") < result.index("/item/1")
