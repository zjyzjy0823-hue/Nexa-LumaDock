"""Persist measured Fleet token usage by workspace."""

from alembic import op
import sqlalchemy as sa


revision = "0022_fleet_usage"
down_revision = "0021_shared_space"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fleet_usage_samples",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_key", sa.String(64), nullable=False),
        sa.Column("whole_turn", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("cached", sa.BigInteger(), nullable=False),
        sa.Column("other_input", sa.BigInteger(), nullable=False),
        sa.Column("output", sa.BigInteger(), nullable=False),
        sa.Column("other", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_fleet_usage_workspace_time", "fleet_usage_samples", ["workspace_id", "recorded_at"])
    op.create_index("ix_fleet_usage_workspace_turn", "fleet_usage_samples", ["workspace_id", "turn_key"])


def downgrade():
    op.drop_table("fleet_usage_samples")
