"""平台自有 ORM 表（`ap_` 前缀）。

与 AgentScope 内核表同库不同表，互不侵入。用户身份 = username，
与前端 `X-User-ID` 保持一致。
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "ap_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Tenant(Base):
    __tablename__ = "ap_tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(64), index=True)  # username
    is_personal: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Membership(Base):
    __tablename__ = "ap_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "username", name="uq_member"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("ap_tenants.id"), index=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")  # owner/admin/member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResourceShare(Base):
    """资源共享：把某 owner 的资源授权给某租户或某用户。"""

    __tablename__ = "ap_resource_shares"
    __table_args__ = (
        Index(
            "uq_share_user_grantee",
            "kind",
            "owner_id",
            "resource_id",
            "grantee_user_id",
            unique=True,
            postgresql_where=text("grantee_user_id IS NOT NULL"),
            sqlite_where=text("grantee_user_id IS NOT NULL"),
        ),
        Index(
            "uq_share_tenant_grantee",
            "kind",
            "owner_id",
            "resource_id",
            "grantee_tenant_id",
            unique=True,
            postgresql_where=text("grantee_tenant_id IS NOT NULL"),
            sqlite_where=text("grantee_tenant_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)  # credential/agent/knowledge_base
    owner_id: Mapped[str] = mapped_column(String(64), index=True)  # 资源主人 username
    resource_id: Mapped[str] = mapped_column(String(128), index=True)
    permission: Mapped[str] = mapped_column(String(16), default="read")  # read/edit
    grantee_tenant_id: Mapped[int | None] = mapped_column(ForeignKey("ap_tenants.id"), nullable=True)
    grantee_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class WorkspaceBinding(Base):
    """工作区的权威归属，显式 legacy ID 必须先登记才能使用。"""

    __tablename__ = "ap_workspace_bindings"
    __table_args__ = (
        UniqueConstraint("owner_id", "agent_id", name="uq_workspace_owner_agent"),
    )

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    backend: Mapped[str] = mapped_column(String(32))
    container_name: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )
    host_path: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32), default="creating")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentToolBinding(Base):
    """用户自己的 Agent 对 Skill/MCP 的启用白名单。"""

    __tablename__ = "ap_agent_tool_bindings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "agent_id",
            "kind",
            "resource_name",
            name="uq_agent_tool_binding",
        ),
        CheckConstraint(
            "kind IN ('skill', 'mcp')",
            name="ck_agent_tool_binding_kind",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    resource_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class KnowledgeChunk(Base):
    """向量检索与关键词检索共用的已发布 chunk 记录。"""

    __tablename__ = "ap_knowledge_chunks"
    __table_args__ = (
        Index(
            "ix_knowledge_chunks_document",
            "knowledge_base_id",
            "document_id",
        ),
        Index(
            "ix_knowledge_chunks_content_trgm",
            "content",
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        ),
    )

    knowledge_base_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_json: Mapped[dict] = mapped_column(JSON)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


async def init_platform_tables(engine: AsyncEngine) -> None:
    """建平台表（不存在则创建）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
