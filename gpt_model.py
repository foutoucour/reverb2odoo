"""Generate RAG-optimised knowledge-base markdown files for ChatGPT.

Three files are produced:

  - ``gpt-files/models_gibson.md``
      Gibson, Gibson Custom Shop, and Epiphone Guitars models.
  - ``gpt-files/models_others.md``
      All other brands.
  - ``gpt-files/tags.md``
      All x_guitar_familly tags with their score.

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
DEFAULT_TAGS_FILE = Path("gpt-files/tags.md")

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
    "x_studio_family_ids",
    "x_studio_weighted_tag_ids",
    "x_studio_weighted_score",
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


def _fetch_family_map(conn) -> dict[int, str]:
    """Return a mapping of x_guitar_familly id → display name."""
    try:
        comodel = _discover_tags_comodel(conn)
    except RuntimeError:
        logger.warning("Could not determine family comodel — family will be empty")
        return {}
    records = conn.get_model(comodel).search_read([], ["x_name"])
    return {r["id"]: r["x_name"] for r in records}


def _fetch_weighted_tags_map(conn) -> dict[int, str]:
    """Return a mapping of x_weighted_tags id → display name."""
    records = conn.get_model("x_weighted_tags").search_read([], ["x_name"])
    return {r["id"]: r["x_name"] for r in records}


_TAGS_FIELDS: list[str] = ["x_name", "x_studio_score"]

#: Prefixes that identify pedal / amp weighted tags.
_PEDAL_AMP_PREFIXES: tuple[str, ...] = ("pedal-", "amp-")

_TAGS_FILE_HEADER = """\
# Tags Knowledge Base

This file contains three independent reference sections used to describe and
score guitar models, their construction families, and related gear.

Each entry has a `score` (higher = more desirable / relevant).

---

"""

_SECTION_GUITAR_TAGS = """\
## Section 1 — Guitar Weighted Tags

Use these tags to describe individual guitar characteristics (body, neck,
fretboard, scale, finish, pickups, shape, etc.).
Tags starting with `pedal-` or `amp-` are excluded from this section.

"""

_SECTION_FAMILY = """\
## Section 2 — Construction Families

These are the core construction families that a guitar model can belong to.
They capture higher-level structural traits shared across multiple models.

"""

_SECTION_PEDAL_AMP_TAGS = """\
## Section 3 — Pedal and Amp Weighted Tags

Use these tags to describe pedals and amplifiers.
Only tags starting with `pedal-` or `amp-` are included here.

"""


def _discover_tags_comodel(conn) -> str:
    """Return the comodel name for x_studio_family_ids."""
    x_models = conn.get_model("x_models")
    meta = x_models.fields_get(["x_studio_family_ids"])
    comodel: str = meta.get("x_studio_family_ids", {}).get("relation", "")
    if not comodel:
        raise RuntimeError("Cannot determine comodel for x_studio_family_ids")
    return comodel


def _fetch_family_tags(conn) -> list[dict]:
    """Fetch all x_guitar_familly records sorted by name."""
    comodel = _discover_tags_comodel(conn)
    return conn.get_model(comodel).search_read([], _TAGS_FIELDS, order="x_name asc")


def _fetch_weighted_tags(conn) -> list[dict]:
    """Fetch all x_weighted_tags records sorted by name."""
    return conn.get_model("x_weighted_tags").search_read([], _TAGS_FIELDS, order="x_name asc")


def _is_pedal_amp(record: dict) -> bool:
    """Return True if the tag name starts with a pedal- or amp- prefix."""
    return record.get("x_name", "").startswith(_PEDAL_AMP_PREFIXES)


def _render_tag(record: dict) -> str:
    """Render a single tag record as a markdown ``###`` section."""
    name = record.get("x_name", "")
    score = record.get("x_studio_score") or 0
    return f"### {name}\n\n- score: {score}\n"


def _render_tag_section(header: str, records: list[dict]) -> str:
    """Render a labelled section of tags."""
    body = "\n".join(_render_tag(r) for r in records)
    return header + body + "\n"


