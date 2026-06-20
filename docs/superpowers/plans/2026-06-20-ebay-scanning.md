# eBay Scanning Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add eBay as a second marketplace in the existing `sync` command, populating `x_listing` rows with `x_platform="ebay"` from both `EBAY_US` (ships-to-CA) and `EBAY_CA` marketplaces.

**Architecture:** New `ebay_scraper.py` module mirrors `ReverbScraper`'s public shape (async HTTPX client with OAuth2 client-credentials auth, parallel pagination, normalised output dicts). `sync_model.py` gains a tiny platform registry and `--platform` flag — the existing dedup/diff/create/update machinery is reused unchanged. A hardcoded slug→category-id map drives eBay category filtering with the model's existing `x_studio_reverb_category_id` as the key. No Odoo Studio schema changes.

**Tech Stack:** Python 3.12, httpx (async), pydantic, pytest, pytest-asyncio, pytest-recording (VCR), loguru, click.

**Spec:** `docs/superpowers/specs/2026-06-20-ebay-scanning-design.md`

---

## File Structure

```
ebay_scraper.py              [CREATE] — EbayAuth + EbayScraper
ebay_categories.py           [CREATE] — REVERB_SLUG_TO_EBAY_CATEGORY map
sync_model.py                [MODIFY] — platform registry + --platform flag
env-template.yml             [MODIFY] — EBAY_CLIENT_ID / EBAY_CLIENT_SECRET
README.md                    [MODIFY] — document --platform and credentials
tests/test_ebay_scraper.py   [CREATE] — unit + VCR tests
tests/test_sync_model.py     [MODIFY] — multi-platform sync test cases
tests/conftest.py            [MODIFY] — eBay scraper fixture
tests/fixtures/ebay/         [CREATE DIR] — recorded API JSON payloads
```

