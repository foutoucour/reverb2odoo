import os
from dataclasses import dataclass
from pathlib import Path

import odoolib
from dotenv import load_dotenv

from odoo_connector import get_connection

# Load .env from project root (parent of this package); does not override existing env vars.
load_dotenv(Path(__file__).parent.parent / ".env")


@dataclass
class OdooConfig:
    hostname: str
    database: str
    login: str
    password: str


def get_odoo_config() -> OdooConfig:
    return OdooConfig(
        hostname=os.environ["ODOO_HOSTNAME"],
        database=os.environ["ODOO_DATABASE"],
        login=os.environ["ODOO_LOGIN"],
        password=os.environ["ODOO_PASSWORD"],
    )


def get_connection_from_env() -> odoolib.main.Connection:
    cfg = get_odoo_config()
    return get_connection(cfg.hostname, cfg.database, cfg.login, cfg.password)
