"""Tests for dedup_model — duplicate detection helpers."""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from dedup_model import (
    _base_url,
    _delete_records,
    _find_exact_url_dupes,
    _find_same_item_id_dupes,
    _ids_to_delete,
    _pick_keeper,
    _reverb_item_id,
    cli,
)

# ── _base_url ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/123-guitar",
            "https://reverb.com/item/123-guitar",
            id="no-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/123-guitar?show_sold=true",
            "https://reverb.com/item/123-guitar",
            id="strip-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/123-guitar?a=1&b=2#frag",
            "https://reverb.com/item/123-guitar",
            id="strip-query-and-fragment",
        ),
        pytest.param("", "", id="empty-string"),
    ],
)
def test_base_url(url: str, expected: str):
    assert _base_url(url) == expected


# ── _reverb_item_id ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium",
            "94370297",
            id="standard-reverb-url",
        ),
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium?show_sold=true",
            "94370297",
            id="with-query-string",
        ),
        pytest.param(
            "https://reverb.com/item/94370297",
            "94370297",
            id="no-slug",
        ),
        pytest.param(
            "https://reverb.com/shop/some-shop",
            None,
            id="non-item-url",
        ),
        pytest.param("", None, id="empty-string"),
        pytest.param(
            "https://reverb.com/item/abc-not-numeric",
            None,
            id="non-numeric-id",
        ),
    ],
)
def test_reverb_item_id(url: str, expected: str | None):
    assert _reverb_item_id(url) == expected


# ── _pick_keeper ──────────────────────────────────────────────────────────


def _rec(id: int, name: str, url: str, available: bool = True, active: bool = True) -> dict:
    return {
        "id": id,
        "x_name": name,
        "x_studio_url": url,
        "x_studio_is_available": available,
        "x_studio_active": active,
    }


@pytest.mark.parametrize(
    "group, expected_keeper_id",
    [
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/1-a", available=True, active=True),
                _rec(2, "Guitar A", "https://reverb.com/item/1-a", available=False, active=False),
            ],
            1,
            id="prefers-active-and-available",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/1-a", available=False, active=True),
                _rec(2, "Guitar A", "https://reverb.com/item/1-a", available=False, active=False),
            ],
            1,
            id="prefers-active-over-archived",
        ),
        pytest.param(
            [
                _rec(2, "Guitar A", "https://reverb.com/item/1-a", available=True, active=True),
                _rec(1, "Guitar A", "https://reverb.com/item/1-a", available=True, active=True),
            ],
            1,
            id="tiebreak-lowest-id",
        ),
        pytest.param(
            [
                _rec(3, "Guitar A", "https://reverb.com/item/1-a", available=False, active=False),
                _rec(1, "Guitar A", "https://reverb.com/item/1-a", available=False, active=False),
                _rec(2, "Guitar A", "https://reverb.com/item/1-a", available=False, active=False),
            ],
            1,
            id="all-same-status-lowest-id-wins",
        ),
    ],
)
def test_pick_keeper(group: list[dict], expected_keeper_id: int):
    assert _pick_keeper(group)["id"] == expected_keeper_id


# ── _find_exact_url_dupes ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "records, expected_group_count",
    [
        pytest.param([], 0, id="empty-list"),
        pytest.param(
            [_rec(1, "Guitar A", "https://reverb.com/item/1-a")],
            0,
            id="single-record-no-dupe",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
                _rec(2, "Guitar B", "https://reverb.com/item/2-b"),
            ],
            0,
            id="two-distinct-urls",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
                _rec(2, "Guitar A copy", "https://reverb.com/item/1-a?show_sold=true"),
            ],
            1,
            id="same-url-different-query-string",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
                _rec(2, "Guitar A v2", "https://reverb.com/item/1-a"),
                _rec(3, "Guitar B", "https://reverb.com/item/2-b"),
                _rec(4, "Guitar B v2", "https://reverb.com/item/2-b"),
            ],
            2,
            id="two-separate-dupe-groups",
        ),
    ],
)
def test_find_exact_url_dupes(records: list[dict], expected_group_count: int):
    groups = _find_exact_url_dupes(records)
    assert len(groups) == expected_group_count


def test_find_exact_url_dupes_group_contains_both_records():
    records = [
        _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
        _rec(2, "Guitar A copy", "https://reverb.com/item/1-a?show_sold=true"),
    ]
    groups = _find_exact_url_dupes(records)
    assert len(groups) == 1
    ids = {r["id"] for r in groups[0]}
    assert ids == {1, 2}


def test_find_exact_url_dupes_ignores_empty_urls():
    records = [
        _rec(1, "Guitar A", ""),
        _rec(2, "Guitar B", ""),
    ]
    groups = _find_exact_url_dupes(records)
    assert groups == []


