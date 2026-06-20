"""Tests for odoo_mcp/resources/kits.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from odoo_mcp.resources.kits import _render_kit, render

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _kit_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 1,
        "x_name": "TV Yellow Korina Explorer",
        "x_studio_status": "building",
        "x_studio_notes": False,
        "x_studio_gear_id": False,
        "x_studio_kit_part_ids": False,
        "x_studio_price": False,
        "x_studio_currency_id": False,
        "x_studio_finishing": False,
    }
    base.update(overrides)
    return base


def _kit_part_dict(**overrides: object) -> dict:
    base: dict = {
        "id": 100,
        "x_name": "Tuners line",
        "x_studio_kit_id": [1, "TV Yellow Korina Explorer"],
        "x_studio_listing_id": [500, "Tuners"],
        "x_studio_quantity": 1,
        "x_studio_status": "wanted",
        "x_studio_notes": False,
        "x_studio_total_price": False,
    }
    base.update(overrides)
    return base


def _make_conn(
    *,
    kit_records: list[dict] | None = None,
    kit_part_records: list[dict] | None = None,
) -> MagicMock:
    conn = MagicMock()
    kit_proxy = MagicMock()
    kit_part_proxy = MagicMock()
    kit_proxy.search_read.return_value = kit_records or []
    kit_part_proxy.search_read.return_value = kit_part_records or []

    proxies = {"x_kit": kit_proxy, "x_kit_part": kit_part_proxy}

    def _get_model(name: str) -> MagicMock:
        return proxies[name]

    conn.get_model.side_effect = _get_model
    return conn


# ---------------------------------------------------------------------------
# _render_kit
# ---------------------------------------------------------------------------


def test_render_kit_header_has_name_and_status() -> None:
    from models import KitRecord

    kit = KitRecord.from_odoo(_kit_dict())
    result = _render_kit(kit, {"wanted": 0, "ordered": 0, "received": 0})
    assert "## TV Yellow Korina Explorer [building]" in result


def test_render_kit_rollup_shows_all_three_counts() -> None:
    from models import KitRecord

    kit = KitRecord.from_odoo(_kit_dict())
    result = _render_kit(kit, {"wanted": 5, "ordered": 3, "received": 2})
    assert "5 wanted" in result
    assert "3 ordered" in result
    assert "2 received" in result


def test_render_kit_shows_notes_excerpt_when_present() -> None:
    from models import KitRecord

    kit = KitRecord.from_odoo(_kit_dict(x_studio_notes="Korina slab · Nitro TV Yellow"))
    result = _render_kit(kit, {"wanted": 0, "ordered": 0, "received": 0})
    assert "Korina slab" in result


def test_render_kit_omits_notes_when_absent() -> None:
    from models import KitRecord

    kit = KitRecord.from_odoo(_kit_dict(x_studio_notes=False))
    result = _render_kit(kit, {"wanted": 0, "ordered": 0, "received": 0})
    assert "**Notes**:" not in result


def test_render_kit_truncates_long_notes() -> None:
    from models import KitRecord

    long_text = "A" * 500
    kit = KitRecord.from_odoo(_kit_dict(x_studio_notes=long_text))
    result = _render_kit(kit, {"wanted": 0, "ordered": 0, "received": 0})
    assert "…" in result or len(result) < 500


# ---------------------------------------------------------------------------
# render — integration
# ---------------------------------------------------------------------------


def test_render_returns_markdown_header() -> None:
    conn = _make_conn(kit_records=[])
    result = render(conn)
    assert "# Kits" in result


def test_render_no_kits_shows_placeholder() -> None:
    conn = _make_conn(kit_records=[])
    result = render(conn)
    assert "No kits in flight" in result


def test_render_excludes_done_kits_case_insensitive() -> None:
    """Done kits are filtered out regardless of selection-value capitalization."""
    conn = _make_conn(
        kit_records=[
            _kit_dict(id=1, x_name="In flight", x_studio_status="Idea"),
            _kit_dict(id=2, x_name="Lower-done", x_studio_status="done"),
            _kit_dict(id=3, x_name="Upper-done", x_studio_status="Done"),
        ],
    )
    result = render(conn)
    assert "In flight" in result
    assert "Lower-done" not in result
    assert "Upper-done" not in result


def test_render_orders_kits_by_lifecycle() -> None:
    """Kits ordered idea → planning → sourcing → building (case-insensitive)."""
    conn = _make_conn(
        kit_records=[
            _kit_dict(id=1, x_name="Build first", x_studio_status="Building"),
            _kit_dict(id=2, x_name="Idea first", x_studio_status="Idea"),
            _kit_dict(id=3, x_name="Sourcing first", x_studio_status="Sourcing"),
        ],
    )
    result = render(conn)
    idea_pos = result.index("Idea first")
    sourcing_pos = result.index("Sourcing first")
    build_pos = result.index("Build first")
    assert idea_pos < sourcing_pos < build_pos


def test_render_aggregates_part_status_counts() -> None:
    kit = _kit_dict(id=1, x_name="My Kit")
    parts = [
        _kit_part_dict(id=10, x_studio_kit_id=[1, "My Kit"], x_studio_status="wanted"),
        _kit_part_dict(id=11, x_studio_kit_id=[1, "My Kit"], x_studio_status="wanted"),
        _kit_part_dict(id=12, x_studio_kit_id=[1, "My Kit"], x_studio_status="ordered"),
        _kit_part_dict(id=13, x_studio_kit_id=[1, "My Kit"], x_studio_status="received"),
    ]
    conn = _make_conn(kit_records=[kit], kit_part_records=parts)
    result = render(conn)
    assert "2 wanted" in result
    assert "1 ordered" in result
    assert "1 received" in result


def test_render_part_status_counts_case_insensitive() -> None:
    """Counter keys are normalized so capitalized Studio values still count."""
    kit = _kit_dict(id=1, x_name="My Kit", x_studio_status="Building")
    parts = [
        _kit_part_dict(id=10, x_studio_kit_id=[1, "My Kit"], x_studio_status="Wanted"),
        _kit_part_dict(id=11, x_studio_kit_id=[1, "My Kit"], x_studio_status="Received"),
        _kit_part_dict(id=12, x_studio_kit_id=[1, "My Kit"], x_studio_status="Received"),
    ]
    conn = _make_conn(kit_records=[kit], kit_part_records=parts)
    result = render(conn)
    assert "1 wanted" in result
    assert "2 received" in result


def test_render_handles_kit_with_no_parts() -> None:
    kit = _kit_dict(id=1, x_name="Empty Kit")
    conn = _make_conn(kit_records=[kit], kit_part_records=[])
    result = render(conn)
    assert "Empty Kit" in result
    assert "0 wanted" in result


def test_render_assigns_parts_to_correct_kit() -> None:
    kits = [
        _kit_dict(id=1, x_name="Kit A", x_studio_status="idea"),
        _kit_dict(id=2, x_name="Kit B", x_studio_status="idea"),
    ]
    parts = [
        _kit_part_dict(id=10, x_studio_kit_id=[1, "Kit A"], x_studio_status="wanted"),
        _kit_part_dict(id=11, x_studio_kit_id=[2, "Kit B"], x_studio_status="ordered"),
        _kit_part_dict(id=12, x_studio_kit_id=[2, "Kit B"], x_studio_status="ordered"),
    ]
    conn = _make_conn(kit_records=kits, kit_part_records=parts)
    result = render(conn)
    kit_a_section = result[result.index("Kit A") : result.index("Kit B")]
    kit_b_section = result[result.index("Kit B") :]
    assert "1 wanted" in kit_a_section
    assert "2 ordered" in kit_b_section


def test_render_does_not_query_parts_when_no_kits() -> None:
    conn = _make_conn(kit_records=[])
    render(conn)
    conn.get_model("x_kit_part").search_read.assert_not_called()


def test_render_output_ends_with_newline() -> None:
    conn = _make_conn(kit_records=[])
    result = render(conn)
    assert result.endswith("\n")
