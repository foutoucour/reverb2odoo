"""Tests for odoo_mcp/resources/tags.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from odoo_mcp.resources import tags


def _group_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "Top Quality",
        "x_active": True,
        "x_studio_multiply": 2.0,
    }
    base.update(overrides)
    return base


def _tag_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 10,
        "x_name": "Figured maple",
        "x_active": True,
        "x_studio_score": 5,
        "x_studio_weighted_tag_group_id": [1, "Top Quality"],
        "x_studio_model_ids": [101, 102],
    }
    base.update(overrides)
    return base


def _make_conn(
    *,
    groups: list[dict] | None = None,
    weighted_tags: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    group_proxy = MagicMock()
    tag_proxy = MagicMock()
    group_proxy.search_read.return_value = groups or []
    tag_proxy.search_read.return_value = weighted_tags or []

    def get_model(name: str) -> MagicMock:
        if name == "x_weighted_tag_groups":
            return group_proxy
        if name == "x_weighted_tags":
            return tag_proxy
        raise ValueError(f"Unexpected model: {name}")

    conn.get_model.side_effect = get_model
    return conn


def test_render_empty_says_no_tags() -> None:
    conn = _make_conn(groups=[], weighted_tags=[])
    result = tags.render(conn)
    assert "No tags or tag groups defined" in result


def test_render_includes_group_header_with_id_and_multiply() -> None:
    conn = _make_conn(groups=[_group_dict()], weighted_tags=[_tag_dict()])
    result = tags.render(conn)
    assert "## Top Quality (id=1)" in result
    assert "**Multiply**: 2.0" in result


def test_render_lists_tag_with_score_and_linked_count() -> None:
    conn = _make_conn(groups=[_group_dict()], weighted_tags=[_tag_dict()])
    result = tags.render(conn)
    assert "Figured maple" in result
    assert "score=5" in result
    assert "linked models=2" in result


def test_render_orders_tags_by_descending_score() -> None:
    conn = _make_conn(
        groups=[_group_dict()],
        weighted_tags=[
            _tag_dict(id=10, x_name="Low", x_studio_score=1),
            _tag_dict(id=11, x_name="High", x_studio_score=9),
        ],
    )
    result = tags.render(conn)
    assert result.index("High") < result.index("Low")


def test_render_shows_empty_group_when_group_has_no_tags() -> None:
    conn = _make_conn(
        groups=[_group_dict(id=2, x_name="Pickups")],
        weighted_tags=[],
    )
    result = tags.render(conn)
    assert "## Pickups (id=2)" in result


def test_render_groups_ungrouped_tags_under_ungrouped_section() -> None:
    conn = _make_conn(
        groups=[],
        weighted_tags=[_tag_dict(x_studio_weighted_tag_group_id=False)],
    )
    result = tags.render(conn)
    assert "## Ungrouped" in result


@pytest.mark.parametrize(
    "score, expected_text",
    [
        pytest.param(0, "score=0", id="zero-score"),
        pytest.param(False, "score=-", id="false-score-fallback"),
    ],
)
def test_render_score_fallback(score: object, expected_text: str) -> None:
    conn = _make_conn(
        groups=[_group_dict()],
        weighted_tags=[_tag_dict(x_studio_score=score)],
    )
    result = tags.render(conn)
    assert expected_text in result
