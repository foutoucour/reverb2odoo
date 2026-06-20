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
