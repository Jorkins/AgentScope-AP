"""新增工作区归属及 Agent 工具白名单。

Revision ID: 0003_workspace_isolation
Revises: 0002_share_uniqueness
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_workspace_isolation"
down_revision = "0002_share_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ap_workspace_bindings",
        sa.Column("workspace_id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("backend", sa.String(length=32), nullable=False),
        sa.Column("container_name", sa.String(length=255), nullable=True),
        sa.Column("host_path", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "agent_id", name="uq_workspace_owner_agent"),
        sa.UniqueConstraint("container_name", name="uq_workspace_container_name"),
    )
    op.create_index(
        "ix_workspace_owner_id",
        "ap_workspace_bindings",
        ["owner_id"],
    )
    op.create_index(
        "ix_workspace_agent_id",
        "ap_workspace_bindings",
        ["agent_id"],
    )
    op.create_table(
        "ap_agent_tool_bindings",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("resource_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "agent_id",
            "kind",
            "resource_name",
            name="uq_agent_tool_binding",
        ),
        sa.CheckConstraint(
            "kind IN ('skill', 'mcp')",
            name="ck_agent_tool_binding_kind",
        ),
    )
    op.create_index(
        "ix_agent_tool_user_id",
        "ap_agent_tool_bindings",
        ["user_id"],
    )
    op.create_index(
        "ix_agent_tool_agent_id",
        "ap_agent_tool_bindings",
        ["agent_id"],
    )


def downgrade() -> None:
    op.drop_table("ap_agent_tool_bindings")
    op.drop_table("ap_workspace_bindings")
