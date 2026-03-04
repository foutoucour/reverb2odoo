"""Generate RAG-optimised knowledge-base markdown files for ChatGPT.

Two files are produced:

  - ``gpt-files/models_gibson.md``
      Gibson, Gibson Custom Shop, and Epiphone Guitars models.
  - ``gpt-files/models_others.md``
      All other brands.

Run with::

    reverb2odoo gpt-files
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import click
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: res.partner IDs that go into the Gibson file.
#:   38  → Gibson
#:   42  → Gibson Custom Shop
#:  120  → Epiphone Guitars
GIBSON_PARTNER_IDS: frozenset[int] = frozenset({38, 42, 120})

#: Default output paths.
DEFAULT_GIBSON_FILE = Path("gpt-files/models_gibson.md")
DEFAULT_OTHER_FILE = Path("gpt-files/models_others.md")

#: Header preamble shared by both files (matches the existing hand-edited files).
_HEADER = """\
# Gear Knowledge Base

Note:
    This document is only what I am tracking, not the only liste you should consider.
    I want to use this list as a base, not as the definitive listing.
    You will use the headers to understand the criterias you need to find
    when we discover new models.

## Fiches détaillées

"""

#: Fields to fetch from x_models.
_MODEL_FIELDS: list[str] = [
    "x_name",
    "x_studio_partner_id",
    "x_studio_model_type",
    "x_studio_guitar_familly_ids",
    "x_studio_guitar_neck_feel_id",
    "x_studio_scale",
    "x_studio_finish",
    "x_studio_fretboard_1",
    "x_studio_web_page_1",
    "x_studio_notes",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts).strip()


_SEP = "\x00"  # internal sentence-break sentinel


def _strip_html(raw: str) -> str:
    """Return plain text from an HTML string, with entities decoded.

    ``<br>`` and ``</p>`` are replaced with a sentinel before tag-stripping,
    then the text is split on the sentinel and joined with ``". "`` so
    sentences stay readable without adding stray punctuation.
    """
    if not raw:
        return ""
    text = re.sub(r"<br\s*/?>", _SEP, raw, flags=re.IGNORECASE)
    text = re.sub(r"</p>", _SEP, text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", _SEP, text, flags=re.IGNORECASE)
    stripper = _HTMLStripper()
    stripper.feed(html.unescape(text))
    plain = stripper.get_text()
    # Split on sentinel (from <br>/<p>) and also on bare newlines (plain-text notes)
    parts = [p.strip() for p in re.split(rf"[{_SEP}\n]", plain) if p.strip()]
    return ". ".join(parts)


def _m2o_name(value: Any) -> str:
    """Extract the display name from a many2one value (``[id, name]`` or ``False``)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return str(value[1])
    return ""


def _fetch_construction_map(conn) -> dict[int, str]:
    """Return a mapping of construction-record id → display name.

    The comodel name is discovered dynamically via ``fields_get`` so the code
    does not need to hard-code the Odoo Studio internal model name.
    """
    x_models = conn.get_model("x_models")
    fields_meta = x_models.fields_get(["x_studio_guitar_familly_ids"])
    comodel: str = fields_meta.get("x_studio_guitar_familly_ids", {}).get("relation", "")
    if not comodel:
        logger.warning("Could not determine construction comodel — construction will be empty")
        return {}
    construction_model = conn.get_model(comodel)
    records = construction_model.search_read([], ["x_name"])
    return {r["id"]: r["x_name"] for r in records}


def _fetch_models(conn) -> list[dict]:
    """Fetch all x_models records sorted by name."""
    model = conn.get_model("x_models")
    return model.search_read([], _MODEL_FIELDS, order="x_name asc")


def _is_gibson(record: dict) -> bool:
    """Return ``True`` if the record belongs to the Gibson family.

    Matches against :data:`GIBSON_PARTNER_IDS` (the res.partner IDs for
    Gibson, Gibson Custom Shop, and Epiphone Guitars).
    """
    partner = record.get("x_studio_partner_id", False)
    if not isinstance(partner, (list, tuple)):
        return False
    return partner[0] in GIBSON_PARTNER_IDS


def _render_model(record: dict, construction_map: dict[int, str]) -> str:
    """Render a single model record as a markdown ``###`` section."""
    name = record.get("x_name", "")
    brand = _m2o_name(record.get("x_studio_partner_id", False))
    model_type = record.get("x_studio_model_type", "") or ""

    # construction is many2many — join names with " + "
    construction_ids: list[int] = record.get("x_studio_guitar_familly_ids", []) or []
    construction = " + ".join(
        construction_map[cid] for cid in construction_ids if cid in construction_map
    )

    neck_feel = _m2o_name(record.get("x_studio_guitar_neck_feel_id", False))
    scale = record.get("x_studio_scale", "") or ""
    finish = _m2o_name(record.get("x_studio_finish", False))
    fretboard = _m2o_name(record.get("x_studio_fretboard_1", False))
    web_page = record.get("x_studio_web_page_1", "") or ""
    notes = _strip_html(record.get("x_studio_notes", "") or "")

    return (
        f"### {name}\n"
        f"\n"
        f"- brand: {brand}\n"
        f"- Model type: {model_type}\n"
        f"- construction: {construction}\n"
        f"- neckFeel: {neck_feel}\n"
        f"- scale: {scale}\n"
        f"- finish: {finish}\n"
        f"- fretboard: {fretboard}\n"
        f"- web page: {web_page}\n"
        f"- notes: {notes}\n"
    )


def _write_file(path: Path, records: list[dict], construction_map: dict[int, str]) -> int:
    """Write the markdown file for *records* to *path*.

    Returns the number of model sections written.
    """
    sections = "\n".join(_render_model(r, construction_map) for r in records)
    content = _HEADER + sections + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return len(records)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("gpt-files")
@click.option(
    "--gibson-file",
    default=str(DEFAULT_GIBSON_FILE),
    show_default=True,
    help="Output path for the Gibson / Epiphone models file.",
)
@click.option(
    "--other-file",
    default=str(DEFAULT_OTHER_FILE),
    show_default=True,
    help="Output path for the non-Gibson models file.",
)
@click.pass_context
def cli(ctx: click.Context, gibson_file: str, other_file: str) -> None:
    """Generate RAG-optimised knowledge-base markdown files for ChatGPT.

    Reads every model from Odoo's x_models catalogue and writes two files:
    one for Gibson / Gibson Custom brands, one for everything else.
    """
    conn = ctx.obj["conn"]

    logger.info("Fetching all models from Odoo…")
    records = _fetch_models(conn)
    logger.info("Found {} model(s)", len(records))

    logger.info("Resolving construction values…")
    construction_map = _fetch_construction_map(conn)

    gibson_records = [r for r in records if _is_gibson(r)]
    other_records = [r for r in records if not _is_gibson(r)]

    gibson_path = Path(gibson_file)
    other_path = Path(other_file)

    n_gibson = _write_file(gibson_path, gibson_records, construction_map)
    logger.success("Gibson file: {} model(s) → {}", n_gibson, gibson_path)

    n_other = _write_file(other_path, other_records, construction_map)
    logger.success("Other file: {} model(s) → {}", n_other, other_path)
