# Quick Spec: Odoo MCP Server — Collection Source of Truth

**Date**: 2026-04-12
**Scope**: 1 new package (`odoo_mcp/`), ~12 files, 2 modified files

## Goal

Replace static knowledge-base markdown files with live MCP resources backed by Odoo.
The server runs via stdio and connects to Claude Desktop as a named MCP server.

---

## Package Layout

```
odoo_mcp/
  __init__.py
  server.py           # FastMCP app, registers all resources + tools
  config.py           # loads .env → OdooConfig dataclass
  brand_cache.py      # fetches GitHub README, merges with res.partner, TTL cache
  resources/
    __init__.py
    collection.py     # odoo://collection
    watchlist.py      # odoo://watchlist
    sold.py           # odoo://sold
    brands.py         # odoo://brands
    models.py         # odoo://models
  tools/
    __init__.py
    search_gear.py    # search_gear(brand?, model_type?, status?, intent?)
    get_model.py      # get_model(name_or_id)
    get_gear.py       # get_gear(id)
```

---

## Tasks

### 1. Add dependencies + entry point
- **Files**: `pyproject.toml` (modify)
- **What**: Add `mcp[cli]>=1.0,<2` and `python-dotenv>=1.0,<2` to `dependencies`.
  Add entry point `odoo-mcp = "odoo_mcp.server:main"` under `[project.scripts]`.
  Add `"odoo_mcp"` to `known-first-party` in ruff isort config.
- **Acceptance**:
  - Given a fresh `uv sync`, when running `uv run odoo-mcp`, then the server starts without import errors.

---

### 2. Expand field constants in `odoo_connector.py`
- **Files**: `odoo_connector.py` (modify)
- **What**: Add three new field-list constants for MCP use (do not remove existing ones):

```python
GEAR_FIELDS_MCP: list[str] = [
    "id", "x_name", "x_model_id", "x_intent", "x_condition", "x_status",
    "x_serial_number", "x_neck_profile", "x_studio_acquiring_price", "x_studio_notes",
    "x_listing_ids",
]

LISTING_FIELDS_MCP: list[str] = [
    "id", "x_name", "x_model_id", "x_url", "x_platform", "x_price",
    "x_currency_id", "x_shipping", "x_condition", "x_status",
    "x_is_available", "x_can_accept_offers", "x_is_taxed", "x_published_at",
    "x_gear_id", "x_studio_listing_score", "x_studio_price_score", "x_studio_notes",
]

MODEL_FIELDS_MCP: list[str] = [
    "id", "x_name", "x_studio_partner_id", "x_studio_model_type",
    "x_studio_wanna", "x_studio_guitar_familly_ids", "x_studio_guitar_neck_feel_id",
    "x_studio_scale", "x_studio_finish", "x_studio_fretboard_1",
    "x_studio_p25", "x_studio_p50", "x_studio_p75",
]
```

> ⚠️ Field names for `x_models` are taken from memory/gpt_model.py patterns —
> verify against live Odoo schema before first run. Score fields
> (`x_studio_listing_score`, `x_studio_price_score`) must be confirmed in Studio.

- **Acceptance**:
  - Given `from odoo_connector import GEAR_FIELDS_MCP, LISTING_FIELDS_MCP, MODEL_FIELDS_MCP`, no ImportError.

---

### 3. Create `odoo_mcp/config.py`
- **Files**: `odoo_mcp/config.py` (create), `odoo_mcp/__init__.py` (create, empty)
- **What**: Load `.env` via `python-dotenv`, expose `OdooConfig` dataclass + `get_connection_from_env()`.

```python
from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv
from odoo_connector import get_connection

load_dotenv(Path(__file__).parent.parent / ".env")

@dataclass
class OdooConfig:
    hostname: str
    database: str
    login: str
    password: str

def get_odoo_config() -> OdooConfig:
    return OdooConfig(
        hostname=os.environ["ODOO_HOSTNAME"],
        database=os.environ["ODOO_DATABASE"],
        login=os.environ["ODOO_LOGIN"],
        password=os.environ["ODOO_PASSWORD"],
    )

def get_connection_from_env():
    cfg = get_odoo_config()
    return get_connection(cfg.hostname, cfg.database, cfg.login, cfg.password)
```

