"""Add isolated Shared Space tables for three-tier sharing (standard / protected / e2ee)."""

from alembic import op
import sqlalchemy as sa


revision = "0021_shared_space"
down_revision = "0020_fleet_nodes_and_blobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shared_spaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("tier", sa.String(20), nullable=False, server_default="standard"),
        sa.Column("active_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("envelope_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("password_verifier", sa.String(255), nullable=True),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("tier IN ('standard', 'protected', 'e2ee')", name="ck_shared_spaces_tier"),
    )
    op.create_index("ix_shared_spaces_user_id", "shared_spaces", ["user_id"])
    op.create_index("ix_shared_spaces_workspace_id", "shared_spaces", ["workspace_id"])
    op.create_index("ix_shared_spaces_workspace_tier", "shared_spaces", ["workspace_id", "tier"])

    op.create_table(
        "space_device_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=True),
        sa.Column("device_label", sa.String(120), nullable=False, server_default=""),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_space_device_grants_workspace_id", "space_device_grants", ["workspace_id"])
    op.create_index("ix_space_device_grants_space_id", "space_device_grants", ["space_id"])
    op.create_index("ix_space_device_grants_space_client", "space_device_grants", ["space_id", "client_id"])

    op.create_table(
        "space_key_envelopes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("envelope_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("envelope_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("space_id", "epoch", name="uq_space_key_envelopes_space_epoch"),
    )
    op.create_index("ix_space_key_envelopes_workspace_id", "space_key_envelopes", ["workspace_id"])
    op.create_index("ix_space_key_envelopes_space_id", "space_key_envelopes", ["space_id"])

    op.create_table(
        "space_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active_epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("mime", sa.String(120), nullable=False, server_default="text/plain"),
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("entry_type IN ('text', 'config', 'key', 'file')", name="ck_space_entries_type"),
    )
    op.create_index("ix_space_entries_workspace_id", "space_entries", ["workspace_id"])
    op.create_index("ix_space_entries_space_id", "space_entries", ["space_id"])
    op.create_index("ix_space_entries_space_deleted", "space_entries", ["space_id", "deleted_at"])

    op.create_table(
        "space_blobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("total_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("chunks_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_space_blobs_workspace_id", "space_blobs", ["workspace_id"])
    op.create_index("ix_space_blobs_space_id", "space_blobs", ["space_id"])
    op.create_index("ix_space_blobs_space_committed", "space_blobs", ["space_id", "committed_at"])

    op.create_table(
        "space_entry_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("space_entries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("wrapped_dek_json", sa.JSON(), nullable=True),
        sa.Column("encrypted_manifest_b64", sa.Text(), nullable=True),
        sa.Column("plaintext_text", sa.Text(), nullable=True),
        sa.Column("blob_id", sa.String(36), sa.ForeignKey("space_blobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="2097152"),
        sa.Column("ciphertext_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("plaintext_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("is_conflict", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("base_revision", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entry_id", "revision", name="uq_space_entry_revisions_entry_rev"),
    )
    op.create_index("ix_space_entry_revisions_workspace_id", "space_entry_revisions", ["workspace_id"])
    op.create_index("ix_space_entry_revisions_space_id", "space_entry_revisions", ["space_id"])
    op.create_index("ix_space_entry_revisions_entry_id", "space_entry_revisions", ["entry_id"])
    op.create_index("ix_space_entry_revisions_space_entry", "space_entry_revisions", ["space_id", "entry_id"])

    op.create_table(
        "space_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_last4", sa.String(4), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False, server_default=sa.text("'[\"read\"]'")),
        sa.Column("entry_ids_json", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("token_kind IN ('standard', 'vault')", name="ck_space_tokens_kind"),
    )
    op.create_index("ix_space_tokens_user_id", "space_tokens", ["user_id"])
    op.create_index("ix_space_tokens_workspace_id", "space_tokens", ["workspace_id"])
    op.create_index("ix_space_tokens_space_id", "space_tokens", ["space_id"])
    op.create_index("ix_space_tokens_token_hash", "space_tokens", ["token_hash"], unique=True)
    op.create_index("ix_space_tokens_space_revoked", "space_tokens", ["space_id", "revoked_at"])

    op.create_table(
        "space_access_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=True),
        sa.Column("actor_kind", sa.String(24), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False, server_default="allowed"),
        sa.Column("detail", sa.String(240), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_space_access_audit_logs_workspace_id", "space_access_audit_logs", ["workspace_id"])
    op.create_index("ix_space_access_audit_logs_space_id", "space_access_audit_logs", ["space_id"])
    op.create_index("ix_space_audit_space_created", "space_access_audit_logs", ["space_id", "created_at"])

    op.create_table(
        "space_changes",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("epoch", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("change_type", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_space_changes_workspace_id", "space_changes", ["workspace_id"])
    op.create_index("ix_space_changes_space_id", "space_changes", ["space_id"])
    op.create_index("ix_space_changes_space_seq", "space_changes", ["space_id", "seq"])

    op.create_table(
        "space_mutation_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", sa.String(36), sa.ForeignKey("shared_spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mutation_id", sa.String(64), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "space_id", "mutation_id", name="uq_space_mutation_receipts_key"),
    )
    op.create_index("ix_space_mutation_receipts_workspace_id", "space_mutation_receipts", ["workspace_id"])
    op.create_index("ix_space_mutation_receipts_space_id", "space_mutation_receipts", ["space_id"])


def downgrade():
    op.drop_table("space_mutation_receipts")
    op.drop_table("space_changes")
    op.drop_table("space_access_audit_logs")
    op.drop_table("space_tokens")
    op.drop_table("space_entry_revisions")
    op.drop_table("space_blobs")
    op.drop_table("space_entries")
    op.drop_table("space_key_envelopes")
    op.drop_table("space_device_grants")
    op.drop_table("shared_spaces")
