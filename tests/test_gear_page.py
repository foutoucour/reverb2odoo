"""Tests for the gear card generator (gear_page.py).

Covers the 3-column card layout: template rendering, the screenshot
viewport, the height budget that makes the card fit one screen, and the
light (GitHub Primer) palette the card shares with cot-ci-hub.
"""

from __future__ import annotations

import base64
import re
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gear_page import (
    RENDER_VIEWPORT_HEIGHT,
    RENDER_VIEWPORT_WIDTH,
    CardContext,
    NeckProfile,
    SpecGroup,
    _make_jinja_env,
    _render_image,
)

#: Vertical page padding on <body> in the template, above and below the card.
_BODY_PADDING_Y = 24

#: 1x1 transparent GIF — stands in for a gear photo in structural assertions.
#: Height-budget checks use a real photo instead, since the photo renders at its
#: natural aspect ratio and so does contribute to the card height.
_PLACEHOLDER_IMAGE = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"


def _photo(width: int, height: int) -> str:
    """Return a base64 solid-grey PNG of the given size.

    Only the aspect ratio matters: the card height depends on how tall the
    photo renders in the left rail, not on its content.
    """
    scanlines = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode()


def _spec_groups() -> list[SpecGroup]:
    """Spec groups matching what _build_spec_groups emits for a real guitar."""
    return [
        SpecGroup(
            title="Instrument",
            style="tiles",
            specs=[
                ("Production Year", "2022"),
                ("Acquiring Date", "2023"),
                ("Serial Number", "210420327"),
                ("Condition", "Fair"),
            ],
        ),
        SpecGroup(
            title="Materials & Finish",
            style="rows",
            specs=[
                ("Body Material", "Mahogany"),
                ("Top Cap Material", "Plain Maple"),
                ("Body Finish", "Satin Nitro"),
                ("Neck Material", "Mahogany"),
                ("Fretboard Material", "Indian Rosewood"),
                ("Neck Finish", "Satin Nitro"),
            ],
        ),
        SpecGroup(
            title="Pickups",
            style="tiles-wide",
            specs=[("Bridge", "Gibson Burstbucker 2"), ("Neck", "Gibson Burstbucker 1")],
        ),
        SpecGroup(
            title="Measurements",
            style="rows",
            specs=[
                ("Scale length", "62.87 cm / 24.75 in"),
                ("Scale radius", "30.48 cm / 12 in"),
                ("Weight", "4.26 kg / 9.39 lbs"),
            ],
        ),
    ]


def _card_context() -> CardContext:
    """A fully populated card context — every section present."""
    return CardContext(
        gear_id=42,
        gear_name="Honeybee",
        brand="Gibson",
        model_name="Les Paul Classic 2019 - 2024",
        intent="Keeper",
        spec_groups=_spec_groups(),
        photos=[_PLACEHOLDER_IMAGE],
        neck_profile=NeckProfile(
            nut_width_mm=43.0,
            thickness_1st_mm=21.0,
            thickness_12th_mm=23.5,
            nut_width_disp='43.0 mm  1.693"',
            thickness_1st_disp='21.0 mm  0.827"',
            thickness_12th_disp='23.5 mm  0.925"',
        ),
        weight_lbs=9.39,
    )


@pytest.fixture
def card_context() -> CardContext:
    return _card_context()


def _render_html(context: CardContext) -> str:
    env = _make_jinja_env()
    return env.get_template("gear-card.html.j2").render(**context.model_dump())


# ---------------------------------------------------------------------------
# Template structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fragment",
    [
        pytest.param(
            "grid-template-columns: var(--col-media) 1fr 1fr",
            id="card-declares-three-columns",
        ),
        pytest.param("columns: 2", id="body-splits-specs-into-two-columns"),
        pytest.param("break-inside: avoid", id="sections-do-not-split-across-columns"),
        pytest.param('<div class="media">', id="photo-and-title-share-the-left-rail"),
        pytest.param("@media (max-width: 1100px)", id="falls-back-to-one-column-when-narrow"),
    ],
)
def test_template_declares_three_column_layout(card_context: CardContext, fragment: str) -> None:
    assert fragment in _render_html(card_context)


