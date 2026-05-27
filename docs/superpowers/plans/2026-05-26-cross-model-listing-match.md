# Cross-Model Listing Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `sync` finds a Reverb URL that already exists on any `x_listing` (regardless of model), update that listing in place instead of creating a duplicate under the syncing model.

**Architecture:** Broaden the existing-listing lookup in `_collect_sync_data` to include cross-model URL matches. `_build_report` flags cross-model matches in a new `other_model_id` field for the printer; `x_model_id` is never written, so listings stay attached to their original model. The user moves them manually later.

**Tech Stack:** Python 3.x, pytest, loguru, Odoo XML-RPC via `odoo_connector`, click, rich.

**Spec:** `docs/superpowers/specs/2026-05-26-cross-model-listing-match-design.md`

---

## File Structure

- Modify: `sync_model.py`
  - `_fetch_listings(conn, model_id)` → `_fetch_listings(conn, model_id, extra_urls)`. Single Odoo query merges model-scoped and URL-scoped rows.
  - `_collect_sync_data` builds the URL candidate set (raw + cleaned) from Reverb results and passes it.
  - `_build_report` populates `item["other_model_id"]: int | None` when matched entry's `x_model_id` differs from the syncing model.
  - `_build_report` URL → entry index uses `setdefault` so the first occurrence wins, with a WARNING log on collision.
  - `_print_report` renders a dim `→ model: <id>` hint in the Info column when `other_model_id` is set.
- Modify: `tests/test_sync_model.py`
  - Extend `TestBuildReport`, `TestPrintReport`, `TestCollectSyncData` with cross-model coverage.
  - New focused class `TestFetchListings` for the broadened domain.

---

## Task 1: Broaden `_fetch_listings` to accept extra URLs

**Files:**
- Modify: `sync_model.py:175-179` (`_fetch_listings`)
- Test: `tests/test_sync_model.py` (new class `TestFetchListings` appended at end of file)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sync_model.py`:

```python
# ── _fetch_listings (mocked Odoo) ────────────────────────────────────────


