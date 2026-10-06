import os
import sys
import pytest
from alembic.config import Config
from alembic import command
import tempfile

def test_alembic_upgrade_downgrade_cycle():
    """
    Section VII & XIII (Requirements 21, 48-51):
    Test Alembic migrations on a clean temporary database:
    1. alembic upgrade head
    2. alembic downgrade base
    3. alembic upgrade head again
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db_path = tmp.name

    try:
        # Build alembic config pointing to this temp SQLite database
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        ini_path = os.path.join(backend_dir, "alembic.ini")
        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_db_path}")

        # 1. Clean DB upgrade head
        command.upgrade(alembic_cfg, "head")

        # 2. Downgrade to base
        command.downgrade(alembic_cfg, "base")

        # 3. Upgrade to head again
        command.upgrade(alembic_cfg, "head")

    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except Exception:
                pass
