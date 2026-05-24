"""Tests for odoo_mcp/resources/watchlist.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models import ListingRecord, ModelsRecord
from odoo_mcp.resources.watchlist import _label, _render_listing, _render_model, _scalar, render

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(
    models: list[dict],
    listings: list[dict],
) -> MagicMock:
    """Build a mock odoolib connection returning given models and listings."""
    conn = MagicMock()

    models_proxy = MagicMock()
    models_proxy.search_read.return_value = models

    listings_proxy = MagicMock()
    listings_proxy.search_read.return_value = listings

    def _get_model(name: str) -> MagicMock:
        if name == "x_models":
            return models_proxy
        if name == "x_listing":
            return listings_proxy
        raise ValueError(f"Unexpected model: {name}")

    conn.get_model.side_effect = _get_model
    return conn


def _make_model_dict(
    mid: int = 1,
    name: str = "LP Standard",
    brand: list | bool | None = None,
    model_type: str = "solidbody",
    scale: str = "24.75",
    neck_feel: list | bool | None = None,
    p25: float = 1200.0,
    p50: float = 1500.0,
    p75: float = 1800.0,
) -> dict:
    """Raw dict that the mock Odoo connection would return."""
    if brand is None:
        brand = [38, "Gibson"]
    if neck_feel is None:
        neck_feel = [5, "SlimTaper"]
    return {
        "id": mid,
        "x_name": name,
        "x_studio_partner_id": brand,
        "x_studio_model_type": model_type,
        "x_studio_wanna": True,
        "x_studio_guitar_familly_ids": [1],
        "x_studio_guitar_neck_feel_id": neck_feel,
        "x_studio_scale": scale,
        "x_studio_finish": [3, "Gloss"],
        "x_studio_fretboard_1": [7, "Rosewood"],
        "x_price_p25": p25,
        "x_price_p50": p50,
        "x_price_p75": p75,
    }


def _make_model(**kwargs) -> ModelsRecord:
    return ModelsRecord.from_odoo(_make_model_dict(**kwargs))


def _make_listing_dict(
    lid: int = 10,
    model_id: int = 1,
    listing_score: float | bool = 88.5,
    price_score: float | bool = 72.0,
    price: float = 1350.0,
    currency: list | bool | None = None,
    platform: str = "reverb",
    url: str = "https://reverb.com/item/12345-lp-standard",
    notes: str | bool = False,
    status: str = "watching",
) -> dict:
    if currency is None:
        currency = [1, "CAD"]
    return {
        "id": lid,
        "x_name": f"Listing {lid}",
        "x_model_id": [model_id, "LP Standard"],
        "x_url": url,
        "x_platform": platform,
        "x_price": price,
        "x_currency_id": currency,
        "x_shipping": False,
        "x_condition": "excellent",
        "x_status": status,
        "x_is_available": True,
        "x_can_accept_offers": True,
        "x_is_taxed": False,
        "x_published_at": False,
        "x_gear_id": False,
        "x_studio_listing_score": listing_score,
        "x_studio_price_score": price_score,
        "x_studio_notes": notes,
    }


def _make_listing(**kwargs) -> ListingRecord:
    return ListingRecord.from_odoo(_make_listing_dict(**kwargs))


# ---------------------------------------------------------------------------
# Unit tests: _label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param((38, "Gibson"), "Gibson", id="many2one-tuple"),
        pytest.param(None, "", id="none-returns-empty"),
    ],
)
def test_label(value: object, expected: str) -> None:
    assert _label(value) == expected  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Unit tests: _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("solidbody", "", "solidbody", id="string-value"),
        pytest.param(1500.0, "", "1500.0", id="float-value"),
        pytest.param(False, "", "", id="false-uses-fallback"),
        pytest.param(None, "n/a", "n/a", id="none-uses-custom-fallback"),
        pytest.param(0, "", "0", id="zero-is-truthy-enough"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# Unit tests: _render_listing
# ---------------------------------------------------------------------------


def test_render_listing_full() -> None:
    listing = _make_listing(
        listing_score=90.0,
        price_score=75.0,
        notes="Frets worn",
    )
    result = _render_listing(listing)

    assert "[score:90.0 price:75.0]" in result
    assert "1350.0 CAD on reverb" in result
    assert "https://reverb.com/item/12345-lp-standard" in result
    assert "Notes: Frets worn" in result


def test_render_listing_omits_notes_when_false() -> None:
    listing = _make_listing(notes=False)
    result = _render_listing(listing)
    assert "Notes:" not in result


def test_render_listing_omits_notes_when_empty_string() -> None:
    listing = _make_listing(notes="")
    result = _render_listing(listing)
    assert "Notes:" not in result


def test_render_listing_score_defaults_to_zero_when_false() -> None:
    listing = _make_listing(listing_score=False, price_score=False)
    result = _render_listing(listing)
    assert "[score:0 price:0]" in result


# ---------------------------------------------------------------------------
# Unit tests: _render_model
# ---------------------------------------------------------------------------


def test_render_model_no_listings_shows_placeholder() -> None:
    model = _make_model()
    result = _render_model(model, [])

    assert "## LP Standard — Gibson" in result
    assert "No listings tracked" in result
    assert "### Watching (0 listings)" in result


def test_render_model_listings_sorted_by_score_descending() -> None:
    model = _make_model(mid=1)
    listings = [
        _make_listing(lid=1, listing_score=50.0),
        _make_listing(lid=2, listing_score=90.0),
        _make_listing(lid=3, listing_score=70.0),
    ]
    result = _render_model(model, listings)

    pos_90 = result.index("score:90.0")
    pos_70 = result.index("score:70.0")
    pos_50 = result.index("score:50.0")
    assert pos_90 < pos_70 < pos_50


def test_render_model_shows_brackets() -> None:
    model = _make_model(p25=1100.0, p50=1400.0, p75=1700.0)
    result = _render_model(model, [])
    assert "**Brackets**: p25=1100.0 p50=1400.0 p75=1700.0" in result


def test_render_model_shows_metadata() -> None:
    model = _make_model(model_type="solidbody", scale="24.75", neck_feel=[5, "SlimTaper"])
    result = _render_model(model, [])
    assert "**Type**: solidbody | **Scale**: 24.75 | **Neck**: SlimTaper" in result


def test_render_model_listing_count_in_header() -> None:
    model = _make_model(mid=1)
    listings = [_make_listing(lid=i, listing_score=float(i)) for i in range(3)]
    result = _render_model(model, listings)
    assert "### Watching (3 listings, best first)" in result


# ---------------------------------------------------------------------------
# Integration tests: render()
# ---------------------------------------------------------------------------


def test_render_returns_markdown_header() -> None:
    conn = _make_conn(models=[], listings=[])
    result = render(conn)
    assert "# Watchlist" in result


def test_render_no_wanna_models() -> None:
    conn = _make_conn(models=[], listings=[])
    result = render(conn)
    assert "No models on the watchlist." in result


def test_render_queries_x_models_with_wanna_true() -> None:
    conn = _make_conn(models=[], listings=[])
    render(conn)
    models_proxy = conn.get_model("x_models")
    domain = models_proxy.search_read.call_args[0][0]
    assert ("x_studio_wanna", "=", True) in domain


def test_render_does_not_query_listings_when_no_models() -> None:
    conn = _make_conn(models=[], listings=[])
    render(conn)
    # x_listing should never be queried when there are no wanna models
    listing_proxy_calls = [
        call for call in conn.get_model.call_args_list if call[0][0] == "x_listing"
    ]
    assert len(listing_proxy_calls) == 0


def test_render_queries_listings_for_correct_model_ids() -> None:
    model_a = _make_model_dict(mid=10)
    model_b = _make_model_dict(mid=20, name="SG Standard")
    conn = _make_conn(models=[model_a, model_b], listings=[])

    render(conn)

    listing_proxy = conn.get_model("x_listing")
    domain = listing_proxy.search_read.call_args[0][0]
    model_id_filter = next(c for c in domain if c[0] == "x_model_id")
    assert set(model_id_filter[2]) == {10, 20}

    status_filter = next(c for c in domain if c[0] == "x_status")
    assert status_filter == ("x_status", "=", "watching")


def test_render_assigns_listings_to_correct_model() -> None:
    model_a = _make_model_dict(mid=1, name="LP Standard")
    model_b = _make_model_dict(mid=2, name="SG Standard")
    listing_a = _make_listing_dict(lid=10, model_id=1, listing_score=80.0)
    listing_b = _make_listing_dict(lid=20, model_id=2, listing_score=60.0)

    conn = _make_conn(models=[model_a, model_b], listings=[listing_a, listing_b])
    result = render(conn)

    # Each section should exist and contain its listing score
    lp_idx = result.index("## LP Standard")
    sg_idx = result.index("## SG Standard")
    score80_idx = result.index("score:80.0")
    score60_idx = result.index("score:60.0")

    assert lp_idx < score80_idx < sg_idx
    assert sg_idx < score60_idx


def test_render_model_with_no_listings_shows_placeholder() -> None:
    model = _make_model_dict(mid=1, name="LP Standard")
    conn = _make_conn(models=[model], listings=[])
    result = render(conn)
    assert "No listings tracked" in result


def test_render_listing_false_score_treated_as_zero() -> None:
    model = _make_model_dict(mid=1)
    listing = _make_listing_dict(lid=1, listing_score=False)
    conn = _make_conn(models=[model], listings=[listing])
    result = render(conn)
    assert "score:0" in result


def test_render_output_ends_with_newline() -> None:
    conn = _make_conn(models=[], listings=[])
    result = render(conn)
    assert result.endswith("\n")