- **Acceptance**:
  - Given valid `.env`, when importing config, then `get_odoo_config()` returns populated dataclass.
  - Given missing env var, when calling `get_odoo_config()`, then `KeyError` is raised (fail fast).

---

### 4. Create `odoo_mcp/brand_cache.py`
- **Files**: `odoo_mcp/brand_cache.py` (create)
- **What**: Fetch GitHub README markdown, parse brand entries, merge with `res.partner` from Odoo.
  Cache result in module-level dict with a timestamp. Refresh if >30 days old.

  GitHub URL: `https://raw.githubusercontent.com/foutoucour/awesome-single-cut-guitars/main/README.md`

  Parse strategy: split on `## Brand:` headers, extract `web:`, `made_in:`, `price_range:`,
  `single_cut_models:`, `description:` per entry.

  Merge key: brand name (case-insensitive match against `res.partner.name`).

  `res.partner` query fields: `["id", "name", "x_studio_average_price", "country_id", "website", "category_id"]`
  Domain: `[("category_id", "!=", False)]` — only partners with a category set.

  Return type per brand:
  ```python
  {
      "name": str,
      "odoo_id": int | None,
      "average_price": str | None,      # from res.partner
      "country": str | None,            # from res.partner.country_id
      "website": str | None,
      "categories": list[str],          # from res.partner.category_id names
      "made_in": str | None,            # from README
      "price_range": str | None,        # from README (💰 symbols)
      "single_cut_models": str | None,  # from README
      "description": str | None,        # from README
  }
  ```
  For brands in Odoo but not README: return partial record (README fields = None).
  For brands in README but not Odoo: return partial record (odoo fields = None).

- **Acceptance**:
  - Given network access, when `get_brands(conn)` is called, then returns list of brand dicts.
  - Given cache is <30 days old, when called again, then no HTTP request is made.
  - Given a brand in Odoo but not README, when returned, then `made_in` is None, `name` is set.

---

### 5. Create `odoo_mcp/resources/collection.py`
- **Files**: `odoo_mcp/resources/collection.py` (create)
- **What**: Query `x_gear` where `x_status in (owned, for_sale)`.
  For each gear, fetch linked `x_listing` records filtered to relevant statuses only:
  - `owned` gear → listings with status `acquired`
  - `for_sale` gear → listings with status `for_sale` or `sold`
  Join with `x_models` for spec fields. Return formatted markdown string.

  Output shape per gear:
  ```
  ## {x_name} [{x_status}]
  **Model**: {x_model_id.name} | **Condition**: {x_condition} | **Intent**: {x_intent}
  **Acquired for**: {x_studio_acquiring_price} | **Serial**: {x_serial_number}
  **Notes**: {x_studio_notes}

  ### Listing(s)
  - [{platform}] {url} — {price} {currency} — score: {x_studio_listing_score}
    Notes: {x_studio_notes}
  ```

- **Acceptance**:
  - Given `x_gear` records with status=owned, when resource is read, then each appears in output.
  - Given `x_gear` with status=for_sale, when resource is read, then only for_sale/sold listings shown.
  - Given gear with no notes, when rendered, then Notes line is omitted.

---

### 6. Create `odoo_mcp/resources/watchlist.py`
- **Files**: `odoo_mcp/resources/watchlist.py` (create)
- **What**: Query `x_models` where `x_studio_wanna = True`.
  For each model, fetch `x_listing` where `x_status = watching`, sorted by
  `x_studio_listing_score desc`. Include price brackets and score fields.

  Output shape per model:
  ```
  ## {model name} — {brand}
  **Type**: {model_type} | **Scale**: {scale} | **Neck**: {neck_feel}
  **Brackets**: p25={p25} p50={p50} p75={p75}

  ### Watching ({n} listings, best first)
  - [score:{listing_score} price_score:{price_score}] {price} {currency} on {platform}
    {url}
    Notes: {notes}
  ```
  Models with no watching listings still appear (show "No listings tracked").

- **Acceptance**:
  - Given `x_models.wanna=True` with 3 watching listings, when read, then listings appear sorted by score desc.
  - Given a wanna model with zero watching listings, when read, then model appears with "No listings tracked".

---

