"""为旧平台表补充分享授权唯一索引。

Revision ID: 0002_share_uniqueness
Revises: 0001_platform_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_share_uniqueness"
down_revision = "0001_platform_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_share_user_grantee",
        "ap_resource_shares",
        ["kind", "owner_id", "resource_id", "grantee_user_id"],
        unique=True,
        postgresql_where=sa.text("grantee_user_id IS NOT NULL"),
        sqlite_where=sa.text("grantee_user_id IS NOT NULL"),
        if_not_exists=True,
    )
    op.create_index(
        "uq_share_tenant_grantee",
        "ap_resource_shares",
        ["kind", "owner_id", "resource_id", "grantee_tenant_id"],
        unique=True,
        postgresql_where=sa.text("grantee_tenant_id IS NOT NULL"),
        sqlite_where=sa.text("grantee_tenant_id IS NOT NULL"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("uq_share_tenant_grantee", table_name="ap_resource_shares")
    op.drop_index("uq_share_user_grantee", table_name="ap_resource_shares")