Each file has one responsibility. `ebay_scraper.py` stays under ~300 lines by keeping `EbayAuth` and `EbayScraper` in the same file (they're tightly coupled). `ebay_categories.py` is its own file so the map can grow without bloating sync_model.py.

---

## Task 1: eBay OAuth token helper (EbayAuth)

**Files:**
- Create: `ebay_scraper.py` (initial — just the auth class)
- Test: `tests/test_ebay_scraper.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_ebay_scraper.py`:

```python
"""Tests for ebay_scraper — unit tests are pure-sync, integration tests use VCR."""

from __future__ import annotations

import time

import httpx
import pytest

from ebay_scraper import EbayAuth, EbayAuthError


def _ok_token_response(token: str = "TOK_ABC", expires_in: int = 7200) -> dict:
    return {
        "access_token": token,
        "expires_in": expires_in,
        "token_type": "Application Access Token",
    }


@pytest.mark.asyncio
async def test_get_token_fetches_when_no_cache(monkeypatch):
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "auth": request.headers.get("authorization")})
        return httpx.Response(200, json=_ok_token_response("TOK_1", expires_in=7200))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)

    token = await auth.get_token()

    assert token == "TOK_1"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.ebay.com/identity/v1/oauth2/token"
    assert calls[0]["auth"].startswith("Basic ")


@pytest.mark.asyncio
async def test_get_token_caches_until_near_expiry(monkeypatch):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=_ok_token_response(f"TOK_{call_count['n']}", 7200))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)

    t1 = await auth.get_token()
    t2 = await auth.get_token()

    assert t1 == t2 == "TOK_1"
    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_get_token_refreshes_when_expiring(monkeypatch):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json=_ok_token_response(f"TOK_{call_count['n']}", 30))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)

    t1 = await auth.get_token()
    # Force the next call to see the cached token as near-expiry
    monkeypatch.setattr("ebay_scraper.time.monotonic", lambda: time.monotonic() + 1000)
    t2 = await auth.get_token()

    assert t1 == "TOK_1"
    assert t2 == "TOK_2"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_get_token_raises_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="bad", client_secret="bad", transport=transport)

    with pytest.raises(EbayAuthError, match="OAuth token request failed"):
        await auth.get_token()


def test_from_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    with pytest.raises(EbayAuthError, match="EBAY_CLIENT_ID"):
        EbayAuth.from_env()


def test_from_env_reads_credentials(monkeypatch):
    monkeypatch.setenv("EBAY_CLIENT_ID", "CID")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "SEC")
    auth = EbayAuth.from_env()
    assert auth.client_id == "CID"
    assert auth.client_secret == "SEC"
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ebay_scraper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebay_scraper'`

- [ ] **Step 1.3: Implement `EbayAuth`**

Create `ebay_scraper.py`:

```python
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
import time
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
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ebay_scraper.py -v`
Expected: 6 passed.

- [ ] **Step 1.5: Commit**

```bash
git add ebay_scraper.py tests/test_ebay_scraper.py
git commit -m "feat(ebay): add EbayAuth OAuth2 client-credentials helper"
```

---

## Task 2: EbayScraper basics — single-marketplace search + parse

**Files:**
- Modify: `ebay_scraper.py` (add the scraper class)
- Modify: `tests/test_ebay_scraper.py` (add parse tests)
- Create: `tests/fixtures/ebay/search_with_results.json`
- Create: `tests/fixtures/ebay/search_empty.json`

- [ ] **Step 2.1: Create fixture payloads**

Create `tests/fixtures/ebay/search_with_results.json`:

```json
{
  "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=Frank+Brothers+Arcane&limit=50&offset=0",
  "total": 2,
  "limit": 50,
  "offset": 0,
  "itemSummaries": [
    {
      "itemId": "v1|256123456789|0",
      "title": "Frank Brothers Arcane TV Yellow 2023",
      "itemWebUrl": "https://www.ebay.com/itm/256123456789",
      "price": {"value": "4200.00", "currency": "USD"},
      "condition": "Used",
      "conditionId": "3000",
      "seller": {"username": "guitarshop_la"},
      "itemLocation": {"country": "US", "city": "Los Angeles", "stateOrProvince": "CA"},
      "shippingOptions": [
        {"shippingCost": {"value": "120.00", "currency": "USD"}, "shippingCostType": "FIXED"}
      ],
      "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l500.jpg"},
      "categories": [{"categoryId": "33034", "categoryName": "Electric Guitars"}],
      "itemCreationDate": "2026-06-15T12:00:00.000Z"
    },
    {
      "itemId": "v1|256987654321|0",
      "title": "Frank Brothers Arcane Trans Red — Mint",
      "itemWebUrl": "https://www.ebay.com/itm/256987654321",
      "price": {"value": "5100.00", "currency": "USD"},
      "condition": "Used",
      "conditionId": "3000",
      "seller": {"username": "vintage_axes"},
      "itemLocation": {"country": "CA", "city": "Toronto", "stateOrProvince": "ON"},
      "shippingOptions": [
        {"shippingCost": {"value": "0.00", "currency": "USD"}, "shippingCostType": "CALCULATED"}
      ],
      "image": {"imageUrl": "https://i.ebayimg.com/images/g/def/s-l500.jpg"},
      "categories": [{"categoryId": "33034", "categoryName": "Electric Guitars"}],
      "itemCreationDate": "2026-06-10T08:30:00.000Z"
    }
  ]
}
```

Create `tests/fixtures/ebay/search_empty.json`:

```json
{
  "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=NoSuchModel&limit=50&offset=0",
  "total": 0,
  "limit": 50,
  "offset": 0,
  "itemSummaries": []
}
```

- [ ] **Step 2.2: Add failing tests for parse + single-marketplace search**

Append to `tests/test_ebay_scraper.py`:

```python
import json
from pathlib import Path

from ebay_scraper import EbayScraper

FIXTURES = Path(__file__).parent / "fixtures" / "ebay"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_item_summary_maps_core_fields():
    raw = _load("search_with_results.json")["itemSummaries"][0]
    parsed = EbayScraper._parse_item_summary(raw, marketplace="EBAY_US")

    assert parsed["url"] == "https://www.ebay.com/itm/256123456789"
    assert parsed["name"] == "Frank Brothers Arcane TV Yellow 2023"
    assert parsed["price"] == "4200.00"
    assert parsed["currency"] == "USD"
    assert parsed["price_display"] == "USD 4200.00"
    assert parsed["condition"] == "Used"
    assert parsed["status"] == "Active"
    assert parsed["sale_ended"] is False
    assert parsed["shipping_price"] == "120.00"
    assert parsed["ships_to_canada"] is True
    assert parsed["seller"] == "guitarshop_la"
    assert parsed["location"] == "Los Angeles, CA, US"
    assert parsed["photo_url"] == "https://i.ebayimg.com/images/g/abc/s-l500.jpg"
    assert parsed["categories"] == ["Electric Guitars"]
    assert parsed["published_at"] == "2026-06-15"
    assert parsed["description"] == ""
    assert parsed["views"] == 0
    assert parsed["watchers"] == 0
    assert parsed["offers_enabled"] is False


def test_parse_item_summary_zero_shipping_is_free():
    raw = _load("search_with_results.json")["itemSummaries"][1]
    parsed = EbayScraper._parse_item_summary(raw, marketplace="EBAY_CA")
    assert parsed["shipping_price"] == "0.00"


def test_parse_item_summary_missing_shipping_falls_back_to_default():
    raw = {
        "itemId": "v1|111|0",
        "title": "No shipping listed",
        "itemWebUrl": "https://www.ebay.com/itm/111",
        "price": {"value": "100.00", "currency": "USD"},
        "condition": "Used",
        "seller": {"username": "x"},
        "itemLocation": {"country": "US"},
        "image": {"imageUrl": ""},
        "categories": [],
        "shippingOptions": [],
    }
    parsed = EbayScraper._parse_item_summary(
        raw, marketplace="EBAY_US", default_shipping="250.00"
    )
    assert parsed["shipping_price"] == "250.00"
    assert parsed["ships_to_canada"] is False


def test_extract_item_id_from_url():
    assert (
        EbayScraper._extract_item_id("https://www.ebay.com/itm/256123456789")
        == "256123456789"
    )
    assert (
        EbayScraper._extract_item_id("https://www.ebay.ca/itm/Some-Slug/256987654321")
        == "256987654321"
    )
    assert EbayScraper._extract_item_id("https://example.com/foo") is None


@pytest.mark.asyncio
async def test_search_single_marketplace_returns_parsed_items():
    payload = _load("search_with_results.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        assert "/buy/browse/v1/item_summary/search" in str(request.url)
        assert request.headers["Authorization"] == "Bearer TOK"
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth,
        marketplaces=("EBAY_US",),
        delivery_country="CA",
        transport=transport,
    ) as scraper:
        results = await scraper.search("Frank Brothers Arcane")

    assert len(results) == 2
    assert results[0]["url"] == "https://www.ebay.com/itm/256123456789"


@pytest.mark.asyncio
async def test_search_empty_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        return httpx.Response(200, json=_load("search_empty.json"))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth, marketplaces=("EBAY_US",), transport=transport
    ) as scraper:
        results = await scraper.search("NoSuchModel")

    assert results == []


@pytest.mark.asyncio
async def test_search_applies_category_filter_when_given():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_load("search_empty.json"))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth, marketplaces=("EBAY_US",), transport=transport
    ) as scraper:
        await scraper.search("test", category_id=33034)

    assert captured["params"]["category_ids"] == "33034"


@pytest.mark.asyncio
async def test_search_us_marketplace_filters_delivery_country():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        captured["filter"] = request.url.params.get("filter", "")
        captured["marketplace"] = request.headers.get("X-EBAY-C-MARKETPLACE-ID", "")
        return httpx.Response(200, json=_load("search_empty.json"))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth, marketplaces=("EBAY_US",), delivery_country="CA", transport=transport
    ) as scraper:
        await scraper.search("test")

    assert "deliveryCountry:CA" in captured["filter"]
    assert captured["marketplace"] == "EBAY_US"
```

- [ ] **Step 2.3: Run tests to verify they fail**

Run: `uv run pytest tests/test_ebay_scraper.py -v`
Expected: New tests FAIL with `ImportError: cannot import name 'EbayScraper'`.

- [ ] **Step 2.4: Implement `EbayScraper` (single-marketplace path)**

Append to `ebay_scraper.py`:

```python
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
import re  # noqa: E402  (kept near its single use site)

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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.auth = auth
        self.marketplaces = marketplaces
        self.delivery_country = delivery_country
        self.default_shipping = default_shipping
        self.page_size = min(page_size, 200)
        self.client = httpx.AsyncClient(transport=transport, timeout=15.0)

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
        if marketplace == "EBAY_US" and self.delivery_country:
            params["filter"] = f"deliveryCountry:{self.delivery_country}"

        first = await self._fetch_search_page(params, marketplace=marketplace)
        if first is None:
            return []

        results: list[dict[str, Any]] = [
            self._parse_item_summary(s, marketplace=marketplace, default_shipping=self.default_shipping)
            for s in first.get("itemSummaries", []) or []
        ]
        total = int(first.get("total", 0))
        if total <= self.page_size:
            return results

        # Fan out remaining pages concurrently.
        offsets = list(range(self.page_size, total, self.page_size))
        page_tasks = [
            self._fetch_search_page({**params, "offset": off}, marketplace=marketplace)
            for off in offsets
        ]
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
            logger.error("eBay search error ({} offset={}): {}", marketplace, params.get("offset"), exc)
            return None

    # ── parsing ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_item_id(url: str) -> str | None:
        match = _ITEM_ID_RE.search(url or "")
        return match.group(1) if match else None

    @staticmethod
    def _format_date(date_str: str) -> str:
        """Format an ISO date string to YYYY-MM-DD (UTC), or '' if blank."""
        from datetime import UTC, datetime  # local import keeps top clean

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
```

- [ ] **Step 2.5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ebay_scraper.py -v`
Expected: All tests pass (the originals from Task 1 plus the new ones).

- [ ] **Step 2.6: Commit**

```bash
git add ebay_scraper.py tests/test_ebay_scraper.py tests/fixtures/ebay/
git commit -m "feat(ebay): add EbayScraper single-marketplace search + parse"
```

---

## Task 3: Multi-marketplace dedup

**Files:**
- Modify: `tests/test_ebay_scraper.py`

The `search()` method already iterates marketplaces and dedupes by `_ebay_item_id`, but it isn't covered by an explicit test. Lock the behaviour in.

- [ ] **Step 3.1: Add failing test for multi-marketplace dedup**

Append to `tests/test_ebay_scraper.py`:

```python
@pytest.mark.asyncio
async def test_search_dedupes_across_marketplaces():
    payload = _load("search_with_results.json")

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        # Same payload returned for both EBAY_US and EBAY_CA — duplicate item ids.
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth, marketplaces=("EBAY_US", "EBAY_CA"), transport=transport
    ) as scraper:
        results = await scraper.search("Frank Brothers Arcane")

    urls = [r["url"] for r in results]
    assert len(urls) == len(set(urls)) == 2
