"""Tests for gpt_model — GPT knowledge-base file generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from gpt_model import (
    GIBSON_PARTNER_IDS,
    _is_gibson,
    _is_pedal_amp,
    _render_tag,
    _strip_html,
    _write_tags_file,
)


class TestStripHtml:
    # ── Odoo div-based format (real examples) ─────────────────────────────

    def test_week33_single_text_then_url(self):
        """Week 33 — text line followed by a URL in an <a> tag."""
        raw = (
            '<div data-oe-version="1.2">Satin vintage Burst</div>'
            '<div><a href="https://youtu.be/tLwrtCSQiNg?si=Spp5nsXcSnGkwpgw&amp;t=1403">'
            "https://youtu.be/tLwrtCSQiNg?si=Spp5nsXcSnGkwpgw&amp;t=1403"
            "</a></div>"
        )
        assert _strip_html(raw) == (
            "Satin vintage Burst. https://youtu.be/tLwrtCSQiNg?si=Spp5nsXcSnGkwpgw&t=1403"
        )

    def test_week42_url_then_multiple_text_lines(self):
        """Week 42 — URL followed by two text lines."""
        raw = (
            '<div data-oe-version="1.2">'
            '<a href="https://youtu.be/tLwrtCSQiNg?si=YH1JPNpH2aFlE5Sm&amp;t=1789">'
            "https://youtu.be/tLwrtCSQiNg?si=YH1JPNpH2aFlE5Sm&amp;t=1789"
            "</a></div>"
            "<div>Dunno about the 3 pickups for now</div>"
            "<div>Dimarzio Super distortions. dunno</div>"
        )
        assert _strip_html(raw) == (
            "https://youtu.be/tLwrtCSQiNg?si=YH1JPNpH2aFlE5Sm&t=1789. "
            "Dunno about the 3 pickups for now. "
            "Dimarzio Super distortions. dunno"
        )

    # ── Other HTML structures ──────────────────────────────────────────────

    def test_br_tags(self):
        raw = "Line one<br>Line two<br/>Line three"
        assert _strip_html(raw) == "Line one. Line two. Line three"

    def test_p_tags(self):
        raw = "<p>First sentence.</p><p>Second sentence.</p>"
        assert _strip_html(raw) == "First sentence.. Second sentence."

    def test_html_entity_ampersand(self):
        raw = "<div>A &amp; B</div>"
        assert _strip_html(raw) == "A & B"

    def test_trailing_period_preserved(self):
        raw = "<div>Just one sentence.</div>"
        assert _strip_html(raw) == "Just one sentence."

    def test_empty_string(self):
        assert _strip_html("") == ""

    def test_false_like_empty(self):
        assert _strip_html(False) == ""  # type: ignore[arg-type]

    # ── Plain-text fallback (no HTML tags) ────────────────────────────────

    def test_newline_separated_plain_text(self):
        raw = "Line one\nLine two\nLine three"
        assert _strip_html(raw) == "Line one. Line two. Line three"

    def test_plain_text_no_markup(self):
        raw = "Just a plain note."
        assert _strip_html(raw) == "Just a plain note."


class TestIsGibson:
    def test_gibson_partner_id(self):
        assert _is_gibson({"x_studio_partner_id": [38, "Gibson"]})

    def test_gibson_custom_shop_partner_id(self):
        assert _is_gibson({"x_studio_partner_id": [42, "Gibson Custom Shop"]})

    def test_epiphone_partner_id(self):
        assert _is_gibson({"x_studio_partner_id": [120, "Epiphone Guitars"]})

    def test_other_brand_not_gibson(self):
        assert not _is_gibson({"x_studio_partner_id": [99, "Fender"]})

    def test_no_brand_not_gibson(self):
        assert not _is_gibson({"x_studio_partner_id": False})

    def test_missing_field_not_gibson(self):
        assert not _is_gibson({})

    def test_gibson_partner_ids_constant(self):
        assert 38 in GIBSON_PARTNER_IDS  # Gibson
        assert 42 in GIBSON_PARTNER_IDS  # Gibson Custom Shop
        assert 120 in GIBSON_PARTNER_IDS  # Epiphone Guitars


class TestRenderTag:
    @pytest.mark.parametrize(
        "record, expected",
        [
            pytest.param(
                {"x_name": "fretboard-Rosewood", "x_studio_score": 85},
                "### fretboard-Rosewood\n\n- score: 85\n",
                id="renders-name-and-score",
            ),
            pytest.param(
                {"x_name": "scale-24.75", "x_studio_score": 0},
                "### scale-24.75\n\n- score: 0\n",
                id="zero-score",
            ),
            pytest.param(
                {"x_name": "finish-Nitrocellulose Lacquer", "x_studio_score": False},
                "### finish-Nitrocellulose Lacquer\n\n- score: 0\n",
                id="false-score-becomes-zero",
            ),
            pytest.param(
                {"x_name": "nech-slim"},
                "### nech-slim\n\n- score: 0\n",
                id="missing-score-becomes-zero",
            ),
        ],
    )
    def test_render_tag(self, record: dict, expected: str) -> None:
        assert _render_tag(record) == expected


class TestIsPedalAmp:
    @pytest.mark.parametrize(
        "name, expected",
        [
            pytest.param("pedal-overdrive", True, id="pedal-prefix"),
            pytest.param("pedal-klon", True, id="pedal-klon"),
            pytest.param("amp-speaker", True, id="amp-prefix"),
            pytest.param("amp", False, id="amp-exact-no-dash-is-not-pedal-amp"),
            pytest.param("fretboard-Ebony", False, id="guitar-tag"),
            pytest.param("scale-24.75", False, id="scale-tag"),
            pytest.param("body-semi-hollow", False, id="body-tag"),
            pytest.param("", False, id="empty-name"),
        ],
    )
    def test_is_pedal_amp(self, name: str, expected: bool) -> None:
        assert _is_pedal_amp({"x_name": name}) == expected


class TestWriteTagsFile:
    def _weighted(self, names_scores: list[tuple[str, int]]) -> list[dict]:
        return [{"x_name": n, "x_studio_score": s} for n, s in names_scores]

    def test_three_sections_in_file(self, tmp_path: Path) -> None:
        weighted = self._weighted(
            [
                ("fretboard-Ebony", 90),
                ("pedal-overdrive", 40),
                ("amp-speaker", 20),
            ]
        )
        family = [{"x_name": "body-semi-hollow", "x_studio_score": 5}]
        out = tmp_path / "tags.md"

        n_guitar, n_family, n_pedal_amp = _write_tags_file(out, weighted, family)

        assert n_guitar == 1
        assert n_family == 1
        assert n_pedal_amp == 2
        content = out.read_text()
        assert "# Tags Knowledge Base" in content
        assert "Section 1" in content
        assert "Section 2" in content
        assert "Section 3" in content
        assert "### fretboard-Ebony" in content
        assert "### body-semi-hollow" in content
        assert "### pedal-overdrive" in content
        assert "### amp-speaker" in content

    def test_guitar_tags_exclude_pedal_amp(self, tmp_path: Path) -> None:
        weighted = self._weighted([("fretboard-Ebony", 90), ("pedal-klon", 30)])
        out = tmp_path / "tags.md"
        n_guitar, _, n_pedal_amp = _write_tags_file(out, weighted, [])
        assert n_guitar == 1
        assert n_pedal_amp == 1
        content = out.read_text()
        s1_end = content.index("Section 2")
        assert "### fretboard-Ebony" in content[:s1_end]
        assert "### pedal-klon" not in content[:s1_end]

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir" / "tags.md"
        _write_tags_file(out, [], [])
        assert out.exists()

    def test_empty_records(self, tmp_path: Path) -> None:
        out = tmp_path / "tags.md"
        n_guitar, n_family, n_pedal_amp = _write_tags_file(out, [], [])
        assert n_guitar == 0
        assert n_family == 0
        assert n_pedal_amp == 0
        assert "# Tags Knowledge Base" in out.read_text()
