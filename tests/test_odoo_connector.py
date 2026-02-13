"""Tests for odoo_connector helper functions."""

from unittest.mock import MagicMock

import pytest

from odoo_connector import (
    GUITAR_FIELDS,
    _extract_reverb_item_id,
    _hostname_from_url,
    find_guitar_by_url,
)

# ── _hostname_from_url ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param(
            "https://reverb2odoo.odoo.com/odoo", "reverb2odoo.odoo.com", id="https-with-path"
        ),
        pytest.param("https://mydb.odoo.com", "mydb.odoo.com", id="https-no-path"),
        pytest.param("http://localhost:8069", "localhost", id="http-localhost"),
        pytest.param("http://192.168.1.10:8069/web", "192.168.1.10", id="http-ip-with-port"),
        pytest.param("localhost", "localhost", id="bare-localhost"),
        pytest.param(
            "myhost.example.com/path/to/something",
            "myhost.example.com",
            id="bare-hostname-with-path",
        ),
        pytest.param("10.0.0.1", "10.0.0.1", id="bare-ip"),
    ],
)
def test_hostname_from_url(raw: str, expected: str):
    assert _hostname_from_url(raw) == expected


# ── _extract_reverb_item_id ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "url, expected",
    [
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium-ht-with-rosewood-fretboard-2022-matte-black",
            "94370297",
            id="standard-reverb-url",
        ),
        pytest.param(
            "https://reverb.com/item/12345-short-slug",
            "12345",
            id="short-item-id",
        ),
        pytest.param(
            "https://reverb.com/item/999999999-a",
            "999999999",
            id="large-item-id",
        ),
        pytest.param(
            "https://reverb.com/item/94370297-godin-stadium-ht-with-rosewood-fretboard-2022-matte-black`",
            "94370297",
            id="trailing-backtick",
        ),
        pytest.param(
            "https://www.kijiji.ca/v-guitar/city-of-toronto/something/123456",
            None,
            id="non-reverb-url",
        ),
        pytest.param(
            "https://reverb.com/shop/some-shop",
            None,
            id="reverb-non-item-url",
        ),
        pytest.param(
            "https://reverb.com/item/not-a-number-slug",
            None,
            id="non-numeric-item-id",
        ),
        pytest.param(
            "localhost",
            None,
            id="bare-hostname",
        ),
    ],
)
def test_extract_reverb_item_id(url: str, expected: str | None):
    assert _extract_reverb_item_id(url) == expected


# ── find_guitar_by_url ────────────────────────────────────────────────────


def _make_mock_conn(search_read_side_effect):
    """Build a mock ``odoolib`` connection whose model responds to search_read."""
    conn = MagicMock()
    model = MagicMock()
    model.search_read.side_effect = search_read_side_effect
    conn.get_model.return_value = model
    return conn, model


class TestFindGuitarByUrl:
    """Unit tests for find_guitar_by_url (no real Odoo connection)."""

    def test_exact_match(self):
        record = {"id": 1884, "x_name": "Godin Stadium HT"}
        conn, model = _make_mock_conn(lambda *a, **kw: [record])

        result = find_guitar_by_url(conn, "https://reverb.com/item/94370297-godin")

        assert result == record
        conn.get_model.assert_called_once_with("x_guitar")
        # Only one call needed (exact match found on first try)
        assert model.search_read.call_count == 1

    def test_fallback_to_partial_match(self):
        record = {"id": 42, "x_name": "Some Guitar"}
        # First call (exact) returns nothing; second call (partial) returns hit
        conn, model = _make_mock_conn(
            lambda domain, *a, **kw: [record] if ("ilike",) and domain[0][2] == "94370297" else [],
        )
        # Override to distinguish the two calls
        model.search_read.side_effect = [[], [record]]

        result = find_guitar_by_url(
            conn,
            "https://reverb.com/item/94370297-godin-stadium-ht",
        )

        assert result == record
        assert model.search_read.call_count == 2

    def test_no_match_returns_none(self):
        conn, model = _make_mock_conn(lambda *a, **kw: [])

        result = find_guitar_by_url(
            conn,
            "https://reverb.com/item/99999999-nonexistent",
        )

        assert result is None

    def test_non_reverb_url_skips_partial(self):
        conn, model = _make_mock_conn(lambda *a, **kw: [])

        result = find_guitar_by_url(
            conn,
            "https://www.kijiji.ca/v-guitar/city-of-toronto/cool-guitar/123",
        )

        assert result is None
        # Only exact match attempted (no Reverb item ID to extract)
        assert model.search_read.call_count == 1

    def test_custom_fields(self):
        record = {"id": 10, "x_name": "Test"}
        conn, model = _make_mock_conn(lambda *a, **kw: [record])
        custom = ["x_name", "x_studio_url"]

        find_guitar_by_url(conn, "https://reverb.com/item/1-test", fields=custom)

        call_args = model.search_read.call_args
        assert call_args[0][1] == custom

    def test_default_fields(self):
        record = {"id": 10, "x_name": "Test"}
        conn, model = _make_mock_conn(lambda *a, **kw: [record])

        find_guitar_by_url(conn, "https://reverb.com/item/1-test")

        call_args = model.search_read.call_args
        assert call_args[0][1] == GUITAR_FIELDS