```

- [ ] **Step 3.2: Run test to verify it passes**

Run: `uv run pytest tests/test_ebay_scraper.py::test_search_dedupes_across_marketplaces -v`
Expected: PASS (the dedup logic was implemented in Task 2).

- [ ] **Step 3.3: Add failing test for pagination**

Append to `tests/test_ebay_scraper.py`:

```python
@pytest.mark.asyncio
async def test_search_paginates_when_total_exceeds_page_size():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            return httpx.Response(200, json=_ok_token_response("TOK", 7200))
        call_count["n"] += 1
        offset = int(request.url.params.get("offset", "0"))
        # Each page returns one synthetic item; total claims 5 items across pages of size 2.
        item = {
            "itemId": f"v1|{offset}|0",
            "title": f"Item at offset {offset}",
            "itemWebUrl": f"https://www.ebay.com/itm/{offset:09d}",
            "price": {"value": "100.00", "currency": "USD"},
            "condition": "Used",
            "seller": {"username": "x"},
            "itemLocation": {"country": "US"},
            "shippingOptions": [{"shippingCost": {"value": "10.00", "currency": "USD"}}],
            "image": {"imageUrl": ""},
            "categories": [],
        }
        return httpx.Response(200, json={
            "total": 5,
            "limit": 2,
            "offset": offset,
            "itemSummaries": [item, {**item, "itemId": f"v1|{offset}b|0",
                                      "itemWebUrl": f"https://www.ebay.com/itm/{offset:09d}b"}],
        })

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(
        auth=auth, marketplaces=("EBAY_US",), page_size=2, transport=transport
    ) as scraper:
        results = await scraper.search("test")

    # 3 pages requested (offset 0, 2, 4); each returns 2 items = 6 items total before dedup.
    # Dedup is by item id — all are distinct in this synthetic data.
    assert call_count["n"] == 3
    assert len(results) == 6
