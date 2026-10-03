"""Personal state metadata; retain local numeric singleton row IDs."""
from alembic import op
import sqlalchemy as sa

revision = "0016_personal_state_sync"
down_revision = "0015_agent_data_actions"
branch_labels = None
depends_on = None
TABLES = ("user_preferences", "dashboards", "automation_workflows")


def upgrade():
    with op.batch_alter_table("user_preferences") as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute(sa.text("UPDATE user_preferences SET workspace_id = "
        "(SELECT id FROM workspaces WHERE owner_user_id = user_preferences.user_id AND kind = 'personal')"))
    with op.batch_alter_table("user_preferences") as batch:
        batch.alter_column("workspace_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key("fk_preferences_workspace", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_user_preferences_workspace_id", ["workspace_id"])
    for name in TABLES:
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("sync_revision", sa.BigInteger(), nullable=False, server_default="0"))
            batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    connection = op.get_bind()
    for name in ("sync_changes", "sync_mutations", "local_mutation_queue"):
        if connection.execute(sa.text(f"SELECT 1 FROM {name} WHERE entity_type IN "
                "('user.preferences', 'dashboard.layout', 'automation.definition') LIMIT 1")).first():
            raise RuntimeError("Personal state history must be exported before downgrading")
    for name in TABLES:
        if connection.execute(sa.text(f"SELECT 1 FROM {name} WHERE sync_revision > 0 OR deleted_at IS NOT NULL LIMIT 1")).first():
            raise RuntimeError("Personal state revisions/tombstones must be exported before downgrading")
    for name in reversed(TABLES):
        with op.batch_alter_table(name) as batch:
            batch.drop_column("deleted_at")
            batch.drop_column("sync_revision")
    with op.batch_alter_table("user_preferences") as batch:
        batch.drop_index("ix_user_preferences_workspace_id")
        batch.drop_constraint("fk_preferences_workspace", type_="foreignkey")
        batch.drop_column("workspace_id")
        batch.drop_column("updated_at")
        batch.drop_column("created_at")
