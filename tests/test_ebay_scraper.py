"""Tests for ebay_scraper — unit tests are pure-sync, integration tests use VCR."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from ebay_scraper import EbayAuth, EbayAuthError, EbayScraper

FIXTURES = Path(__file__).parent / "fixtures" / "ebay"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


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
    # Force the next call to see the cached token as near-expiry.
    # Capture the real monotonic before patching, otherwise the lambda
    # would recurse into its own replacement.
    real_monotonic = time.monotonic
    monkeypatch.setattr("ebay_scraper.time.monotonic", lambda: real_monotonic() + 1000)
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
    parsed = EbayScraper._parse_item_summary(raw, marketplace="EBAY_US", default_shipping="250.00")
    assert parsed["shipping_price"] == "250.00"
    assert parsed["ships_to_canada"] is False


def test_extract_item_id_from_url():
    assert EbayScraper._extract_item_id("https://www.ebay.com/itm/256123456789") == "256123456789"
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
    async with EbayScraper(auth=auth, marketplaces=("EBAY_US",), transport=transport) as scraper:
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
    async with EbayScraper(auth=auth, marketplaces=("EBAY_US",), transport=transport) as scraper:
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


@pytest.mark.asyncio
async def test_search_retries_once_on_401():
    """A 401 should trigger token invalidation + a single retry."""
    token_calls = {"n": 0}
    search_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth2/token" in str(request.url):
            token_calls["n"] += 1
            return httpx.Response(200, json=_ok_token_response(f"TOK_{token_calls['n']}", 7200))
        search_calls["n"] += 1
        if search_calls["n"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json=_load("search_empty.json"))

    transport = httpx.MockTransport(handler)
    auth = EbayAuth(client_id="CID", client_secret="SEC", transport=transport)
    async with EbayScraper(auth=auth, marketplaces=("EBAY_US",), transport=transport) as scraper:
        results = await scraper.search("test")

    assert results == []
    assert search_calls["n"] == 2  # initial + 1 retry
    assert token_calls["n"] == 2  # initial fetch + post-invalidate refetch