```

- [ ] **Step 3.4: Run test to verify it passes**

Run: `uv run pytest tests/test_ebay_scraper.py::test_search_paginates_when_total_exceeds_page_size -v`
Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add tests/test_ebay_scraper.py
git commit -m "test(ebay): cover multi-marketplace dedup and pagination"
```

---

## Task 4: Category map module

**Files:**
- Create: `ebay_categories.py`
- Modify: `tests/test_ebay_scraper.py`

- [ ] **Step 4.1: Write failing test**

Append to `tests/test_ebay_scraper.py`:

```python
from ebay_categories import REVERB_SLUG_TO_EBAY_CATEGORY, ebay_category_for_reverb_slug


def test_ebay_category_for_known_slug():
    assert ebay_category_for_reverb_slug("electric-guitars") == 33034


def test_ebay_category_for_unknown_slug_is_none():
    assert ebay_category_for_reverb_slug("not-a-real-slug") is None


def test_ebay_category_for_none_slug_is_none():
    assert ebay_category_for_reverb_slug(None) is None


def test_category_map_has_seed_entries():
    assert "electric-guitars" in REVERB_SLUG_TO_EBAY_CATEGORY
    assert "acoustic-guitars" in REVERB_SLUG_TO_EBAY_CATEGORY
    assert "effects-and-pedals" in REVERB_SLUG_TO_EBAY_CATEGORY
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ebay_scraper.py -k category -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ebay_categories'`.

- [ ] **Step 4.3: Create the module**

Create `ebay_categories.py`:

```python
"""Static map from Reverb category slugs to eBay numeric category ids.

The slug is read from each ``x_models`` row's linked ``x_reverb_category``
record (``x_studio_slug``).  When a slug has no mapping here, eBay search
runs without a ``categoryIds`` filter — noisier but still functional.

Extend the map as new categories are encountered in Odoo; there is no
runtime requirement to keep it exhaustive.
"""

from __future__ import annotations

REVERB_SLUG_TO_EBAY_CATEGORY: dict[str, int] = {
    # Guitars
    "electric-guitars": 33034,
    "acoustic-guitars": 33021,
    "bass-guitars": 4713,
    # Pedals & effects
    "effects-and-pedals": 41419,
    # Amps
    "amps": 38072,
    "guitar-amplifiers": 38072,
}


def ebay_category_for_reverb_slug(slug: str | None) -> int | None:
    """Return the eBay category id for *slug*, or ``None`` if not mapped."""
    if not slug:
        return None
    return REVERB_SLUG_TO_EBAY_CATEGORY.get(slug)
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ebay_scraper.py -k category -v`
Expected: 4 passed.