class TestFetchListings:
    """Unit tests for _fetch_listings (cross-model URL lookup)."""

    def _mock_conn(self, listing_rows=None):
        from unittest.mock import MagicMock

        conn = MagicMock()
        listing = MagicMock()
        listing.search_read.return_value = listing_rows or []
        conn.get_model.return_value = listing
        return conn, listing

    def test_no_extra_urls_uses_model_only_domain(self):
        from sync_model import _fetch_listings

        conn, listing = self._mock_conn()
        _fetch_listings(conn, model_id=42)

        call_domain = listing.search_read.call_args[0][0]
        # Old behaviour: a plain ('x_model_id', '=', 42) domain.
        assert call_domain == [("x_model_id", "=", 42)]

    def test_extra_urls_unions_with_model_domain(self):
        from sync_model import _fetch_listings

        conn, listing = self._mock_conn()
        urls = ["https://reverb.com/item/1-g", "https://reverb.com/item/2-g"]
        _fetch_listings(conn, model_id=42, extra_urls=urls)

        call_domain = listing.search_read.call_args[0][0]
        # OR(model_id=42, x_url in [...])  →  ['|', term1, term2]
        assert call_domain[0] == "|"
        assert ("x_model_id", "=", 42) in call_domain
        url_clause = next(
            t for t in call_domain if isinstance(t, tuple) and t[0] == "x_url"
        )
        assert url_clause[1] == "in"
        assert set(url_clause[2]) == set(urls)

    def test_empty_extra_urls_still_uses_model_only_domain(self):
        from sync_model import _fetch_listings

        conn, listing = self._mock_conn()
        _fetch_listings(conn, model_id=42, extra_urls=[])

        call_domain = listing.search_read.call_args[0][0]
        assert call_domain == [("x_model_id", "=", 42)]

    def test_returns_listing_records(self):
        from sync_model import _fetch_listings

        conn, listing = self._mock_conn(
            listing_rows=[
                {"id": 1, "x_url": "https://reverb.com/item/1-g", "x_model_id": [42, "M"]},
            ]
        )
        result = _fetch_listings(conn, model_id=42)
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].x_url == "https://reverb.com/item/1-g"
        assert result[0].x_model_id == (42, "M")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_model.py::TestFetchListings -v`
Expected: tests fail — `test_extra_urls_unions_with_model_domain` fails because `_fetch_listings` doesn't accept `extra_urls`. Others may also fail / error on TypeError.

- [ ] **Step 3: Modify `_fetch_listings`**

Replace `sync_model.py:175-179`:

```python
def _fetch_listings(
    conn,
    model_id: int,
    extra_urls: list[str] | None = None,
) -> list[ListingRecord]:
    """Return ``x_listing`` records for *model_id* plus any rows whose
    ``x_url`` matches *extra_urls* (cross-model lookup).

    Cross-model rows are returned with their original ``x_model_id`` intact
    so the caller can detect when a Reverb result already exists under a
    different model.
    """
    listing = conn.get_model("x_listing")
    if extra_urls:
        domain: list = [
            "|",
            ("x_model_id", "=", model_id),
            ("x_url", "in", list(extra_urls)),
        ]
    else:
        domain = [("x_model_id", "=", model_id)]
    rows = listing.search_read(domain, ListingRecord.odoo_fields())
    return [ListingRecord.from_odoo(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sync_model.py::TestFetchListings -v`
Expected: all four tests PASS.

- [ ] **Step 5: Run the full sync_model test file**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: every test PASSes (existing call sites use the default `extra_urls=None`, so the old behaviour is preserved).

- [ ] **Step 6: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): broaden _fetch_listings with cross-model URL lookup

Adds optional extra_urls parameter that unions an x_url IN [...] clause
with the model-scoped domain, so callers can detect listings that
already exist under a different model. Default behaviour unchanged."
```

---

## Task 2: Wire URL candidates into `_collect_sync_data`

**Files:**
- Modify: `sync_model.py:627-695` (`_collect_sync_data`)
- Test: `tests/test_sync_model.py` (extend `TestCollectSyncData`)

- [ ] **Step 1: Write the failing test**

Append inside `class TestCollectSyncData` in `tests/test_sync_model.py`:

```python
    def test_passes_url_candidates_to_fetch_listings(self):
        """URL candidates from Reverb results are forwarded to _fetch_listings
        as both raw and cleaned forms so the DB lookup is lossless."""
        reverb_results = [
            {
                "url": "https://reverb.com/item/1-g?show_sold=true",
                "name": "G1",
                "price": "100.00",
                "price_display": "C$100",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
            {
                "url": "https://reverb.com/item/2-g",
                "name": "G2",
                "price": "200.00",
                "price_display": "C$200",
                "offers_enabled": False,
                "sale_ended": False,
                "published_at": "",
                "shipping_price": "0.00",
                "ships_to_canada": True,
                "condition": "Excellent",
            },
        ]
        captured: dict = {}

        def fake_fetch_listings(conn, model_id, extra_urls=None):
            captured["model_id"] = model_id
            captured["extra_urls"] = list(extra_urls or [])
            return []

        with (
            patch("sync_model._search_reverb", return_value=reverb_results),
            patch("sync_model._fetch_listings", side_effect=fake_fetch_listings),
        ):
            _collect_sync_data(
                MagicMock(),
                model_id=42,
                model_name="Test",
                category_slug=None,
                default_shipping=250.0,
            )

        assert captured["model_id"] == 42
        # Both the raw URL (with query string) and the cleaned URL should be present
        assert "https://reverb.com/item/1-g?show_sold=true" in captured["extra_urls"]
        assert "https://reverb.com/item/1-g" in captured["extra_urls"]
        assert "https://reverb.com/item/2-g" in captured["extra_urls"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sync_model.py::TestCollectSyncData::test_passes_url_candidates_to_fetch_listings -v`
Expected: FAIL — `_collect_sync_data` currently calls `_fetch_listings(conn, model_id)` with no URL set.

- [ ] **Step 3: Modify `_collect_sync_data`**

In `sync_model.py`, replace the call at the line currently reading:

```python
    logger.debug("[{}] Fetching existing Odoo listing records…", model_name)
    odoo_entries = _fetch_listings(conn, model_id)
```

with:

```python
    logger.debug("[{}] Fetching existing Odoo listing records…", model_name)
    url_candidates: set[str] = set()
    for r in reverb_results:
        raw = r.get("url", "")
        if not raw:
            continue
        url_candidates.add(raw)
        url_candidates.add(_clean_url(raw))
    odoo_entries = _fetch_listings(conn, model_id, extra_urls=list(url_candidates))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sync_model.py::TestCollectSyncData -v`
Expected: every `TestCollectSyncData` test PASSes (existing tests mock `_search_reverb` to return `[]`, so the URL candidate set is empty and the call still works).

- [ ] **Step 5: Run the full sync_model test file**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): forward URL candidates from _collect_sync_data

Collects raw and cleaned URLs from Reverb results and passes them to
_fetch_listings as extra_urls so listings that exist under a different
model are pulled into the comparison set."
```

---

## Task 3: Flag cross-model matches in `_build_report`

**Files:**
- Modify: `sync_model.py:415-489` (`_build_report`)
- Test: `tests/test_sync_model.py` (extend `TestBuildReport`)

- [ ] **Step 1: Write the failing tests**

Append inside `class TestBuildReport` in `tests/test_sync_model.py`:

```python
    def test_cross_model_match_flags_other_model_id(self):
        """When the matched entry belongs to a different model, the report
        item should expose other_model_id and never include x_model_id in
        the change set."""
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, price="4000.00")]
        # Entry belongs to model 99, not the syncing model 42.
        odoo_entries = [
            self._make_odoo(url=url, x_model_id=[99, "Other Model"]),
        ]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert len(report) == 1
        assert report[0]["action"] == "update"
        assert report[0]["other_model_id"] == 99
        assert "x_model_id" not in report[0]["changes"]

    def test_same_model_match_other_model_id_is_none(self):
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url)]
        odoo_entries = [self._make_odoo(url=url, x_model_id=[42, "Same"])]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        assert report[0]["other_model_id"] is None

    def test_new_listing_has_other_model_id_none(self):
        reverb_results = [
            self._make_reverb(url="https://reverb.com/item/999-new", condition="Excellent"),
        ]
        report = _build_report(reverb_results, [], model_id=42)

        assert report[0]["action"] == "create"
        assert report[0]["other_model_id"] is None

    def test_cross_model_match_does_not_create(self):
        """If the URL already exists under another model, no create entry
        should be produced — the existing row is updated instead."""
        url = "https://reverb.com/item/1-g"
        reverb_results = [self._make_reverb(url=url, condition="Excellent")]
        odoo_entries = [self._make_odoo(url=url, x_model_id=[99, "Other"])]

        report = _build_report(reverb_results, odoo_entries, model_id=42)

        actions = [r["action"] for r in report]
        assert "create" not in actions

    def test_duplicate_url_first_wins_and_warns(self):
        """If two existing entries share the same URL, the first one is
        kept and a WARNING is logged so the user can dedupe manually.

        We patch ``sync_model.logger.warning`` directly because the project
        uses loguru, which does not propagate to ``caplog`` by default.
        """
        url = "https://reverb.com/item/1-g"
        first = self._make_odoo(url=url, id=100)
        second = self._make_odoo(url=url, id=200)
        reverb_results = [self._make_reverb(url=url)]

        with patch("sync_model.logger.warning") as warn:
            report = _build_report(reverb_results, [first, second], model_id=42)

        assert report[0]["entry"].id == 100
        assert warn.called
        warn_args = " ".join(str(a) for call in warn.call_args_list for a in call.args)
        assert "100" in warn_args and "200" in warn_args
