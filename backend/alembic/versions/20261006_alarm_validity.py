"""Alarm validity and retire legacy viewer accounts."""
from alembic import op
import sqlalchemy as sa
from datetime import timedelta, timezone

revision = '20261006_validity'
down_revision = '20261006_runtime'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alarm_types', sa.Column('validity_seconds', sa.Integer(), nullable=False, server_default='300'))
    op.add_column('alarms', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_alarms_expires_at', 'alarms', ['expires_at'])
    alarms = sa.table('alarms', sa.column('id', sa.Integer), sa.column('created_at', sa.DateTime(timezone=True)), sa.column('expires_at', sa.DateTime(timezone=True)))
    connection = op.get_bind()
    for row in connection.execute(sa.select(alarms.c.id, alarms.c.created_at)):
        created = row.created_at
        if created:
            connection.execute(alarms.update().where(alarms.c.id == row.id).values(expires_at=created + timedelta(seconds=300)))
    op.execute("UPDATE users SET enabled = false WHERE role = 'VIEWER'")


def downgrade():
    op.drop_index('ix_alarms_expires_at', table_name='alarms')
    op.drop_column('alarms', 'expires_at')
    op.drop_column('alarm_types', 'validity_seconds')
