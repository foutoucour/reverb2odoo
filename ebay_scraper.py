"""
Extract guitar listing information from eBay via the Browse API.

Two-step access:

1. ``EbayAuth`` exchanges client credentials for an OAuth2 access token
   (cached in memory until near expiry).
2. ``EbayScraper`` calls the Browse API with that token; ``search()``
   targets one or more marketplaces in parallel and dedupes by item id.

All HTTP methods are async — use ``async with EbayScraper(...) as scraper``
or call :meth:`aclose` when done.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

# ─────────────────────────────────────────────────────────────────────────
# OAuth2 client-credentials authentication
# ─────────────────────────────────────────────────────────────────────────

OAUTH_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"

#: Refresh tokens this many seconds before their stated expiry to avoid
#: race conditions with downstream calls.
TOKEN_REFRESH_SLACK_SECONDS = 60


class EbayAuthError(RuntimeError):
    """Raised when eBay OAuth fails or credentials are missing."""


class EbayAuth:
    """OAuth2 client-credentials helper for the eBay Browse API.

    Caches the access token in memory and refreshes it when within
    ``TOKEN_REFRESH_SLACK_SECONDS`` of its expiry.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._transport = transport
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls) -> EbayAuth:
        """Build an ``EbayAuth`` from ``EBAY_CLIENT_ID`` / ``EBAY_CLIENT_SECRET``.

        Raises ``EbayAuthError`` if either is missing.
        """
        cid = os.environ.get("EBAY_CLIENT_ID")
        sec = os.environ.get("EBAY_CLIENT_SECRET")
        if not cid or not sec:
            raise EbayAuthError(
                "EBAY_CLIENT_ID and EBAY_CLIENT_SECRET must be set in the environment"
            )
        return cls(client_id=cid, client_secret=sec)

    async def get_token(self) -> str:
        """Return a valid access token, fetching/refreshing as needed."""
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at - TOKEN_REFRESH_SLACK_SECONDS:
                return self._token
            self._token = await self._fetch_token()
            return self._token

    def invalidate(self) -> None:
        """Drop the cached token (caller can then re-call ``get_token``)."""
        self._token = None
        self._expires_at = 0.0

    async def _fetch_token(self) -> str:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials", "scope": OAUTH_SCOPE}

        async with httpx.AsyncClient(transport=self._transport, timeout=15.0) as client:
            try:
                response = await client.post(OAUTH_TOKEN_URL, headers=headers, data=data)
            except httpx.HTTPError as exc:
                raise EbayAuthError(f"OAuth token request failed: {exc}") from exc

        if response.status_code != 200:
            raise EbayAuthError(
                f"OAuth token request failed: {response.status_code} {response.text[:200]}"
            )

        body = response.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in", 0))
        if not token:
            raise EbayAuthError(f"OAuth response missing access_token: {body!r}")

        self._expires_at = time.monotonic() + expires_in
        logger.debug("Fetched eBay OAuth token (expires in {}s)", expires_in)
        return token


# ─────────────────────────────────────────────────────────────────────────
# Browse API client
# ─────────────────────────────────────────────────────────────────────────

BROWSE_API_BASE = "https://api.ebay.com/buy/browse/v1"
SEARCH_URL = f"{BROWSE_API_BASE}/item_summary/search"

#: eBay Browse API caps page size at 200; we mirror the Reverb scraper's
#: smaller default to keep payloads manageable.
DEFAULT_PAGE_SIZE = 50

#: Used by the parser to detect free shipping vs missing rates.
DEFAULT_SHIPPING_FALLBACK = "250.00"

#: Regex for extracting the numeric eBay item id from a listing URL.

_ITEM_ID_RE = re.compile(r"/itm/(?:[^/]*/)?(\d{6,})")