def test_render_includes_every_spec_group(card_context: CardContext) -> None:
    html = _render_html(card_context)
    for group in card_context.spec_groups:
        assert group.title in html, f"missing section {group.title!r}"
        for label, value in group.specs:
            assert label in html, f"missing label {label!r}"
            assert value in html, f"missing value {value!r}"


@pytest.mark.parametrize(
    "photos, expected",
    [
        pytest.param([_PLACEHOLDER_IMAGE], "data:image/jpeg;base64,", id="renders-photo-when-set"),
        pytest.param([], "No photo", id="renders-placeholder-when-photo-missing"),
    ],
)
def test_photo_rail_handles_missing_photo(
    card_context: CardContext, photos: list[str], expected: str
) -> None:
    card_context.photos = photos
    assert expected in _render_html(card_context)


def test_title_renders_model_name(card_context: CardContext) -> None:
    assert card_context.model_name in _render_html(card_context)


@pytest.mark.parametrize(
    "photo_markup",
    [
        pytest.param('<div class="photos">', id="with-photo"),
        pytest.param('<div class="photos-empty">', id="without-photo"),
    ],
)
def test_title_sits_above_the_photo(card_context: CardContext, photo_markup: str) -> None:
    """The title bar caps the left rail; the photo hangs beneath it."""
    card_context.photos = [_PLACEHOLDER_IMAGE] if photo_markup == '<div class="photos">' else []
    html = _render_html(card_context)

    rail = html.index('<div class="media">')
    title = html.index('<div class="header">', rail)
    photo = html.index(photo_markup, rail)
    assert title < photo, "title must render before the photo inside the rail"


# ---------------------------------------------------------------------------
# Screenshot viewport
# ---------------------------------------------------------------------------


def test_render_image_uses_the_wide_viewport(tmp_path: Path) -> None:
    """The screenshot must be taken at the 3-column width, not the old 760px."""
    html_path = tmp_path / "card.html"
    html_path.write_text("<html><body>card</body></html>", encoding="utf-8")

    page = MagicMock()
    browser = MagicMock()
    browser.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser

    with patch("gear_page.sync_playwright") as sync_pw:
        sync_pw.return_value.__enter__.return_value = playwright
        png_path = _render_image(html_path)

    assert browser.new_page.call_args.kwargs["viewport"] == {
        "width": RENDER_VIEWPORT_WIDTH,
        "height": RENDER_VIEWPORT_HEIGHT,
    }
    assert png_path == html_path.with_suffix(".png")


def test_render_image_captures_the_card_not_the_page(tmp_path: Path) -> None:
    """The card is shorter than the viewport — a full-page shot would pad it."""
    html_path = tmp_path / "card.html"
    html_path.write_text("<html><body>card</body></html>", encoding="utf-8")

    page = MagicMock()
    browser = MagicMock()
    browser.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser

    with patch("gear_page.sync_playwright") as sync_pw:
        sync_pw.return_value.__enter__.return_value = playwright
        png_path = _render_image(html_path)

    page.screenshot.assert_not_called()
    page.locator.assert_called_once_with(".card")
    page.locator.return_value.screenshot.assert_called_once_with(path=str(png_path))


def test_render_viewport_is_landscape() -> None:
    """A card that fits 'one screen' must be wider than it is tall."""
    assert RENDER_VIEWPORT_WIDTH > RENDER_VIEWPORT_HEIGHT


