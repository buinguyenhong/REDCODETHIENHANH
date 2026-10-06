"""initial_complete_schema

Revision ID: 8280022f67e9
Revises: 
Create Date: 2026-10-06 08:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8280022f67e9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # PostgreSQL sequence for atomic server_sequence
    if is_postgres:
        op.execute("CREATE SEQUENCE IF NOT EXISTS alarm_server_sequence START 1;")

    # 1. departments
    op.create_table(
        'departments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 2. users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(length=50), nullable=False, server_default='OPERATOR'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username')
    )

    # 3. receiver_groups
    op.create_table(
        'receiver_groups',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 4. stations
    op.create_table(
        'stations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('station_code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(length=255), nullable=True),
        sa.Column('device_token_hash', sa.String(length=255), nullable=False),
        sa.Column('ip_address', sa.String(length=50), nullable=True),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='OFFLINE'),
        sa.Column('audio_ready', sa.Boolean(), nullable=False, server_default=sa.text('0' if not is_postgres else 'false')),
        sa.Column('client_ready', sa.Boolean(), nullable=False, server_default=sa.text('0' if not is_postgres else 'false')),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('station_code')
    )
    op.create_index('ix_stations_status', 'stations', ['status'], unique=False)

    # 5. receiver_group_stations
    op.create_table(
        'receiver_group_stations',
        sa.Column('receiver_group_id', sa.Integer(), nullable=False),
        sa.Column('station_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['receiver_group_id'], ['receiver_groups.id'], ),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
        sa.PrimaryKeyConstraint('receiver_group_id', 'station_id')
    )

    # 6. alarm_types
    op.create_table(
        'alarm_types',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('display_color', sa.String(length=50), nullable=False, server_default='#dc2626'),
        sa.Column('receiver_group_id', sa.Integer(), nullable=True),
        sa.Column('audio_sequence', sa.JSON(), nullable=True),
        sa.Column('repeat_count', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('repeat_interval_ms', sa.Integer(), nullable=False, server_default='1000'),
        sa.Column('allowed_department_ids', sa.JSON(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['receiver_group_id'], ['receiver_groups.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 7. department_alarm_permissions
    op.create_table(
        'department_alarm_permissions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('alarm_type_id', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['alarm_type_id'], ['alarm_types.id'], ),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('department_id', 'alarm_type_id', name='uq_department_alarm_type')
    )

    # 8. alarms
    op.create_table(
        'alarms',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('alarm_code', sa.String(length=100), nullable=False),
        sa.Column('server_sequence', sa.BigInteger(), nullable=False),
        sa.Column('alarm_type_id', sa.Integer(), nullable=False),
        sa.Column('source_department_id', sa.Integer(), nullable=False),
        sa.Column('location_text', sa.String(length=255), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='ACTIVE'),
        sa.Column('idempotency_key', sa.String(length=100), nullable=True),
        sa.Column('triggered_by_user_id', sa.Integer(), nullable=True),
        sa.Column('cancelled_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['alarm_type_id'], ['alarm_types.id'], ),
        sa.ForeignKeyConstraint(['cancelled_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['source_department_id'], ['departments.id'], ),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alarm_code'),
        sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('ix_alarms_server_sequence', 'alarms', ['server_sequence'], unique=False)
    op.create_index('ix_alarms_status', 'alarms', ['status'], unique=False)

    # 9. alarm_station_states
    op.create_table(
        'alarm_station_states',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('alarm_id', sa.Integer(), nullable=False),
        sa.Column('station_id', sa.Integer(), nullable=False),
        sa.Column('state', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('displayed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('audio_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('audio_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['alarm_id'], ['alarms.id'], ),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alarm_id', 'station_id', name='uq_alarm_station')
    )

    # 10. notification_outbox
    op.create_table(
        'notification_outbox',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False, server_default='ALARM_TRIGGERED'),
        sa.Column('alarm_id', sa.Integer(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['alarm_id'], ['alarms.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notification_outbox_status', 'notification_outbox', ['status'], unique=False)
    op.create_index('ix_notification_outbox_next_attempt_at', 'notification_outbox', ['next_attempt_at'], unique=False)

    # 11. audio_files
    op.create_table(
        'audio_files',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False, server_default='audio/wav'),
        sa.Column('duration_seconds', sa.Float(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('1' if not is_postgres else 'true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )

    # 12. alarm_events
    op.create_table(
        'alarm_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('alarm_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('station_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('event_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['alarm_id'], ['alarms.id'], ),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # 13. system_events
    op.create_table(
        'system_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False, server_default='INFO'),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.drop_table('system_events')
    op.drop_table('alarm_events')
    op.drop_table('audio_files')
    op.drop_table('notification_outbox')
    op.drop_table('alarm_station_states')
    op.drop_table('alarms')
    op.drop_table('department_alarm_permissions')
    op.drop_table('alarm_types')
    op.drop_table('receiver_group_stations')
    op.drop_table('stations')
    op.drop_table('receiver_groups')
    op.drop_table('users')
    op.drop_table('departments')

    if is_postgres:
        op.execute("DROP SEQUENCE IF EXISTS alarm_server_sequence;")
