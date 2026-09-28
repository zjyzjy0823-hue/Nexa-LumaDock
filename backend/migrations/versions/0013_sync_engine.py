"""Allow a frozen outbound mutation and an editable pending tail."""

from alembic import op
import sqlalchemy as sa

revision = "0013_sync_engine"
down_revision = "0012_local_sync_queue"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("local_mutation_queue") as batch:
        batch.drop_constraint("uq_local_mutation_entity", type_="unique")
        batch.add_column(sa.Column("depends_on_mutation_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("result_revision", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("conflict_json", sa.JSON(), nullable=True))
    op.create_index("uq_local_mutation_pending_entity", "local_mutation_queue",
                    ["workspace_id", "entity_type", "entity_id"], unique=True,
                    sqlite_where=sa.text("status = 'pending'"),
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index("uq_local_mutation_frozen_entity", "local_mutation_queue",
                    ["workspace_id", "entity_type", "entity_id"], unique=True,
                    sqlite_where=sa.text("status IN ('in_flight', 'conflict', 'rejected')"),
                    postgresql_where=sa.text("status IN ('in_flight', 'conflict', 'rejected')"))


def downgrade():
    # A Phase 3 tail can coexist with its frozen predecessor. Refuse to erase it.
    connection = op.get_bind()
    duplicates = connection.execute(sa.text(
        "SELECT workspace_id, entity_type, entity_id FROM local_mutation_queue "
        "GROUP BY workspace_id, entity_type, entity_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicates is not None:
        raise RuntimeError("Resolve Phase 3 mutation tails before downgrading")
    op.drop_index("uq_local_mutation_frozen_entity", table_name="local_mutation_queue")
    op.drop_index("uq_local_mutation_pending_entity", table_name="local_mutation_queue")
    with op.batch_alter_table("local_mutation_queue") as batch:
        batch.drop_column("conflict_json")
        batch.drop_column("result_revision")
        batch.drop_column("depends_on_mutation_id")
        batch.create_unique_constraint("uq_local_mutation_entity", ["workspace_id", "entity_type", "entity_id"])
