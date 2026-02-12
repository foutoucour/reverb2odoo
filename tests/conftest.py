"""Shared fixtures for the test suite."""

from pathlib import Path

import pytest

from reverb_scraper import ReverbScraper

CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.fixture(scope="module")
def vcr_config():
    """VCR configuration shared across all tests.

    Record mode is controlled via the CLI flag --record-mode (default: none).
    To record cassettes:  uv run pytest --record-mode=once
    To re-record all:     uv run pytest --record-mode=all
    """
    return {
        "cassette_library_dir": str(CASSETTE_DIR),
        "filter_headers": ["Authorization", "Cookie"],
    }


@pytest.fixture
def scraper() -> ReverbScraper:
    """Return a ReverbScraper configured for CAD / Canada."""
    return ReverbScraper(currency="CAD", shipping_region="CA")