### 7. Create `odoo_mcp/resources/sold.py`
- **Files**: `odoo_mcp/resources/sold.py` (create)
- **What**: Query `x_gear` where `x_status = sold`.
  For each, fetch `x_listing` with `x_status = sold` to get sale price.
  Compute P&L: `sale_price - acquiring_price` (both in listing currency; note if currencies differ).

  Output shape:
  ```
  ## {x_name}
  **Model**: {model} | **Condition**: {condition}
  **Acquired**: {acquiring_price} | **Sold**: {sale_price} ({platform}) | **P&L**: {pnl}
  **Notes**: {notes}
  ```

- **Acceptance**:
  - Given sold gear with both prices set, when read, then P&L is computed and shown.
  - Given sold gear with no sale listing found, when read, then P&L shows "unknown".

---

### 8. Create `odoo_mcp/resources/brands.py`
- **Files**: `odoo_mcp/resources/brands.py` (create)
- **What**: Call `brand_cache.get_brands(conn)`, group by `res.partner.category_id` names.
  Guitar-maker brands show README enrichment (made_in, single_cut_models, price_range).
  Other categories show odoo-only fields.

  Output shape:
  ```
  ## Guitar Makers
  ### {brand name}
  Country: {country} | Made in: {made_in} | Price range: {price_range}
  Models: {single_cut_models}
  Avg price: {average_price}
  {description}

  ## Pedal Makers
  ### {brand name}
  Country: {country} | Avg price: {average_price}
  ```

- **Acceptance**:
  - Given brands with category_id set, when read, then grouped by category.
  - Given a brand in Odoo but not GitHub README, when read, then README fields absent but brand shown.

---

### 9. Create `odoo_mcp/resources/models.py`
- **Files**: `odoo_mcp/resources/models.py` (create)
- **What**: Query all `x_models` records (no wanna filter). For each, show spec + counts of
  linked `x_gear` grouped by status (owned/for_sale/sold/watching).
  This answers "what listing am I not watching that I should be?" — show models with
  `x_studio_wanna=True` that have zero watching listings highlighted at the top.

  Output shape:
  ```
  # Models Catalog

  ## ⚠️ Wanted — No Listings Tracked
  - {model name} (brand) — p50={p50}

  ## Full Catalog
  ### {model name}
  **Brand**: {brand} | **Type**: {type} | **Wanna**: {yes/no}
  **Specs**: scale={scale} neck={neck} fretboard={fretboard} finish={finish}
  **Brackets**: p25={p25} p50={p50} p75={p75}
  **Gear**: {n} owned, {n} for_sale, {n} sold, {n} watching listings
  ```

- **Acceptance**:
  - Given a wanna=True model with zero watching listings, when read, then appears in "⚠️ Wanted — No Listings Tracked" section.
  - Given all x_models, when read, then full catalog is shown regardless of wanna status.

---

### 10. Create `odoo_mcp/tools/`
- **Files**: `odoo_mcp/tools/__init__.py` (create, empty),
  `odoo_mcp/tools/search_gear.py` (create),
  `odoo_mcp/tools/get_model.py` (create),
  `odoo_mcp/tools/get_gear.py` (create)
- **What**:

  **`search_gear(brand="", model_type="", status="", intent="")`**
  — Build Odoo domain from non-empty params, search `x_gear` joined with `x_models`.
  Return compact cards (name, status, model, condition, intent).

  **`get_model(name_or_id: str)`**
  — Search `x_models` by name (ilike) or id. Return full spec + all linked x_gear across all statuses + all linked x_listing grouped by status.

  **`get_gear(gear_id: int)`**
  — Fetch single `x_gear` by id. Return full gear record + all linked listings with full details (scores, notes, url).

- **Acceptance**:
  - Given `search_gear(brand="Gibson")`, when called, then only Gibson gear returned.
  - Given `get_model("Les Paul Custom")`, when called, then model spec + all gear instances returned.
  - Given `get_gear(42)`, when called, then gear notes + all listing notes returned.

---

### 11. Create `odoo_mcp/server.py` — wire everything
- **Files**: `odoo_mcp/server.py` (create)
- **What**: Create `FastMCP("odoo-collection")` app. Register all 5 resources and 3 tools.
  Each resource/tool imports its module function and wraps it in an `@mcp.resource` /
  `@mcp.tool` decorator. Connection is created once per call via `get_connection_from_env()`.
  Expose `main()` that calls `mcp.run()` (stdio transport for Claude Desktop).

