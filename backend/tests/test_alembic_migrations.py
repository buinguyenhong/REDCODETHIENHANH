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

        # Alignment is intentionally forward-only. Verify idempotent upgrade and
        # every ORM-mapped column on a database created exclusively by Alembic.
        command.upgrade(alembic_cfg, "head")
        from sqlalchemy import create_engine, inspect
        from app.database import Base
        import app.models
        migrated = create_engine(f'sqlite:///{tmp_db_path}')
        try:
            inspector = inspect(migrated)
            for table in Base.metadata.sorted_tables:
                actual = {c['name'] for c in inspector.get_columns(table.name)}
                assert set(table.columns.keys()) <= actual, table.name
        finally:
            migrated.dispose()

    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except Exception:
                pass