- [ ] **Step 4.5: Commit**

```bash
git add ebay_categories.py tests/test_ebay_scraper.py
git commit -m "feat(ebay): add Reverb-slug to eBay-category-id map"
```

---

## Task 5: Wire eBay into `sync_model.py` — registry + helpers

**Files:**
- Modify: `sync_model.py`
- Modify: `tests/test_sync_model.py`

This task introduces the platform registry and the new `_search_ebay` helper, plus renames `_reverb_to_listing_vals` so it can serve both platforms. CLI changes come in Task 6.

- [ ] **Step 5.1: Read the existing helpers to find their exact locations**

Run: `grep -n "_reverb_to_listing_vals\|_search_reverb\|x_platform" sync_model.py`
Expected output shows `_search_reverb` near line 277, `_reverb_to_listing_vals` near line 391 (with `"x_platform": "reverb"` hardcoded inside).

- [ ] **Step 5.2: Add failing test for the platform registry**

Append to `tests/test_sync_model.py` (after the existing imports — verify `import sync_model` is available or add it):

```python
def test_platforms_registry_has_reverb_and_ebay():
    from sync_model import PLATFORMS

    assert set(PLATFORMS.keys()) == {"reverb", "ebay"}
    assert callable(PLATFORMS["reverb"])
    assert callable(PLATFORMS["ebay"])


def test_listing_vals_from_scrape_tags_platform():
    from sync_model import _listing_vals_from_scrape

    scrape = {
        "url": "https://www.ebay.com/itm/123",
        "name": "Test eBay Listing",
        "price": "100.00",
        "shipping_price": "20.00",
        "sale_ended": False,
        "offers_enabled": False,
        "description": "",
        "published_at": "",
    }
    vals = _listing_vals_from_scrape(scrape, model_id=42, default_shipping=250.0, platform="ebay")
    assert vals["x_platform"] == "ebay"
    assert vals["x_url"] == "https://www.ebay.com/itm/123"
    assert vals["x_model_id"] == 42


def test_listing_vals_from_scrape_reverb_unchanged():
    from sync_model import _listing_vals_from_scrape

    scrape = {
        "url": "https://reverb.com/item/123-foo",
        "name": "Reverb Listing",
        "price": "100.00",
        "shipping_price": "20.00",
        "sale_ended": False,
        "offers_enabled": True,
        "description": "",
        "published_at": "2026-06-01",
    }
    vals = _listing_vals_from_scrape(scrape, model_id=42, default_shipping=250.0, platform="reverb")
    assert vals["x_platform"] == "reverb"
    assert vals["x_can_accept_offers"] is True
```

- [ ] **Step 5.3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_model.py -k "platforms_registry or listing_vals_from_scrape" -v`
Expected: FAIL with `ImportError` on `PLATFORMS` / `_listing_vals_from_scrape`.

- [ ] **Step 5.4: Refactor `_reverb_to_listing_vals` → `_listing_vals_from_scrape`**

In `sync_model.py`, locate the existing `_reverb_to_listing_vals` definition (around line 391) and replace it with:

```python
def _listing_vals_from_scrape(
    scrape: dict,
    model_id: int,
    default_shipping: float = DEFAULT_SHIPPING,
    *,
    platform: str = "reverb",
) -> dict[str, Any]:
    """Build x_listing creation values from a scraped listing dict.

    *platform* is the value written to ``x_platform`` (e.g. ``"reverb"`` or
    ``"ebay"``).  All input dicts must share the keys produced by
    :meth:`reverb_scraper.ReverbScraper._parse_api_response` / its eBay
    counterpart.
    """
    price = float(scrape.get("price", 0) or 0)
    ship = scrape.get("shipping_price")
    ship_f = float(ship) if ship is not None else default_shipping
    published = scrape.get("published_at", "")

    vals: dict[str, Any] = {
        "x_name": scrape.get("name", ""),
        "x_model_id": model_id,
        "x_status": "watching",
        "x_url": scrape.get("url", ""),
        "x_platform": platform,
        "x_price": _round_price(price),
        "x_shipping": _round_price(ship_f),
        "x_is_available": not scrape.get("sale_ended", False),
        "x_can_accept_offers": scrape.get("offers_enabled", False),
        "x_is_taxed": False,
    }
    description = scrape.get("description", "")
    if description:
        vals["x_studio_notes"] = description
    if published:
        vals["x_published_at"] = published + " 00:00:00"

    return vals
