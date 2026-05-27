# Cross-model listing match on sync

## Problem

During `sync_model.py` runs, the Reverb search for one model can return
listings that belong to a different model in Odoo. Example: a sync of
*Grez the Mendocino* (`x_models` id=1113) catches listings for
*Grez Mendocino Jr* (id=1155) because both share the brand/keyword
prefix.

Today, `_build_report` only looks up existing listings under the current
`model_id`. A URL that already exists under another model is treated as
a new listing and a duplicate `x_listing` row is created. The user
notices this manually later and moves the listing — wasted writes and
extra cleanup.

## Goal

When sync sees a Reverb URL that already exists on **any** `x_listing`
record (regardless of model), treat that listing as the match. Update
fields in place. Do **not** create a duplicate. Do **not** reassign
`x_model_id` — the user moves it manually when they see fit.

## Non-goals

- Auto-reassignment of `x_model_id` to the syncing model.
- Heuristic matching beyond exact URL / Reverb item-id (which the
  current code already supports).
- Cleanup of pre-existing duplicates created before this change.

## Design

### Detection

Listings are now indexed across the whole catalog, scoped to the URLs
actually returned by the Reverb search. After Reverb search returns
results in `_collect_sync_data`:

1. Collect the deduped URL set from `reverb_results`.
2. Build a search domain that unions:
   - All listings with `x_model_id = model_id` (existing behaviour;
     needed so we still see "ok" listings that no longer appear in the
     Reverb feed and report counts stay correct), **and**
   - All listings with `x_url IN reverb_urls` (the cross-model
     lookup).
3. Pass the merged set into `_build_report`.

The existing `odoo_by_url` / `odoo_by_item_id` index in
`_build_report` does the actual match — no logic change there, just a
broader input.

### URL normalisation in the lookup

`_clean_url` strips the query string for comparison. The DB may store
either the clean or raw URL. To keep the `x_url IN [...]` Odoo domain
lossless, include **both** forms of each URL in the `in` clause:

```python
url_candidates = set()
for r in reverb_results:
    raw = r.get("url", "")
    if not raw:
        continue
    url_candidates.add(raw)
    url_candidates.add(_clean_url(raw))
```

This is a small over-fetch, never an under-fetch.

### Behaviour on cross-model match

When the matched `ListingRecord.x_model_id` is **not** the syncing
model:

- `action` is computed normally (`update` / `ok`).
- `changes` does **not** include `x_model_id`. The listing stays
  attached to its original model.
- The report's *Info* column appends a dim hint, e.g.
  `→ model: Grez Mendocino Jr (1155)`, so the user can spot listings
  they may want to move manually.
- A log line at INFO level: `Cross-model match: listing id={lid} belongs
  to model id={other_id}, updating in place`.

Same model match → no behavioural change.

### Multiple existing rows for the same URL

If two `x_listing` rows share a URL (shouldn't normally happen, but the
DB has no uniqueness constraint), the first hit wins. Log a WARNING
with both IDs so the user can dedupe manually. The sync still
completes.

### Threading (`--all` mode)

The cross-model lookup is per-worker. Each `_collect_sync_data` call
runs its own broader Odoo query against the URLs it just scraped. No
shared state, safe inside `ThreadPoolExecutor`. The extra query is
small (bounded by the Reverb search page size) and only adds a single
round-trip per worker.

## Implementation surface

- `sync_model.py`
  - `_fetch_listings(conn, model_id)` →
    `_fetch_listings(conn, model_id, extra_urls)`. Domain becomes
    `['|', ('x_model_id','=',model_id), ('x_url','in', list(extra_urls))]`.
    The `extra_urls` arg defaults to an empty iterable so any other
    caller keeps working unchanged.
  - `_collect_sync_data` builds the URL candidate set and passes it in.
  - `_build_report` already receives `model_id` (the syncing model).
    When the matched entry's `x_model_id` differs, populate a new
    `item["other_model_id"]: int | None` so `_print_report` can render
    a hint. No signature change.
  - `_print_report` renders the other-model hint in the Info column
    when present.
- `tests/test_sync_model.py`
  - New test: a Reverb URL matches a listing whose `x_model_id`
    differs from the syncing one → action `update`, `x_model_id`
    absent from `changes`, no `create` entry generated.
  - New test: same URL, no diff → action `ok`.
  - Existing tests stay green.

## Acceptance criteria

- Running `uv run python cli.py sync "Grez the Mendocino"` against a DB
  containing a *Grez Mendocino Jr* listing whose URL is in the Reverb
  feed:
  - Produces one `update` (or `ok`) entry for that listing.
  - Produces zero `create` entries for that URL.
  - Listing's `x_model_id` is unchanged after the run.
- Single-model sync and `--all` sync both honour the new lookup.
- Existing tests in `tests/test_sync_model.py` continue to pass.
- `uv run pytest` passes.

## Risks

- **Broader Odoo query cost.** Adds one `x_url IN [...]` clause per
  sync. Bounded by Reverb page size (~50 results typical), so impact
  is minor.
- **URL stored with tracking params.** If a stored URL has a query
  string we don't replicate, the lookup misses it. Mitigated by
  including both raw and cleaned URL forms in the `in` clause and by
  the `_reverb_item_id` fallback already in `_build_report`.
