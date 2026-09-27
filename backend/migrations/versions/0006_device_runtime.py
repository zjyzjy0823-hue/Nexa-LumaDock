"""Device credentials and Windows runtime metadata.

Revision ID: 0006_device_runtime
Revises: 0005_persistent_pages
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_device_runtime"
down_revision = "0005_persistent_pages"
branch_labels = None
depends_on = None

COLUMNS = {
    "token_hash": sa.String(64),
    "token_last4": sa.String(4),
    "token_created_at": sa.DateTime(timezone=True),
    "hostname": sa.String(120),
    "os": sa.String(40),
    "os_version": sa.String(120),
    "architecture": sa.String(40),
    "cpu_name": sa.String(160),
    "memory_total": sa.BigInteger(),
    "memory_used": sa.BigInteger(),
    "disk_total": sa.BigInteger(),
    "disk_used": sa.BigInteger(),
    "uptime_seconds": sa.BigInteger(),
    "local_ip": sa.String(45),
    "client_version": sa.String(40),
}


def upgrade():
    existing = {column["name"] for column in inspect(op.get_bind()).get_columns("devices")}
    for name, column_type in COLUMNS.items():
        if name not in existing:
            op.add_column("devices", sa.Column(name, column_type, nullable=True))
    indexes = {index["name"] for index in inspect(op.get_bind()).get_indexes("devices")}
    if "ix_devices_token_hash" not in indexes:
        op.create_index("ix_devices_token_hash", "devices", ["token_hash"], unique=True)


def downgrade():
    op.drop_index("ix_devices_token_hash", table_name="devices")
    for name in reversed(COLUMNS):
        op.drop_column("devices", name)
