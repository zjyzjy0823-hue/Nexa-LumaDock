"""Store per-user API Key digests."""

from alembic import op
from sqlalchemy import inspect

from app.database import Base
from app import models  # noqa: F401

revision = "0004_api_keys"
down_revision = "0003_devices_agents"
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.tables["api_keys"].create(bind=op.get_bind(), checkfirst=True)


def downgrade():
    if "api_keys" in inspect(op.get_bind()).get_table_names():
        op.drop_table("api_keys")