```

Then find every caller (there is currently one) and update it. Run:

```bash
grep -n "_reverb_to_listing_vals" sync_model.py
```

Expected: one usage inside `_build_report` (around line 515). Replace `_reverb_to_listing_vals(r, model_id, default_shipping)` with `_listing_vals_from_scrape(r, model_id, default_shipping, platform=r.get("_platform", "reverb"))`.

- [ ] **Step 5.5: Add `_search_ebay` and the `PLATFORMS` registry**

Insert after the existing `_search_reverb` (around line 318):

```python
def _search_ebay(
    query: str,
    *,
    category: str | None = None,
    default_shipping: float = DEFAULT_SHIPPING,
    include_sold: bool = False,
) -> list[dict]:
    """Search eBay for *query* across EBAY_US (ships-to-CA) + EBAY_CA.

    *category* is the Reverb category **slug** (e.g. ``"electric-guitars"``);
    it is mapped to an eBay numeric category id via
    :data:`ebay_categories.REVERB_SLUG_TO_EBAY_CATEGORY`.  Unknown slugs
    fall back to no category filter.

    *include_sold* is accepted for signature compatibility with
    :func:`_search_reverb` but is a no-op (eBay's Browse API does not
    return sold listings); a one-time warning is emitted.
    """
    from ebay_categories import ebay_category_for_reverb_slug
    from ebay_scraper import EbayAuth, EbayAuthError, EbayScraper

    if include_sold:
        logger.warning("eBay: --include-sold is a no-op (Browse API returns live listings only)")

    try:
        auth = EbayAuth.from_env()
    except EbayAuthError as exc:
        logger.warning("eBay search skipped: {}", exc)
        return []

    category_id = ebay_category_for_reverb_slug(category)
    shipping_str = f"{default_shipping:.2f}"

    async def _fetch() -> list[dict]:
        async with EbayScraper(
            auth=auth,
            marketplaces=("EBAY_US", "EBAY_CA"),
            delivery_country="CA",
            default_shipping=shipping_str,
        ) as scraper:
            return await scraper.search(query, category_id=category_id)

    try:
        results = asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001 — surface as warning, keep Reverb leg alive
        logger.warning("eBay search failed for '{}': {}", query, exc)
        return []

    for r in results:
        r["_platform"] = "ebay"

    logger.debug("eBay search '{}': {} unique listing(s)", query, len(results))
    return results
```

Tag Reverb results with `_platform` too — find the body of `_search_reverb` and after the dedup loop add:

```python
    for r in unique:
        r["_platform"] = "reverb"
```

Then, at the module level (just above the CLI definition, near line 663), add:

```python
PLATFORMS: dict[str, Any] = {
    "reverb": _search_reverb,
    "ebay": _search_ebay,
}
```

- [ ] **Step 5.6: Run tests**

Run: `uv run pytest tests/test_sync_model.py -k "platforms_registry or listing_vals_from_scrape" -v`
Expected: 3 passed.

- [ ] **Step 5.7: Run full sync_model test suite to catch regressions**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: All existing tests still pass (the rename and `_platform` tag must not break anything).

If a test fails because it called `_reverb_to_listing_vals`, update the test to import `_listing_vals_from_scrape` instead and add `platform="reverb"` to the call.

- [ ] **Step 5.8: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): introduce PLATFORMS registry + eBay search helper"
```

---

## Task 6: Wire eBay into `_collect_sync_data` and the CLI

**Files:**
- Modify: `sync_model.py`
- Modify: `tests/test_sync_model.py`

- [ ] **Step 6.1: Add failing test for `--platform` filter wiring**

Append to `tests/test_sync_model.py`:

```python
def test_collect_sync_data_runs_only_selected_platforms(monkeypatch):
    """`platforms=["reverb"]` must NOT invoke the eBay search at all."""
    from unittest.mock import MagicMock

    import sync_model

    fake_reverb = MagicMock(return_value=[
        {"url": "https://reverb.com/item/1-foo", "name": "Reverb 1", "price": "100",
         "sale_ended": False, "shipping_price": "10", "_platform": "reverb"}
    ])
    fake_ebay = MagicMock(return_value=[])

    monkeypatch.setattr(sync_model, "PLATFORMS", {"reverb": fake_reverb, "ebay": fake_ebay})

    fake_conn = MagicMock()
    fake_listing = MagicMock()
    fake_listing.search_read.return_value = []
    fake_conn.get_model.return_value = fake_listing

    data = sync_model._collect_sync_data(
        fake_conn,
        model_id=1,
        model_name="Test",
        category_slug=None,
        default_shipping=250.0,
        platforms=["reverb"],
    )

    fake_reverb.assert_called_once()
    fake_ebay.assert_not_called()
    assert len(data["reverb_results"]) == 1


def test_collect_sync_data_runs_all_platforms_by_default(monkeypatch):
    from unittest.mock import MagicMock

    import sync_model

    fake_reverb = MagicMock(return_value=[])
    fake_ebay = MagicMock(return_value=[])
    monkeypatch.setattr(sync_model, "PLATFORMS", {"reverb": fake_reverb, "ebay": fake_ebay})

    fake_conn = MagicMock()
    fake_listing = MagicMock()
    fake_listing.search_read.return_value = []
    fake_conn.get_model.return_value = fake_listing

    sync_model._collect_sync_data(
        fake_conn,
        model_id=1,
        model_name="Test",
        category_slug=None,
        default_shipping=250.0,
        platforms=["reverb", "ebay"],
    )

    fake_reverb.assert_called_once()
    fake_ebay.assert_called_once()
```

