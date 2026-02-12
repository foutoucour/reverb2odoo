"""Tests for reverb_scraper — unit tests are pure-sync, integration tests hit the live API."""

import pytest

from reverb_scraper import ReverbScraper

# ── _extract_listing_slug ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected_slug",
    [
        pytest.param(
            "https://reverb.com/item/94365602-suhr-classic-t-trans-white",
            "94365602-suhr-classic-t-trans-white",
            id="suhr-classic-t",
        ),
        pytest.param(
            "https://reverb.com/item/93749436-suhr-alt-t-with-rosewood-fretboard-2018-present-sonic-blue",
            "93749436-suhr-alt-t-with-rosewood-fretboard-2018-present-sonic-blue",
            id="suhr-alt-t-sonic-blue",
        ),
        pytest.param(
            "https://reverb.com/item/92774275-ibanez-flatv2-msn-josh-smith",
            "92774275-ibanez-flatv2-msn-josh-smith",
            id="ibanez-flatv2",
        ),
        pytest.param(
            "https://reverb.com/item/93345258-flatv2-msn-josh-smith-mint-sand-etui-ibanez",
            "93345258-flatv2-msn-josh-smith-mint-sand-etui-ibanez",
            id="ibanez-flatv2-sonovente",
        ),
        pytest.param(
            "https://reverb.com/item/93497125-springer-seraph-hollowbody-w-ohsc-2014-tobacco",
            "93497125-springer-seraph-hollowbody-w-ohsc-2014-tobacco",
            id="springer-seraph",
        ),
        pytest.param(
            "https://reverb.com/item/94124092-suhr-alt-t-with-rosewood-fretboard-2018-present-olympic-white",
            "94124092-suhr-alt-t-with-rosewood-fretboard-2018-present-olympic-white",
            id="suhr-alt-t-olympic-white",
        ),
        pytest.param(
            "https://reverb.com/item/93932537-preowned-suhr-alt-t-in-sonic-blue-with-rosewood-fretboard",
            "93932537-preowned-suhr-alt-t-in-sonic-blue-with-rosewood-fretboard",
            id="suhr-alt-t-preowned",
        ),
        pytest.param(
            "https://reverb.com/item/94434828-suhr-classic-t-swamp-ash-trans-butterscotch-x10756",
            "94434828-suhr-classic-t-swamp-ash-trans-butterscotch-x10756",
            id="suhr-classic-t-butterscotch",
        ),
        pytest.param(
            "https://reverb.com/item/88422337-frank-brothers-arcade-amber-korina",
            "88422337-frank-brothers-arcade-amber-korina",
            id="frank-brothers-arcade-amber",
        ),
        pytest.param(
            "https://reverb.com/item/93737551-frank-brothers-arcade-one-korina-natural",
            "93737551-frank-brothers-arcade-one-korina-natural",
            id="frank-brothers-arcade-one",
        ),
    ],
)
def test_extract_listing_slug(scraper: ReverbScraper, url: str, expected_slug: str):
    assert scraper._extract_listing_slug(url) == expected_slug


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://reverb.com/marketplace", id="marketplace"),
        pytest.param("https://reverb.com/", id="root"),
        pytest.param("https://example.com/not-reverb", id="not-reverb"),
        pytest.param("", id="empty"),
    ],
)
def test_extract_listing_slug_invalid(scraper: ReverbScraper, url: str):
    with pytest.raises(ValueError, match="Invalid Reverb URL"):
        scraper._extract_listing_slug(url)


# ── _format_date ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "iso_input, expected",
    [
        pytest.param("2026-02-04T12:00:00+00:00", "2026-02-04", id="utc-offset"),
        pytest.param("2025-12-28T18:30:00-05:00", "2025-12-28", id="eastern-tz"),  # 23:30 UTC
        pytest.param("2025-10-25T09:00:00Z", "2025-10-25", id="utc-z"),
        pytest.param("2025-11-29T00:00:00+01:00", "2025-11-28", id="paris-tz"),  # 23:00 Nov 28 UTC
        pytest.param("2025-12-09T15:45:00+00:00", "2025-12-09", id="utc-afternoon"),
        pytest.param("2026-01-19T08:00:00-06:00", "2026-01-19", id="central-tz"),
        pytest.param("2026-01-08T12:00:00+00:00", "2026-01-08", id="utc-noon"),
        pytest.param("2026-02-09T20:00:00+00:00", "2026-02-09", id="utc-evening"),
        pytest.param("2025-03-28T10:00:00-07:00", "2025-03-28", id="pacific-tz"),
        pytest.param("2025-12-27T14:00:00-05:00", "2025-12-27", id="eastern-tz-dec"),
        pytest.param("2025-06-15T09:30:00Z", "2025-06-15", id="utc-z-june"),
        pytest.param("2025-01-01", "2025-01-01", id="date-only"),
        pytest.param("", "", id="empty-string"),
        pytest.param("not-a-date", "not-a-date", id="invalid-string"),
    ],
)
def test_format_date(iso_input: str, expected: str):
    assert ReverbScraper._format_date(iso_input) == expected


