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
