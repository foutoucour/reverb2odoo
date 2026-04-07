"""Set CAD as the default currency for x_studio_currency_id on a given model.

Usage::

    reverb2odoo set-default-currency x_gear
"""

from __future__ import annotations

import click
from loguru import logger

_CURRENCY_NAME = "CAD"
_FIELD_NAME = "x_studio_currency_id"


@click.command("set-default-currency")
@click.argument("model")
@click.pass_context
def cli(ctx: click.Context, model: str) -> None:
    """Set CAD as the default currency for MODEL.

    MODEL is the Odoo model name (e.g. x_gear).
    """
    conn = ctx.obj["conn"]

    cad_ids = conn.get_model("res.currency").search([("name", "=", _CURRENCY_NAME)])
    if not cad_ids:
        logger.error("Currency '{}' not found in Odoo.", _CURRENCY_NAME)
        raise SystemExit(1)
    cad_id = cad_ids[0]

    conn.get_model("ir.default").set(model, _FIELD_NAME, cad_id)
    logger.success(
        "Default {} set to {} (id={}) on model '{}'.",
        _FIELD_NAME,
        _CURRENCY_NAME,
        cad_id,
        model,
    )
