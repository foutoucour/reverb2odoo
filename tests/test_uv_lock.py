"""Guards on `uv.lock` — specifically, which package index it points at.

CI runs on GitHub-hosted `ubuntu-latest` runners, which have no route to any
corporate network. A lockfile that resolves against an internal mirror still
installs fine on the machine that produced it and then fails every CI run with
a DNS error, so the breakage is invisible until a pull request is opened.

This has happened once already: a `uv lock` run on a machine with
`UV_INDEX_URL` / `UV_DEFAULT_INDEX` pointing at an internal Artifactory mirror
rewrote all 608 URLs in the lockfile, and CI died on the first download. Those
environment variables outrank a `[[tool.uv.index]]` block in `pyproject.toml`,
so the project cannot pin the index itself — asserting on the committed
lockfile is the only guard that holds regardless of who locked it and where.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

LOCKFILE = Path(__file__).parent.parent / "uv.lock"

#: The only hosts a publicly resolvable lockfile may reference: PyPI's index
#: and the CDN its artifacts are served from.
PUBLIC_PYPI_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})


def _lock_packages() -> list[dict]:
    return tomllib.loads(LOCKFILE.read_text(encoding="utf-8"))["package"]


def _index_urls() -> list[tuple[str, str]]:
    """Return `(package_name, url)` for every registry a package resolves from."""
    return [
        (package["name"], package["source"]["registry"])
        for package in _lock_packages()
        if "registry" in package.get("source", {})
    ]


def _sdist_urls() -> list[tuple[str, str]]:
    """Return `(package_name, url)` for every source distribution download."""
    return [
        (package["name"], package["sdist"]["url"])
        for package in _lock_packages()
        if "url" in package.get("sdist", {})
    ]


def _wheel_urls() -> list[tuple[str, str]]:
    """Return `(package_name, url)` for every wheel download."""
    return [
        (package["name"], wheel["url"])
        for package in _lock_packages()
        for wheel in package.get("wheels", [])
        if "url" in wheel
    ]


@pytest.mark.parametrize(
    "collect",
    [
        pytest.param(_index_urls, id="package-index"),
        pytest.param(_sdist_urls, id="sdist-download"),
        pytest.param(_wheel_urls, id="wheel-download"),
    ],
)
def test_lockfile_points_only_at_public_pypi(collect) -> None:
    """Every URL in the lockfile must be reachable from a GitHub-hosted runner."""
    urls = collect()
    assert urls, "found no URLs of this kind — the lockfile layout changed"

    offenders = [
        (name, urlsplit(url).netloc)
        for name, url in urls
        if urlsplit(url).netloc not in PUBLIC_PYPI_HOSTS
    ]
    if not offenders:
        return

    # A bad lock is bad for every package at once, so listing all 58 buries the
    # one thing that matters — which host. Name the hosts, then a few examples.
    hosts = ", ".join(sorted({host for _, host in offenders}))
    examples = ", ".join(sorted({name for name, _ in offenders})[:5])
    pytest.fail(
        f"uv.lock points {len(offenders)} download(s) at {hosts}, which a "
        f"GitHub-hosted runner cannot resolve (e.g. {examples}).\n"
        "Re-lock against PyPI — note the env overrides, which outrank any "
        "index configured in pyproject.toml:\n"
        "  UV_INDEX_URL=https://pypi.org/simple "
        "UV_DEFAULT_INDEX=https://pypi.org/simple uv lock --no-config"
    )
