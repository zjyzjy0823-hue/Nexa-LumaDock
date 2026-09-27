"""Record the most recent visit to each website."""

from alembic import op
from sqlalchemy import Column, DateTime, inspect

revision = "0002_website_visits"
down_revision = "0001_websites"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("websites")}
    if "last_visited_at" not in columns:
        with op.batch_alter_table("websites") as batch:
            batch.add_column(Column("last_visited_at", DateTime(timezone=True), nullable=True))


def downgrade():
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("websites")}
    if "last_visited_at" in columns:
        with op.batch_alter_table("websites") as batch:
            batch.drop_column("last_visited_at")