def _write_tags_file(
    path: Path,
    weighted_tags: list[dict],
    family_tags: list[dict],
) -> tuple[int, int, int]:
    """Write the three-section tags file to *path*.

    Returns (n_guitar_tags, n_family_tags, n_pedal_amp_tags).
    """
    guitar_tags = [r for r in weighted_tags if not _is_pedal_amp(r)]
    pedal_amp_tags = [r for r in weighted_tags if _is_pedal_amp(r)]

    content = (
        _TAGS_FILE_HEADER
        + _render_tag_section(_SECTION_GUITAR_TAGS, guitar_tags)
        + "\n---\n\n"
        + _render_tag_section(_SECTION_FAMILY, family_tags)
        + "\n---\n\n"
        + _render_tag_section(_SECTION_PEDAL_AMP_TAGS, pedal_amp_tags)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return len(guitar_tags), len(family_tags), len(pedal_amp_tags)


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


def _render_model(
    record: dict,
    family_map: dict[int, str],
    weighted_tags_map: dict[int, str],
) -> str:
    """Render a single model record as a markdown ``###`` section."""
    name = record.get("x_name", "")
    brand = _m2o_name(record.get("x_studio_partner_id", False))
    model_type = record.get("x_studio_model_type", "") or ""

    family_ids: list[int] = record.get("x_studio_family_ids", []) or []
    family = " + ".join(family_map[fid] for fid in family_ids if fid in family_map)

    tag_ids: list[int] = record.get("x_studio_weighted_tag_ids", []) or []
    tags = " + ".join(weighted_tags_map[tid] for tid in tag_ids if tid in weighted_tags_map)

    score = record.get("x_studio_weighted_score") or 0
    web_page = record.get("x_studio_web_page_1", "") or ""
    notes = _strip_html(record.get("x_studio_notes", "") or "")

    return (
        f"### {name}\n"
        f"\n"
        f"- brand: {brand}\n"
        f"- Model type: {model_type}\n"
        f"- score: {score}\n"
        f"- family: {family}\n"
        f"- tags: {tags}\n"
        f"- web page: {web_page}\n"
        f"- notes: {notes}\n"
    )


def _write_file(
    path: Path,
    records: list[dict],
    family_map: dict[int, str],
    weighted_tags_map: dict[int, str],
) -> int:
    """Write the markdown file for *records* to *path*.

    Returns the number of model sections written.
    """
    sections = "\n".join(_render_model(r, family_map, weighted_tags_map) for r in records)
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
@click.option(
    "--tags-file",
    default=str(DEFAULT_TAGS_FILE),
    show_default=True,
    help="Output path for the tags (x_guitar_familly) file.",
)
@click.pass_context
def cli(ctx: click.Context, gibson_file: str, other_file: str, tags_file: str) -> None:
    """Generate RAG-optimised knowledge-base markdown files for ChatGPT.

    Reads every model from Odoo's x_models catalogue and writes three files:
    one for Gibson / Gibson Custom brands, one for everything else, and one
    listing all tags with their score.
    """
    conn = ctx.obj["conn"]

    logger.info("Fetching all models from Odoo…")
    records = _fetch_models(conn)
    logger.info("Found {} model(s)", len(records))

    logger.info("Resolving families and weighted tags…")
    family_map = _fetch_family_map(conn)
    weighted_tags_map = _fetch_weighted_tags_map(conn)

    gibson_records = [r for r in records if _is_gibson(r)]
    other_records = [r for r in records if not _is_gibson(r)]

    gibson_path = Path(gibson_file)
    other_path = Path(other_file)
    tags_path = Path(tags_file)

    n_gibson = _write_file(gibson_path, gibson_records, family_map, weighted_tags_map)
    logger.success("Gibson file: {} model(s) → {}", n_gibson, gibson_path)

    n_other = _write_file(other_path, other_records, family_map, weighted_tags_map)
    logger.success("Other file: {} model(s) → {}", n_other, other_path)

    logger.info("Fetching weighted tags and families from Odoo…")
    weighted_tags = _fetch_weighted_tags(conn)
    family_tags = _fetch_family_tags(conn)
    n_guitar, n_family, n_pedal_amp = _write_tags_file(tags_path, weighted_tags, family_tags)
    logger.success(
        "Tags file: {} guitar tag(s), {} famil(ies), {} pedal/amp tag(s) → {}",
        n_guitar,
        n_family,
        n_pedal_amp,
        tags_path,
    )
