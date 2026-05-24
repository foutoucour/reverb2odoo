"""Tests for odoo_mcp/config.py — get_odoo_config()."""

from __future__ import annotations

from unittest.mock import patch

import pytest

# Patch load_dotenv to a no-op so the .env file (absent in CI) does not interfere.
_PATCH_LOAD_DOTENV = patch("odoo_mcp.config.load_dotenv", return_value=None)

_ALL_ENV_VARS = {
    "ODOO_HOSTNAME": "odoo.example.com",
    "ODOO_DATABASE": "mydb",
    "ODOO_LOGIN": "admin",
    "ODOO_PASSWORD": "secret",
}


@pytest.fixture(autouse=True)
def patch_load_dotenv():
    """Suppress load_dotenv for every test in this module."""
    with _PATCH_LOAD_DOTENV:
        yield


def test_get_odoo_config_returns_dataclass(monkeypatch):
    """All 4 env vars set → OdooConfig dataclass with correct values."""
    for key, value in _ALL_ENV_VARS.items():
        monkeypatch.setenv(key, value)

    # Import after env vars are set so os.environ["…"] reads them.
    from odoo_mcp.config import OdooConfig, get_odoo_config

    result = get_odoo_config()

    assert isinstance(result, OdooConfig)
    assert result.hostname == "odoo.example.com"
    assert result.database == "mydb"
    assert result.login == "admin"
    assert result.password == "secret"


@pytest.mark.parametrize(
    "missing_var",
    [
        pytest.param("ODOO_HOSTNAME", id="missing-hostname"),
        pytest.param("ODOO_DATABASE", id="missing-database"),
        pytest.param("ODOO_LOGIN", id="missing-login"),
        pytest.param("ODOO_PASSWORD", id="missing-password"),
    ],
)
def test_get_odoo_config_raises_on_missing_var(monkeypatch, missing_var: str):
    """Any missing env var → KeyError from get_odoo_config()."""
    for key, value in _ALL_ENV_VARS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing_var, raising=False)

    from odoo_mcp.config import get_odoo_config

    with pytest.raises(KeyError):
        get_odoo_config()