# ── _find_same_item_id_dupes ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "records, expected_group_count",
    [
        pytest.param([], 0, id="empty-list"),
        pytest.param(
            [_rec(1, "Guitar A", "https://reverb.com/item/100-old-slug")],
            0,
            id="single-record",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/100-old-slug"),
                _rec(2, "Guitar A renamed", "https://reverb.com/item/100-new-slug"),
            ],
            1,
            id="same-id-different-slug",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/100-old-slug"),
                _rec(2, "Guitar A copy", "https://reverb.com/item/100-old-slug"),
            ],
            0,
            id="same-id-same-url-already-caught-by-exact",
        ),
        pytest.param(
            [
                _rec(1, "Guitar A", "https://reverb.com/item/100-slug-v1"),
                _rec(2, "Guitar A renamed", "https://reverb.com/item/100-slug-v2"),
                _rec(3, "Guitar B", "https://reverb.com/item/200-other"),
            ],
            1,
            id="one-same-id-group-one-distinct",
        ),
    ],
)
def test_find_same_item_id_dupes(records: list[dict], expected_group_count: int):
    groups = _find_same_item_id_dupes(records)
    assert len(groups) == expected_group_count


# ── _ids_to_delete ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "groups, expected_deleted_ids",
    [
        pytest.param([], [], id="no-groups"),
        pytest.param(
            [
                [
                    _rec(1, "Guitar A", "https://reverb.com/item/1-a", active=True, available=True),
                    _rec(
                        2, "Guitar A", "https://reverb.com/item/1-a", active=False, available=False
                    ),
                ]
            ],
            [2],
            id="keeps-active-available-deletes-other",
        ),
        pytest.param(
            [
                [
                    _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
                    _rec(2, "Guitar A", "https://reverb.com/item/1-a"),
                    _rec(3, "Guitar A", "https://reverb.com/item/1-a"),
                ]
            ],
            [2, 3],
            id="three-dupes-keeps-lowest-id",
        ),
    ],
)
def test_ids_to_delete(groups: list[list[dict]], expected_deleted_ids: list[int]):
    assert sorted(_ids_to_delete(groups)) == sorted(expected_deleted_ids)


# ── _delete_records ───────────────────────────────────────────────────────


def test_delete_records_calls_unlink():
    conn = MagicMock()
    guitar_model = MagicMock()
    conn.get_model.return_value = guitar_model

    deleted = _delete_records(conn, [1, 2, 3])

    conn.get_model.assert_called_once_with("x_guitar")
    guitar_model.unlink.assert_called_once_with([1, 2, 3])
    assert deleted == 3


def test_delete_records_empty_list_skips_unlink():
    conn = MagicMock()
    guitar_model = MagicMock()
    conn.get_model.return_value = guitar_model

    deleted = _delete_records(conn, [])

    guitar_model.unlink.assert_not_called()
    assert deleted == 0


# ── CLI ───────────────────────────────────────────────────────────────────


class TestDedupCli:
    runner = CliRunner()

    def _make_conn(self, records: list[dict]) -> MagicMock:
        conn = MagicMock()
        guitar_model = MagicMock()
        guitar_model.search_read.return_value = records
        conn.get_model.return_value = guitar_model
        return conn

    def test_help(self):
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "--delete" in result.output
        assert "--yes" in result.output

    def test_no_records(self):
        conn = self._make_conn([])
        result = self.runner.invoke(cli, obj={"conn": conn})
        assert result.exit_code == 0

    def test_exact_dupe_shown(self):
        records = [
            _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
            _rec(2, "Guitar A copy", "https://reverb.com/item/1-a?show_sold=true"),
        ]
        conn = self._make_conn(records)
        result = self.runner.invoke(cli, obj={"conn": conn})
        assert result.exit_code == 0
        assert "EXACT URL" in result.output

    def test_delete_flag_without_yes_prompts_per_record(self):
        records = [
            _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
            _rec(2, "Guitar A copy", "https://reverb.com/item/1-a"),
        ]
        conn = self._make_conn(records)
        # Answer "n" — record should be skipped, not deleted
        result = self.runner.invoke(cli, ["--delete"], obj={"conn": conn}, input="n\n")
        assert result.exit_code == 0
        assert "KEEP" in result.output
        assert "DEL" in result.output
        conn.get_model.return_value.unlink.assert_not_called()

    def test_delete_flag_without_yes_confirms_and_deletes(self):
        records = [
            _rec(1, "Guitar A", "https://reverb.com/item/1-a", active=True, available=True),
            _rec(2, "Guitar A copy", "https://reverb.com/item/1-a", active=False, available=False),
        ]
        conn = self._make_conn(records)
        # Answer "y" — record should be deleted
        result = self.runner.invoke(cli, ["--delete"], obj={"conn": conn}, input="y\n")
        assert result.exit_code == 0
        assert "KEEP" in result.output
        assert "DEL" in result.output
        conn.get_model.return_value.unlink.assert_called_once_with([2])

    def test_delete_with_yes_skips_prompt_and_deletes(self):
        records = [
            _rec(1, "Guitar A", "https://reverb.com/item/1-a", active=True, available=True),
            _rec(2, "Guitar A copy", "https://reverb.com/item/1-a", active=False, available=False),
        ]
        conn = self._make_conn(records)
        result = self.runner.invoke(cli, ["--delete", "--yes"], obj={"conn": conn})
        assert result.exit_code == 0
        conn.get_model.return_value.unlink.assert_called_once_with([2])

    def test_delete_without_dupes_skips_unlink(self):
        records = [
            _rec(1, "Guitar A", "https://reverb.com/item/1-a"),
            _rec(2, "Guitar B", "https://reverb.com/item/2-b"),
        ]
        conn = self._make_conn(records)
        result = self.runner.invoke(cli, ["--delete", "--yes"], obj={"conn": conn})
        assert result.exit_code == 0
        conn.get_model.return_value.unlink.assert_not_called()
