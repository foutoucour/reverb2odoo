"""MCP tool: fetch a single weighted tag by name or id.

Returns the tag's score, its parent tag group (with multiply factor), and the
list of ``x_models`` it is attached to.
"""

from __future__ import annotations

import odoolib
from loguru import logger

from models import ModelsRecord, WeightedTagGroupRecord, WeightedTagRecord


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _label(m2o: tuple[int, str] | None) -> str:
    return m2o[1] if m2o else ""


def _render_tag_header(
    tag: WeightedTagRecord,
    group: WeightedTagGroupRecord | None,
) -> str:
    name = _scalar(tag.x_name, fallback="(unnamed)")
    score = _scalar(tag.x_studio_score, fallback="-")
    group_label = _label(tag.x_studio_weighted_tag_group_id) or "(no group)"
    multiply = _scalar(group.x_studio_multiply, fallback="1.0") if group else "1.0"
    effective = (
        tag.x_studio_score * group.x_studio_multiply
        if (tag.x_studio_score is not None and group and group.x_studio_multiply is not None)
        else None
    )

    lines: list[str] = [
        f"# {name} (id={tag.id})",
        f"**Group**: {group_label} | **Score**: {score} | **Multiply**: {multiply}",
    ]
    if effective is not None:
        lines.append(f"**Effective contribution**: {effective}")
    description = _scalar(tag.x_studio_description)
    if description:
        lines.append("")
        lines.append(description)
    return "\n".join(lines)


def _render_models_section(models: list[ModelsRecord]) -> str:
    if not models:
        return "## Linked Models\n\n*None*"

    lines: list[str] = ["## Linked Models"]
    for model in sorted(models, key=lambda m: (m.x_name or "").lower()):
        name = _scalar(model.x_name, fallback="(unnamed)")
        brand = _label(model.x_studio_partner_id)
        wscore = _scalar(model.x_studio_weighted_score, fallback="-")
        lines.append(f"- **{name}** (id={model.id}) | brand={brand} | weighted_score={wscore}")
    return "\n".join(lines)


def run(conn: odoolib.main.Connection, name_or_id: str) -> str:
    """Fetch a single ``x_weighted_tags`` record with its group and linked models.

    ``name_or_id`` is matched against id when numeric, otherwise an ilike search
    on ``x_name``.
    """
    name_or_id = name_or_id.strip()
    tag_proxy = conn.get_model("x_weighted_tags")

    if name_or_id.isdigit():
        logger.info("get_tag: searching by id={}", name_or_id)
        domain: list = [("id", "=", int(name_or_id))]
    else:
        logger.info("get_tag: searching by name ilike '{}'", name_or_id)
        domain = [("x_name", "ilike", name_or_id)]

    tag_rows: list[dict] = tag_proxy.search_read(domain, WeightedTagRecord.odoo_fields(), limit=1)
    if not tag_rows:
        return f"No tag found matching: **{name_or_id}**"

    tag = WeightedTagRecord.from_odoo(tag_rows[0])
    logger.info("get_tag: found tag id={}", tag.id)

    group: WeightedTagGroupRecord | None = None
    if tag.x_studio_weighted_tag_group_id:
        group_id = tag.x_studio_weighted_tag_group_id[0]
        group_rows = conn.get_model("x_weighted_tag_groups").search_read(
            [("id", "=", group_id)], WeightedTagGroupRecord.odoo_fields(), limit=1
        )
        if group_rows:
            group = WeightedTagGroupRecord.from_odoo(group_rows[0])

    models: list[ModelsRecord] = []
    if tag.x_studio_model_ids:
        model_rows = conn.get_model("x_models").search_read(
            [("id", "in", tag.x_studio_model_ids)], ModelsRecord.odoo_fields()
        )
        models = [ModelsRecord.from_odoo(r) for r in model_rows]

    sections: list[str] = [
        _render_tag_header(tag, group),
        "",
        _render_models_section(models),
    ]
    return "\n".join(sections)
