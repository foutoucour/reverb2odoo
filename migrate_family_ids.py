"""Migrate field values into x_studio_guitar_familly_ids on x_models.

For each model, reads the following source fields and creates corresponding
entries in x_studio_guitar_familly_ids with a type-specific prefix:

  x_studio_fretboard_1        → ``fretboard-<name>``
  x_studio_scale              → ``scale-<value>``
  x_studio_finish             → ``finish-<name>``
  x_studio_guitar_neck_feel_id → ``nech-<name>``

Usage (dry-run, default)::

    reverb2odoo migrate-family-ids

Usage (apply changes)::

    reverb2odoo migrate-family-ids --apply

"""

from __future__ import annotations

from typing import Any

import click
from loguru import logger

# ---------------------------------------------------------------------------
# Source-field → prefix mapping
# ---------------------------------------------------------------------------

#: (odoo_field_name, prefix, is_many2one)
SOURCE_FIELDS: list[tuple[str, str, bool]] = [
    ("x_studio_fretboard_1", "fretboard-", True),
    ("x_studio_scale", "scale-", False),
    ("x_studio_finish", "finish-", True),
    ("x_studio_guitar_neck_feel_id", "nech-", True),
]

_FETCH_FIELDS: list[str] = ["x_name"] + [f for f, _, _ in SOURCE_FIELDS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _m2o_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return str(value[1])
    return ""


def _source_value(record: dict, field: str, is_m2o: bool) -> str:
    """Return the display value for a source field, or empty string."""
    raw = record.get(field)
    if not raw:
        return ""
    if is_m2o:
        return _m2o_name(raw)
    return str(raw).strip()


def _discover_comodel(conn) -> str:
    """Return the comodel name for x_studio_guitar_familly_ids."""
    x_models = conn.get_model("x_models")
    meta = x_models.fields_get(["x_studio_guitar_familly_ids"])
    comodel = meta.get("x_studio_guitar_familly_ids", {}).get("relation", "")
    if not comodel:
        raise RuntimeError("Cannot determine comodel for x_studio_guitar_familly_ids")
    return comodel


def _fetch_existing_family(conn, comodel: str) -> dict[str, int]:
    """Return existing family records as {x_name: id}."""
    family_model = conn.get_model(comodel)
    records = family_model.search_read([], ["x_name"])
    return {r["x_name"]: r["id"] for r in records}


def _fetch_existing_links(conn) -> dict[int, list[int]]:
    """Return current x_studio_guitar_familly_ids
    per x_models record as {model_id: [family_ids]}."""
    x_models = conn.get_model("x_models")
    records = x_models.search_read([], ["x_studio_guitar_familly_ids"])
    return {r["id"]: r["x_studio_guitar_familly_ids"] for r in records}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def compute_plan(conn) -> tuple[list[str], dict[int, dict]]:
    """Compute what needs to be created / linked.

    Returns
    -------
    new_family_names : list[str]
        Family record names that do not yet exist and must be created.
    model_additions : dict[int, dict]
        Mapping model_id → {
            "name": str,
            "add_new": list[str],   # family names not yet linked (will be created)
            "add_existing": list[str],  # family names not yet linked (already exist)
        }
    """
    logger.info("Fetching all x_models…")
    x_models_model = conn.get_model("x_models")
    records = x_models_model.search_read([], _FETCH_FIELDS, order="x_name asc")
    logger.info("  {} model(s) fetched", len(records))

    logger.info("Discovering comodel for x_studio_guitar_familly_ids…")
    comodel = _discover_comodel(conn)
    logger.info("  comodel: {}", comodel)

    logger.info("Fetching existing family records…")
    existing_family: dict[str, int] = _fetch_existing_family(conn, comodel)
    logger.info("  {} existing family records", len(existing_family))

    logger.info("Fetching existing model↔family links…")
    existing_links: dict[int, list[int]] = _fetch_existing_links(conn)

    # Collect all family names we'll need (by value)
    needed_names: set[str] = set()
    # Per-model: which family names to add
    model_plan: dict[int, dict] = {}

    for record in records:
        model_id = record["id"]
        model_name = record.get("x_name", f"id={model_id}")
        current_family_ids = set(existing_links.get(model_id, []))

        names_to_add: list[str] = []
        for field, prefix, is_m2o in SOURCE_FIELDS:
            val = _source_value(record, field, is_m2o)
            if not val:
                continue
            family_name = f"{prefix}{val}"
            needed_names.add(family_name)
            # Check if already linked
            fam_id = existing_family.get(family_name)
            if fam_id is not None and fam_id in current_family_ids:
                continue  # already linked, skip
            names_to_add.append(family_name)

        if names_to_add:
            model_plan[model_id] = {
                "name": model_name,
                "add_new": [n for n in names_to_add if n not in existing_family],
                "add_existing": [n for n in names_to_add if n in existing_family],
            }

    new_family_names = sorted(needed_names - existing_family.keys())
    return new_family_names, model_plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_plan(conn, new_family_names: list[str], model_plan: dict[int, dict]) -> None:
    """Create missing family records and update x_models links."""
    comodel = _discover_comodel(conn)
    family_model = conn.get_model("x_models_" if comodel == "x_models" else comodel)
    family_model = conn.get_model(comodel)

    # Refresh existing map (in case something changed)
    existing_family: dict[str, int] = _fetch_existing_family(conn, comodel)

    # Create missing records
    created: dict[str, int] = {}
    for name in new_family_names:
        if name in existing_family:
            created[name] = existing_family[name]
            continue
        new_id = family_model.create({"x_name": name})
        created[name] = new_id
        logger.success("Created family record '{}' (id={})", name, new_id)

    # Merge into existing map
    existing_family.update(created)

    # Update x_models
    x_models_model = conn.get_model("x_models")
    for model_id, info in model_plan.items():
        all_names = info["add_new"] + info["add_existing"]
        ids_to_add = [existing_family[n] for n in all_names if n in existing_family]
        if not ids_to_add:
            continue
        x_models_model.write(
            [model_id],
            {
                "x_studio_guitar_familly_ids": [(4, fid) for fid in ids_to_add],
            },
        )
        logger.success(
            "Updated '{}' → added {}",
            info["name"],
            ", ".join(all_names),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("migrate-family-ids")
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Apply changes to Odoo (default: dry-run only).",
)
@click.pass_context
def cli(ctx: click.Context, apply: bool) -> None:
    """Migrate fretboard/scale/finish/neck-feel into x_studio_guitar_familly_ids.

    Runs in dry-run mode by default.  Pass --apply to write changes to Odoo.
    """
    conn = ctx.obj["conn"]

    new_family_names, model_plan = compute_plan(conn)

    # ── Dry-run report ──────────────────────────────────────────────────────
    total_additions = sum(len(v["add_new"]) + len(v["add_existing"]) for v in model_plan.values())
    logger.info("")
    logger.info("=== DRY-RUN REPORT ===")
    logger.info("")

    if new_family_names:
        logger.info("Family records to CREATE ({}):", len(new_family_names))
        for name in new_family_names:
            logger.info("  + {}", name)
    else:
        logger.info("No new family records needed.")

    logger.info("")
    if model_plan:
        logger.info(
            "x_models to UPDATE ({} model(s), {} link(s) total):", len(model_plan), total_additions
        )
        for _mid, info in sorted(model_plan.items(), key=lambda kv: kv[1]["name"]):
            all_names = info["add_new"] + info["add_existing"]
            logger.info("  '{}' → {}", info["name"], ", ".join(all_names))
    else:
        logger.info("No x_models updates needed.")

    logger.info("")

    if not apply:
        logger.info("[DRY RUN] No changes written.  Pass --apply to apply.")
        return

    # ── Apply ───────────────────────────────────────────────────────────────
    logger.info("Applying changes…")
    apply_plan(conn, new_family_names, model_plan)
    logger.success("Done.")