- [ ] **Step 6.2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_model.py -k "collect_sync_data_runs" -v`
Expected: FAIL — `_collect_sync_data` does not accept `platforms` yet.

- [ ] **Step 6.3: Update `_collect_sync_data`**

In `sync_model.py`, locate `_collect_sync_data` (around line 669) and update its signature + body:

```python
def _collect_sync_data(
    conn,
    *,
    model_id: int,
    model_name: str,
    category_slug: str | None,
    default_shipping: float,
    search_query: str | None = None,
    include_brand_new: bool = False,
    include_sold: bool = False,
    platforms: list[str] | None = None,
) -> dict[str, Any]:
    """Search every enabled marketplace and fetch Odoo entries for one model.

    *platforms* defaults to ``list(PLATFORMS.keys())`` (i.e. all registered
    marketplaces).  Each platform's search function is invoked sequentially
    and its results are concatenated; per-result deduplication happens later
    in :func:`_build_report`.
    """
    enabled = platforms if platforms is not None else list(PLATFORMS.keys())
    query = search_query or model_name

    all_results: list[dict] = []
    for platform in enabled:
        searcher = PLATFORMS.get(platform)
        if searcher is None:
            logger.warning("Unknown platform '{}' — skipped", platform)
            continue
        logger.debug("[{}] Searching {} for '{}'…", model_name, platform, query)
        all_results.extend(
            searcher(
                query,
                category=category_slug,
                default_shipping=default_shipping,
                include_sold=include_sold,
            )
        )

    if not all_results:
        logger.warning("[{}] No marketplace results for '{}'", model_name, query)
        return {
            "model_id": model_id,
            "model_name": model_name,
            "default_shipping": default_shipping,
            "reverb_results": [],
            "odoo_entries": [],
            "report": [],
            "update_count": 0,
            "create_count": 0,
        }

    logger.debug("[{}] Fetching existing Odoo listing records…", model_name)
    url_candidates: set[str] = set()
    for r in all_results:
        raw = r.get("url", "")
        if not raw:
            continue
        url_candidates.add(raw)
        url_candidates.add(_clean_url(raw))
    odoo_entries = _fetch_listings(conn, model_id, extra_urls=list(url_candidates))
    logger.debug("[{}] Found {} existing listing records", model_name, len(odoo_entries))

    report = _build_report(
        all_results,
        odoo_entries,
        model_id,
        default_shipping,
        include_brand_new=include_brand_new,
    )
    update_count = sum(1 for item in report if item["action"] == "update")
    create_count = sum(1 for item in report if item["action"] == "create")

    return {
        "model_id": model_id,
        "model_name": model_name,
        "default_shipping": default_shipping,
        "reverb_results": all_results,  # legacy key — now holds ALL platform results
        "odoo_entries": odoo_entries,
        "report": report,
        "update_count": update_count,
        "create_count": create_count,
    }
