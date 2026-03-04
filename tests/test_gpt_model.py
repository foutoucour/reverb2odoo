"""Tests for gpt_model — GPT knowledge-base file generation."""

from __future__ import annotations

from gpt_model import GIBSON_PARTNER_IDS, _is_gibson, _strip_html


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
