"""Optional n8n configuration; no implicit replay of pre-enable notifications."""
from alembic import op
import sqlalchemy as sa

revision = '20261007_integrations'
down_revision = '20261007_permissions'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('integration_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('webhook_url', sa.Text(), nullable=False),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False),
        sa.Column('max_retries', sa.Integer(), nullable=False),
        sa.Column('enabled_since', sa.DateTime(timezone=True), nullable=True))
    op.execute("INSERT INTO integration_settings (id,enabled,webhook_url,timeout_seconds,max_retries) VALUES (1,false,'',4,3)")


def downgrade():
    raise RuntimeError('Forward-only migration; restore a verified backup.')
