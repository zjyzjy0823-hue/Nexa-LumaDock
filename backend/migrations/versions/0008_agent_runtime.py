"""Add adapter-independent agent credentials and task runtime state."""

from alembic import op
import sqlalchemy as sa

revision = "0008_agent_runtime"
down_revision = "0007_device_kind_laptop"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agents") as batch:
        batch.add_column(sa.Column("token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("token_last4", sa.String(4), nullable=True))
        batch.add_column(sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("runtime_type", sa.String(40), nullable=True))
        batch.add_column(sa.Column("runtime_version", sa.String(40), nullable=True))
        batch.add_column(sa.Column("runtime_instance", sa.String(120), nullable=True))
        batch.add_column(sa.Column("current_task_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(500), nullable=True))
        batch.create_index("ix_agents_token_hash", ["token_hash"], unique=True)
    with op.batch_alter_table("agent_tasks") as batch:
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("result_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("error_message", sa.String(500), nullable=True))
    with op.batch_alter_table("agent_events") as batch:
        batch.add_column(sa.Column("task_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("event_type", sa.String(40), nullable=True))
        batch.add_column(sa.Column("data_json", sa.JSON(), nullable=True))
        batch.create_index("ix_agent_events_task_id", ["task_id"])


def downgrade():
    with op.batch_alter_table("agent_events") as batch:
        batch.drop_index("ix_agent_events_task_id")
        for name in ("data_json", "event_type", "task_id"):
            batch.drop_column(name)
    with op.batch_alter_table("agent_tasks") as batch:
        for name in ("error_message", "result_json", "completed_at", "claimed_at"):
            batch.drop_column(name)
    with op.batch_alter_table("agents") as batch:
        batch.drop_index("ix_agents_token_hash")
        for name in ("last_error", "current_task_id", "runtime_instance", "runtime_version", "runtime_type",
                     "token_created_at", "token_last4", "token_hash"):
            batch.drop_column(name)