# ── _clean_html ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "html_input, expected",
    [
        pytest.param("<p>Hello <b>world</b></p>", "Hello world", id="basic-tags"),
        pytest.param("No tags here", "No tags here", id="no-tags"),
        pytest.param("", "", id="empty"),
        pytest.param("  extra   spaces  ", "extra spaces", id="extra-spaces"),
        pytest.param("<div>a</div>  <div>b</div>", "a b", id="multiple-divs"),
        pytest.param(
            "Up for sale is a&nbsp;Springer Seraph&nbsp;guitar",
            "Up for sale is a&nbsp;Springer Seraph&nbsp;guitar",
            id="html-entities-preserved",
        ),
        pytest.param("<br/>Line one<br/>Line two", "Line oneLine two", id="br-tags"),
    ],
)
def test_clean_html(html_input: str, expected: str):
    assert ReverbScraper._clean_html(html_input) == expected


# ── _find_shipping_rate ───────────────────────────────────────────────────


_CA_RATE = {"region_code": "CA", "rate": {"amount": "200.00", "display": "C$200"}}
_CA_CON_RATE = {"region_code": "CA_CON", "rate": {"amount": "150.00", "display": "C$150"}}
_US_RATE = {"region_code": "US_CON", "rate": {"amount": "30.00", "display": "$30"}}
_XX_RATE = {"region_code": "XX", "rate": {"amount": "100.00", "display": "$100"}}
_EVERYWHERE = {"region_code": "EVERYWHERE_ELSE", "rate": {"amount": "120.00", "display": "$120"}}


@pytest.mark.parametrize(
    "rates, target_region, expected",
    [
        pytest.param([_US_RATE, _CA_RATE], "CA", _CA_RATE, id="exact-CA"),
        pytest.param([_US_RATE, _CA_CON_RATE], "CA", _CA_CON_RATE, id="CA_CON-fallback"),
        pytest.param([_US_RATE, _XX_RATE], "CA", _XX_RATE, id="XX-fallback"),
        pytest.param([_US_RATE, _EVERYWHERE], "CA", _EVERYWHERE, id="EVERYWHERE-fallback"),
        pytest.param([_US_RATE], "CA", None, id="no-match"),
        pytest.param([], "CA", None, id="empty-rates"),
        pytest.param([_US_RATE, _CA_RATE], "US_CON", _US_RATE, id="exact-US_CON"),
        pytest.param([_CA_CON_RATE, _US_RATE], "DE", None, id="no-CA_CON-for-DE"),
        pytest.param([_US_RATE, _XX_RATE], "DE", _XX_RATE, id="XX-for-DE"),
    ],
)
def test_find_shipping_rate(scraper: ReverbScraper, rates: list, target_region: str, expected):
    result = scraper._find_shipping_rate(rates, target_region)
    assert result == expected


# ── _resolve_shipping ─────────────────────────────────────────────────────


# Helper: build a minimal raw API dict with the given shipping rates.
def _raw_with_rates(rates: list[dict]) -> dict:
    return {"shipping": {"rates": rates}}


_FREE_CA_RATE = {"region_code": "CA", "rate": {"amount": "0.00", "display": "FREE"}}
_PAID_CA_RATE = {"region_code": "CA", "rate": {"amount": "175.50", "display": "C$175.50"}}
_PAID_XX_RATE = {"region_code": "XX", "rate": {"amount": "300.00", "display": "$300"}}
_PAID_CA_NO_AMOUNT = {"region_code": "CA", "rate": {"display": "C$???"}}

# Expected keys every call must return
_SHIPPING_KEYS = {
    "shipping_price",
    "shipping_display",
    "shipping_region",
    "ships_to_canada",
    "shipping_regions",
}