```python
from mcp.server.fastmcp import FastMCP
from odoo_mcp.config import get_connection_from_env
from odoo_mcp.resources import collection, watchlist, sold, brands, models
from odoo_mcp.tools import search_gear, get_model, get_gear

mcp = FastMCP("odoo-collection")

@mcp.resource("odoo://collection")
def resource_collection() -> str:
    return collection.render(get_connection_from_env())

# ... repeat for watchlist, sold, brands, models

@mcp.tool()
def tool_search_gear(brand: str = "", model_type: str = "", status: str = "", intent: str = "") -> str:
    return search_gear.run(get_connection_from_env(), brand, model_type, status, intent)

# ... repeat for get_model, get_gear

def main() -> None:
    mcp.run()
```

- **Acceptance**:
  - Given valid `.env`, when `uv run odoo-mcp`, then server starts and responds to MCP protocol.
  - Given Claude Desktop configured with this server, when asking "what guitars do I own?", then collection resource is returned.

---

### 12. Update `.mcp.json` and write tests
- **Files**: `.mcp.json` (modify), `tests/test_odoo_mcp_config.py` (create),
  `tests/test_odoo_mcp_brand_cache.py` (create)
- **What**:

  `.mcp.json`:
  ```json
  {
    "mcpServers": {
      "odoo-collection": {
        "command": "uv",
        "args": ["run", "odoo-mcp"],
        "env": {
          "ODOO_HOSTNAME": "${ODOO_HOSTNAME}",
          "ODOO_DATABASE": "${ODOO_DATABASE}",
          "ODOO_LOGIN": "${ODOO_LOGIN}",
          "ODOO_PASSWORD": "${ODOO_PASSWORD}"
        }
      }
    }
  }
  ```

  Tests (no live Odoo needed — mock the connection):
  - `test_odoo_mcp_config.py`: test `get_odoo_config()` raises on missing env var; returns correct dataclass when vars set.
  - `test_odoo_mcp_brand_cache.py`: test parse of README markdown → brand dict; test cache TTL logic (mock datetime); test partial record when brand in Odoo but not README.

- **Acceptance**:
  - Given missing `ODOO_HOSTNAME`, when `get_odoo_config()` called, then `KeyError` raised.
  - Given mocked README response, when `parse_readme_brands()` called, then brand name and made_in extracted correctly.
  - Given cache timestamp <30 days ago, when `get_brands()` called, then no HTTP call made.

---

## Testing Strategy

- **Unit tests**: `config.py` (env loading), `brand_cache.py` (parsing + TTL logic)
- **Integration tests**: none required — resources/tools are tested manually against live Odoo
- **Manual verification**:
  1. `uv run odoo-mcp` — server starts
  2. Use MCP inspector (`npx @modelcontextprotocol/inspector uv run odoo-mcp`) to call each resource
  3. Verify `odoo://watchlist` shows models with wanna=True and listings sorted by score
  4. Verify `odoo://models` highlights wanna=True models with zero watching listings

---

## Dependencies

- `mcp[cli]>=1.0,<2` — MCP Python SDK (FastMCP)
- `python-dotenv>=1.0,<2` — load `.env` file
- `httpx` — already in deps (used for GitHub README fetch in brand_cache)

---

## Notes

- **Field name verification**: `MODEL_FIELDS_MCP` field names (especially `x_studio_p25/p50/p75`,
  `x_studio_guitar_familly_ids`, score fields) must be confirmed against live Odoo schema
  before implementation. Run `conn.get_model("x_models").fields_get()` to inspect.
- **Connection per call**: `get_connection_from_env()` is called once per resource/tool invocation.
  odoolib connections are lightweight (HTTP-based); no connection pooling needed.
- **Brand cache TTL**: stored as module-level `(_cache: list[dict], _fetched_at: datetime)`.
  Reset on server restart — monthly refresh assumes server restarts at least monthly.
- **Currency**: prices are stored with a `x_currency_id` field. P&L in `sold.py` only computes
  when both prices share the same currency; otherwise shows "mixed currencies".
- **`odoo://passed`**: deferred — not in this spec per user decision.
