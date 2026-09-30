"""Explicit Agent data authorization and transactional action receipts."""

from alembic import op
import sqlalchemy as sa

revision = "0015_agent_data_actions"
down_revision = "0014_multi_entity_sync"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column("data_scopes", sa.JSON(), nullable=False, server_default="[]")
        )
    op.create_table(
        "agent_action_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), nullable=True),
        sa.Column("action_id", sa.String(36), nullable=True),
        sa.Column("action_type", sa.String(80), nullable=False),
        sa.Column("required_scope", sa.String(40), nullable=False),
        sa.Column("target_entity_type", sa.String(40), nullable=True),
        sa.Column("target_entity_id", sa.String(36), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("result_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("agent_id", "action_id", name="uq_agent_action_id"),
    )
    op.create_index("ix_agent_action_logs_agent_id", "agent_action_logs", ["agent_id"])
    op.create_index(
        "ix_agent_action_logs_workspace_id", "agent_action_logs", ["workspace_id"]
    )


def downgrade():
    op.drop_table("agent_action_logs")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("data_scopes")
