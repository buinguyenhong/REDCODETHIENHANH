"""Retire JSON permissions and repair legacy receiver acknowledgement states.

Existing normalized grants/denials win over legacy JSON; only missing pairs
with valid department IDs are imported. Invalid JSON never broadens access.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261007_permissions'
down_revision = '20261006_validity'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    types = sa.table('alarm_types', sa.column('id', sa.Integer),
                     sa.column('allowed_department_ids', sa.JSON))
    permissions = sa.table('department_alarm_permissions',
        sa.column('department_id', sa.Integer), sa.column('alarm_type_id', sa.Integer),
        sa.column('enabled', sa.Boolean), sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)))
    departments = set(bind.execute(sa.text('SELECT id FROM departments')).scalars())
    existing = set(bind.execute(sa.select(permissions.c.department_id, permissions.c.alarm_type_id)).all())
    for row in bind.execute(sa.select(types)).all():
        if not isinstance(row.allowed_department_ids, list):
            continue
        for department_id in row.allowed_department_ids:
            if type(department_id) is not int or department_id not in departments:
                continue
            pair = (department_id, row.id)
            if pair not in existing:
                bind.execute(permissions.insert().values(department_id=department_id,
                    alarm_type_id=row.id, enabled=True, created_at=sa.func.now(), updated_at=sa.func.now()))
                existing.add(pair)
    with op.batch_alter_table('alarm_types') as batch:
        batch.drop_column('allowed_department_ids')
    op.execute("UPDATE alarm_station_states SET state = 'DELIVERED' WHERE state = 'PENDING' AND received_at IS NOT NULL")


def downgrade():
    raise RuntimeError('Forward-only production migration; restore a verified backup.')
