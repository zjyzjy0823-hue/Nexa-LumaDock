"""Website/Data tombstones and extensible bootstrap generations."""
from alembic import op
import sqlalchemy as sa

revision = "0014_multi_entity_sync"
down_revision = "0013_sync_engine"
branch_labels = None
depends_on = None

TABLES = ("website_categories", "websites", "data_collections", "data_records")


def upgrade():
    for name in TABLES:
        with op.batch_alter_table(name) as batch:
            batch.add_column(sa.Column("sync_revision", sa.BigInteger(), nullable=False, server_default="0"))
            batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    for table, column, marker in (
        ("local_sync_state", "queue_seed_version", "queue_seeded_at"),
        ("sync_workspace_state", "bootstrap_version", "initialized_at"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column(column, sa.Integer(), nullable=False, server_default="0"))
        op.execute(sa.text(f"UPDATE {table} SET {column} = 1 WHERE {marker} IS NOT NULL"))


def downgrade():
    # Protocol v1 cannot consume a history containing Website/Data revisions.
    connection = op.get_bind()
    for table in ("sync_changes", "sync_mutations", "local_mutation_queue"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} WHERE entity_type NOT IN "
                "('ledger.category', 'ledger.transaction') LIMIT 1")).first():
            raise RuntimeError("Multi-entity history must be exported before downgrading")
    for name in TABLES:
        if connection.execute(sa.text(f"SELECT 1 FROM {name} WHERE deleted_at IS NOT NULL LIMIT 1")).first():
            raise RuntimeError("Multi-entity tombstones must be exported before downgrading")
    for table, column in (("local_sync_state", "queue_seed_version"),
                          ("sync_workspace_state", "bootstrap_version")):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)
    for name in reversed(TABLES):
        with op.batch_alter_table(name) as batch:
            batch.drop_column("deleted_at")
            batch.drop_column("sync_revision")
