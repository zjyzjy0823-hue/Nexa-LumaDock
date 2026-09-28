"""Add revocable client credential metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0010_client_auth"
down_revision = "0009_workspace_clients"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("token_last4", sa.String(4), nullable=True))
        batch.add_column(sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_clients_token_hash", ["token_hash"], unique=True)


def downgrade():
    with op.batch_alter_table("clients") as batch:
        batch.drop_index("ix_clients_token_hash")
        batch.drop_column("token_created_at")
        batch.drop_column("token_last4")
        batch.drop_column("token_hash")