# ---------------------------------------------------------------------------
# Height budget — the acceptance criterion for "fits on one screen"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "photo",
    [
        pytest.param(_photo(40, 30), id="landscape-photo"),
        pytest.param(_photo(30, 30), id="square-photo"),
        # Guitars are often shot vertically; an uncapped tall photo used to
        # push the card past the viewport.
        pytest.param(_photo(30, 40), id="portrait-photo"),
        pytest.param(_photo(18, 32), id="tall-portrait-photo"),
        pytest.param(None, id="no-photo"),
    ],
)
def test_card_fits_within_one_screen(
    card_context: CardContext, tmp_path: Path, photo: str | None
) -> None:
    """A fully populated card must not overflow the render viewport."""
    playwright_api = pytest.importorskip("playwright.sync_api")

    card_context.photos = [photo] if photo else []
    html_path = tmp_path / "card.html"
    html_path.write_text(_render_html(card_context), encoding="utf-8")

    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": RENDER_VIEWPORT_WIDTH, "height": RENDER_VIEWPORT_HEIGHT}
        )
        page.goto(f"file://{html_path.resolve()}", wait_until="load")
        scroll_height = page.evaluate("document.documentElement.scrollHeight")
        card_height = page.evaluate(
            "document.querySelector('.card').getBoundingClientRect().height"
        )
        column_count = page.evaluate(
            "getComputedStyle(document.querySelector('.card'))"
            ".gridTemplateColumns.split(' ').length"
        )
        browser.close()

    assert column_count == 3, f"expected 3 card columns, got {column_count}"
    # scrollHeight floors at the viewport height, so it only detects overflow.
    assert scroll_height <= RENDER_VIEWPORT_HEIGHT, (
        f"page scrolls to {scroll_height}px, overflowing the {RENDER_VIEWPORT_HEIGHT}px viewport"
    )
    # The card itself must clear the viewport minus the body padding.
    budget = RENDER_VIEWPORT_HEIGHT - 2 * _BODY_PADDING_Y
    assert card_height <= budget, f"card is {card_height:.0f}px tall, budget is {budget}px"


# ---------------------------------------------------------------------------
# Light mode — the card's palette mirrors cot-ci-hub's GitHub Primer tokens
# ---------------------------------------------------------------------------

#: Relative luminance either side of which a colour reads as a light surface or
#: as dark ink on one. Mid-grey (#777) sits at ~0.19, so the split is nowhere
#: near any colour the palette actually uses.
_LIGHT_SURFACE_LUMINANCE = 0.5

#: WCAG AA for body text. The failure this guards is specific: a colour picked
#: to sit on a near-black card (the old --text-dim #8890a8) still "looks fine"
#: on white while failing contrast outright.
_WCAG_AA_CONTRAST = 4.5

#: Hex literals from the dark palette the card used before the switch, spanning
#: both the stylesheet and the inline SVG diagrams, whose presentation
#: attributes no computed-style check reaches.
_DARK_PALETTE_LITERALS = (
    "#0e0f14",  # page canvas
    "#13151c",  # card, and the header/footer gradients
    "#1c1f2b",  # spec tiles, and the weight-gauge track
    "#181b26",  # zebra rows
    "#252836",  # borders
    "#1e2130",  # row separators
    "#080a10",  # photo letterbox
    "#e4e6f0",  # body text, and the weight-gauge marker
    "#8890a8",  # dimmed text, and the neck-profile measurements
    "#434a5e",  # muted text, and the weight-gauge ticks
    "#7b61ff",  # accent, in the title gradient
    "#f0a732",  # gold section titles, and the neck-profile annotation
    "#2dd4bf",  # teal spec values, and the gauge's light end
    "#2a1f14",  # neck cross-section fill
    "#5a2d0c",  # fingerboard edge
    "#c8963c",  # neck cross-section outline
)

#: Every (selector, property) the light-mode checks read, resolved in a single
#: browser session — one Chromium launch per parametrized case would dominate
#: the suite's runtime.
_COLOUR_PROBES: tuple[tuple[str, str], ...] = (
    ("body", "backgroundColor"),
    (".card", "backgroundColor"),
    (".header", "backgroundColor"),
    (".footer", "backgroundColor"),
    (".spec", "backgroundColor"),
    (".mrow:nth-child(even)", "backgroundColor"),
    (".title", "color"),
    (".section-title", "color"),
    (".spec-label", "color"),
    (".spec-value", "color"),
    (".mrow-label", "color"),
    (".mrow-value", "color"),
    (".footer", "color"),
)


def _parse_rgb(css_colour: str) -> tuple[int, int, int]:
    """Pull the RGB triple out of a computed `rgb()` / `rgba()` string."""
    channels = [int(n) for n in re.findall(r"\d+", css_colour)[:3]]
    return channels[0], channels[1], channels[2]


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB triple."""

    def linearize(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linearize(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two sRGB triples."""
    lighter, darker = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.fixture(scope="module")
