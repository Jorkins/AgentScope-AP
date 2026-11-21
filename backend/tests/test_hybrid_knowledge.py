from types import SimpleNamespace

import pytest
import pytest_asyncio
from agentscope.rag import Chunk, VectorSearchResult
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.platform.hybrid_knowledge import HybridKnowledgeBase
from app.platform.models import Base, KnowledgeChunk


class FakeEmbeddingModel:
    dimensions = 2
    supports_multimodal = False

    async def __call__(self, inputs):
        embeddings = []
        for item in inputs:
            text = item if isinstance(item, str) else getattr(item, "text", "")
            embeddings.append([1.0, 0.0] if "semantic" in text else [0.9, 0.0])
        return SimpleNamespace(embeddings=embeddings)


class FakeVectorStore:
    def __init__(self):
        self.collections = set()
        self.records = {}
        self.fail_delete = False

    async def has_collection(self, name):
        return name in self.collections

    async def create_collection(self, name, dimensions):
        del dimensions
        self.collections.add(name)

    async def insert(self, collection, records):
        for record in records:
            self.records[(collection, record.document_id, record.chunk.chunk_index)] = record

    async def search(self, collection, query_vector, top_k=5, metadata_filter=None):
        del metadata_filter
        results = [
            VectorSearchResult(
                score=sum(a * b for a, b in zip(query_vector, record.vector)),
                document_id=record.document_id,
                chunk=record.chunk,
            )
            for (stored_collection, _, _), record in self.records.items()
            if stored_collection == collection
        ]
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]

    async def delete(self, collection, document_id, metadata_filter=None):
        del metadata_filter
        if self.fail_delete:
            raise RuntimeError("vector delete failed")
        for key in list(self.records):
            if key[0] == collection and key[1] == document_id:
                del self.records[key]

    async def list_documents(self, collection, metadata_filter=None):
        raise NotImplementedError

    async def list_chunks(
        self,
        collection,
        document_id,
        *,
        offset=0,
        limit=30,
        metadata_filter=None,
    ):
        del metadata_filter
        chunks = [
            record.chunk
            for (stored_collection, stored_document, _), record in self.records.items()
            if stored_collection == collection and stored_document == document_id
        ]
        return sorted(chunks, key=lambda chunk: chunk.chunk_index)[offset : offset + limit]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def make_knowledge(session_factory, vector_store=None, knowledge_base_id="kb-1"):
    return HybridKnowledgeBase(
        knowledge_base_id=knowledge_base_id,
        session_factory=session_factory,
        name="test",
        description="test knowledge",
        embedding_model=FakeEmbeddingModel(),
        vector_store=vector_store or FakeVectorStore(),
        collection=f"collection-{knowledge_base_id}",
    )


def make_chunk(text, index=0, total=1):
    return Chunk(
        content={"type": "text", "text": text},
        source="test.txt",
        chunk_index=index,
        total_chunks=total,
    )


@pytest.mark.asyncio
async def test_hybrid_search_uses_rrf_to_promote_exact_keyword_hit(session_factory):
    knowledge = make_knowledge(session_factory)
    await knowledge.insert_document([make_chunk("semantic overlap")], document_id="doc-a")
    await knowledge.insert_document(
        [make_chunk("unique-neologism exact")],
        document_id="doc-b",
    )

    results = await knowledge.search(["unique-neologism"], top_k=2)

    assert [result.document_id for result in results] == ["doc-b", "doc-a"]
    assert results[0].score > results[1].score


@pytest.mark.asyncio
async def test_unpublished_vector_hit_fails_closed(session_factory):
    knowledge = make_knowledge(session_factory)
    await knowledge.insert_document([make_chunk("semantic overlap")], document_id="doc-a")
    async with session_factory() as session:
        await session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == "kb-1")
        )
        await session.commit()

    assert await knowledge.search(["semantic"], top_k=5) == []


@pytest.mark.asyncio
async def test_delete_unpublishes_before_vector_failure(session_factory):
    vector_store = FakeVectorStore()
    knowledge = make_knowledge(session_factory, vector_store)
    await knowledge.insert_document([make_chunk("semantic overlap")], document_id="doc-a")
    vector_store.fail_delete = True

    with pytest.raises(RuntimeError, match="vector delete failed"):
        await knowledge.delete_document("doc-a")

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert count == 0
    assert await knowledge.search(["semantic"], top_k=5) == []


@pytest.mark.asyncio
async def test_keyword_index_is_scoped_to_one_knowledge_base(session_factory):
    first = make_knowledge(session_factory, knowledge_base_id="kb-1")
    second = make_knowledge(session_factory, knowledge_base_id="kb-2")
    await first.insert_document([make_chunk("shared-secret-token")], document_id="doc-a")

    assert await second.search(["shared-secret-token"], top_k=5) == []
