"""Persist standard-space conflict candidates for Core decisions."""

from alembic import op
import sqlalchemy as sa


revision = "0023_space_sync_candidates"
down_revision = "0022_fleet_usage"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "space_sync_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("space_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mutation_id", sa.String(36), nullable=False),
        sa.Column("base_revision", sa.Integer, nullable=False),
        sa.Column("device_label", sa.String(120), nullable=False),
        sa.Column("operation", sa.String(12), nullable=False),
        sa.Column("edited_fields", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(12), nullable=True),
        sa.Column("result_revision", sa.Integer, nullable=True),
        sa.UniqueConstraint("space_id", "mutation_id", name="uq_space_sync_candidate_mutation"),
    )
    op.create_index("ix_space_sync_candidates_space_pending", "space_sync_candidates", ["space_id", "resolved_at"])


def downgrade():
    op.drop_table("space_sync_candidates")
