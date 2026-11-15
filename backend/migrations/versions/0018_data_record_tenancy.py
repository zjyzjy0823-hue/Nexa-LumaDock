"""Tenant ownership on data records, inherited from the parent collection."""
from alembic import op
import sqlalchemy as sa

revision = "0018_data_record_tenancy"
down_revision = "0017_automation_engine"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("data_records") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("workspace_id", sa.String(36), nullable=True))

    bind = op.get_bind()
    collections = sa.table(
        "data_collections",
        sa.column("id", sa.String(36)),
        sa.column("user_id", sa.Integer()),
        sa.column("workspace_id", sa.String(36)),
    )
    records = sa.table(
        "data_records",
        sa.column("id", sa.String(36)),
        sa.column("collection_id", sa.String(36)),
        sa.column("user_id", sa.Integer()),
        sa.column("workspace_id", sa.String(36)),
    )
    for collection in bind.execute(
        sa.select(collections.c.id, collections.c.user_id, collections.c.workspace_id)
    ).all():
        bind.execute(
            sa.update(records)
            .where(records.c.collection_id == collection.id)
            .values(user_id=collection.user_id, workspace_id=collection.workspace_id)
        )

    orphans = bind.scalar(
        sa.select(sa.func.count())
        .select_from(records)
        .where(sa.or_(records.c.user_id.is_(None), records.c.workspace_id.is_(None)))
    )
    if orphans:
        raise RuntimeError(
            f"Cannot backfill data_records tenancy: {orphans} rows have no matching data_collections row"
        )

    with op.batch_alter_table("data_records") as batch:
        batch.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("workspace_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key(
            "fk_data_records_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_foreign_key(
            "fk_data_records_workspace_id_workspaces", "workspaces", ["workspace_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_data_records_workspace_id", ["workspace_id"])
        batch.create_index("ix_data_records_user_id", ["user_id"])


def downgrade():
    # Tenancy that disagrees with the parent collection cannot be recovered from
    # the parent alone; refuse to erase it silently.
    diverged = op.get_bind().execute(sa.text(
        "SELECT 1 FROM data_records r LEFT JOIN data_collections c ON c.id = r.collection_id "
        "WHERE c.id IS NULL OR c.user_id != r.user_id OR c.workspace_id != r.workspace_id LIMIT 1"
    )).first()
    if diverged is not None:
        raise RuntimeError("Data record tenancy diverges from its collection; export it before downgrading")
    with op.batch_alter_table("data_records") as batch:
        batch.drop_index("ix_data_records_user_id")
        batch.drop_index("ix_data_records_workspace_id")
        batch.drop_constraint("fk_data_records_user_id_users", type_="foreignkey")
        batch.drop_constraint("fk_data_records_workspace_id_workspaces", type_="foreignkey")
        batch.drop_column("workspace_id")
        batch.drop_column("user_id")
