"""新增知识库关键词索引与检索发布表。

Revision ID: 0004_hybrid_knowledge
Revises: 0003_workspace_isolation
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_hybrid_knowledge"
down_revision = "0003_workspace_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "ap_knowledge_chunks",
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_json", sa.JSON(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "knowledge_base_id",
            "document_id",
            "chunk_index",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_document",
        "ap_knowledge_chunks",
        ["knowledge_base_id", "document_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_knowledge_chunks_content_trgm",
            "ap_knowledge_chunks",
            ["content"],
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        )


def downgrade() -> None:
    op.drop_table("ap_knowledge_chunks")
