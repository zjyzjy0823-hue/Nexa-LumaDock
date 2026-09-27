"""Persistent devices, agents, tasks and events. Schema snapshot for 0003_devices_agents."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_devices_agents"
down_revision = '0002_website_visits'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "devices" not in existing:
        op.create_table("devices",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('system', sa.String(length=120), nullable=False),
            sa.Column('kind', sa.String(length=20), nullable=False),
            sa.Column('ip', sa.String(length=120), nullable=False),
            sa.Column('location', sa.String(length=120), nullable=False),
            sa.Column('cpu', sa.Integer(), nullable=False),
            sa.Column('memory', sa.Integer(), nullable=False),
            sa.Column('disk', sa.Integer(), nullable=False),
            sa.Column('battery', sa.Integer(), nullable=True),
            sa.Column('activity_json', sa.JSON(), nullable=False),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_devices_user_id', 'devices', ['user_id'], unique=False)
    if "agents" not in existing:
        op.create_table("agents",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('role', sa.String(length=120), nullable=False),
            sa.Column('description', sa.String(length=500), nullable=False),
            sa.Column('model', sa.String(length=120), nullable=False),
            sa.Column('workspace', sa.String(length=120), nullable=False),
            sa.Column('avatar', sa.String(length=20), nullable=False),
            sa.Column('enabled', sa.Boolean(), nullable=False),
            sa.Column('runtime_status', sa.String(length=20), nullable=False),
            sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_agents_user_id', 'agents', ['user_id'], unique=False)
    if "agent_tasks" not in existing:
        op.create_table("agent_tasks",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('agent_id', sa.String(length=36), nullable=False),
            sa.Column('title', sa.String(length=160), nullable=False),
            sa.Column('description', sa.String(length=500), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_agent_tasks_agent_id', 'agent_tasks', ['agent_id'], unique=False)
    if "agent_events" not in existing:
        op.create_table("agent_events",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('agent_id', sa.String(length=36), nullable=False),
            sa.Column('level', sa.String(length=20), nullable=False),
            sa.Column('message', sa.String(length=500), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_agent_events_agent_id', 'agent_events', ['agent_id'], unique=False)


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    if "agent_events" in existing:
        op.drop_table("agent_events")
    if "agent_tasks" in existing:
        op.drop_table("agent_tasks")
    if "agents" in existing:
        op.drop_table("agents")
    if "devices" in existing:
        op.drop_table("devices")
