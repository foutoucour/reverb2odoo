# eBay scanning support

Add eBay as a second marketplace alongside Reverb in the existing `sync` command, populating `x_listing` rows with `x_platform="ebay"`.

## Goals

- `reverb2odoo sync "Frank Brothers Arcane"` queries Reverb AND eBay by default
- `--platform reverb|ebay|all` restricts to a single source (default: `all`)
- Cross-marketplace eBay coverage: query both `EBAY_US` (filtered to ships-to-Canada) and `EBAY_CA`, deduped by item id
- Reuse the existing dedup/create/update machinery in `sync_model.py` unchanged
- No Odoo Studio schema changes

## Non-goals

- Sold/ended eBay listings (gated behind eBay's Marketplace Insights API — deferred)
- Brand-new condition filter for eBay (deferred; `--include-brand-new` is a no-op for eBay for now)
- `x_ebay_category` Studio model (using a hardcoded slug → category-id map instead)
- Backfilling eBay listings into existing watchlists (user re-runs `sync` per model)
- Changes to `compute_price_brackets.py` — it will pick up eBay live prices automatically; flag in PR

## Architecture

```
                           sync CLI
                              │
                              ▼
                   _collect_sync_data(model)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    PLATFORMS["reverb"]               PLATFORMS["ebay"]
    (existing _search_reverb)         (new _search_ebay)
              │                               │
              ▼                               ▼
       ReverbScraper.search          EbayScraper.search × 2 marketplaces
              │                               │ (EBAY_US + EBAY_CA, deduped)
              └───────────────┬───────────────┘
                              ▼
                 normalized result list,
                 each tagged with platform
                              ▼
                       _build_report ── existing dedup/diff logic
                              ▼
                      _apply_updates ── writes x_listing with x_platform tag
```

## Components

### `ebay_scraper.py` (new)

Async HTTPX client mirroring `ReverbScraper`'s public shape.

- `EbayAuth`
  - Reads `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` from env.
  - Fetches OAuth2 client-credentials token from `https://api.ebay.com/identity/v1/oauth2/token` with scope `https://api.ebay.com/oauth/api_scope`.
  - Caches token in memory; refreshes when within 60s of expiry OR on a 401 from a downstream call.
- `EbayScraper`
  - `__init__(auth, marketplaces=("EBAY_US", "EBAY_CA"), delivery_country="CA")`
  - `search(query, *, category_id=None) -> list[dict]`:
    - Calls `/buy/browse/v1/item_summary/search` for each marketplace in parallel (asyncio.gather).
    - Pagination identical to `ReverbScraper.search`: fetch page 1, discover `total`, fan out the rest concurrently.
    - For `EBAY_US`, applies `filter=deliveryCountry:CA`.
    - Dedupes results by `itemId` across marketplaces.
    - Returns list of dicts shaped like `ReverbScraper._parse_api_response` output (same keys; eBay-missing fields are `""`).
  - `aclose()` for cleanup; `__aenter__`/`__aexit__` like Reverb.
- Output dict keys (matching Reverb scraper):
  - `url`, `name`, `make`, `model`, `finish` (""), `year` (""), `price`, `currency`, `price_display`, `condition`, `status` ("Active"), `sale_ended` (False), `shipping_price`, `shipping_display`, `shipping_region`, `ships_to_canada` (True), `shipping_regions`, `offers_enabled` (False unless eBay surfaces it), `created_at` (""), `published_at` (item's `itemCreationDate` if present, else ""), `seller`, `location`, `description` ("" — search endpoint doesn't return it), `views` (0), `watchers` (0), `categories` (from `categories[].categoryName`), `photo_url` (`image.imageUrl`)

### `sync_model.py` changes

- New constant at top:
  ```python
  REVERB_SLUG_TO_EBAY_CATEGORY: dict[str, int] = {
      "electric-guitars": 33034,
      "acoustic-guitars": 33021,
      "effects-and-pedals": 41419,
      # extended over time as needed
  }
  ```
- New `_search_ebay(query, *, category_slug, default_shipping, include_sold)` mirroring `_search_reverb`:
  - Maps `category_slug` → eBay category id via the map (None → no filter).
  - Logs a warning + no-op when `include_sold=True` (eBay Browse API does not return sold listings).
  - Returns list of dicts (same shape as Reverb).
- Platform registry:
  ```python
  PLATFORMS: dict[str, Callable] = {
      "reverb": _search_reverb,
      "ebay": _search_ebay,
  }
  ```
- `_collect_sync_data` accepts `platforms: list[str]`; iterates and concatenates results, tagging each with `platform`.
- `_reverb_to_listing_vals` renamed to `_listing_vals_from_scrape(scrape, model_id, default_shipping, platform)`; sets `x_platform=platform`.
- `cli` gains `--platform [reverb|ebay|all]`, default `all`. `--platform ebay` without `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` fails hard.
- Item id parsing: add `_ebay_item_id(url)` parallel to `_reverb_item_id` (extracts the numeric id from `/itm/<id>`). `_build_report` indexes by URL and by per-platform item id.

### `reverb_scraper.py`

Unchanged.

### `env-template.yml`

Add:
```yaml
EBAY_CLIENT_ID: ""
EBAY_CLIENT_SECRET: ""
```

### Tests

- `tests/fixtures/ebay/search_with_results.json`, `search_empty.json`, `oauth_token.json` — recorded API payloads.
- `tests/test_ebay_scraper.py`:
  - `_parse_api_response` field mapping against fixture.
  - Marketplace dedup by `itemId`.
  - Pagination math (page 1 discovers `total`, remaining pages fetched in parallel).
  - `EbayAuth` token caching and refresh-on-401.
- `tests/test_sync_model.py` extensions:
  - Sync run with mixed `x_platform="reverb"` + `x_platform="ebay"` existing rows; verify dedup/update logic works per platform.
  - `--platform reverb` makes zero eBay HTTP calls.
  - `--platform ebay` without credentials fails with a clear message.
  - Hardcoded slug map: unknown slug → no `categoryIds` filter sent.

## Error handling

- eBay OAuth failure (missing creds, bad creds, network): log error, skip eBay leg for that run, Reverb results still flow. Report banner: `eBay: auth failed — skipped`.
- eBay 429 / 5xx: caught at `_search_ebay` boundary, logged, returns `[]` for that model. Same shape as existing Reverb error tolerance.
- Missing slug in category map: search without `categoryIds`, debug-log the miss.
- `--platform ebay` with no credentials: fail hard up front (don't run anything else).

## Data flow (single model, default `--platform all`)

```
1. resolve x_models row → (model_id, reverb_category_slug, default_shipping)
2. lookup ebay_category_id via REVERB_SLUG_TO_EBAY_CATEGORY[slug]
3. parallel (asyncio.gather):
     reverb.search(name, category=reverb_slug)        → tag platform="reverb"
     ebay.search(name, category_id=ebay_cat_id,
                 marketplaces=["EBAY_US","EBAY_CA"])  → tag platform="ebay"
4. fetch existing x_listing rows by x_model_id OR x_url in candidate urls
5. _build_report: dedupe by URL + per-platform item id, classify create/update/ok/skip
6. _apply_updates: write to Odoo with each row's x_platform tag
```

## Open questions

- None blocking. Categories beyond the seed three can be added to the map as we hit them.
