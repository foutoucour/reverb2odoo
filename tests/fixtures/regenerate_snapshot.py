"""Regenerate ``odoo_fields_snapshot.json`` from live Odoo.

Run when Studio fields are added or renamed:

.. code-block:: bash

    set -a && source .env && set +a
    uv run python tests/fixtures/regenerate_snapshot.py

The snapshot drives :mod:`tests.test_models`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Allow imports from the repo root when this script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from odoo_connector import get_connection  # noqa: E402

_OUTPUT = Path(__file__).parent / "odoo_fields_snapshot.json"
_MODELS = (
    "x_gear",
    "x_listing",
    "x_models",
    "x_weighted_tags",
    "x_weighted_tag_groups",
)


def main() -> None:
    conn = get_connection(
        hostname=os.environ["ODOO_HOSTNAME"],
        database=os.environ["ODOO_DATABASE"],
        login=os.environ["ODOO_LOGIN"],
        password=os.environ["ODOO_PASSWORD"],
    )
    fields_proxy = conn.get_model("ir.model.fields")

    snapshot: dict[str, list[str]] = {}
    for model_name in _MODELS:
        rows = fields_proxy.search_read([("model", "=", model_name)], ["name"])
        snapshot[model_name] = sorted({r["name"] for r in rows})

    _OUTPUT.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Wrote {_OUTPUT}")
    for name in _MODELS:
        print(f"  {name}: {len(snapshot[name])} fields")


if __name__ == "__main__":
    main()