```

Note: `patch` is already imported at the top of `tests/test_sync_model.py` (line 3).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_model.py::TestBuildReport -v`
Expected: the four new tests FAIL (no `other_model_id` key yet, no duplicate-URL warning).

- [ ] **Step 3: Modify `_build_report`**

In `sync_model.py`, change the index-building loop and the per-result item construction:

Replace:

```python
    odoo_by_url: dict[str, ListingRecord] = {}
    odoo_by_item_id: dict[str, ListingRecord] = {}
    for e in odoo_entries:
        clean = _clean_url(e.x_url or "")
        odoo_by_url[clean] = e
        item_id = _reverb_item_id(clean)
        if item_id:
            odoo_by_item_id[item_id] = e
```

with:

```python
    odoo_by_url: dict[str, ListingRecord] = {}
    odoo_by_item_id: dict[str, ListingRecord] = {}
    for e in odoo_entries:
        clean = _clean_url(e.x_url or "")
        existing_url_match = odoo_by_url.get(clean)
        if existing_url_match is not None and existing_url_match.id != e.id:
            logger.warning(
                "Duplicate x_url in Odoo: keeping listing id={}, ignoring id={} "
                "(url={})",
                existing_url_match.id,
                e.id,
                clean,
            )
            continue
        odoo_by_url[clean] = e
        item_id = _reverb_item_id(clean)
        if item_id and item_id not in odoo_by_item_id:
            odoo_by_item_id[item_id] = e
```

