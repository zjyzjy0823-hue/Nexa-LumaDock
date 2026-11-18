"""Add agent_nodes and encrypted_blobs metadata tables for multi-device fleet and encrypted transfer."""
from alembic import op
import sqlalchemy as sa

revision = "0020_fleet_nodes_and_blobs"
down_revision = "0019_local_automation_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False, server_default="windows"),
        sa.Column("hostname", sa.String(120), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("token_last4", sa.String(4), nullable=True),
        sa.Column("token_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allowed_roots_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("adapters_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("transfer_endpoints_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("runtime_status", sa.String(20), nullable=False, server_default="offline"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_nodes_user_id", "agent_nodes", ["user_id"])
    op.create_index("ix_agent_nodes_workspace_id", "agent_nodes", ["workspace_id"])
    op.create_index("ix_agent_nodes_token_hash", "agent_nodes", ["token_hash"], unique=True)

    op.create_table(
        "encrypted_blobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_kind", sa.String(20), nullable=False, server_default="user"),
        sa.Column("uploader_id", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False, server_default="fleet_artifact"),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("ciphertext_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("storage_role", sa.String(24), nullable=False, server_default="core"),
        sa.Column("storage_location", sa.String(500), nullable=False, server_default=""),
        sa.Column("manifest_json", sa.JSON(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_encrypted_blobs_user_id", "encrypted_blobs", ["user_id"])
    op.create_index("ix_encrypted_blobs_workspace_id", "encrypted_blobs", ["workspace_id"])
    op.create_index("ix_encrypted_blobs_digest", "encrypted_blobs", ["digest"])
    op.create_index("ix_encrypted_blobs_workspace_purpose", "encrypted_blobs", ["workspace_id", "purpose", "expires_at"])


def downgrade():
    op.drop_table("encrypted_blobs")
    op.drop_table("agent_nodes")
