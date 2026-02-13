"""
Unified CLI entry point for reverb2odoo.

Assembles individual commands from each module into a single Click group::

    reverb2odoo sync "Frank Brothers Arcane"
    reverb2odoo validate --all --dry-run
    reverb2odoo sync-categories
"""

from __future__ import annotations

import click

from sync_model import cli as sync_cmd
from validate_model import cli as validate_cmd


@click.group()
@click.version_option(package_name="reverb2odoo")
def main() -> None:
    """reverb2odoo — Sync Reverb listings with Odoo."""


main.add_command(sync_cmd)
main.add_command(validate_cmd)

if __name__ == "__main__":
    main()
