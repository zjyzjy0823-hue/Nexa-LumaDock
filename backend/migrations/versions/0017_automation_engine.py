"""Core automation runtime; shared SQLite/PostgreSQL schema."""
from alembic import op
import sqlalchemy as sa

revision = "0017_automation_engine"
down_revision = "0016_personal_state_sync"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("automation_executions") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("trigger_type", sa.String(30), nullable=False, server_default="simulation"))
        batch.add_column(sa.Column("trigger_instance_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("automation_revision", sa.BigInteger(), nullable=False, server_default="0"))
        for name, default in (("trigger_snapshot", "{}"), ("action_snapshot", "{}"), ("ancestry", "[]")):
            batch.add_column(sa.Column(name, sa.JSON(), nullable=False, server_default=default))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("worker_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(60), nullable=True))
        for name in ("lease_expires_at", "next_attempt_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.create_foreign_key("fk_execution_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
        batch.create_unique_constraint("uq_automation_trigger", ["workspace_id", "workflow_id", "trigger_instance_id"])
        batch.create_index("ix_automation_due", ["status", "next_attempt_at", "lease_expires_at"])
    op.execute(sa.text("UPDATE automation_executions SET workspace_id = "
        "(SELECT workspace_id FROM automation_workflows WHERE id = automation_executions.workflow_id), created_at = started_at"))
    op.create_table("automation_schedule_state",
        sa.Column("workflow_id", sa.String(36), sa.ForeignKey("automation_workflows.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True)), sa.Column("last_run_at", sa.DateTime(timezone=True)))
    op.create_table("automation_action_receipts",
        sa.Column("execution_id", sa.String(36), sa.ForeignKey("automation_executions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("action_key", sa.String(30), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("automation_events",
        sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False), sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False), sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False), sa.Column("origin_execution_id", sa.String(36)),
        sa.Column("ancestry", sa.JSON(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("dispatched_at", sa.DateTime(timezone=True)))
    op.create_index("ix_automation_events_workspace_id", "automation_events", ["workspace_id"])
    op.create_index("ix_automation_events_dispatched_at", "automation_events", ["dispatched_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM automation_executions WHERE trigger_type != 'simulation' LIMIT 1")).first():
        raise RuntimeError("Export automation runtime before downgrading")
    for table in ("automation_events", "automation_action_receipts", "automation_schedule_state"):
        op.drop_table(table)
    with op.batch_alter_table("automation_executions") as batch:
        batch.drop_index("ix_automation_due")
        batch.drop_constraint("uq_automation_trigger", type_="unique")
        batch.drop_constraint("fk_execution_workspace", type_="foreignkey")
        for name in ("workspace_id", "trigger_type", "trigger_instance_id", "automation_revision", "trigger_snapshot",
                     "action_snapshot", "ancestry", "attempt", "worker_id", "error_code", "lease_expires_at", "next_attempt_at", "created_at"):
            batch.drop_column(name)
