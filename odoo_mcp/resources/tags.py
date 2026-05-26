"""MCP resource: render the weighted tag catalog as markdown.

Lists every ``x_weighted_tags`` record grouped by its ``x_weighted_tag_groups``
parent, with each tag's score and the number of linked ``x_models``. Groups
show their ``x_studio_multiply`` factor so the effective contribution of a
tag (``score * multiply``) is computable at a glance.
"""

from __future__ import annotations

from collections import defaultdict

import odoolib
from loguru import logger

from models import WeightedTagGroupRecord, WeightedTagRecord

_UNGROUPED = "Ungrouped"


def _scalar(value: object, fallback: str = "") -> str:
    if value is False or value is None or value == "":
        return fallback
    return str(value)


def _render_tag_line(tag: WeightedTagRecord) -> str:
    name = _scalar(tag.x_name, fallback="(unnamed)")
    score = _scalar(tag.x_studio_score, fallback="-")
    linked = len(tag.x_studio_model_ids)
    return f"- **{name}** (id={tag.id}) | score={score} | linked models={linked}"


def _render_group_section(
    group: WeightedTagGroupRecord | None,
    tags: list[WeightedTagRecord],
) -> list[str]:
    if group is None:
        header = f"## {_UNGROUPED}"
        meta = ""
    else:
        name = _scalar(group.x_name, fallback="(unnamed)")
        multiply = _scalar(group.x_studio_multiply, fallback="1.0")
        header = f"## {name} (id={group.id})"
        meta = f"**Multiply**: {multiply}"

    lines: list[str] = [header]
    if meta:
        lines.append(meta)
    lines.append("")
    for tag in sorted(tags, key=lambda t: (-(t.x_studio_score or 0), (t.x_name or "").lower())):
        lines.append(_render_tag_line(tag))
    return lines


def render(conn: odoolib.main.Connection) -> str:
    """Return a markdown catalog of all weighted tags grouped by tag group."""
    logger.info("Rendering weighted tag catalog resource")

    group_rows: list[dict] = conn.get_model("x_weighted_tag_groups").search_read(
        [], WeightedTagGroupRecord.odoo_fields()
    )
    groups = [WeightedTagGroupRecord.from_odoo(r) for r in group_rows]
    groups_by_id: dict[int, WeightedTagGroupRecord] = {g.id: g for g in groups}

    tag_rows: list[dict] = conn.get_model("x_weighted_tags").search_read(
        [], WeightedTagRecord.odoo_fields()
    )
    tags = [WeightedTagRecord.from_odoo(r) for r in tag_rows]
    logger.info("Tag catalog: {} group(s), {} tag(s)", len(groups), len(tags))

    tags_by_group: dict[int | None, list[WeightedTagRecord]] = defaultdict(list)
    for tag in tags:
        group_ref = tag.x_studio_weighted_tag_group_id
        gid = group_ref[0] if group_ref else None
        tags_by_group[gid].append(tag)

    sections: list[str] = ["# Weighted Tag Catalog", ""]

    if not tags and not groups:
        sections.append("*No tags or tag groups defined.*")
        return "\n".join(sections) + "\n"

    seen_group_ids: set[int] = set()
    for gid, group_tags in sorted(
        tags_by_group.items(),
        key=lambda kv: (groups_by_id[kv[0]].x_name or "").lower() if kv[0] in groups_by_id else "~",
    ):
        if gid is None:
            continue
        group = groups_by_id.get(gid)
        sections.extend(_render_group_section(group, group_tags))
        sections.append("")
        seen_group_ids.add(gid)

    # Groups with no tags — surface them so the catalog stays honest.
    empty_groups = [g for g in groups if g.id not in seen_group_ids]
    for group in sorted(empty_groups, key=lambda g: (g.x_name or "").lower()):
        sections.extend(_render_group_section(group, []))
        sections.append("")

    if None in tags_by_group:
        sections.extend(_render_group_section(None, tags_by_group[None]))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
