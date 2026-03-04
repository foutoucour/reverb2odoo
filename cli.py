"""
Unified CLI entry point for reverb2odoo.

Assembles individual commands from each module into a single Click group::

    reverb2odoo sync "Frank Brothers Arcane"
    reverb2odoo validate --all --dry-run
    reverb2odoo sync-categories

Odoo credentials are read from environment variables (``ODOO_HOSTNAME``,
``ODOO_DATABASE``, ``ODOO_LOGIN``, ``ODOO_PASSWORD``) or passed as
``--odoo-*`` options.
"""

from __future__ import annotations

import sys

import click
from loguru import logger

from odoo_connector import get_connection
from sync_model import cli as sync_cmd
from validate_model import cli as validate_cmd

# Reconfigure loguru: clean single-line format, no timestamps or file references.
logger.remove()
logger.add(sys.stderr, format="<level>{message}</level>", colorize=True, level="INFO")


@click.group()
@click.version_option(package_name="reverb2odoo")
@click.option(
    "--odoo-hostname",
    envvar="ODOO_HOSTNAME",
    required=True,
    help="Odoo hostname or URL (env: ODOO_HOSTNAME).",
)
@click.option(
    "--odoo-database",
    envvar="ODOO_DATABASE",
    required=True,
    help="Odoo database name (env: ODOO_DATABASE).",
)
@click.option(
    "--odoo-login",
    envvar="ODOO_LOGIN",
    required=True,
    help="Odoo login / email (env: ODOO_LOGIN).",
)
@click.option(
    "--odoo-password",
    envvar="ODOO_PASSWORD",
    required=True,
    help="Odoo password (env: ODOO_PASSWORD).",
)
@click.pass_context
def main(
    ctx: click.Context,
    odoo_hostname: str,
    odoo_database: str,
    odoo_login: str,
    odoo_password: str,
) -> None:
    """reverb2odoo — Sync Reverb listings with Odoo."""
    ctx.ensure_object(dict)
    ctx.obj["conn"] = get_connection(
        hostname=odoo_hostname,
        database=odoo_database,
        login=odoo_login,
        password=odoo_password,
    )


main.add_command(sync_cmd)
main.add_command(validate_cmd)

if __name__ == "__main__":
    main()
