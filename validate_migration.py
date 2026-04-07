"""Validate the x_guitar → x_gear + x_listing migration.

Runs a series of checks against the live Odoo database and reports pass/fail
for each one.  Does not write anything — read-only.

Checks performed:

  1. Coverage     — every x_guitar has an x_listing; owned-status guitars have an x_gear
  2. Listing link — every x_gear from migration has at least one x_listing
  3. Status map   — x_gear.x_status matches expected value for each source status
  4. Not-interest — "Not Interested" x_guitar → x_gear.x_is_not_interested = True (where x_gear exists)
  5. Listing vals — x_listing.x_url, x_price, x_platform populated for migrated records
  6. Orphans      — no x_listing records with x_gear_id = False
  7. Brackets     — x_models with ≥5 linked listings have price brackets set

Usage::

    reverb2odoo validate-migration

"""

from __future__ import annotations

from dataclasses import dataclass, field

import click
from loguru import logger

from migrate_guitar_to_gear_listing import _GEAR_STATUS_MAP, _STATUS_FIELD

# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

_PASS = "[✓]"
_FAIL = "[✗]"
_WARN = "[~]"


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_coverage(conn) -> CheckResult:
    """Validate migration coverage for listings and owned-status gear records."""
    guitar = conn.get_model("x_guitar")
    gear = conn.get_model("x_gear")
    listing = conn.get_model("x_listing")

    total_guitars = guitar.search_read([], ["id", _STATUS_FIELD])
    total_guitar_ids = {r["id"] for r in total_guitars}
    gear_expected_statuses = set(_GEAR_STATUS_MAP.keys())
    expected_gear_guitar_ids = {
        r["id"] for r in total_guitars if r.get(_STATUS_FIELD) in gear_expected_statuses
    }

    migrated_listings = listing.search_read([("x_guitar_id", "!=", False)], ["x_guitar_id"])
    listed_guitar_ids: set[int] = set()
    for r in migrated_listings:
        ref = r["x_guitar_id"]
        gid = ref[0] if isinstance(ref, (list, tuple)) else ref
        listed_guitar_ids.add(int(gid))

    migrated_gear = gear.search_read([("x_guitar_id", "!=", False)], ["x_guitar_id"])
    geared_guitar_ids: set[int] = set()
    for r in migrated_gear:
        ref = r["x_guitar_id"]
        gid = ref[0] if isinstance(ref, (list, tuple)) else ref
        geared_guitar_ids.add(int(gid))

    missing_listings = total_guitar_ids - listed_guitar_ids
    extra_listings = listed_guitar_ids - total_guitar_ids
    missing_gear = expected_gear_guitar_ids - geared_guitar_ids
    extra_gear = geared_guitar_ids - total_guitar_ids

    warnings: list[str] = []
    if extra_listings:
        warnings.append(
            f"{len(extra_listings)} x_listing record(s) reference non-existent x_guitar ids"
        )
    if extra_gear:
        warnings.append(
            f"{len(extra_gear)} x_gear record(s) reference non-existent x_guitar ids"
        )

    if missing_listings or missing_gear:
        parts: list[str] = [
            f"{len(listed_guitar_ids)}/{len(total_guitar_ids)} x_guitar records have an x_listing"
        ]
        if missing_listings:
            parts.append(f"{len(missing_listings)} listing(s) missing")
        parts.append(
            f"{len(geared_guitar_ids & expected_gear_guitar_ids)}/{len(expected_gear_guitar_ids)} "
            f"owned-status x_guitar records have an x_gear"
        )
        if missing_gear:
            parts.append(f"{len(missing_gear)} owned-status gear record(s) missing")

        return CheckResult(
            name="coverage",
            passed=False,
            message=" — ".join(parts),
            warnings=warnings,
        )

    return CheckResult(
        name="coverage",
        passed=True,
        message=(
            f"All {len(total_guitar_ids)} x_guitar records have an x_listing, and all "
            f"{len(expected_gear_guitar_ids)} owned-status x_guitar records have a corresponding x_gear"
        ),
        warnings=warnings,
    )


def check_listing_link(conn) -> CheckResult:
    """Every x_gear created from migration should have at least one x_listing."""
    gear = conn.get_model("x_gear")
    listing = conn.get_model("x_listing")

    migrated_gear = gear.search_read([("x_guitar_id", "!=", False)], ["id"])
    migrated_gear_ids = [r["id"] for r in migrated_gear]

    if not migrated_gear_ids:
        return CheckResult(
            name="listing_link",
            passed=False,
            message="No migrated x_gear records found — has the migration run?",
        )

    # Find gear with no listing
    linked_gear = listing.search_read(
        [("x_gear_id", "in", migrated_gear_ids)],
        ["x_gear_id"],
    )
    linked_gear_ids = {
        (r["x_gear_id"][0] if isinstance(r["x_gear_id"], (list, tuple)) else r["x_gear_id"])
        for r in linked_gear
    }
    unlinked = set(migrated_gear_ids) - linked_gear_ids

    if unlinked:
        return CheckResult(
            name="listing_link",
            passed=False,
            message=(
                f"{len(unlinked)} migrated x_gear record(s) have no x_listing"
                f" (total migrated: {len(migrated_gear_ids)})"
            ),
        )

    return CheckResult(
        name="listing_link",
        passed=True,
        message=f"All {len(migrated_gear_ids)} migrated x_gear records have at least one x_listing",
    )