def computed_colours(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Computed colours for `_COLOUR_PROBES`, keyed `"<selector> <property>"`."""
    playwright_api = pytest.importorskip("playwright.sync_api")

    html_path = tmp_path_factory.mktemp("light") / "card.html"
    html_path.write_text(_render_html(_card_context()), encoding="utf-8")

    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{html_path.resolve()}", wait_until="load")
        colours = {
            f"{selector} {prop}": page.evaluate(
                f"getComputedStyle(document.querySelector('{selector}')).{prop}"
            )
            for selector, prop in _COLOUR_PROBES
        }
        browser.close()

    return colours


@pytest.mark.parametrize(
    "selector",
    [
        pytest.param("body", id="page-canvas"),
        pytest.param(".card", id="card"),
        pytest.param(".header", id="title-band"),
        pytest.param(".footer", id="footer-band"),
        pytest.param(".spec", id="spec-tile"),
        pytest.param(".mrow:nth-child(even)", id="zebra-row"),
    ],
)
def test_surfaces_are_light(computed_colours: dict[str, str], selector: str) -> None:
    """Every surface the card paints is a light one — this is not a dark card."""
    colour = computed_colours[f"{selector} backgroundColor"]
    luminance = _relative_luminance(_parse_rgb(colour))
    assert luminance > _LIGHT_SURFACE_LUMINANCE, (
        f"{selector} paints {colour} (luminance {luminance:.2f}), which is a dark surface"
    )


@pytest.mark.parametrize(
    "selector",
    [
        pytest.param(".title", id="title"),
        pytest.param(".section-title", id="section-title"),
        pytest.param(".spec-label", id="spec-label"),
        pytest.param(".spec-value", id="spec-value"),
        pytest.param(".mrow-label", id="row-label"),
        pytest.param(".mrow-value", id="row-value"),
        pytest.param(".footer", id="footer"),
    ],
)
def test_text_is_dark_ink(computed_colours: dict[str, str], selector: str) -> None:
    """Text is ink on the light surface, not the pale type a dark card needs."""
    colour = computed_colours[f"{selector} color"]
    luminance = _relative_luminance(_parse_rgb(colour))
    assert luminance < _LIGHT_SURFACE_LUMINANCE, (
        f"{selector} writes in {colour} (luminance {luminance:.2f}), which is light-on-light"
    )


@pytest.mark.parametrize(
    "selector, surface",
    [
        pytest.param(".section-title", ".card", id="section-title-on-card"),
        pytest.param(".spec-label", ".spec", id="spec-label-on-tile"),
        pytest.param(".spec-value", ".spec", id="spec-value-on-tile"),
        # Odd rows are transparent, so their backdrop is the card itself.
        pytest.param(".mrow-label", ".card", id="row-label-on-card"),
        pytest.param(".mrow-value", ".card", id="row-value-on-card"),
        pytest.param(".mrow-label", ".mrow:nth-child(even)", id="row-label-on-zebra"),
        pytest.param(".mrow-value", ".mrow:nth-child(even)", id="row-value-on-zebra"),
        pytest.param(".title", ".header", id="title-on-band"),
        pytest.param(".footer", ".footer", id="footer-on-band"),
    ],
)
def test_text_clears_wcag_aa_against_its_surface(
    computed_colours: dict[str, str], selector: str, surface: str
) -> None:
    fg = _parse_rgb(computed_colours[f"{selector} color"])
    bg = _parse_rgb(computed_colours[f"{surface} backgroundColor"])
    ratio = _contrast_ratio(fg, bg)
    assert ratio >= _WCAG_AA_CONTRAST, (
        f"{selector} on {surface} contrasts {ratio:.2f}:1, below AA's {_WCAG_AA_CONTRAST}:1"
    )


@pytest.mark.parametrize(
    "literal",
    [pytest.param(hexcode, id=f"drops-{hexcode[1:]}") for hexcode in _DARK_PALETTE_LITERALS],
)
def test_no_dark_palette_literal_survives(card_context: CardContext, literal: str) -> None:
    """Catches a dark colour left behind in an SVG diagram, where no computed
    style check on the stylesheet would reach it."""
    assert literal not in _render_html(card_context).lower()
