"""Generate a shareable product card for a single x_gear item.

Scans the live x_gear schema via fields_get(), groups fields by theme,
and renders via Jinja2 (templates/gear-card.html.j2).

Usage::

    reverb2odoo gear-page 42
    reverb2odoo gear-page "Gibson Les Paul Standard"
    reverb2odoo gear-page 42 --output-dir /tmp
"""

from __future__ import annotations

import html as _html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_console = Console()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FieldMeta(BaseModel):
    """Metadata for a single Odoo field (subset of fields_get() output)."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    string: str = ""
    selection: list[list[str]] = []
    relation: str = ""


class GearRecord(BaseModel):
    """Raw x_gear record as returned by Odoo search_read."""

    model_config = ConfigDict(extra="allow")

    id: int
    x_name: str = ""
    x_model_id: Any = False
    x_studio_image: Any = False


class ModelRecord(BaseModel):
    """Raw x_models record."""

    model_config = ConfigDict(extra="allow")

    x_name: str = ""
    x_studio_partner_id: Any = False
    x_studio_model_type: Any = False
    x_studio_notes: Any = False


class ListingRecord(BaseModel):
    """Raw x_listing record."""

    model_config = ConfigDict(extra="allow")

    id: int
    x_price: float = 0.0
    x_shipping: float = 0.0
    x_currency_id: Any = False
    x_platform: str = ""
    x_is_available: bool = False
    x_studio_image: Any = False


class ListingRow(BaseModel):
    """Shaped listing data for the template."""

    price_str: str
    platform: str
    available: bool


class SpecGroup(BaseModel):
    """A named group of label/value spec pairs."""

    title: str
    specs: list[tuple[str, str]]
    style: str = "tiles"  # "tiles" | "rows"


class NeckProfile(BaseModel):
    """Neck cross-section data for the SVG diagram."""

    nut_width_mm: float
    thickness_1st_mm: float
    thickness_12th_mm: float
    nut_width_disp: str
    thickness_1st_disp: str
    thickness_12th_disp: str


class CardContext(BaseModel):
    """Full context passed to the Jinja2 template."""

    gear_id: int
    gear_name: str
    brand: str
    model_name: str
    intent: str
    spec_groups: list[SpecGroup]
    photos: list[str]
    neck_profile: NeckProfile | None = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = Path("gear-page")
TEMPLATES_DIR = Path(__file__).parent / "templates"

_FIELD_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Instrument",
        [
            "x_studio_production_year",
            "x_studio_acquiring_date",
            "x_serial_number",
            "x_studio_current_condition",
        ],
    ),
    (
        "Materials & Finish",
        [
            "x_studio_body_material",
            "x_studio_top_cap_material",
            "x_studio_body_finish",
            "x_studio_neck_material",
            "x_studio_fretboard_material",
            "x_studio_neck_finish",
        ],
    ),
]

#: Words to strip (case-insensitive) from field labels within each group.
_GROUP_LABEL_STRIP: dict[str, str] = {
    "Instrument": "current",
}

#: Date fields that should display only the year (YYYY).
_YEAR_FIELDS: frozenset[str] = frozenset({"x_studio_acquiring_date"})

#: Paired metric/imperial measurements rendered as "<mm> mm / <in> in".
#: Each tuple: (label, metric_field, imperial_field)
# Measurement entry types:
#   Single pair  → (tile_label, metric_field, metric_unit, imperial_field, imperial_unit)
#   Grouped pair → (tile_label, [(sub_label, metric_field,
#   metric_unit, imperial_field, imperial_unit), ...])
type _MeasPair = tuple[str, str, str, str, str]
type _MeasEntry = _MeasPair | tuple[str, list[_MeasPair]]

_MEASUREMENTS: list[_MeasEntry] = [
    ("Scale length", "x_studio_scale_length", "cm", "x_studio_scale_length_imperial", "in"),
    ("Scale radius", "x_studio_scale_radius", "cm", "x_studio_scale_radius_imperial", "in"),
    ("Weight", "x_studio_weight", "kg", "x_studio_weight_imperial", "lbs"),
]

#: All x_gear spec fields (excludes x_name, x_model_id, x_studio_image — handled separately).
_GEAR_SPEC_FIELDS: list[str] = [
    "x_intent",
    "x_serial_number",
    "x_studio_acquiring_date",
    "x_studio_body_finish",
    "x_studio_body_material",
    "x_studio_current_condition",
    "x_studio_current_pickup_ids",
    "x_studio_fretboard_material",
    "x_studio_model_name",
    "x_studio_neck_finish",
    "x_studio_neck_material",
    "x_studio_nut_width",
    "x_studio_nut_width_imperial",
    "x_studio_production_year",
    "x_studio_scale_length",
    "x_studio_scale_length_imperial",
    "x_studio_scale_radius",
    "x_studio_scale_radius_imperial",
    "x_studio_thickness_first_fret",
    "x_studio_thickness_first_fret_imperial",
    "x_studio_thickness_twelfth_fret",
    "x_studio_thickness_twelfth_fret_imperial",
    "x_studio_top_cap_material",
    "x_studio_weight",
    "x_studio_weight_imperial",
]

_MODEL_FIELDS: list[str] = [
    "x_name",
    "x_studio_partner_id",
    "x_studio_model_type",
    "x_studio_notes",
]

_LISTING_FIELDS: list[str] = [
    "id",
    "x_price",
    "x_shipping",
    "x_currency_id",
    "x_platform",
    "x_is_available",
    "x_studio_image",
]


# ---------------------------------------------------------------------------
# Field metadata
# ---------------------------------------------------------------------------


def _get_gear_field_meta(conn) -> dict[str, FieldMeta]:
    """Return FieldMeta for the known x_gear spec fields."""
    raw_meta: dict[str, dict] = conn.get_model("x_gear").fields_get(_GEAR_SPEC_FIELDS)
    return {
        name: FieldMeta(name=name, **{k: v for k, v in raw.items() if k != "name"})
        for name, raw in raw_meta.items()
    }


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def _m2o_name(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return str(value[1])
    return ""


def _available_fields(conn, model_name: str, wanted: list[str]) -> list[str]:
    model = conn.get_model(model_name)
    existing: set[str] = set(model.fields_get(wanted).keys())
    return [f for f in wanted if f in existing]


def _find_gear(conn, gear_ref: str, field_names: list[str]) -> GearRecord:
    gear_model = conn.get_model("x_gear")
    fields = ["id", "x_name", "x_model_id", "x_studio_image"] + field_names

    if gear_ref.isdigit():
        results = gear_model.search_read([("id", "=", int(gear_ref))], fields, limit=1)
    else:
        results = gear_model.search_read([("x_name", "ilike", gear_ref)], fields)

    if not results:
        _console.print(f"[red]No x_gear record found for '{gear_ref}'[/red]")
        sys.exit(1)

    if len(results) > 1:
        matches = ", ".join(f"{r['x_name']!r} (id={r['id']})" for r in results)
        _console.print(f"[red]Ambiguous — {len(results)} matches: {matches}[/red]")
        sys.exit(1)

    return GearRecord(**results[0])


def _fetch_model(conn, model_id: int) -> ModelRecord:
    fields = _available_fields(conn, "x_models", _MODEL_FIELDS)
    model = conn.get_model("x_models")
    results = model.search_read([("id", "=", model_id)], fields, limit=1)
    return ModelRecord(**results[0]) if results else ModelRecord()


def _fetch_listings(conn, gear_id: int) -> list[ListingRecord]:
    fields = _available_fields(conn, "x_listing", _LISTING_FIELDS)
    listing_model = conn.get_model("x_listing")
    rows = listing_model.search_read([("x_gear_id", "=", gear_id)], fields)
    return [ListingRecord(**r) for r in rows]


def _resolve_m2m_names(
    conn,
    gear: GearRecord,
    field_meta: dict[str, FieldMeta],
) -> dict[str, list[str]]:
    """Resolve many2many IDs to a list of display names per field."""
    resolved: dict[str, list[str]] = {}
    for fname, meta in field_meta.items():
        if meta.type != "many2many":
            continue
        ids = getattr(gear, fname, None) or gear.model_extra.get(fname)
        if not ids:
            continue
        if not meta.relation:
            continue
        try:
            records = conn.get_model(meta.relation).read(ids, ["display_name"])
            resolved[fname] = [r["display_name"] for r in records]
        except Exception:
            resolved[fname] = []
    return resolved


# ---------------------------------------------------------------------------
# Data shaping
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts).strip()


def _strip_html(raw: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", raw, flags=re.IGNORECASE)
    stripper = _HTMLStripper()
    stripper.feed(_html.unescape(text))
    return stripper.get_text()


def _format_field_value(
    value: Any,
    meta: FieldMeta,
    m2m_resolved: dict[str, list[str]],
) -> str:
    if meta.type == "many2many":
        names = m2m_resolved.get(meta.name)
        return ", ".join(names) if names else "—"

    if value is False or value is None or value == "":
        return "—"

    if meta.type == "boolean":
        return "Yes" if value else "No"

    if meta.type == "many2one":
        return _m2o_name(value) or "—"

    if meta.type == "selection":
        label_map = {k: v for k, v in meta.selection}
        return label_map.get(str(value), str(value))

    if meta.type in ("float", "monetary"):
        f = float(value)
        return f"{f:,.2f}".rstrip("0").rstrip(".")

    if meta.type == "integer":
        return str(int(value))

    if meta.type in ("datetime", "date"):
        return str(value)[:4] if meta.name in _YEAR_FIELDS else str(value)[:10]

    return str(value)


def _build_spec_groups(
    gear: GearRecord,
    field_meta: dict[str, FieldMeta],
    m2m_resolved: dict[str, list[str]],
) -> list[SpecGroup]:
    all_values = {**gear.model_dump(), **gear.model_extra}

    formatted: dict[str, tuple[str, str]] = {}
    for fname, meta in field_meta.items():
        value = _format_field_value(all_values.get(fname), meta, m2m_resolved)
        formatted[fname] = (meta.string or fname, value)

    groups: list[SpecGroup] = []
    assigned: set[str] = set()

    for title, field_names in _FIELD_GROUPS:
        strip_word = _GROUP_LABEL_STRIP.get(title, "").lower()
        specs = []
        for f in field_names:
            if f not in formatted:
                continue
            label, value = formatted[f]
            if strip_word and label.lower().startswith(strip_word):
                label = label[len(strip_word) :].lstrip()
            specs.append((label, value))
        assigned.update(field_names)
        style = "rows" if title == "Materials & Finish" else "tiles"
        groups.append(SpecGroup(title=title, specs=specs, style=style))

    # Pickups: one tile per pickup name
    pickup_names = m2m_resolved.get("x_studio_current_pickup_ids") or []
    if pickup_names:
        groups.append(
            SpecGroup(
                title="Pickups",
                specs=[("Pickup", name) for name in pickup_names],
            )
        )
    assigned.add("x_studio_current_pickup_ids")

    # Measurements: collapse metric + imperial into single rows; grouped entries use newlines
    def _fmt_pair(m_field: str, m_unit: str, i_field: str, i_unit: str) -> str:
        m = formatted.get(m_field, ("", "—"))[1]
        i = formatted.get(i_field, ("", "—"))[1]
        assigned.update({m_field, i_field})
        return f"{m} {m_unit} / {i} {i_unit}"

    measurement_specs: list[tuple[str, str]] = []
    for entry in _MEASUREMENTS:
        tile_label = entry[0]
        if isinstance(entry[1], list):
            lines = [f"{sub}: {_fmt_pair(mf, mu, if_, iu)}" for sub, mf, mu, if_, iu in entry[1]]
            measurement_specs.append((tile_label, "\n".join(lines)))
        else:
            _, m_field, m_unit, i_field, i_unit = entry
            measurement_specs.append((tile_label, _fmt_pair(m_field, m_unit, i_field, i_unit)))
    groups.append(SpecGroup(title="Measurements", style="rows", specs=measurement_specs))

    return groups


def _raw_float(gear: GearRecord, field: str) -> float:
    val = gear.model_extra.get(field)
    if val is False or val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _build_neck_profile(gear: GearRecord) -> NeckProfile | None:
    nut_w = _raw_float(gear, "x_studio_nut_width")
    if nut_w <= 0:
        return None

    def _disp(mm_field: str, in_field: str) -> str:
        mm = _raw_float(gear, mm_field)
        imp = _raw_float(gear, in_field)
        mm_s = f"{mm:.1f} mm" if mm else "—"
        in_s = f"{imp:.3f}".rstrip("0").rstrip(".") + '"' if imp else ""
        return f"{mm_s}  {in_s}".strip() if in_s else mm_s

    return NeckProfile(
        nut_width_mm=nut_w,
        thickness_1st_mm=_raw_float(gear, "x_studio_thickness_first_fret"),
        thickness_12th_mm=_raw_float(gear, "x_studio_thickness_twelfth_fret"),
        nut_width_disp=_disp("x_studio_nut_width", "x_studio_nut_width_imperial"),
        thickness_1st_disp=_disp(
            "x_studio_thickness_first_fret", "x_studio_thickness_first_fret_imperial"
        ),
        thickness_12th_disp=_disp(
            "x_studio_thickness_twelfth_fret", "x_studio_thickness_twelfth_fret_imperial"
        ),
    )


def _build_context(
    gear: GearRecord,
    field_meta: dict[str, FieldMeta],
    model: ModelRecord,
    listings: list[ListingRecord],
    m2m_resolved: dict[str, str],
) -> CardContext:
    spec_groups = _build_spec_groups(gear, field_meta, m2m_resolved)

    # Resolve intent label from field metadata
    intent_raw = gear.model_extra.get("x_intent") or ""
    intent_meta = field_meta.get("x_intent")
    if intent_meta and intent_raw:
        label_map = {k: v for k, v in intent_meta.selection}
        intent = label_map.get(str(intent_raw), str(intent_raw))
    else:
        intent = ""

    photo: str | None = gear.x_studio_image or next(
        (lst.x_studio_image for lst in listings if lst.x_studio_image), None
    )
    photos: list[str] = [photo] if photo else []

    return CardContext(
        gear_id=gear.id,
        gear_name=gear.x_name or "(unnamed)",
        brand=_m2o_name(model.x_studio_partner_id),
        model_name=model.x_name,
        intent=intent,
        spec_groups=spec_groups,
        photos=photos,
        neck_profile=_build_neck_profile(gear),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _make_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug or "gear"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def generate_gear_card(conn, gear_ref: str, *, output_dir: Path) -> Path:
    """Fetch one gear item and write a product card HTML file.

    The filename is derived from the gear's x_name.
    Returns the path of the written file.
    """
    with _console.status("[bold cyan]Fetching gear record…[/bold cyan]"):
        field_meta = _get_gear_field_meta(conn)
        gear = _find_gear(conn, gear_ref, list(field_meta.keys()))
    _console.print(f"  [dim]Gear:[/dim] [bold]{gear.x_name}[/bold] [dim](id={gear.id})[/dim]")

    model: ModelRecord = ModelRecord()
    if gear.x_model_id:
        model_id = (
            gear.x_model_id[0] if isinstance(gear.x_model_id, (list, tuple)) else gear.x_model_id
        )
        with _console.status("[bold cyan]Fetching model…[/bold cyan]"):
            model = _fetch_model(conn, model_id)
        _console.print(f"  [dim]Model:[/dim] {model.x_name}")

    with _console.status("[bold cyan]Fetching listings…[/bold cyan]"):
        listings = _fetch_listings(conn, gear.id)
        m2m_resolved = _resolve_m2m_names(conn, gear, field_meta)
    _console.print(f"  [dim]Listings:[/dim] {len(listings)}")

    context = _build_context(gear, field_meta, model, listings, m2m_resolved)

    # Summary table
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    for group in context.spec_groups:
        table.add_row(group.title, ", ".join(v for _, v in group.specs))
    _console.print()
    _console.print(Panel(table, title=f"[bold]{gear.x_name}[/bold]", border_style="cyan"))

    env = _make_jinja_env()
    template = env.get_template("gear-card.html.j2")
    html_content = template.render(**context.model_dump())

    slug = _slugify(gear.x_name or "gear")
    output = output_dir / f"{slug}.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_content, encoding="utf-8")
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("gear-page")
@click.argument("gear_ref")
@click.option(
    "--output-dir",
    default=str(DEFAULT_OUTPUT_DIR),
    show_default=True,
    help="Directory to write the HTML file into.",
)
@click.pass_context
def cli(ctx: click.Context, gear_ref: str, output_dir: str) -> None:
    """Generate a shareable product card for a single gear item.

    GEAR_REF is either a numeric gear ID or a name (partial match).

    The output filename is derived from the gear name.
    Scans the live x_gear schema automatically so Studio-added fields
    are included without code changes.
    """
    conn = ctx.obj["conn"]
    out = generate_gear_card(conn, gear_ref, output_dir=Path(output_dir))
    _console.print(f"\n[bold green]✓[/bold green] Card written → [cyan]{out}[/cyan]")