Then in the per-result loop, initialise the new key and populate it after the match:

Replace:

```python
        item: dict[str, Any] = {
            "reverb": r,
            "entry": None,
            "changes": {},
            "create_vals": {},
            "warnings": [],
            "action": "skip",
        }
```

with:

```python
        item: dict[str, Any] = {
            "reverb": r,
            "entry": None,
            "changes": {},
            "create_vals": {},
            "warnings": [],
            "action": "skip",
            "other_model_id": None,
        }
```

And immediately after the `if existing:` branch sets `item["entry"] = existing`, derive the other-model id. Replace:

```python
        if existing:
            item["entry"] = existing
            item["changes"] = _compute_changes(existing, r)
            item["action"] = "update" if item["changes"] else "ok"
```

with:

```python
        if existing:
            item["entry"] = existing
            item["changes"] = _compute_changes(existing, r)
            item["action"] = "update" if item["changes"] else "ok"
            entry_model = existing.x_model_id
            entry_model_id = entry_model[0] if entry_model else None
            if entry_model_id is not None and entry_model_id != model_id:
                item["other_model_id"] = entry_model_id
                logger.info(
                    "Cross-model match: listing id={} belongs to model id={},"
                    " updating in place",
                    existing.id,
                    entry_model_id,
                )
```

Confirm `_compute_changes` does **not** set `x_model_id` — read `sync_model.py:_compute_changes` once to verify (it does not). No change needed there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sync_model.py::TestBuildReport -v`
Expected: all `TestBuildReport` tests PASS (existing ones continue to work because the new `other_model_id` key is additive).

- [ ] **Step 5: Run the full sync_model test file**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): detect cross-model URL matches in _build_report

When a Reverb URL matches a listing under a different x_models record,
expose other_model_id on the report item and log an INFO line. The
listing is updated in place; x_model_id is never written so the user
can move it manually later. Duplicate URLs in the existing set keep the
first entry and emit a WARNING."
```

---

## Task 4: Render cross-model hint in `_print_report`

**Files:**
- Modify: `sync_model.py:497-549` (`_print_report`)
- Test: `tests/test_sync_model.py` (extend `TestPrintReport`)

- [ ] **Step 1: Write the failing test**

Append inside `class TestPrintReport`:

```python
    def test_cross_model_hint_shown_in_info_column(self, capsys):
        report = [
            {
                "action": "update",
                "reverb": {"name": "G", "price_display": "$1"},
                "entry": ListingRecord.from_odoo(
                    {"id": 200, "x_price": 99, "x_model_id": [1155, "Grez Mendocino Jr"]}
                ),
                "changes": {"x_price": 99},
                "warnings": [],
                "other_model_id": 1155,
            },
        ]
        _print_report(report)
        out = capsys.readouterr().out
        # Hint must surface the other model id so the user can spot it.
        assert "1155" in out

    def test_no_hint_when_same_model(self, capsys):
        report = [
            {
                "action": "update",
                "reverb": {"name": "G", "price_display": "$1"},
                "entry": ListingRecord.from_odoo({"id": 200, "x_price": 99}),
                "changes": {"x_price": 99},
                "warnings": [],
                "other_model_id": None,
            },
        ]
        _print_report(report)
        out = capsys.readouterr().out
        assert "model:" not in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_model.py::TestPrintReport -v`
