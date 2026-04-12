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

from compute_price_brackets import cli as compute_price_brackets_cmd
from create_odoo_schema import cli as add_model_fields_cmd
from dedup_model import cli as dedup_cmd
from gear_page import cli as gear_page_cmd
from gpt_model import cli as gpt_files_cmd
from odoo_connector import get_connection
from remove_studio_sequence import cli as remove_studio_sequence_cmd
from set_default_currency import cli as set_default_currency_cmd
from sync_model import cli as sync_cmd
from trigger_weighted_score import cli as trigger_weighted_score_cmd
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


main.add_command(gear_page_cmd)
main.add_command(sync_cmd)
main.add_command(validate_cmd)
main.add_command(gpt_files_cmd)
main.add_command(dedup_cmd)
main.add_command(remove_studio_sequence_cmd)
main.add_command(trigger_weighted_score_cmd)
main.add_command(compute_price_brackets_cmd)
main.add_command(add_model_fields_cmd)
main.add_command(set_default_currency_cmd)

if __name__ == "__main__":
    main()
