"""Add Core revision, change log, idempotency, and Ledger tombstones."""

from alembic import op
import sqlalchemy as sa

revision = "0011_sync_foundation"
down_revision = "0010_client_auth"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("ledger_categories", "ledger_transactions"):
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("sync_revision", sa.BigInteger(), nullable=False, server_default="0"))
            batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "sync_workspace_state",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("current_revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("current_revision >= 0", name="ck_sync_workspace_revision_nonnegative"),
    )
    op.create_table(
        "sync_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("origin_client_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "revision", name="uq_sync_changes_workspace_revision"),
    )
    op.create_index("ix_sync_changes_workspace_id", "sync_changes", ["workspace_id"])
    op.create_table(
        "sync_mutations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mutation_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("base_revision", sa.BigInteger(), nullable=False),
        sa.Column("result_revision", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", "mutation_id", name="uq_sync_mutations_client_mutation"),
    )
    op.create_index("ix_sync_mutations_workspace_id", "sync_mutations", ["workspace_id"])
    op.create_index("ix_sync_mutations_client_id", "sync_mutations", ["client_id"])


def downgrade():
    op.drop_index("ix_sync_mutations_client_id", table_name="sync_mutations")
    op.drop_index("ix_sync_mutations_workspace_id", table_name="sync_mutations")
    op.drop_table("sync_mutations")
    op.drop_index("ix_sync_changes_workspace_id", table_name="sync_changes")
    op.drop_table("sync_changes")
    op.drop_table("sync_workspace_state")
    for name in ("ledger_transactions", "ledger_categories"):
        with op.batch_alter_table(name) as batch:
            batch.drop_column("deleted_at")
            batch.drop_column("sync_revision")
