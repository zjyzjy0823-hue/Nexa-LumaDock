"""Persistent Data, Automation, and Ledger resources. Schema snapshot for 0005_persistent_pages."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_persistent_pages"
down_revision = '0004_api_keys'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "data_collections" not in existing:
        op.create_table("data_collections",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('description', sa.String(length=500), nullable=False),
            sa.Column('icon', sa.String(length=30), nullable=False),
            sa.Column('tone', sa.String(length=30), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_data_collections_user_id', 'data_collections', ['user_id'], unique=False)
    if "data_records" not in existing:
        op.create_table("data_records",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('collection_id', sa.String(length=36), nullable=False),
            sa.Column('name', sa.String(length=160), nullable=False),
            sa.Column('status', sa.String(length=40), nullable=False),
            sa.Column('category', sa.String(length=80), nullable=False),
            sa.Column('data_json', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['collection_id'], ['data_collections.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_data_records_collection_id', 'data_records', ['collection_id'], unique=False)
    if "automation_workflows" not in existing:
        op.create_table("automation_workflows",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('description', sa.String(length=500), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('trigger_type', sa.String(length=30), nullable=False),
            sa.Column('trigger_config_json', sa.JSON(), nullable=False),
            sa.Column('workflow_json', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_automation_workflows_user_id', 'automation_workflows', ['user_id'], unique=False)
    if "automation_executions" not in existing:
        op.create_table("automation_executions",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('workflow_id', sa.String(length=36), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('message', sa.String(length=500), nullable=False),
            sa.Column('result_json', sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(['workflow_id'], ['automation_workflows.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_automation_executions_workflow_id', 'automation_executions', ['workflow_id'], unique=False)
    if "ledger_categories" not in existing:
        op.create_table("ledger_categories",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=80), nullable=False),
            sa.Column('type', sa.String(length=10), nullable=False),
            sa.Column('icon', sa.String(length=30), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_ledger_categories_user_id', 'ledger_categories', ['user_id'], unique=False)
    if "ledger_transactions" not in existing:
        op.create_table("ledger_transactions",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('category_id', sa.String(length=36), nullable=True),
            sa.Column('type', sa.String(length=10), nullable=False),
            sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
            sa.Column('description', sa.String(length=200), nullable=False),
            sa.Column('merchant', sa.String(length=120), nullable=False),
            sa.Column('note', sa.String(length=500), nullable=False),
            sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['category_id'], ['ledger_categories.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_ledger_transactions_category_id', 'ledger_transactions', ['category_id'], unique=False)
        op.create_index('ix_ledger_transactions_user_id', 'ledger_transactions', ['user_id'], unique=False)


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    if "ledger_transactions" in existing:
        op.drop_table("ledger_transactions")
    if "ledger_categories" in existing:
        op.drop_table("ledger_categories")
    if "automation_executions" in existing:
        op.drop_table("automation_executions")
    if "automation_workflows" in existing:
        op.drop_table("automation_workflows")
    if "data_records" in existing:
        op.drop_table("data_records")
    if "data_collections" in existing:
        op.drop_table("data_collections")
