"""Align the original migration schema with the runtime ORM without dropping data."""
from alembic import op
import sqlalchemy as sa

revision = '20261006_runtime'
down_revision = '8280022f67e9'
branch_labels = None
depends_on = None


def upgrade():
    renames = {
        'stations': {'last_heartbeat_at': 'last_seen_at'},
        'alarms': {'location_text': 'source_location', 'triggered_by_user_id': 'created_by_user_id'},
        'alarm_events': {'event_metadata': 'metadata'},
        'system_events': {'details': 'metadata'},
    }
    additions = {
        'users': [sa.Column('last_login_at', sa.DateTime(timezone=True))],
        'stations': [sa.Column('websocket_connected', sa.Boolean(), nullable=False, server_default=sa.false())],
        'alarms': [sa.Column('activated_at', sa.DateTime(timezone=True))],
        'alarm_events': [sa.Column('event_time', sa.DateTime(timezone=True))],
        'system_events': [sa.Column('station_id', sa.Integer(), nullable=True)],
        'audio_files': [sa.Column('updated_at', sa.DateTime(timezone=True))],
        'notification_outbox': [sa.Column('locked_at', sa.DateTime(timezone=True))],
    }
    bind = op.get_bind()
    for table in set(renames) | set(additions):
        cols = {c['name']: c for c in sa.inspect(bind).get_columns(table)}
        with op.batch_alter_table(table) as batch:
            for old, new in renames.get(table, {}).items():
                if old in cols and new not in cols:
                    batch.alter_column(old, new_column_name=new)
            for column in additions.get(table, []):
                if column.name not in cols:
                    batch.add_column(column)
            if table == 'alarms':
                if 'alarm_code' in cols:
                    batch.alter_column('alarm_code', existing_type=sa.String(100), nullable=True)
                batch.alter_column('source_department_id', existing_type=sa.Integer(), nullable=True)
            if table == 'notification_outbox':
                batch.alter_column('next_attempt_at', existing_type=sa.DateTime(timezone=True), nullable=True)
    op.execute('UPDATE alarm_events SET event_time = created_at WHERE event_time IS NULL')
    op.execute('UPDATE audio_files SET updated_at = created_at WHERE updated_at IS NULL')
    op.execute('UPDATE alarms SET activated_at = created_at WHERE activated_at IS NULL')
    if bind.dialect.name == 'postgresql':
        op.execute("SELECT setval('alarm_server_sequence', GREATEST(COALESCE((SELECT MAX(server_sequence) FROM alarms), 0) + 1, 1), false)")


def downgrade():
    raise RuntimeError('Data-preserving runtime alignment cannot be automatically downgraded; restore a backup.')
