"""Initialize legacy Core changes and add the Local transactional outbox."""

from alembic import op
import sqlalchemy as sa

revision = "0012_local_sync_queue"
down_revision = "0011_sync_foundation"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sync_workspace_state") as batch:
        batch.add_column(sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "local_sync_state",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("cursor", sa.BigInteger(), nullable=False),
        sa.Column("remote_core_url", sa.String(2048), nullable=True),
        sa.Column("remote_workspace_id", sa.String(36), nullable=True),
        sa.Column("remote_client_id", sa.String(36), nullable=True),
        sa.Column("queue_seeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cursor >= 0", name="ck_local_sync_cursor_nonnegative"),
    )
    op.create_table(
        "local_mutation_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mutation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("base_revision", sa.BigInteger(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "entity_type", "entity_id", name="uq_local_mutation_entity"),
        sa.CheckConstraint("base_revision >= 0", name="ck_local_mutation_base_nonnegative"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_local_mutation_attempt_nonnegative"),
    )
    op.create_index("ix_local_mutation_workspace_status", "local_mutation_queue", ["workspace_id", "status"])


def downgrade():
    op.drop_index("ix_local_mutation_workspace_status", table_name="local_mutation_queue")
    op.drop_table("local_mutation_queue")
    op.drop_table("local_sync_state")
    with op.batch_alter_table("sync_workspace_state") as batch:
        batch.drop_column("initialized_at")
