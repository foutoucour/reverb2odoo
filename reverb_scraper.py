"""
Extract guitar listing information from Reverb.com via the public API.
Prices displayed in CAD, shipping rates for Canada.

All HTTP methods are async — use ``async with ReverbScraper() as scraper``
or call :meth:`aclose` when done.
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import httpx
import uritemplate
from loguru import logger

# Region codes used by Reverb for Canada
CANADA_REGION_CODES = ("CA", "CA_CON")


class ReverbScraper:
    """Extract listing information from the Reverb.com public API."""

    API_BASE = "https://api.reverb.com/api"
    LISTING_URL = uritemplate.URITemplate(API_BASE + "/listings/{slug}")
    LISTINGS_URL = API_BASE + "/listings"
    CATEGORIES_URL = API_BASE + "/categories/flat"

    def __init__(
        self,
        currency: str = "CAD",
        shipping_region: str = "CA",
        default_shipping: str = "250.00",
    ):
        self.currency = currency
        self.shipping_region = shipping_region
        self.default_shipping = default_shipping
        self.client = httpx.AsyncClient(
            headers={
                "Accept": "application/hal+json",
                "Accept-Version": "3.0",
                "Content-Type": "application/hal+json",
                "X-Display-Currency": self.currency,
            },
            timeout=15.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def aclose(self):
        """Close the underlying HTTP client."""
        await self.client.aclose()

    def _extract_listing_slug(self, url: str) -> str:
        """Extract the listing slug from a Reverb URL.

        URL format:
            https://reverb.com/item/<id>-<slug>
        """
        match = re.search(r"/item/(.+)$", url.rstrip("/"))
        if not match:
            raise ValueError(f"Invalid Reverb URL: {url}")
        return match.group(1)

    async def extract_data(self, url: str) -> dict[str, Any]:
        """
        Extract listing information from a Reverb.com page via the API.

        Args:
            url: Reverb.com listing URL

        Returns:
            Dict containing the extracted information
        """
        try:
            listing_slug = self._extract_listing_slug(url)
            api_url = self.LISTING_URL.expand(slug=listing_slug)
            response = await self.client.get(api_url)
            response.raise_for_status()
            raw = response.json()
            return self._parse_api_response(raw, url)

        except httpx.HTTPError as e:
            return {"url": url, "error": f"API error: {e}"}
        except Exception as e:
            return {"url": url, "error": f"Error: {e}"}

    async def extract_many(
        self,
        urls: list[str],
        *,
        max_concurrent: int = 10,
    ) -> list[dict[str, Any]]:
        """Extract data from multiple listings concurrently.

        Args:
            urls: Reverb.com listing URLs.
            max_concurrent: Maximum number of requests in flight at once.

        Returns:
            List of result dicts in the same order as *urls*.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _limited(url: str) -> dict[str, Any]:
            async with semaphore:
                return await self.extract_data(url)

        return list(await asyncio.gather(*[_limited(u) for u in urls]))

    # ── Search ────────────────────────────────────────────────────────────

    async def _fetch_search_page(
        self,
        params: dict[str, Any],
        page: int,
    ) -> dict[str, Any] | None:
        """Fetch a single page of search results.

        Returns the parsed JSON body, or ``None`` on error.
        """
        try:
            response = await self.client.get(
                self.LISTINGS_URL,
                params={**params, "page": page},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("API error on page {}: {}", page, e)
            return None

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
        ships_to: str | None = None,
        state: str = "live",
        per_page: int = 50,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search Reverb listings and return normalised results.

        After fetching the first page (to discover ``total_pages``), all
        remaining pages are fetched **concurrently** for speed.

        Args:
            query: Free-text search string (e.g. "Godin Stadium HT").
            category: Reverb product-type slug used to restrict results
                      to a single category (e.g. ``"electric-guitars"``).
                      Pass ``None`` to search across all categories.
                      Slugs are the kebab-case names returned by the
                      ``/api/categories/flat`` endpoint.
            ships_to: ISO country code to filter by shipping destination
                      (e.g. "CA" for Canada). Pass explicitly to filter.
                      Defaults to None (no shipping filter — returns all
                      listings regardless of shipping destination).
            state: Listing state filter – "live", "sold", "ended", or
                   "all" (no filter). Defaults to "live".
            per_page: Number of results per API page (max 50).
            max_pages: Maximum number of pages to fetch.  ``None`` means
                       fetch all pages.

        Returns:
            List of normalised listing dicts (same shape as extract_data).
        """

        params: dict[str, Any] = {
            "query": query,
            "per_page": min(per_page, 50),
        }
        if state and state != "all":
            params["state"] = state
        if ships_to:
            params["ships_to"] = ships_to
        if category:
            params["product_type"] = category

        # Fetch first page to discover total_pages
        first_body = await self._fetch_search_page(params, 1)
        if first_body is None:
            return [{"error": "API error on page 1"}]

        listings = first_body.get("listings", [])
        total_pages = first_body.get("total_pages", 1)
        total = first_body.get("total", 0)

        logger.info(
            'Search "{}" — {} result(s), {} page(s)',
            query,
            total,
            total_pages,
        )

        all_results: list[dict[str, Any]] = []
        for raw in listings:
            web_url = raw.get("_links", {}).get("web", {}).get("href", "")
            all_results.append(self._parse_api_response(raw, web_url))

        # Determine remaining pages to fetch
        effective_max = total_pages
        if max_pages is not None:
            effective_max = min(total_pages, max_pages)

        if effective_max > 1:
            remaining = await asyncio.gather(
                *[self._fetch_search_page(params, p) for p in range(2, effective_max + 1)]
            )
            for body in remaining:
                if body is None:
                    continue
                for raw in body.get("listings", []):
                    web_url = raw.get("_links", {}).get("web", {}).get("href", "")
                    all_results.append(self._parse_api_response(raw, web_url))

        return all_results

    # ── Categories ─────────────────────────────────────────────────────────

    async def fetch_categories(self) -> list[dict[str, Any]]:
        """Fetch the flat list of all Reverb categories.

        Each returned dict contains:

        - ``full_name`` – human-readable category path
          (e.g. ``"Acoustic Guitars / 12-String"``).
        - ``name`` – short category name (e.g. ``"12-String"``).
        - ``slug`` – kebab-case slug of this category.
        - ``root_slug`` – slug of the root (top-level) category.
        - ``uuid`` – Reverb's unique identifier for this category.

        Returns:
            List of category dicts, one per (sub)category.
        """
        try:
            response = await self.client.get(self.CATEGORIES_URL)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as e:
            logger.error("Failed to fetch categories: {}", e)
            return []

        raw_categories = body.get("categories", [])
        logger.info("Fetched {} categories from Reverb", len(raw_categories))

        return [
            {
                "full_name": cat.get("full_name", ""),
                "name": cat.get("name", ""),
                "slug": cat.get("slug", ""),
                "root_slug": cat.get("root_slug", ""),
                "uuid": cat.get("uuid", ""),
            }
            for cat in raw_categories
        ]

    # ── Shipping helpers ──────────────────────────────────────────────────

    #: Legacy class-level fallback — prefer the instance attribute
    #: ``self.default_shipping`` set in ``__init__``.
    DEFAULT_SHIPPING = "250.00"

    def _find_shipping_rate(self, rates: list[dict], target_region: str) -> dict | None:
        """Find the shipping rate for a given region.

        Looks for an exact region code match first (e.g. CA), then
        Canadian variants (CA_CON, etc.), then a global/international rate (XX).
        """
        # 1. Exact match
        for rate in rates:
            if rate.get("region_code") == target_region:
                return rate

        # 2. Canadian variants
        if target_region == "CA":
            for rate in rates:
                if rate.get("region_code") in CANADA_REGION_CODES:
                    return rate

        # 3. International / global rate
        for rate in rates:
            if rate.get("region_code") in ("XX", "EVERYWHERE_ELSE"):
                return rate

        return None

    def _resolve_shipping(
        self,
        raw: dict[str, Any],
        *,
        sale_ended: bool,
    ) -> dict[str, Any]:
        """Resolve shipping information from the raw API response.

        Rules
        -----
        1. **Listing ended** (sold / ended / suspended): all shipping
           fields are set to ``None`` so that downstream sync logic
           preserves the existing value in the database.
        2. **Rate found for the target region**: use the rate from the API.
           If the amount is ``"0.00"`` that means free shipping and is
           kept as-is.
        3. **No rate found**: assume ``self.default_shipping``.

        Returns a dict with keys ``shipping_price``, ``shipping_display``,
        ``shipping_region``, ``ships_to_canada``, and ``shipping_regions``.
        """
        shipping = raw.get("shipping", {})
        rates = shipping.get("rates", [])
        ca_rate = self._find_shipping_rate(rates, self.shipping_region)
        fallback = self.default_shipping

        if sale_ended:
            return {
                "shipping_price": None,
                "shipping_display": None,
                "shipping_region": None,
                "ships_to_canada": None,
                "shipping_regions": [r.get("region_code", "") for r in rates],
            }

        if ca_rate:
            rate_info = ca_rate.get("rate", {})
            return {
                "shipping_price": rate_info.get("amount", fallback),
                "shipping_display": rate_info.get("display", ""),
                "shipping_region": ca_rate.get("region_code", ""),
                "ships_to_canada": True,
                "shipping_regions": [r.get("region_code", "") for r in rates],
            }

        return {
            "shipping_price": fallback,
            "shipping_display": f"C${fallback}",
            "shipping_region": "",
            "ships_to_canada": False,
            "shipping_regions": [r.get("region_code", "") for r in rates],
        }

    def _parse_api_response(self, raw: dict[str, Any], url: str) -> dict[str, Any]:
        """Transform the API response into a normalised structure."""
        data: dict[str, Any] = {}

        # URL
        data["url"] = url

        # Name
        data["name"] = raw.get("title", "")

        # Make / Model
        data["make"] = raw.get("make", "")
        data["model"] = raw.get("model", "")

        # Finish / Year
        data["finish"] = raw.get("finish", "")
        data["year"] = raw.get("year", "")

        # Price (in CAD thanks to the X-Display-Currency header)
        price_info = raw.get("price", {})
        data["price"] = price_info.get("amount", "")
        data["currency"] = price_info.get("currency", self.currency)
        data["price_display"] = price_info.get("display", "")

        # Condition
        cond = raw.get("condition", {})
        data["condition"] = cond.get("display_name", "")

        # Sale status (resolved early — shipping logic depends on it)
        state = raw.get("state", {})
        state_slug = state.get("slug", "")
        data["status"] = state.get("description", state_slug)
        data["sale_ended"] = state_slug in ("sold", "ended", "suspended")

        # Shipping to Canada
        data.update(self._resolve_shipping(raw, sale_ended=data["sale_ended"]))

        # Offers
        data["offers_enabled"] = raw.get("offers_enabled", False)

        # Dates
        data["created_at"] = self._format_date(raw.get("created_at", ""))
        data["published_at"] = self._format_date(raw.get("published_at", ""))

        # Useful extras
        data["seller"] = raw.get("shop_name", "")
        location = raw.get("location", {})
        data["location"] = location.get("display_location", "")
        data["description"] = self._clean_html(raw.get("description", ""))

        stats = raw.get("stats", {})
        data["views"] = stats.get("views", 0)
        data["watchers"] = stats.get("watches", 0)

        # Categories
        raw_cats = raw.get("categories", [])
        data["categories"] = [c.get("full_name", "") for c in raw_cats]

        # Main photo
        links = raw.get("_links", {})
        photo_link = links.get("photo", {})
        data["photo_url"] = photo_link.get("href", "")

        return data

    @staticmethod
    def _format_date(date_str: str) -> str:
        """Format an ISO date string to YYYY-MM-DD (normalised to UTC).

        Normalising to UTC ensures the date component is stable regardless
        of which timezone offset the API returns for the same instant.
        """
        if not date_str:
            return ""
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(UTC)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return date_str

    @staticmethod
    def _clean_html(html: str) -> str:
        """Strip basic HTML tags from a string."""
        if not html:
            return ""
        clean = re.sub(r"<[^>]+>", "", html)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean
