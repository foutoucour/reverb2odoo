"""Set CAD as the default currency for a currency field on a given model.

Usage::

    reverb2odoo set-default-currency x_gear
    reverb2odoo set-default-currency x_gear --field x_currency_id
"""

from __future__ import annotations

import click
from loguru import logger

_CURRENCY_NAME = "CAD"
_DEFAULT_FIELD = "x_studio_currency_id"


@click.command("set-default-currency")
@click.argument("model")
@click.option(
    "--field",
    default=_DEFAULT_FIELD,
    show_default=True,
    help="Currency field name to set the default on.",
)
@click.pass_context
def cli(ctx: click.Context, model: str, field: str) -> None:
    """Set CAD as the default currency for MODEL.

    MODEL is the Odoo model name (e.g. x_gear).
    """
    conn = ctx.obj["conn"]

    cad_ids = conn.get_model("res.currency").search([("name", "=", _CURRENCY_NAME)])
    if not cad_ids:
        logger.error("Currency '{}' not found in Odoo.", _CURRENCY_NAME)
        raise SystemExit(1)
    cad_id = cad_ids[0]

    conn.get_model("ir.default").set(model, field, cad_id)
    logger.success(
        "Default {} set to {} (id={}) on model '{}'.",
        field,
        _CURRENCY_NAME,
        cad_id,
        model,
    )
