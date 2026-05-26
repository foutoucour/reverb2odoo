"""Tests for odoo_mcp/tools/search_models.py."""

from unittest.mock import MagicMock

import pytest

from models import ModelsRecord
from odoo_mcp.tools.search_models import (
    _DEFAULT_LIMIT,
    _label,
    _render_card,
    _resolve_order,
    _scalar,
    run,
)

# ---------------------------------------------------------------------------
# _label / _scalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        pytest.param((10, "Gibson"), "Gibson", id="valid-m2o"),
        pytest.param(None, "", id="none-m2o"),
    ],
)
def test_label(field: object, expected: str) -> None:
    assert _label(field) == expected


@pytest.mark.parametrize(
    "value, fallback, expected",
    [
        pytest.param("Les Paul", "", "Les Paul", id="string-value"),
        pytest.param(False, "", "", id="false-no-fallback"),
        pytest.param(None, "n/a", "n/a", id="none-with-fallback"),
        pytest.param(0, "", "0", id="zero-stringified"),
    ],
)
def test_scalar(value: object, fallback: str, expected: str) -> None:
    assert _scalar(value, fallback) == expected


# ---------------------------------------------------------------------------
# _resolve_order
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sort_by, expected_key, expected_order",
    [
        pytest.param(
            "weighted_score",
            "weighted_score",
            "x_studio_weighted_score desc",
            id="weighted-score-desc",
        ),
        pytest.param("p50", "p50", "x_price_p50 desc", id="p50-desc"),
        pytest.param("name", "name", "x_name asc", id="name-asc"),
        pytest.param(
            "",
            "weighted_score",
            "x_studio_weighted_score desc",
            id="empty-defaults-to-weighted-score",
        ),
        pytest.param(
            "unknown_key",
            "weighted_score",
            "x_studio_weighted_score desc",
            id="unknown-defaults-to-weighted-score",
        ),
        pytest.param(
            "Weighted_Score",
            "weighted_score",
            "x_studio_weighted_score desc",
            id="case-insensitive",
        ),
    ],
)
def test_resolve_order(sort_by: str, expected_key: str, expected_order: str) -> None:
    key, order = _resolve_order(sort_by)
    assert key == expected_key
    assert order == expected_order


# ---------------------------------------------------------------------------
# _render_card
# ---------------------------------------------------------------------------


def _model_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "Les Paul Standard",
        "x_active": True,
        "x_studio_partner_id": [10, "Gibson"],
        "x_studio_model_type": "solidbody",
        "x_studio_wanna": True,
        "x_studio_notes": False,
        "x_studio_image": False,
        "x_studio_guitar_familly_ids": [],
        "x_studio_guitar_neck_feel_id": False,
        "x_studio_scale": False,
        "x_studio_finish": False,
        "x_studio_fretboard_1": False,
        "x_price_p25": 2000.0,
        "x_price_p50": 2500.0,
        "x_price_p75": 3000.0,
        "x_price_sample_size": 12,
        "x_price_updated_at": False,
        "x_studio_reverb_category_id": False,
        "x_studio_weighted_tag_ids": [],
        "x_studio_weighted_score": 87,
    }
    base.update(overrides)
    return base


def _make_model(**overrides: object) -> ModelsRecord:
    return ModelsRecord.from_odoo(_model_dict(**overrides))


def test_render_card_includes_core_fields() -> None:
    card = _render_card(_make_model())
    assert "**Les Paul Standard**" in card
    assert "(Gibson)" in card
    assert "type=solidbody" in card
    assert "wanna=yes" in card
    assert "score=87" in card
    assert "p50=2500.0" in card


def test_render_card_handles_missing_optional_fields() -> None:
    card = _render_card(
        _make_model(
            x_name=False,
            x_studio_partner_id=False,
            x_studio_model_type=False,
            x_studio_wanna=False,
            x_studio_weighted_score=False,
            x_price_p50=False,
        )
    )
    assert "(unnamed)" in card
    assert "(Gibson)" not in card
    assert "type=-" in card
    assert "wanna=no" in card
    assert "score=0" in card
    assert "p50=-" in card


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _make_conn(rows: list[dict] | None = None) -> MagicMock:
    conn = MagicMock()
    models_proxy = MagicMock()
    models_proxy.search_read.return_value = rows or []
    conn.get_model.return_value = models_proxy
    return conn


def _call_kwargs(conn: MagicMock) -> dict:
    proxy = conn.get_model("x_models")
    return proxy.search_read.call_args.kwargs


def _call_args(conn: MagicMock) -> tuple:
    proxy = conn.get_model("x_models")
    return proxy.search_read.call_args.args


def test_run_no_query_passes_empty_domain() -> None:
    conn = _make_conn(rows=[])
    run(conn)
    assert _call_args(conn)[0] == []


def test_run_query_adds_ilike_clause() -> None:
    conn = _make_conn(rows=[])
    run(conn, query="paul")
    domain = _call_args(conn)[0]
    assert ("x_name", "ilike", "paul") in domain


def test_run_default_sort_is_weighted_score_desc() -> None:
    conn = _make_conn(rows=[])
    run(conn)
    assert _call_kwargs(conn)["order"] == "x_studio_weighted_score desc"


def test_run_sort_by_p50_orders_by_price() -> None:
    conn = _make_conn(rows=[])
    run(conn, sort_by="p50")
    assert _call_kwargs(conn)["order"] == "x_price_p50 desc"


def test_run_sort_by_name_orders_alphabetically() -> None:
    conn = _make_conn(rows=[])
    run(conn, sort_by="name")
    assert _call_kwargs(conn)["order"] == "x_name asc"


def test_run_unknown_sort_falls_back_to_default() -> None:
    conn = _make_conn(rows=[])
    run(conn, sort_by="invalid")
    assert _call_kwargs(conn)["order"] == "x_studio_weighted_score desc"


def test_run_default_limit_is_20() -> None:
    conn = _make_conn(rows=[])
    run(conn)
    assert _call_kwargs(conn)["limit"] == _DEFAULT_LIMIT == 20


def test_run_custom_limit_passed_through() -> None:
    conn = _make_conn(rows=[])
    run(conn, limit=5)
    assert _call_kwargs(conn)["limit"] == 5


def test_run_non_positive_limit_falls_back_to_default() -> None:
    conn = _make_conn(rows=[])
    run(conn, limit=0)
    assert _call_kwargs(conn)["limit"] == _DEFAULT_LIMIT


def test_run_empty_rows_returns_no_results_notice() -> None:
    conn = _make_conn(rows=[])
    result = run(conn)
    assert "No models found" in result


def test_run_renders_count_and_sort_in_header() -> None:
    conn = _make_conn(rows=[_model_dict()])
    result = run(conn, sort_by="p50")
    assert "1 found" in result
    assert "sort=p50" in result


def test_run_renders_one_card_per_record() -> None:
    rows = [
        _model_dict(id=1, x_name="Les Paul Standard", x_studio_weighted_score=90),
        _model_dict(id=2, x_name="Stratocaster", x_studio_weighted_score=75),
    ]
    conn = _make_conn(rows=rows)
    result = run(conn)
    assert "Les Paul Standard" in result
    assert "Stratocaster" in result
