"""PostgreSQL 关键词索引与向量检索的 AP 混合检索包装。"""

from collections.abc import Iterable

from agentscope.app.rag import CollectionPerKbManager
from agentscope.message import DataBlock, TextBlock
from agentscope.rag import Chunk, KnowledgeBase, VectorSearchResult
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import KnowledgeChunk

_RRF_K = 60


def _text_content(content: TextBlock | DataBlock) -> str:
    if not isinstance(content, TextBlock):
        return ""
    return content.text


def _query_text(query: str | TextBlock | DataBlock) -> str:
    if isinstance(query, str):
        return query.strip()
    return _text_content(query).strip()


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class KnowledgeChunkStore:
    """以发布表约束检索可见性，并提供 PostgreSQL pg_trgm 关键词查询。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def publish_document(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
        chunks: Iterable[Chunk],
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                    KnowledgeChunk.document_id == document_id,
                )
            )
            session.add_all(
                [
                    KnowledgeChunk(
                        knowledge_base_id=knowledge_base_id,
                        document_id=document_id,
                        chunk_index=chunk.chunk_index,
                        chunk_json=chunk.model_dump(mode="json"),
                        content=_text_content(chunk.content),
                    )
                    for chunk in chunks
                ]
            )
            await session.commit()

    async def unpublish_document(
        self,
        *,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                    KnowledgeChunk.document_id == document_id,
                )
            )
            await session.commit()

    async def unpublish_knowledge_base(self, *, knowledge_base_id: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(KnowledgeChunk).where(
                    KnowledgeChunk.knowledge_base_id == knowledge_base_id
                )
            )
            await session.commit()

    async def published_keys(
        self,
        *,
        knowledge_base_id: str,
        results: list[VectorSearchResult],
    ) -> set[tuple[str, int]]:
        document_ids = {result.document_id for result in results}
        if not document_ids:
            return set()
        async with self._session_factory() as session:
            rows = await session.execute(
                select(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index).where(
                    KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                    KnowledgeChunk.document_id.in_(document_ids),
                )
            )
            return {(document_id, chunk_index) for document_id, chunk_index in rows}

    async def keyword_search(
        self,
        *,
        knowledge_base_id: str,
        query: str,
        limit: int,
    ) -> list[VectorSearchResult]:
        if not query:
            return []
        async with self._session_factory() as session:
            pattern = _like_pattern(query)
            if session.bind.dialect.name == "postgresql":
                rank = func.similarity(KnowledgeChunk.content, query)
                matches = or_(
                    KnowledgeChunk.content.op("%")(query),
                    KnowledgeChunk.content.ilike(pattern, escape="\\"),
                )
            else:
                # SQLite 仅用于隔离单元测试；生产查询始终使用上面的 pg_trgm。
                rank = func.instr(KnowledgeChunk.content, query)
                matches = KnowledgeChunk.content.ilike(pattern, escape="\\")
            rows = await session.execute(
                select(KnowledgeChunk, rank)
                .where(
                    KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                    matches,
                )
                .order_by(
                    rank.desc(),
                    KnowledgeChunk.document_id,
                    KnowledgeChunk.chunk_index,
                )
                .limit(limit)
            )
            return [
                VectorSearchResult(
                    score=float(score or 0),
                    document_id=row.document_id,
                    chunk=Chunk.model_validate(row.chunk_json),
                )
                for row, score in rows
            ]


class HybridKnowledgeBase(KnowledgeBase):
    """向量先写入、PostgreSQL 后发布；删除时先撤发布再删向量。"""

    def __init__(
        self,
        *,
        knowledge_base_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._knowledge_base_id = knowledge_base_id
        self._chunks = KnowledgeChunkStore(session_factory)

    async def insert_document(
        self,
        chunks: list[Chunk],
        document_id: str | None = None,
        document_metadata: dict | None = None,
    ) -> str:
        resolved_id = await super().insert_document(
            chunks=chunks,
            document_id=document_id,
            document_metadata=document_metadata,
        )
        published_chunks = [
            chunk.model_copy(
                update={
                    "metadata": {
                        **(document_metadata or {}),
                        **chunk.metadata,
                        **(self._metadata_filter or {}),
                    }
                }
            )
            for chunk in chunks
        ]
        await self._chunks.publish_document(
            knowledge_base_id=self._knowledge_base_id,
            document_id=resolved_id,
            chunks=published_chunks,
        )
        return resolved_id

    async def delete_document(self, document_id: str) -> None:
        await self._chunks.unpublish_document(
            knowledge_base_id=self._knowledge_base_id,
            document_id=document_id,
        )
        await super().delete_document(document_id)

    async def _published_semantic_search(
        self,
        queries: list[str | TextBlock | DataBlock],
        *,
        top_k: int,
        score_threshold: float | None,
    ) -> list[VectorSearchResult]:
        results = await super().search(
            queries=queries,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        published = await self._chunks.published_keys(
            knowledge_base_id=self._knowledge_base_id,
            results=results,
        )
        return [
            result
            for result in results
            if (result.document_id, result.chunk.chunk_index) in published
        ]

    async def _keyword_search(
        self,
        queries: list[str | TextBlock | DataBlock],
        *,
        top_k: int,
    ) -> list[VectorSearchResult]:
        best: dict[tuple[str, int], VectorSearchResult] = {}
        for query in queries:
            text = _query_text(query)
            if not text:
                continue
            for result in await self._chunks.keyword_search(
                knowledge_base_id=self._knowledge_base_id,
                query=text,
                limit=top_k,
            ):
                key = (result.document_id, result.chunk.chunk_index)
                if key not in best or result.score > best[key].score:
                    best[key] = result
        return sorted(best.values(), key=lambda result: result.score, reverse=True)[:top_k]

    @staticmethod
    def _rrf(
        rankings: list[list[VectorSearchResult]],
        *,
        top_k: int,
    ) -> list[VectorSearchResult]:
        scores: dict[tuple[str, int], float] = {}
        best: dict[tuple[str, int], VectorSearchResult] = {}
        for ranking in rankings:
            for rank, result in enumerate(ranking, start=1):
                key = (result.document_id, result.chunk.chunk_index)
                scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank)
                best.setdefault(key, result)
        ordered = sorted(
            best,
            key=lambda key: scores[key],
            reverse=True,
        )
        return [
            best[key].model_copy(update={"score": scores[key]}) for key in ordered[:top_k]
        ]

    async def search(
        self,
        queries: list[str | TextBlock | DataBlock],
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        candidate_k = max(top_k, min(50, top_k * 4))
        semantic = await self._published_semantic_search(
            queries,
            top_k=candidate_k,
            score_threshold=score_threshold,
        )
        keyword = await self._keyword_search(queries, top_k=candidate_k)
        return self._rrf([semantic, keyword], top_k=top_k)


class HybridKnowledgeBaseManager(CollectionPerKbManager):
    """让 UI 检索和 Agent RAG 共用同一个混合检索实现。"""

    def __init__(
        self,
        storage,
        vector_store,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(storage, vector_store)
        self._session_factory = session_factory

    async def get_knowledge(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> HybridKnowledgeBase:
        knowledge = await super().get_knowledge(user_id, knowledge_base_id)
        return HybridKnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            session_factory=self._session_factory,
            name=knowledge.name,
            description=knowledge.description,
            embedding_model=knowledge.embedding_model,
            vector_store=knowledge.vector_store,
            collection=knowledge.collection,
            metadata_filter=knowledge.metadata_filter,
        )

    async def delete_knowledge_base(
        self,
        user_id: str,
        knowledge_base_id: str,
    ) -> bool:
        deleted = await super().delete_knowledge_base(user_id, knowledge_base_id)
        if deleted:
            await KnowledgeChunkStore(self._session_factory).unpublish_knowledge_base(
                knowledge_base_id=knowledge_base_id
            )
        return deleted
