"""平台基础表与分享去重索引。

Revision ID: 0001_platform_baseline
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_platform_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ap_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_ap_users_username", "ap_users", ["username"], unique=True)

    op.create_table(
        "ap_tenants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("is_personal", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ap_tenants_owner_id", "ap_tenants", ["owner_id"])

    op.create_table(
        "ap_memberships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["ap_tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "username", name="uq_member"),
    )
    op.create_index("ix_ap_memberships_tenant_id", "ap_memberships", ["tenant_id"])
    op.create_index("ix_ap_memberships_username", "ap_memberships", ["username"])

    op.create_table(
        "ap_resource_shares",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("grantee_tenant_id", sa.BigInteger(), nullable=True),
        sa.Column("grantee_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grantee_tenant_id"], ["ap_tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ap_resource_shares_kind", "ap_resource_shares", ["kind"])
    op.create_index("ix_ap_resource_shares_owner_id", "ap_resource_shares", ["owner_id"])
    op.create_index("ix_ap_resource_shares_resource_id", "ap_resource_shares", ["resource_id"])


def downgrade() -> None:
    op.drop_table("ap_resource_shares")
    op.drop_table("ap_memberships")
    op.drop_table("ap_tenants")
    op.drop_table("ap_users")
