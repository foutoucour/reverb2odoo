"""Brand cache — fetches GitHub README and merges with res.partner from Odoo.

Public interface (contract for brands.py):
    get_brands(conn) -> list[dict]

Each dict has keys:
    name: str
    odoo_id: int | None
    average_price: str | None
    country: str | None
    website: str | None
    categories: list[str]
    made_in: str | None
    price_range: str | None
    single_cut_models: str | None
    description: str | None
"""

from __future__ import annotations

# Implementation to be filled in by T-004 teammate.
# This stub ensures brands.py (T-008) can import and type-check against the interface.
