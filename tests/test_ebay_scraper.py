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
