"""Persistent devices, agents, tasks and events."""

from alembic import op
from sqlalchemy import inspect

from app.database import Base
from app import models  # noqa: F401

revision = "0003_devices_agents"
down_revision = "0002_website_visits"
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade():
    for name in ("agent_events", "agent_tasks", "agents", "devices"):
        if name in inspect(op.get_bind()).get_table_names():
            op.drop_table(name)
