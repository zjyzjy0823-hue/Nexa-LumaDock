"""Add persistent websites and preferences to the existing Nexa schema.

Revision ID: 0001_websites
Revises:
"""
from alembic import op
from sqlalchemy import inspect, text
from app.database import Base
from app import models  # noqa: F401

revision = "0001_websites"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "users" in existing and "updated_at" not in {column["name"] for column in inspect(bind).get_columns("users")}:
        with op.batch_alter_table("users") as batch:
            batch.add_column(__import__("sqlalchemy").Column("updated_at", __import__("sqlalchemy").DateTime(timezone=True), nullable=True))
        bind.execute(text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))
    Base.metadata.create_all(bind=bind)


def downgrade():
    for name in ("user_preferences", "websites", "website_categories"):
        if name in inspect(op.get_bind()).get_table_names():
            op.drop_table(name)
