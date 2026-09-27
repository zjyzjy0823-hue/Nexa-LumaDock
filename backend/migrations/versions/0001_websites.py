"""Add persistent websites and preferences. Schema snapshot for 0001_websites."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "0001_websites"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    if "users" in existing and "updated_at" not in {column["name"] for column in inspect(bind).get_columns("users")}:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        bind.execute(text("UPDATE users SET updated_at = created_at WHERE updated_at IS NULL"))
    if "users" not in existing:
        op.create_table("users",
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('username', sa.String(length=80), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=False),
            sa.Column('password_hash', sa.String(length=255), nullable=False),
            sa.Column('avatar', sa.String(length=500), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index('ix_users_email', 'users', ['email'], unique=True)
        op.create_index('ix_users_username', 'users', ['username'], unique=True)
    if "dashboards" not in existing:
        op.create_table("dashboards",
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('layout_json', sa.JSON(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('user_id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_dashboards_user_id', 'dashboards', ['user_id'], unique=False)
    if "website_categories" not in existing:
        op.create_table("website_categories",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=80), nullable=False),
            sa.Column('order', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_website_categories_user_id', 'website_categories', ['user_id'], unique=False)
    if "websites" not in existing:
        op.create_table("websites",
            sa.Column('id', sa.String(length=36), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('category_id', sa.String(length=36), nullable=True),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('url', sa.String(length=2048), nullable=False),
            sa.Column('icon', sa.String(length=500), nullable=True),
            sa.Column('description', sa.String(length=500), nullable=True),
            sa.Column('favorite', sa.Boolean(), nullable=False),
            sa.Column('order', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['category_id'], ['website_categories.id'], ondelete='SET NULL'),
        )
        op.create_index('ix_websites_category_id', 'websites', ['category_id'], unique=False)
        op.create_index('ix_websites_user_id', 'websites', ['user_id'], unique=False)
    if "user_preferences" not in existing:
        op.create_table("user_preferences",
            sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('theme', sa.String(length=30), nullable=False),
            sa.Column('language', sa.String(length=20), nullable=False),
            sa.Column('timezone', sa.String(length=80), nullable=False),
            sa.Column('settings_json', sa.JSON(), nullable=False),
            sa.UniqueConstraint('user_id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )
        op.create_index('ix_user_preferences_user_id', 'user_preferences', ['user_id'], unique=False)


def downgrade():
    existing = set(inspect(op.get_bind()).get_table_names())
    if "user_preferences" in existing:
        op.drop_table("user_preferences")
    if "websites" in existing:
        op.drop_table("websites")
    if "website_categories" in existing:
        op.drop_table("website_categories")