def check_status_mapping(conn) -> CheckResult:
    """x_gear.x_status must match the expected value for the source x_guitar status."""
    guitar = conn.get_model("x_guitar")
    gear = conn.get_model("x_gear")

    # Fetch x_guitar status for all records that have been migrated
    migrated_gear = gear.search_read(
        [("x_guitar_id", "!=", False)],
        ["id", "x_status", "x_guitar_id"],
    )

    if not migrated_gear:
        return CheckResult(name="status_map", passed=False, message="No migrated records found")

    # Build guitar_id → source_status map
    guitar_ids = []
    for r in migrated_gear:
        ref = r["x_guitar_id"]
        guitar_ids.append(ref[0] if isinstance(ref, (list, tuple)) else ref)

    guitar_records = guitar.search_read(
        [("id", "in", guitar_ids)],
        ["id", _STATUS_FIELD],
    )
    guitar_status_map: dict[int, str] = {
        r["id"]: (r.get(_STATUS_FIELD) or "Watched") for r in guitar_records
    }

    mismatches: list[str] = []
    for r in migrated_gear:
        ref = r["x_guitar_id"]
        guitar_id = ref[0] if isinstance(ref, (list, tuple)) else ref
        source_status = guitar_status_map.get(int(guitar_id), "Watched")
        expected_gear_status = _GEAR_STATUS_MAP.get(source_status, "watching")
        actual_gear_status = r.get("x_status", "")
        if actual_gear_status != expected_gear_status:
            mismatches.append(
                f"x_gear id={r['id']}: expected {expected_gear_status!r}"
                f" (source={source_status!r}), got {actual_gear_status!r}"
            )

    if mismatches:
        sample = mismatches[:5]
        return CheckResult(
            name="status_map",
            passed=False,
            message=f"{len(mismatches)} status mismatch(es): {'; '.join(sample)}",
        )

    return CheckResult(
        name="status_map",
        passed=True,
        message=f"Status mapping correct for all {len(migrated_gear)} migrated x_gear records",
    )


def check_not_interested_flag(conn) -> CheckResult:
    """'Not Interested' x_guitar records must have x_gear.x_is_not_interested = True."""
    guitar = conn.get_model("x_guitar")
    gear = conn.get_model("x_gear")

    not_interested_guitars = guitar.search_read(
        [(_STATUS_FIELD, "=", "Not Interested")],
        ["id"],
    )
    if not not_interested_guitars:
        return CheckResult(
            name="not_interested",
            passed=True,
            message="No 'Not Interested' x_guitar records found — nothing to check",
        )

    ni_guitar_ids = [r["id"] for r in not_interested_guitars]
    gear_records = gear.search_read(
        [("x_guitar_id", "in", ni_guitar_ids)],
        ["id", "x_is_not_interested", "x_guitar_id"],
    )

    found_guitar_ids = {
        r["x_guitar_id"][0] if isinstance(r["x_guitar_id"], (list, tuple)) else r["x_guitar_id"]
        for r in gear_records
        if r.get("x_guitar_id")
    }
    missing_guitar_ids = sorted(set(ni_guitar_ids) - found_guitar_ids)

    if missing_guitar_ids:
        return CheckResult(
            name="not_interested",
            passed=False,
            message=(
                f"{len(missing_guitar_ids)} 'Not Interested' x_guitar record(s) have no linked x_gear "
                f"record, so x_is_not_interested could not be validated"
            ),
        )

    wrong: list[int] = [r["id"] for r in gear_records if not r.get("x_is_not_interested")]

    if wrong:
        return CheckResult(
            name="not_interested",
            passed=False,
            message=(
                f"{len(wrong)} x_gear record(s) from 'Not Interested' source"
                f" have x_is_not_interested = False"
            ),
        )

    return CheckResult(
        name="not_interested",
        passed=True,
        message=(
            f"All {len(gear_records)} 'Not Interested' x_guitar records correctly flagged on x_gear"
        ),
    )


