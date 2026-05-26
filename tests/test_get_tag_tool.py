"""Tests for odoo_mcp/tools/get_tag.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.tools.get_tag import run


def _tag_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 10,
        "x_name": "Figured maple",
        "x_active": True,
        "x_studio_score": 5,
        "x_studio_description": False,
        "x_studio_weighted_tag_group_id": [1, "Top Quality"],
        "x_studio_model_ids": [101, 102],
    }
    base.update(overrides)
    return base


def _group_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "Top Quality",
        "x_active": True,
        "x_studio_multiply": 2.0,
    }
    base.update(overrides)
    return base


def _model_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 101,
        "x_name": "Les Paul Standard",
        "x_studio_partner_id": [38, "Gibson"],
        "x_studio_model_type": "solidbody",
        "x_studio_wanna": True,
        "x_studio_weighted_score": 42,
        "x_studio_weighted_tag_ids": [10],
    }
    base.update(overrides)
    return base


def _make_conn(
    *,
    tag_records: list[dict] | None = None,
    group_records: list[dict] | None = None,
    model_records: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    tag_proxy = MagicMock()
    group_proxy = MagicMock()
    model_proxy = MagicMock()

    tag_proxy.search_read.return_value = tag_records or []
    group_proxy.search_read.return_value = group_records or []
    model_proxy.search_read.return_value = model_records or []

    def get_model(name: str) -> MagicMock:
        if name == "x_weighted_tags":
            return tag_proxy
        if name == "x_weighted_tag_groups":
            return group_proxy
        if name == "x_models":
            return model_proxy
        raise ValueError(f"Unexpected model: {name}")

    conn.get_model.side_effect = get_model
    return conn


def test_run_not_found_returns_notice() -> None:
    conn = _make_conn(tag_records=[])
    result = run(conn, "Nonexistent")
    assert "No tag found" in result


def test_run_numeric_id_uses_id_domain() -> None:
    conn = _make_conn(tag_records=[_tag_dict()])
    run(conn, "10")
    domain = conn.get_model("x_weighted_tags").search_read.call_args[0][0]
    assert ("id", "=", 10) in domain


def test_run_name_uses_ilike_domain() -> None:
    conn = _make_conn(tag_records=[_tag_dict()])
    run(conn, "maple")
    domain = conn.get_model("x_weighted_tags").search_read.call_args[0][0]
    assert ("x_name", "ilike", "maple") in domain


def test_run_renders_tag_header_with_group_and_score() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict()],
        group_records=[_group_dict()],
        model_records=[_model_dict()],
    )
    result = run(conn, "maple")
    assert "# Figured maple (id=10)" in result
    assert "**Group**: Top Quality" in result
    assert "**Score**: 5" in result
    assert "**Multiply**: 2.0" in result


def test_run_renders_effective_contribution() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict()],
        group_records=[_group_dict()],
        model_records=[_model_dict()],
    )
    result = run(conn, "maple")
    assert "Effective contribution" in result
    assert "10" in result  # 5 * 2.0


def test_run_renders_description_when_set() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict(x_studio_description="Flamed top with strong figuring.")],
        group_records=[_group_dict()],
        model_records=[_model_dict()],
    )
    result = run(conn, "maple")
    assert "Flamed top with strong figuring." in result


def test_run_omits_description_when_blank() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict()],
        group_records=[_group_dict()],
        model_records=[_model_dict()],
    )
    result = run(conn, "maple")
    assert "False" not in result


def test_run_handles_tag_without_group() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict(x_studio_weighted_tag_group_id=False)],
        model_records=[],
    )
    result = run(conn, "maple")
    assert "(no group)" in result


def test_run_lists_linked_models() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict()],
        group_records=[_group_dict()],
        model_records=[_model_dict()],
    )
    result = run(conn, "maple")
    assert "## Linked Models" in result
    assert "Les Paul Standard" in result
    assert "weighted_score=42" in result


def test_run_shows_none_when_no_linked_models() -> None:
    conn = _make_conn(
        tag_records=[_tag_dict(x_studio_model_ids=[])],
        group_records=[_group_dict()],
    )
    result = run(conn, "maple")
    assert "## Linked Models" in result
    assert "*None*" in result


@pytest.mark.parametrize(
    "input_str, expected_value",
    [
        pytest.param("  10  ", 10, id="strips-whitespace-around-id"),
        pytest.param("10", 10, id="bare-id"),
    ],
)
def test_run_strips_whitespace_from_input(input_str: str, expected_value: int) -> None:
    conn = _make_conn(tag_records=[_tag_dict()])
    run(conn, input_str)
    domain = conn.get_model("x_weighted_tags").search_read.call_args[0][0]
    assert ("id", "=", expected_value) in domain