Expected: `test_cross_model_hint_shown_in_info_column` FAILs — the hint is not rendered.

- [ ] **Step 3: Modify `_print_report`**

In `sync_model.py`, locate the `update` branch in `_print_report`:

```python
        elif item["action"] == "update":
            update_count += 1
            entry: ListingRecord = item["entry"]
            eid = entry.id
            info = escape(f"id={eid}  {warn_str}".strip())
            table.add_row(str(i), "[bold yellow]~ UPD[/bold yellow]", price, name, info)
```

Replace with:

```python
        elif item["action"] == "update":
            update_count += 1
            entry: ListingRecord = item["entry"]
            eid = entry.id
            other_model_id = item.get("other_model_id")
            cross = f"  → model: {other_model_id}" if other_model_id else ""
            info = escape(f"id={eid}{cross}  {warn_str}".strip())
            table.add_row(str(i), "[bold yellow]~ UPD[/bold yellow]", price, name, info)
```

Also, ensure the existing `TestPrintReport.test_counts` and `test_all_ok_returns_zeros` items include `"other_model_id": None` so they exercise the same shape — they currently omit the key. Loosen the access by using `item.get("other_model_id")` (already in the snippet above), so legacy items still render. No test edit needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sync_model.py::TestPrintReport -v`
Expected: every `TestPrintReport` test PASSes.

- [ ] **Step 5: Run the full sync_model test file**

Run: `uv run pytest tests/test_sync_model.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add sync_model.py tests/test_sync_model.py
git commit -m "feat(sync): show cross-model hint in sync report

Adds a dim → model: <id> suffix to the Info column when a listing
matched by URL belongs to a different x_models record. Lets the user
spot listings they may want to move manually."
```

---

## Task 5: Run the full test suite and update README if needed

**Files:**
- Read: `README.md`
- Modify: `README.md` (only if it documents the sync flow's cross-model behaviour)

- [ ] **Step 1: Run the full project test suite**

Run: `uv run pytest`
Expected: all tests PASS. If any unrelated test fails, stop and report — do not "fix" it.

- [ ] **Step 2: Check README for sync-flow documentation**

Read `README.md` and look for a sync section that describes how existing listings are matched (search for "sync", "url", "listing"). If a section explains the matching rules, add a short paragraph noting that URL matches across models are now consolidated (the listing is updated in place; `x_model_id` is preserved). If no such section exists, skip the edit — the spec in `docs/superpowers/specs/` and the inline docstrings are sufficient.

- [ ] **Step 3: Commit (only if README was changed)**

```bash
git add README.md
git commit -m "docs: note cross-model URL match in sync flow"
```

Otherwise skip this step.

- [ ] **Step 4: Final manual smoke check (optional, requires live Odoo)**

If a live Odoo connection is available and the user wants a smoke test, run:

```bash
uv run python cli.py sync "Grez the Mendocino" --dry-run
```

Look in the report for any `~ UPD` rows with a `→ model: <other id>` hint. None of them should also produce a `+ NEW` row for the same URL. Do not run without `--dry-run` unless the user explicitly approves.

---

## Acceptance criteria recap

- `_fetch_listings(conn, model_id, extra_urls=urls)` returns model-scoped rows **plus** any row whose `x_url` is in `urls`, in a single query.
- A Reverb URL that already exists on a different model's listing produces a single `update`/`ok` report item with `other_model_id` set, and **no** corresponding `create` entry.
- The matched listing's `x_model_id` is **never** in the `changes` dict written to Odoo.
- The sync report's Info column shows `→ model: <id>` on cross-model matches.
- Duplicate-URL entries in the lookup pool keep the first occurrence and log a WARNING with both IDs.
- `uv run pytest` passes.
