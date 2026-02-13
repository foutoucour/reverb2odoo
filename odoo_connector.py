"""
Connect to an Odoo instance using odoo-client-lib.

Credentials are supplied as explicit arguments (sourced from environment
variables / CLI options by the caller).
"""

from urllib.parse import urlparse

import odoolib
from loguru import logger

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _hostname_from_url(raw: str) -> str:
    """Extract a clean hostname from a possibly-full URL.

    ``https://reverb2odoo.odoo.com/odoo`` → ``reverb2odoo.odoo.com``
    ``localhost`` → ``localhost``
    """
    if "://" in raw:
        return urlparse(raw).hostname or raw
    return raw.split("/")[0]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def get_connection(
    hostname: str,
    database: str,
    login: str,
    password: str,
) -> odoolib.main.Connection:
    """Return an authenticated ``odoolib`` connection.

    *hostname* may be a full URL (``https://mydb.odoo.com/odoo``) or a
    bare host (``localhost``).  Protocol and port are inferred from the
    URL scheme.
    """
    clean_host = _hostname_from_url(hostname)

    is_https = hostname.startswith("https://")
    protocol = "jsonrpcs" if is_https else "jsonrpc"
    port = 443 if is_https else 8069

    logger.info("Connecting to Odoo at {}:{} ({})…", clean_host, port, protocol)

    connection = odoolib.get_connection(
        hostname=clean_host,
        database=database,
        login=login,
        password=password,
        protocol=protocol,
        port=port,
    )
    return connection


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# x_guitar lookups
# ---------------------------------------------------------------------------

#: Fields typically needed when looking up a guitar entry.
GUITAR_FIELDS: list[str] = [
    "x_name",
    "x_studio_url",
    "x_studio_models",
    "x_studio_value",
    "x_studio_best_price",
    "x_studio_best_price_ht",
    "x_studio_shipping",
    "x_studio_taxed",
    "x_studio_is_available",
    "x_studio_active",
    "x_studio_accept_offers",
    "x_studio_score",
    "x_studio_model_type",
    "x_studio_currency_id",
    "x_studio_average",
    "x_studio_my_cad_ttc",
    "x_studio_target_price_ht",
    "x_studio_target_price_ttc",
    "x_studio_published_at",
]


def find_guitar_by_url(
    conn: odoolib.main.Connection,
    url: str,
    fields: list[str] | None = None,
) -> dict | None:
    """Look up a single ``x_guitar`` record by its Reverb / listing URL.

    The search tries, in order:

    1. **Exact match** on ``x_studio_url``.
    2. **Partial match** using the Reverb item ID extracted from the URL
       (e.g. ``94370297`` from
       ``https://reverb.com/item/94370297-godin-stadium-…``).

    Parameters
    ----------
    conn:
        An authenticated ``odoolib`` connection.
    url:
        The full listing URL to search for.
    fields:
        Fields to return.  Defaults to :data:`GUITAR_FIELDS`.

    Returns
    -------
    dict | None
        The matching record, or ``None`` if nothing was found.
    """
    if fields is None:
        fields = GUITAR_FIELDS

    model = conn.get_model("x_guitar")

    # 1. Exact match ----------------------------------------------------------
    results = model.search_read([("x_studio_url", "=", url)], fields, limit=1)
    if results:
        logger.success("Exact URL match → id={}", results[0]["id"])
        return results[0]

    # 2. Partial match on Reverb item ID --------------------------------------
    item_id = _extract_reverb_item_id(url)
    if item_id:
        logger.debug("Trying partial match with Reverb item ID '{}'…", item_id)
        results = model.search_read(
            [("x_studio_url", "ilike", item_id)],
            fields,
            limit=1,
        )
        if results:
            logger.success("Partial URL match (item {}) → id={}", item_id, results[0]["id"])
            return results[0]

    logger.warning("No x_guitar record found for URL: {}", url)
    return None


def _extract_reverb_item_id(url: str) -> str | None:
    """Extract the numeric Reverb item ID from a URL.

    ``https://reverb.com/item/94370297-godin-…`` → ``"94370297"``

    Returns ``None`` when the URL does not look like a Reverb item link.
    """
    # Path looks like /item/94370297-slug-text
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "item":
        slug = parts[-1]
        # The item ID is the leading digits before the first hyphen
        segment = slug.split("-", 1)[0]
        if segment.isdigit():
            return segment
    return None