class EbayScraper:
    """Extract listing information from the eBay Browse API.

    Each ``search()`` call fans out across ``marketplaces`` in parallel and
    dedupes results by ``itemId``.
    """

    def __init__(
        self,
        auth: EbayAuth,
        *,
        marketplaces: tuple[str, ...] = ("EBAY_US", "EBAY_CA"),
        delivery_country: str = "CA",
        default_shipping: str = DEFAULT_SHIPPING_FALLBACK,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_concurrent: int = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.auth = auth
        self.marketplaces = marketplaces
        self.delivery_country = delivery_country
        self.default_shipping = default_shipping
        self.page_size = min(page_size, 200)
        self.client = httpx.AsyncClient(transport=transport, timeout=15.0)
        self._page_sem = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self) -> EbayScraper:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self.client.aclose()

    # ── search ─────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        category_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search eBay for *query* across all configured marketplaces.

        Results are deduplicated by ``itemId``.  Returns dicts shaped like
        :meth:`reverb_scraper.ReverbScraper._parse_api_response`.
        """
        tasks = [
            self._search_one_marketplace(query, marketplace=mp, category_id=category_id)
            for mp in self.marketplaces
        ]
        per_marketplace = await asyncio.gather(*tasks)

        seen_ids: set[str] = set()
        combined: list[dict[str, Any]] = []
        for results in per_marketplace:
            for item in results:
                item_id = item.get("_ebay_item_id") or item.get("url", "")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                combined.append(item)
        return combined

    async def _search_one_marketplace(
        self,
        query: str,
        *,
        marketplace: str,
        category_id: int | None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": query, "limit": self.page_size, "offset": 0}
        if category_id is not None:
            params["category_ids"] = str(category_id)
        if self.delivery_country:
            params["filter"] = f"deliveryCountry:{self.delivery_country}"

        async def _limited(p: dict[str, Any]) -> dict[str, Any] | None:
            async with self._page_sem:
                return await self._fetch_search_page(p, marketplace=marketplace)

        first = await _limited(params)
        if first is None:
            return []

        results: list[dict[str, Any]] = [
            self._parse_item_summary(
                s, marketplace=marketplace, default_shipping=self.default_shipping
            )
            for s in first.get("itemSummaries", []) or []
        ]
        total = int(first.get("total", 0))
        if total <= self.page_size:
            return results

        # Fan out remaining pages concurrently, but capped by the semaphore.
        offsets = list(range(self.page_size, total, self.page_size))
        page_tasks = [_limited({**params, "offset": off}) for off in offsets]
        for page in await asyncio.gather(*page_tasks):
            if page is None:
                continue
            for s in page.get("itemSummaries", []) or []:
                results.append(
                    self._parse_item_summary(
                        s, marketplace=marketplace, default_shipping=self.default_shipping
                    )
                )
        return results

    async def _fetch_search_page(
        self,
        params: dict[str, Any],
        *,
        marketplace: str,
    ) -> dict[str, Any] | None:
        token = await self.auth.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace,
            "Content-Type": "application/json",
        }
        try:
            response = await self.client.get(SEARCH_URL, params=params, headers=headers)
            if response.status_code == 401:
                # Token may have been revoked early — invalidate and retry once.
                self.auth.invalidate()
                token = await self.auth.get_token()
                headers["Authorization"] = f"Bearer {token}"
                response = await self.client.get(SEARCH_URL, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.error(
                "eBay search error ({} offset={}): {}", marketplace, params.get("offset"), exc
            )
            return None

    # ── parsing ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_item_id(url: str) -> str | None:
        match = _ITEM_ID_RE.search(url or "")
        return match.group(1) if match else None

    @staticmethod
    def _format_date(date_str: str) -> str:
        """Format an ISO date string to YYYY-MM-DD (UTC), or '' if blank."""

        if not date_str:
            return ""
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(UTC)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return date_str

    @staticmethod
    def _format_location(loc: dict[str, Any]) -> str:
        parts = [loc.get("city"), loc.get("stateOrProvince"), loc.get("country")]
        return ", ".join(p for p in parts if p)

    @staticmethod
    def _resolve_shipping(
        raw: dict[str, Any],
        *,
        delivery_country: str = "CA",
        default_shipping: str = DEFAULT_SHIPPING_FALLBACK,
    ) -> dict[str, Any]:
        options = raw.get("shippingOptions") or []
        item_country = (raw.get("itemLocation") or {}).get("country", "")
        ships_to_country = bool(options) or item_country == delivery_country

        if options:
            cost = options[0].get("shippingCost", {})
            return {
                "shipping_price": cost.get("value", default_shipping),
                "shipping_display": f"{cost.get('currency', '')} {cost.get('value', '')}".strip(),
                "shipping_region": delivery_country if ships_to_country else "",
                "ships_to_canada": ships_to_country,
                "shipping_regions": [delivery_country] if ships_to_country else [],
            }

        # No options listed — fall back, mark as not ships-to-CA.
        return {
            "shipping_price": default_shipping,
            "shipping_display": f"CAD {default_shipping}",
            "shipping_region": "",
            "ships_to_canada": False,
            "shipping_regions": [],
        }

    @staticmethod
    def _parse_item_summary(
        raw: dict[str, Any],
        *,
        marketplace: str,
        default_shipping: str = DEFAULT_SHIPPING_FALLBACK,
    ) -> dict[str, Any]:
        """Transform an ``itemSummary`` entry into the shared listing dict shape."""
        url = raw.get("itemWebUrl", "")
        price_info = raw.get("price", {}) or {}
        cats = raw.get("categories") or []
        photo = (raw.get("image") or {}).get("imageUrl", "")

        data: dict[str, Any] = {
            "url": url,
            "name": raw.get("title", ""),
            "make": "",  # not on item_summary; populated later if needed
            "model": "",
            "finish": "",
            "year": "",
            "price": price_info.get("value", ""),
            "currency": price_info.get("currency", ""),
            "price_display": (
                f"{price_info.get('currency', '')} {price_info.get('value', '')}".strip()
            ),
            "condition": raw.get("condition", ""),
            "status": "Active",
            "sale_ended": False,
            "offers_enabled": False,
            "created_at": "",
            "published_at": EbayScraper._format_date(raw.get("itemCreationDate", "")),
            "seller": (raw.get("seller") or {}).get("username", ""),
            "location": EbayScraper._format_location(raw.get("itemLocation") or {}),
            "description": "",
            "views": 0,
            "watchers": 0,
            "categories": [c.get("categoryName", "") for c in cats],
            "photo_url": photo,
            "_ebay_item_id": EbayScraper._extract_item_id(url),
            "_ebay_marketplace": marketplace,
        }
        data.update(EbayScraper._resolve_shipping(raw, default_shipping=default_shipping))
        return data
