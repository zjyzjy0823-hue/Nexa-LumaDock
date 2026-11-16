"""Durable Local completion event delivery to Core."""
from alembic import op
import sqlalchemy as sa

revision = "0019_local_automation_events"
down_revision = "0018_data_record_tenancy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("local_automation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(160), nullable=False, unique=True),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("agent_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(80), nullable=True))
    op.create_index("ix_local_automation_events_pending", "local_automation_events", ["workspace_id", "delivered_at"])


def downgrade():
    op.drop_table("local_automation_events")