def check_listing_values(conn) -> CheckResult:
    """Migrated x_listing records must have x_url and x_platform populated."""
    listing = conn.get_model("x_listing")

    migrated = listing.search_read(
        [("x_guitar_id", "!=", False)],
        ["id", "x_url", "x_platform", "x_price"],
    )

    if not migrated:
        return CheckResult(
            name="listing_values",
            passed=False,
            message="No migrated x_listing records found",
        )

    missing_url = [r["id"] for r in migrated if not r.get("x_url")]
    missing_platform = [r["id"] for r in migrated if not r.get("x_platform")]
    zero_price = [r["id"] for r in migrated if not r.get("x_price")]

    warnings: list[str] = []
    if zero_price:
        warnings.append(f"{len(zero_price)} listing(s) have x_price = 0")

    if missing_url or missing_platform:
        issues = []
        if missing_url:
            issues.append(f"{len(missing_url)} missing x_url")
        if missing_platform:
            issues.append(f"{len(missing_platform)} missing x_platform")
        return CheckResult(
            name="listing_values",
            passed=False,
            message=f"{len(migrated)} listings checked — {', '.join(issues)}",
            warnings=warnings,
        )

    return CheckResult(
        name="listing_values",
        passed=True,
        message=f"All {len(migrated)} migrated x_listing records have x_url and x_platform set",
        warnings=warnings,
    )


def check_orphan_listings(conn) -> CheckResult:
    """No x_listing should have x_gear_id = False."""
    listing = conn.get_model("x_listing")

    orphans = listing.search_read(
        [("x_gear_id", "=", False)],
        ["id", "x_name"],
    )

    if orphans:
        sample = [f"id={r['id']} '{r.get('x_name', '')}'" for r in orphans[:5]]
        return CheckResult(
            name="orphan_listings",
            passed=False,
            message=f"{len(orphans)} x_listing record(s) have no x_gear_id: {'; '.join(sample)}",
        )

    total = listing.search_read([], ["id"])
    return CheckResult(
        name="orphan_listings",
        passed=True,
        message=f"No orphaned listings — all {len(total)} x_listing records are linked to x_gear",
    )


def check_price_brackets(conn) -> CheckResult:
    """x_models with ≥5 linked listings should have price brackets computed."""
    x_models = conn.get_model("x_models")
    gear = conn.get_model("x_gear")
    listing = conn.get_model("x_listing")

    all_models = x_models.search_read(
        [],
        ["id", "x_name", "x_price_p50", "x_price_sample_size"],
    )

    missing_brackets: list[str] = []
    for model in all_models:
        model_id = model["id"]
        # Count listings via gear
        gear_records = gear.search_read([("x_model_id", "=", model_id)], ["id"])
        if not gear_records:
            continue
        gear_ids = [r["id"] for r in gear_records]
        listings = listing.search_read(
            [("x_gear_id", "in", gear_ids), ("x_price", ">", 0)],
            ["id"],
        )
        if len(listings) >= 5 and not model.get("x_price_p50"):
            missing_brackets.append(model.get("x_name", f"id={model_id}"))

    if missing_brackets:
        sample = missing_brackets[:5]
        return CheckResult(
            name="price_brackets",
            passed=False,
            message=(
                f"{len(missing_brackets)} model(s) with ≥5 listings have no price brackets"
                f" — run compute-price-brackets: {', '.join(sample)}"
            ),
        )

    computed = sum(1 for m in all_models if m.get("x_price_p50"))
    return CheckResult(
        name="price_brackets",
        passed=True,
        message=f"Price brackets set on {computed}/{len(all_models)} models",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all_checks(conn) -> list[CheckResult]:
    checks = [
        ("Coverage (all x_guitar migrated)", check_coverage),
        ("Listing link (every x_gear has x_listing)", check_listing_link),
        ("Status mapping", check_status_mapping),
        ("Not-interested flag", check_not_interested_flag),
        ("Listing field values", check_listing_values),
        ("Orphan listings", check_orphan_listings),
        ("Price brackets", check_price_brackets),
    ]

    results: list[CheckResult] = []
    for label, fn in checks:
        logger.info("Checking: {}…", label)
        try:
            result = fn(conn)
        except Exception as e:
            result = CheckResult(name=label, passed=False, message=f"ERROR: {e}")
        results.append(result)

    return results


def print_results(results: list[CheckResult]) -> int:
    """Print check results. Returns number of failures."""
    logger.info("")
    logger.info("=== VALIDATION RESULTS ===")
    logger.info("")

    failures = 0
    for r in results:
        icon = _PASS if r.passed else _FAIL
        level = logger.success if r.passed else logger.error
        level("{} {} — {}", icon, r.name, r.message)
        for w in r.warnings:
            logger.warning("    {} {}", _WARN, w)
        if not r.passed:
            failures += 1

    logger.info("")
    if failures == 0:
        logger.success("All {} checks passed.", len(results))
    else:
        logger.error("{}/{} checks failed.", failures, len(results))

    return failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("validate-migration")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Validate the x_guitar → x_gear + x_listing migration.

    Runs read-only checks against the live Odoo database and reports
    pass/fail for each one.  Exit code 1 if any check fails.
    """
    conn = ctx.obj["conn"]
    results = run_all_checks(conn)
    failures = print_results(results)
    if failures:
        raise SystemExit(1)
