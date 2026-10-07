import os
import sys
import pytest
from alembic.config import Config
from alembic import command
import tempfile

def test_alembic_upgrade_and_schema_alignment():
    """
    Upgrade a clean database, repeat upgrade, and check ORM schema alignment.
    Production migrations are forward-only; no destructive downgrade cycle.
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
            assert 'allowed_department_ids' not in {c['name'] for c in inspector.get_columns('alarm_types')}
            assert any(set(item['column_names']) == {'idempotency_key'} for item in inspector.get_unique_constraints('alarms'))
        finally:
            migrated.dispose()

    finally:
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except Exception:
                pass


def test_permission_migration_preserves_explicit_denial_and_history():
    from sqlalchemy import create_engine, text
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'legacy.db')
        backend = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        cfg = Config(os.path.join(backend, 'alembic.ini'))
        cfg.set_main_option('script_location', os.path.join(backend, 'alembic'))
        cfg.set_main_option('sqlalchemy.url', f'sqlite:///{path}')
        command.upgrade(cfg, '20261006_validity')
        db = create_engine(f'sqlite:///{path}')
        try:
            with db.begin() as connection:
                connection.execute(text("INSERT INTO departments (id,code,name) VALUES (1,'D1','D1'), (2,'D2','D2')"))
                connection.execute(text("INSERT INTO alarm_types (id,code,name,allowed_department_ids) VALUES (1,'A','A','[1,2,999,true,\"bad\"]')"))
                connection.execute(text('INSERT INTO department_alarm_permissions (department_id,alarm_type_id,enabled) VALUES (1,1,0)'))
                connection.execute(text("INSERT INTO stations (id,station_code,name,device_token_hash) VALUES (1,'S','S','hash')"))
                connection.execute(text("INSERT INTO alarms (id,alarm_type_id,source_department_id,server_sequence,status) VALUES (1,1,1,1,'ACTIVE')"))
                connection.execute(text("INSERT INTO alarm_station_states (alarm_id,station_id,state,received_at) VALUES (1,1,'PENDING','2026-10-07 00:00:00')"))
            command.upgrade(cfg, 'head')
            with db.connect() as connection:
                assert connection.execute(text('SELECT department_id,enabled FROM department_alarm_permissions ORDER BY department_id')).all() == [(1, 0), (2, 1)]
                assert connection.execute(text('SELECT state FROM alarm_station_states')).scalar() == 'DELIVERED'
                assert connection.execute(text('SELECT COUNT(*) FROM alarms')).scalar() == 1
        finally:
            db.dispose()