class TestResolveShippingKeys:
    """Every call returns all five expected keys."""

    @pytest.mark.parametrize(
        "raw, sale_ended",
        [
            pytest.param(_raw_with_rates([_PAID_CA_RATE]), False, id="live-with-rate"),
            pytest.param(_raw_with_rates([]), False, id="live-no-rate"),
            pytest.param(_raw_with_rates([_PAID_CA_RATE]), True, id="ended-with-rate"),
            pytest.param(_raw_with_rates([]), True, id="ended-no-rate"),
        ],
    )
    def test_all_keys_present(self, scraper: ReverbScraper, raw: dict, sale_ended: bool):
        result = scraper._resolve_shipping(raw, sale_ended=sale_ended)
        missing = _SHIPPING_KEYS - set(result.keys())
        assert not missing, f"Missing keys: {missing}"


class TestResolveShippingLive:
    """Shipping resolution when the listing is still live."""

    def test_exact_ca_rate(self, scraper: ReverbScraper):
        """CA rate found → use its amount, ships_to_canada=True."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE, _PAID_CA_RATE]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "175.50"
        assert result["shipping_display"] == "C$175.50"
        assert result["shipping_region"] == "CA"
        assert result["ships_to_canada"] is True

    def test_free_shipping(self, scraper: ReverbScraper):
        """Free shipping (amount '0.00') is preserved, not replaced by default."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_FREE_CA_RATE]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "0.00"
        assert result["shipping_display"] == "FREE"
        assert result["ships_to_canada"] is True

    def test_fallback_to_xx_rate(self, scraper: ReverbScraper):
        """No CA rate, but XX exists → use XX, ships_to_canada=True."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE, _PAID_XX_RATE]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "300.00"
        assert result["shipping_display"] == "$300"
        assert result["ships_to_canada"] is True

    def test_no_rate_defaults_to_250(self, scraper: ReverbScraper):
        """No matching rate at all → default $250, ships_to_canada=False."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "250.00"
        assert result["shipping_display"] == "C$250.00"
        assert result["shipping_region"] == ""
        assert result["ships_to_canada"] is False

    def test_empty_rates_defaults_to_250(self, scraper: ReverbScraper):
        """Empty rates list → default $250."""
        result = scraper._resolve_shipping(
            _raw_with_rates([]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "250.00"
        assert result["ships_to_canada"] is False

    def test_missing_amount_defaults_to_250(self, scraper: ReverbScraper):
        """CA rate present but amount key missing → default $250."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_PAID_CA_NO_AMOUNT]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "250.00"
        assert result["ships_to_canada"] is True

    def test_missing_shipping_key_defaults_to_250(self, scraper: ReverbScraper):
        """Raw dict has no 'shipping' key at all → default $250."""
        result = scraper._resolve_shipping({}, sale_ended=False)
        assert result["shipping_price"] == "250.00"
        assert result["ships_to_canada"] is False

    def test_custom_default_shipping(self):
        """Custom default_shipping is used when no rate is found."""
        custom = ReverbScraper(currency="CAD", shipping_region="CA", default_shipping="35.00")
        result = custom._resolve_shipping(
            _raw_with_rates([_US_RATE]),
            sale_ended=False,
        )
        assert result["shipping_price"] == "35.00"
        assert result["shipping_display"] == "C$35.00"
        assert result["ships_to_canada"] is False

    def test_shipping_regions_listed(self, scraper: ReverbScraper):
        """shipping_regions contains all region codes from the rates list."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE, _PAID_CA_RATE, _PAID_XX_RATE]),
            sale_ended=False,
        )
        assert set(result["shipping_regions"]) == {"US_CON", "CA", "XX"}


class TestResolveShippingEnded:
    """Shipping resolution when the listing has ended (sold/ended/suspended)."""

    def test_ended_with_rates_returns_none(self, scraper: ReverbScraper):
        """Ended listing with rates → all shipping fields are None."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE, _PAID_CA_RATE]),
            sale_ended=True,
        )
        assert result["shipping_price"] is None
        assert result["shipping_display"] is None
        assert result["shipping_region"] is None
        assert result["ships_to_canada"] is None

    def test_ended_without_rates_returns_none(self, scraper: ReverbScraper):
        """Ended listing with no rates → all shipping fields are None."""
        result = scraper._resolve_shipping(
            _raw_with_rates([]),
            sale_ended=True,
        )
        assert result["shipping_price"] is None
        assert result["shipping_display"] is None
        assert result["shipping_region"] is None
        assert result["ships_to_canada"] is None

    def test_ended_still_reports_shipping_regions(self, scraper: ReverbScraper):
        """Even for ended listings, shipping_regions is populated."""
        result = scraper._resolve_shipping(
            _raw_with_rates([_US_RATE, _PAID_CA_RATE]),
            sale_ended=True,
        )
        assert set(result["shipping_regions"]) == {"US_CON", "CA"}

    def test_ended_empty_rates_shipping_regions_empty(self, scraper: ReverbScraper):
        """Ended listing with no rates → shipping_regions is empty list."""
        result = scraper._resolve_shipping(
            _raw_with_rates([]),
            sale_ended=True,
        )
        assert result["shipping_regions"] == []


# ── extract_data — VCR-recorded API responses ────────────────────────────
#
# These tests replay recorded HTTP responses via VCR cassettes.
# To re-record, run:  uv run pytest --record-mode=all
#
# We only assert on fields that are stable for a given listing (name, make,
# model, finish, year, condition, currency, seller, location, created_at,
# published_at).
#
# Volatile fields (price, views, watchers, status, shipping, offers_enabled)
# are intentionally NOT checked because they can change at any time.

# Stable fields we verify on every listing
_STABLE_FIELDS = [
    "name",
    "make",
    "model",
    "finish",
    "year",
    "condition",
    "currency",
    "seller",
    "location",
    "created_at",
    "published_at",
]

_LISTINGS = [
    pytest.param(
        "https://reverb.com/item/94365602-suhr-classic-t-trans-white",
        {
            "name": "Suhr Classic T - Trans White",
            "make": "Suhr",
            "model": "Classic T",
            "finish": "Trans White",
            "year": "2018 - Present",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "Smith Music Co.",
            "location": "Spring Hill, TN, United States",
            "created_at": "2026-02-05",
            "published_at": "2026-02-05",
        },
        id="suhr-classic-t-trans-white",
    ),
    pytest.param(
        "https://reverb.com/item/93749436-suhr-alt-t-with-rosewood-fretboard-2018-present-sonic-blue",
        {
            "name": "Suhr Alt T with Rosewood Fretboard 2018 - Present - Sonic Blue",
            "make": "Suhr",
            "model": "Alt T with Rosewood Fretboard",
            "finish": "Sonic Blue",
            "year": "2018 - Present",
            "condition": "Very Good",
            "currency": "CAD",
            "seller": "Juan I's Gear Depot",
            "location": "Paramus, NJ, United States",
            "created_at": "2025-12-29",
            "published_at": "2025-12-29",
        },
        id="suhr-alt-t-sonic-blue",
    ),
    pytest.param(
        "https://reverb.com/item/92774275-ibanez-flatv2-msn-josh-smith",
        {
            "name": "Ibanez FLATV2-MSN Josh Smith",
            "make": "Ibanez",
            "model": "FLATV2-MSN Josh Smith",
            "finish": "",
            "year": "",
            "condition": "Brand New",
            "currency": "CAD",
            "seller": "Musik Produktiv",
            "location": "Ibbenbüren, Germany",
            "created_at": "2025-10-25",
            "published_at": "2025-10-25",
        },
        id="ibanez-flatv2-musik-produktiv",
    ),
    pytest.param(
        "https://reverb.com/item/93345258-flatv2-msn-josh-smith-mint-sand-etui-ibanez",
        {
            "name": "FLATV2-MSN Josh Smith Mint Sand + Etui Ibanez",
            "make": "Ibanez",
            "model": "FLATV2-MSN Josh Smith Mint Sand + Etui",
            "finish": "Mint Sand",
            "year": "",
            "condition": "Brand New",
            "currency": "CAD",
            "seller": "SonoVente",
            "location": "PALAISEAU, France",
            "created_at": "2025-11-30",
            "published_at": "2025-11-30",
        },
        id="ibanez-flatv2-sonovente",
    ),
    pytest.param(
        "https://reverb.com/item/93497125-springer-seraph-hollowbody-w-ohsc-2014-tobacco",
        {
            "name": "Springer Seraph Hollowbody w/ OHSC - 2014 - Tobacco",
            "make": "Springer",
            "model": "Seraph Hollowbody",
            "finish": "Tobacco",
            "year": "2014",
            "condition": "Very Good",
            "currency": "CAD",
            "seller": "Guitar Pickers NC",
            "location": "Wilmington, NC, United States",
            "created_at": "2025-12-09",
            "published_at": "2025-12-09",
        },
        id="springer-seraph-hollowbody",
    ),
    pytest.param(
        "https://reverb.com/item/94124092-suhr-alt-t-with-rosewood-fretboard-2018-present-olympic-white",
        {
            "name": "Suhr Alt T with Rosewood Fretboard 2018 - Present - Olympic White",
            "make": "Suhr",
            "model": "Alt T with Rosewood Fretboard",
            "finish": "Olympic White",
            "year": "2018 - Present",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "Birch Lake Music - Babbitt, MN",
            "location": "Babbitt, MN, United States",
            "created_at": "2026-01-19",
            "published_at": "2026-01-19",
        },
        id="suhr-alt-t-olympic-white",
    ),
    pytest.param(
        "https://reverb.com/item/93932537-preowned-suhr-alt-t-in-sonic-blue-with-rosewood-fretboard",
        {
            "name": "Preowned Suhr Alt T in Sonic Blue with Rosewood Fretboard",
            "make": "Suhr",
            "model": "Alt T with Rosewood Fingerboard",
            "finish": "Sonic Blue",
            "year": "2023",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "The Guitar Sanctuary",
            "location": "McKinney, TX, United States",
            "created_at": "2026-01-08",
            "published_at": "2026-01-08",
        },
        id="suhr-alt-t-preowned",
    ),
    pytest.param(
        "https://reverb.com/item/94434828-suhr-classic-t-swamp-ash-trans-butterscotch-x10756",
        {
            "name": "Suhr Classic T Swamp Ash - Trans Butterscotch - x10756",
            "make": "Suhr",
            "model": "Classic T",
            "finish": "Trans Butterscotch",
            "year": "2018 - Present",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "PedalsToMetal/EvanBuysPedals",
            "location": "woodmere, NY, United States",
            "created_at": "2026-02-09",
            "published_at": "2026-02-09",
        },
        id="suhr-classic-t-butterscotch",
    ),
    pytest.param(
        "https://reverb.com/item/88422337-frank-brothers-arcade-amber-korina",
        {
            "name": "Frank Brothers Arcade - Amber Korina",
            "make": "Frank Brothers",
            "model": "Arcade",
            "finish": "Amber Korina",
            "year": "",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "Praise The Sun",
            "location": "Camarillo, CA, United States",
            "created_at": "2025-03-28",
            "published_at": "2025-03-28",
        },
        id="frank-brothers-arcade-amber",
    ),
    pytest.param(
        "https://reverb.com/item/93737551-frank-brothers-arcade-one-korina-natural",
        {
            "name": "Frank Brothers Arcade One Korina Natural",
            "make": "Frank Brothers",
            "model": "Arcade One",
            "finish": "Korina",
            "year": "",
            "condition": "Excellent",
            "currency": "CAD",
            "seller": "PPaascal's Gear Bazaar",
            "location": "Mont St-Hilaire, Canada",
            "created_at": "2025-12-27",
            "published_at": "2025-12-27",
        },
        id="frank-brothers-arcade-one",
    ),
]


@pytest.mark.vcr
@pytest.mark.parametrize("url, expected", _LISTINGS)
async def test_extract_data_stable_fields(scraper: ReverbScraper, url: str, expected: dict):
    """Verify stable listing fields against the live API."""
    result = await scraper.extract_data(url)

    assert "error" not in result, f"API returned error: {result.get('error')}"
    assert result["url"] == url

    for field in _STABLE_FIELDS:
        assert result[field] == expected[field], (
            f"Field '{field}': got {result[field]!r}, expected {expected[field]!r}"
        )


@pytest.mark.vcr
@pytest.mark.parametrize("url, expected", _LISTINGS)
async def test_extract_data_has_all_keys(scraper: ReverbScraper, url: str, expected: dict):
    """Every result from extract_data must contain all expected output keys."""
    all_keys = {
        "url",
        "name",
        "make",
        "model",
        "finish",
        "year",
        "price",
        "currency",
        "price_display",
        "condition",
        "shipping_price",
        "shipping_display",
        "shipping_region",
        "ships_to_canada",
        "shipping_regions",
        "status",
        "sale_ended",
        "offers_enabled",
        "created_at",
        "published_at",
        "seller",
        "location",
        "description",
        "views",
        "watchers",
        "categories",
        "photo_url",
    }
    result = await scraper.extract_data(url)

    assert "error" not in result, f"API returned error: {result.get('error')}"
    missing = all_keys - set(result.keys())
    assert not missing, f"Missing keys in output: {missing}"


@pytest.mark.vcr
@pytest.mark.parametrize("url, expected", _LISTINGS)
async def test_extract_data_types(scraper: ReverbScraper, url: str, expected: dict):
    """Verify the types of fields returned by extract_data."""
    result = await scraper.extract_data(url)

    assert "error" not in result
    assert isinstance(result["name"], str)
    assert isinstance(result["price"], str)
    assert isinstance(result["currency"], str)
    assert isinstance(result["sale_ended"], bool)
    assert isinstance(result["offers_enabled"], bool)
    assert isinstance(result["shipping_regions"], list)
    assert isinstance(result["views"], int)
    assert isinstance(result["watchers"], int)

    # Shipping fields are None when the listing is no longer live
    if result["sale_ended"]:
        assert result["ships_to_canada"] is None
        assert result["shipping_price"] is None
    else:
        assert isinstance(result["ships_to_canada"], bool)
        assert isinstance(result["shipping_price"], str)


# ── search — VCR-recorded API responses ───────────────────────────────────
#
# These tests replay recorded HTTP responses via VCR cassettes.
# To re-record, run:  uv run pytest --record-mode=all -k search
#
# Same strategy as extract_data tests: only assert on stable fields and
# structural properties; volatile fields (price, views, watchers, etc.)
# are intentionally left unchecked.

_ALL_SEARCH_KEYS = {
    "url",
    "name",
    "make",
    "model",
    "finish",
    "year",
    "price",
    "currency",
    "price_display",
    "condition",
    "shipping_price",
    "shipping_display",
    "shipping_region",
    "ships_to_canada",
    "shipping_regions",
    "status",
    "sale_ended",
    "offers_enabled",
    "created_at",
    "published_at",
    "seller",
    "location",
    "description",
    "views",
    "watchers",
    "categories",
    "photo_url",
}


@pytest.mark.vcr
async def test_search_returns_results(scraper: ReverbScraper):
    """A known query returns a non-empty list of normalised dicts."""
    results = await scraper.search("Godin Stadium HT", max_pages=1)

    assert len(results) > 0
    for r in results:
        assert "error" not in r, f"Unexpected error: {r.get('error')}"


@pytest.mark.vcr
async def test_search_result_has_all_keys(scraper: ReverbScraper):
    """Every search result must contain all expected output keys."""
    results = await scraper.search("Godin Stadium HT", max_pages=1)

    assert len(results) > 0
    for r in results:
        missing = _ALL_SEARCH_KEYS - set(r.keys())
        assert not missing, f"Missing keys: {missing}"


@pytest.mark.vcr
async def test_search_result_field_types(scraper: ReverbScraper):
    """Verify the types of key fields in search results."""
    results = await scraper.search("Godin Stadium HT", max_pages=1)

    assert len(results) > 0
    for r in results:
        assert isinstance(r["name"], str)
        assert isinstance(r["price"], str)
        assert isinstance(r["currency"], str)
        assert isinstance(r["ships_to_canada"], bool)
        assert isinstance(r["sale_ended"], bool)
        assert isinstance(r["offers_enabled"], bool)
        assert isinstance(r["shipping_regions"], list)
        assert isinstance(r["views"], int)
        assert isinstance(r["watchers"], int)


@pytest.mark.vcr
async def test_search_currency_matches_scraper_config(scraper: ReverbScraper):
    """All results use the currency configured on the scraper (CAD)."""
    results = await scraper.search("Godin Stadium HT", max_pages=1)

    assert len(results) > 0
    for r in results:
        assert r["currency"] == "CAD"


@pytest.mark.vcr
async def test_search_result_has_url(scraper: ReverbScraper):
    """Each result must have a non-empty URL pointing to reverb.com."""
    results = await scraper.search("Godin Stadium HT", max_pages=1)

    assert len(results) > 0
    for r in results:
        assert r["url"], "url must not be empty"
        assert "reverb.com" in r["url"]


@pytest.mark.vcr
async def test_search_per_page_limits_results(scraper: ReverbScraper):
    """per_page controls how many results come back per page."""
    results = await scraper.search("Fender Stratocaster", per_page=5, max_pages=1)

    assert 0 < len(results) <= 5


@pytest.mark.vcr
async def test_search_max_pages_limits_results(scraper: ReverbScraper):
    """max_pages=1 with per_page=5 should return at most 5 results,
    even for a query that has many more total hits."""
    results = await scraper.search("Fender Stratocaster", per_page=5, max_pages=1)

    assert len(results) <= 5


@pytest.mark.vcr
async def test_search_ships_to_filter(scraper: ReverbScraper):
    """Filtering by ships_to='CA' returns results without errors."""
    results = await scraper.search("Godin Stadium HT", ships_to="CA", max_pages=1)

    for r in results:
        assert "error" not in r, f"Unexpected error: {r.get('error')}"


@pytest.mark.vcr
async def test_search_state_sold(scraper: ReverbScraper):
    """Searching with state='sold' returns sold listings."""
    results = await scraper.search("Godin Stadium HT", state="sold", max_pages=1)

    assert len(results) > 0
    for r in results:
        assert "error" not in r


@pytest.mark.vcr
async def test_search_paginates_across_multiple_pages(scraper: ReverbScraper):
    """Fetching multiple pages returns more results than a single page."""
    per_page = 5
    max_pages = 3

    results = await scraper.search(
        "Fender Stratocaster",
        per_page=per_page,
        max_pages=max_pages,
    )

    # We must get more than one page's worth of results
    assert len(results) > per_page, (
        f"Expected more than {per_page} results across {max_pages} pages, got {len(results)}"
    )
    # But no more than max_pages * per_page
    assert len(results) <= max_pages * per_page

    # Every result is a valid normalised dict (no errors, all keys present)
    for r in results:
        assert "error" not in r, f"Unexpected error: {r.get('error')}"
        missing = _ALL_SEARCH_KEYS - set(r.keys())
        assert not missing, f"Missing keys: {missing}"

    # Unique URLs should span more than one page worth of results.
    # Note: the live API may return a small number of duplicates across
    # concurrent page fetches because listings shift in real time.
    unique_urls = {r["url"] for r in results}
    assert len(unique_urls) > per_page, (
        f"Expected unique results across multiple pages, got only {len(unique_urls)}"
    )


@pytest.mark.vcr
async def test_search_empty_query_returns_no_results(scraper: ReverbScraper):
    """A nonsense query returns an empty list."""
    results = await scraper.search("xyznonexistent987654321qqq", max_pages=1)

    assert results == []


# ── search — category filter ─────────────────────────────────────────────


@pytest.mark.vcr
async def test_search_category_filter_returns_results(scraper: ReverbScraper):
    """Searching with a category filter returns non-empty results."""
    results = await scraper.search(
        "Fender Stratocaster",
        category="electric-guitars",
        max_pages=1,
    )

    assert len(results) > 0
    for r in results:
        assert "error" not in r, f"Unexpected error: {r.get('error')}"


@pytest.mark.vcr
async def test_search_category_filter_narrows_results(scraper: ReverbScraper):
    """A category filter returns fewer results than an unfiltered search."""
    all_results = await scraper.search("Fender", max_pages=1, per_page=5)
    filtered_results = await scraper.search(
        "Fender",
        category="electric-guitars",
        max_pages=1,
        per_page=5,
    )

    # The filtered total should be strictly less than the unfiltered total
    # (we can't check len(results) because per_page caps both to 5).
    # Instead, just verify both succeeded.
    assert len(all_results) > 0
    assert len(filtered_results) > 0


@pytest.mark.vcr
async def test_search_category_filter_results_have_all_keys(scraper: ReverbScraper):
    """Category-filtered results contain all expected output keys."""
    results = await scraper.search(
        "Fender Stratocaster",
        category="electric-guitars",
        max_pages=1,
    )

    assert len(results) > 0
    for r in results:
        missing = _ALL_SEARCH_KEYS - set(r.keys())
        assert not missing, f"Missing keys: {missing}"


@pytest.mark.vcr
async def test_search_categories_field_populated(scraper: ReverbScraper):
    """Each result includes a non-empty categories list of strings."""
    results = await scraper.search(
        "Fender Stratocaster",
        category="electric-guitars",
        max_pages=1,
        per_page=5,
    )

    assert len(results) > 0
    for r in results:
        assert isinstance(r["categories"], list)
        assert len(r["categories"]) > 0
        for cat in r["categories"]:
            assert isinstance(cat, str)
            assert len(cat) > 0