```

(The dict key remains `reverb_results` for backwards compatibility with the printing code; it now stores combined results.)

- [ ] **Step 6.4: Run targeted tests**

Run: `uv run pytest tests/test_sync_model.py -k "collect_sync_data_runs" -v`
Expected: 2 passed.

- [ ] **Step 6.5: Run full sync_model test suite**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: All tests pass. If any existing test calls `_collect_sync_data` with positional args, switch to keyword args.

- [ ] **Step 6.6: Add `--platform` CLI flag**

Locate the `@click.command("sync")` block at the bottom of `sync_model.py` (around line 747). Add this option after `--include-sold`:

```python
@click.option(
    "--platform",
    "platform_filter",
    type=click.Choice(["reverb", "ebay", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Restrict search to a single marketplace (default: search all).",
)
```

Add a matching parameter `platform_filter: str` to the `cli(...)` function signature.

Inside `cli(...)`, just before the `if all_models:` branch, add:

```python
    # Resolve the platform filter -----------------------------------------------
    if platform_filter == "all":
        selected_platforms = list(PLATFORMS.keys())
    else:
        selected_platforms = [platform_filter]
        # Fail fast on ebay without creds — better than silent empty results.
        if platform_filter == "ebay":
            from ebay_scraper import EbayAuth, EbayAuthError
            try:
                EbayAuth.from_env()
            except EbayAuthError as exc:
                raise click.UsageError(str(exc)) from None
```

Then pass `platforms=selected_platforms` to **every** call site of `_collect_sync_data` in the function — there are two (one inside the `--all` thread pool submission, one in the single-model branch).

- [ ] **Step 6.7: Add failing test for `--platform ebay` without credentials**

Append to `tests/test_sync_model.py`:

```python
def test_cli_platform_ebay_without_credentials_fails_clearly(monkeypatch):
    from click.testing import CliRunner

    import sync_model

    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    runner = CliRunner()
    # Build a minimal context the way Click expects: use the standalone group.
    from cli import main as cli_root

    result = runner.invoke(
        cli_root,
        [
            "--odoo-hostname", "h",
            "--odoo-database", "d",
            "--odoo-login", "u",
            "--odoo-password", "p",
            "sync", "--platform", "ebay", "Test Model",
        ],
        catch_exceptions=False,
    )
    # The Odoo connection won't actually be made because the platform-ebay
    # check happens after group init but the connection step will fail first
    # in this environment. The important thing is the error message mentions
    # eBay credentials when it surfaces — assert that the error path is hit.
    assert result.exit_code != 0
```

This test verifies the CLI path is wired up; if Odoo connection fails first, that's acceptable as long as the exit is non-zero. The real verification is in Step 6.8 below.

A more direct test of the credential check (no Odoo dependency):

```python
def test_resolve_platforms_ebay_without_credentials_raises(monkeypatch):
    """Direct check: the platform filter resolution raises when ebay creds missing."""
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)

    from ebay_scraper import EbayAuth, EbayAuthError

    with pytest.raises(EbayAuthError, match="EBAY_CLIENT_ID"):
        EbayAuth.from_env()
```

- [ ] **Step 6.8: Run tests**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: All pass.

- [ ] **Step 6.9: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): add --platform flag (reverb|ebay|all) to sync command"
```

---

## Task 7: Document credentials + flag

**Files:**
- Modify: `env-template.yml`
- Modify: `README.md`

- [ ] **Step 7.1: Update `env-template.yml`**

Read the current file and add an `ebay` section at the bottom:

```yaml
ebay:
  client_id: ""        # https://developer.ebay.com/my/keys — production keyset
  client_secret: ""
```

- [ ] **Step 7.2: Update `README.md`**

Search the README for the existing `sync` documentation:

```bash
grep -n "sync" README.md | head -20
```

Locate the section describing the `sync` command. Add a subsection (place it where it fits the document's structure — typically right after the `--include-sold` documentation):

```markdown
### Multi-platform search

By default `sync` queries both Reverb and eBay. Restrict with `--platform`:

```bash
reverb2odoo sync "Frank Brothers Arcane" --platform reverb   # Reverb only
reverb2odoo sync "Frank Brothers Arcane" --platform ebay     # eBay only
reverb2odoo sync "Frank Brothers Arcane"                     # both (default)
```

eBay searches use the Browse API and require OAuth2 client credentials. Register an app at <https://developer.ebay.com/my/keys> and export:

```bash
export EBAY_CLIENT_ID="..."
export EBAY_CLIENT_SECRET="..."
```

eBay coverage:

- Searches `EBAY_US` (filtered to ships-to-Canada) AND `EBAY_CA`, deduped by item id.
- Returns LIVE listings only — `--include-sold` is a no-op for eBay (the Browse API does not expose sold/ended items).
- Categories are mapped from the model's Reverb category via a static map in `ebay_categories.py`. Unknown slugs search without a category filter.
```

- [ ] **Step 7.3: Commit**

```bash
git add env-template.yml README.md
git commit -m "docs: document eBay credentials and --platform flag"
```

---

## Task 8: End-to-end smoke + final test sweep

**Files:** none (verification only)

- [ ] **Step 8.1: Full test suite passes**

Run: `uv run pytest -v`
Expected: All tests pass (existing + new).

- [ ] **Step 8.2: Lint clean**

Run: `uv run ruff check .`
Expected: 0 errors. Fix any issues inline.

Run: `uv run ruff format --check .`
Expected: 0 files would be reformatted. If any would be, run `uv run ruff format .` and commit the fixes.

- [ ] **Step 8.3: Verify CLI help renders**

Run: `uv run reverb2odoo sync --help`
Expected: help text includes `--platform` with choices `[reverb|ebay|all]`.

- [ ] **Step 8.4: (Optional) Live smoke against a known model**

Only run if `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` and `ODOO_*` are set in the environment:

```bash
uv run reverb2odoo sync "Frank Brothers Arcane" --platform ebay --dry-run
```

Expected: report table shows eBay listings (or "no results" for the query); no Odoo writes occur.

- [ ] **Step 8.5: Commit lint fixes if any**

```bash
git status
# If anything is dirty:
git add -A && git commit -m "style: ruff format pass"
```

---

## Done

After Task 8 the feature is shippable:

- `sync` queries Reverb + eBay by default; `--platform` restricts.
- eBay listings are created in `x_listing` with `x_platform="ebay"`, indistinguishable to the rest of the system from Reverb listings.
- All existing Reverb behaviour is preserved.
- Test suite covers OAuth caching, parse mapping, multi-marketplace dedup, pagination, platform-registry wiring, and the CLI flag.
