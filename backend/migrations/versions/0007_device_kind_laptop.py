"""Normalize the legacy device shape name mac to laptop."""

from alembic import op
import sqlalchemy as sa

revision = "0007_device_kind_laptop"
down_revision = "0006_device_runtime"
branch_labels = None
depends_on = None


def upgrade():
    devices = sa.table("devices", sa.column("kind", sa.String(20)))
    op.execute(devices.update().where(devices.c.kind == "mac").values(kind="laptop"))


def downgrade():
    devices = sa.table("devices", sa.column("kind", sa.String(20)))
    op.execute(devices.update().where(devices.c.kind == "laptop").values(kind="mac"))
