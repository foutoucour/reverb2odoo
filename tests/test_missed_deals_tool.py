"""Tests for odoo_mcp/tools/missed_deals.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models import ListingRecord, ModelsRecord
from odoo_mcp.tools.missed_deals import _format_got_away, _format_under_p25, run

# ── formatters ────────────────────────────────────────────────────────────────


def _listing(**kwargs: object) -> ListingRecord:
    base: dict = {"id": kwargs.pop("id", 1)}
    base.update(kwargs)
    return ListingRecord.from_odoo(base)


def _model(**kwargs: object) -> ModelsRecord:
    base: dict = {"id": kwargs.pop("id", 10)}
    base.update(kwargs)
    return ModelsRecord.from_odoo(base)


def test_format_under_p25_empty_says_so() -> None:
    lines = _format_under_p25([])
    assert any("No active listings priced below p25" in line for line in lines)


def test_format_under_p25_includes_model_and_gap() -> None:
    listing = _listing(
        x_price=1800.0,
        x_currency_id=[1, "CAD"],
        x_platform="reverb",
        x_url="https://reverb.com/item/abc",
        x_studio_listing_score=80,
    )
    model = _model(
        x_name="Les Paul Standard",
        x_studio_partner_id=[38, "Gibson"],
        x_price_p25=2200.0,
    )
    lines = _format_under_p25([(listing, model, 400.0)])
    blob = "\n".join(lines)
    assert "Les Paul Standard" in blob
    assert "Gibson" in blob
    assert "gap: 400" in blob


def test_format_got_away_empty_says_so() -> None:
    lines = _format_got_away({}, {})
    assert any("No closed/sold listings" in line for line in lines)


def test_format_got_away_lists_listings_per_model() -> None:
    model = _model(x_name="SG", x_studio_partner_id=[38, "Gibson"])
    listing = _listing(
        x_status="sold",
        x_price=1500.0,
        x_currency_id=[1, "CAD"],
        x_platform="reverb",
        x_published_at="2026-04-01",
        x_url="https://reverb.com/item/sold",
    )
    lines = _format_got_away({5: [listing]}, {5: model})
    blob = "\n".join(lines)
    assert "SG" in blob
    assert "Gibson" in blob
    assert "sold" in blob
    assert "1500.0 CAD" in blob


# ── run ───────────────────────────────────────────────────────────────────────


def _make_conn(
    *,
    wanna_models: list[dict] | None = None,
    owned_gear: list[dict] | None = None,
    watching_listings: list[dict] | None = None,
    missed_listings: list[dict] | None = None,
) -> MagicMock:
    """Build a mock conn where x_listing.search_read returns based on domain."""
    conn = MagicMock()
    models_proxy = MagicMock()
    gear_proxy = MagicMock()
    listing_proxy = MagicMock()

    models_proxy.search_read.return_value = wanna_models or []
    gear_proxy.search_read.return_value = owned_gear or []

    def listing_search_read(domain: list, fields: list) -> list[dict]:
        statuses: list = []
        for clause in domain:
            if isinstance(clause, tuple) and clause[0] == "x_status":
                statuses.append(clause)
        for clause in statuses:
            if clause[1] == "=" and clause[2] == "watching":
                return watching_listings or []
            if clause[1] == "in" and "sold" in clause[2]:
                return missed_listings or []
        return []

    listing_proxy.search_read.side_effect = listing_search_read

    def get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        if name == "x_gear":
            return gear_proxy
        return listing_proxy

    conn.get_model.side_effect = get_model
    return conn


def test_run_no_wanna_models_returns_notice() -> None:
    conn = _make_conn(wanna_models=[])
    result = run(conn)
    assert "No candidate models" in result
    assert "too_expensive=False" in result


def test_run_filters_candidate_domain() -> None:
    """Models domain must require wanna=True AND too_expensive=False."""
    conn = _make_conn(wanna_models=[])
    run(conn)
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert ("x_studio_wanna", "=", True) in domain
    assert ("x_studio_too_expensive", "=", False) in domain


def test_run_renders_both_sections_when_data_present() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_price_p25": 2200.0,
        "x_price_p50": 2500.0,
        "x_price_p75": 2800.0,
        "x_studio_wanna": True,
    }
    watching = {
        "id": 100,
        "x_model_id": [10, "Les Paul"],
        "x_status": "watching",
        "x_price": 1800.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_url": "https://reverb.com/item/cheap",
        "x_studio_listing_score": 90,
    }
    missed = {
        "id": 101,
        "x_model_id": [10, "Les Paul"],
        "x_status": "sold",
        "x_price": 2100.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_published_at": "2026-04-01",
        "x_url": "https://reverb.com/item/missed",
    }
    conn = _make_conn(
        wanna_models=[model],
        owned_gear=[],
        watching_listings=[watching],
        missed_listings=[missed],
    )
    result = run(conn, days_lookback=30)
    assert "## Got Away" in result
    assert "## Under-p25 Active Deals" in result
    assert "Les Paul" in result
    # gap = 2200 - 1800 = 400
    assert "gap: 400" in result


def test_run_excludes_models_user_already_owns_from_got_away() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_price_p25": 2200.0,
        "x_studio_wanna": True,
    }
    owned = {"id": 1, "x_model_id": [10, "Les Paul"]}
    missed = {
        "id": 99,
        "x_model_id": [10, "Les Paul"],
        "x_status": "sold",
        "x_price": 2100.0,
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_published_at": "2026-04-01",
        "x_url": "",
    }
    conn = _make_conn(
        wanna_models=[model],
        owned_gear=[owned],
        watching_listings=[],
        missed_listings=[missed],
    )
    result = run(conn)
    assert "No closed/sold listings" in result


def test_run_skips_listings_at_or_above_p25() -> None:
    model = {
        "id": 10,
        "x_name": "Les Paul",
        "x_studio_partner_id": [38, "Gibson"],
        "x_price_p25": 2200.0,
        "x_studio_wanna": True,
    }
    pricey = {
        "id": 200,
        "x_model_id": [10, "Les Paul"],
        "x_status": "watching",
        "x_price": 2200.0,  # equal to p25 — excluded
        "x_currency_id": [1, "CAD"],
        "x_platform": "reverb",
        "x_url": "",
        "x_studio_listing_score": 0,
    }
    conn = _make_conn(
        wanna_models=[model],
        watching_listings=[pricey],
        missed_listings=[],
    )
    result = run(conn)
    assert "No active listings priced below p25" in result


def test_run_negative_days_clamps_to_default() -> None:
    """Negative days_lookback should not raise."""
    conn = _make_conn(wanna_models=[])
    run(conn, days_lookback=-5)


# Keep pytest happy if no parametrize id collides.
@pytest.mark.parametrize(
    "value",
    [pytest.param(0.0, id="zero"), pytest.param(None, id="none")],
)
def test_listing_record_handles_empty_price(value: object) -> None:
    """Quick sanity check on the pydantic m2o coercion."""
    rec = ListingRecord.from_odoo({"id": 1, "x_price": value if value is not None else False})
    assert rec.x_price in (None, 0.0)
