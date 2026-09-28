"""Add personal workspaces, workspace ownership, and client identities."""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0009_workspace_clients"
down_revision = "0008_agent_runtime"
branch_labels = None
depends_on = None


RESOURCE_TABLES = (
    "dashboards",
    "website_categories",
    "websites",
    "devices",
    "agents",
    "data_collections",
    "automation_workflows",
    "ledger_categories",
    "ledger_transactions",
)


def upgrade():
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])
    op.create_table(
        "clients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("app_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "installation_id"),
    )
    op.create_index("ix_clients_workspace_id", "clients", ["workspace_id"])

    for table_name in RESOURCE_TABLES:
        op.add_column(table_name, sa.Column("workspace_id", sa.String(36), nullable=True))

    bind = op.get_bind()
    users = sa.table("users", sa.column("id", sa.Integer()))
    workspaces = sa.table(
        "workspaces", sa.column("id", sa.String(36)), sa.column("owner_user_id", sa.Integer()),
        sa.column("name", sa.String(120)), sa.column("kind", sa.String(30)),
        sa.column("created_at", sa.DateTime(timezone=True)), sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    resources = {
        name: sa.table(name, sa.column("user_id", sa.Integer()), sa.column("workspace_id", sa.String(36)))
        for name in RESOURCE_TABLES
    }
    now = datetime.now(timezone.utc)
    for user_id in bind.execute(sa.select(users.c.id)).scalars():
        workspace_id = str(uuid4())
        bind.execute(sa.insert(workspaces).values(
            id=workspace_id, owner_user_id=user_id, name="个人工作区", kind="personal",
            created_at=now, updated_at=now,
        ))
        for resource in resources.values():
            bind.execute(sa.update(resource).where(resource.c.user_id == user_id).values(workspace_id=workspace_id))

    for name, resource in resources.items():
        missing = bind.scalar(sa.select(sa.func.count()).select_from(resource).where(resource.c.workspace_id.is_(None)))
        if missing:
            raise RuntimeError(f"Cannot backfill {name}.workspace_id: {missing} rows have no matching user")
        with op.batch_alter_table(name) as batch:
            batch.alter_column("workspace_id", existing_type=sa.String(36), nullable=False)
            batch.create_foreign_key(f"fk_{name}_workspace_id_workspaces", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
            batch.create_index(f"ix_{name}_workspace_id", ["workspace_id"])


def downgrade():
    for name in reversed(RESOURCE_TABLES):
        with op.batch_alter_table(name) as batch:
            batch.drop_index(f"ix_{name}_workspace_id")
            batch.drop_constraint(f"fk_{name}_workspace_id_workspaces", type_="foreignkey")
            batch.drop_column("workspace_id")
    op.drop_index("ix_clients_workspace_id", table_name="clients")
    op.drop_table("clients")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_table("workspaces")
