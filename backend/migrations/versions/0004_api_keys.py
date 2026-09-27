"""Store per-user API Key digests. Schema snapshot for 0004_api_keys."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_api_keys"
down_revision = '0003_devices_agents'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "api_keys" not in existing:
        op.create_table("api_keys",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('token_hash', sa.String(length=64), nullable=False),
            sa.Column('name', sa.String(length=48), nullable=False),
            sa.Column('last4', sa.String(length=4), nullable=False),
            sa.Column('scopes', sa.JSON(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_api_keys_token_hash', 'api_keys', ['token_hash'], unique=True)
        op.create_index('ix_api_keys_user_id', 'api_keys', ['user_id'], unique=False)


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    if "api_keys" in existing:
        op.drop_table("api_keys")
