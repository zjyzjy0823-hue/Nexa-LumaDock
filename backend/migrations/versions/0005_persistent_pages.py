"""Persistent Data, Automation, and Ledger resources.

Revision ID: 0005_persistent_pages
Revises: 0004_api_keys
"""
from alembic import op
from sqlalchemy import inspect
from app.database import Base
from app import models  # noqa: F401

revision = "0005_persistent_pages"
down_revision = "0004_api_keys"
branch_labels = None
depends_on = None

TABLES = (
    "data_collections", "data_records", "automation_workflows",
    "automation_executions", "ledger_categories", "ledger_transactions",
)


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for name in TABLES:
        if name not in existing:
            Base.metadata.tables[name].create(bind=bind)


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    for name in reversed(TABLES):
        if name in existing:
            op.drop_table(name)
