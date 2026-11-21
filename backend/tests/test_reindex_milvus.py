from types import SimpleNamespace

import pytest
from agentscope.app.storage import KnowledgeDocumentRecord

from scripts.reindex_milvus import _smoke_result_count, reindex_knowledge_base


class FakeVectorStore:
    def __init__(self):
        self.collections = set()
        self.summaries = {}
        self.created = []

    async def has_collection(self, name):
        return name in self.collections

    async def create_collection(self, name, dimensions):
        self.created.append((name, dimensions))
        self.collections.add(name)

    async def list_documents(self, name):
        return [
            SimpleNamespace(document_id=document_id, chunk_count=count)
            for document_id, count in self.summaries.get(name, {}).items()
        ]


class FakeStorage:
    def __init__(self, documents):
        self.documents = {document.id: document for document in documents}

    async def update_knowledge_document_status(
        self,
        user_id,
        knowledge_base_id,
        document_id,
        status,
        chunk_count=None,
    ):
        document = self.documents[document_id]
        document.status = status
        if chunk_count is not None:
            document.data.chunk_count = chunk_count

    async def get_knowledge_document(self, user_id, knowledge_base_id, document_id):
        return self.documents[document_id]


class FakeWorker:
    def __init__(self, storage, vector_store, collection, actual_count=None):
        self.storage = storage
        self.vector_store = vector_store
        self.collection = collection
        self.actual_count = actual_count
        self.calls = []

    async def process(self, user_id, knowledge_base_id, document_id):
        self.calls.append(document_id)
        document = self.storage.documents[document_id]
        count = self.actual_count or document.data.chunk_count
        self.vector_store.summaries.setdefault(self.collection, {})[document_id] = count
        await self.storage.update_knowledge_document_status(
            user_id,
            knowledge_base_id,
            document_id,
            "ready",
            chunk_count=document.data.chunk_count,
        )


def make_document(chunk_count=2):
    return KnowledgeDocumentRecord(
        id="doc-1",
        user_id="alice",
        knowledge_base_id="kb-id",
        status="ready",
        data={
            "filename": "notes.txt",
            "size": 7,
            "blob_uri": "s3://ap-knowledge/kb/kb-id/doc-1",
            "chunk_count": chunk_count,
        },
    )


def make_kb():
    return SimpleNamespace(
        id="kb-id",
        user_id="alice",
        data=SimpleNamespace(
            collection_name="kb_collection_id",
            embedding_model_config=SimpleNamespace(dimensions=1536),
        ),
    )


@pytest.mark.asyncio
async def test_reindex_preserves_ids_and_reconciles_chunk_counts():
    kb = make_kb()
    document = make_document()
    storage = FakeStorage([document])
    vectors = FakeVectorStore()
    worker = FakeWorker(storage, vectors, kb.data.collection_name)

    report = await reindex_knowledge_base(kb, [document], vectors, worker, storage)

    assert vectors.created == [("kb_collection_id", 1536)]
    assert worker.calls == ["doc-1"]
    assert report.indexed == 1
    assert report.failures == []
    assert report.documents["doc-1"] == {"expected": 2, "actual": 2}


@pytest.mark.asyncio
async def test_resume_skips_already_reconciled_document():
    kb = make_kb()
    document = make_document()
    storage = FakeStorage([document])
    vectors = FakeVectorStore()
    vectors.collections.add(kb.data.collection_name)
    vectors.summaries[kb.data.collection_name] = {"doc-1": 2}
    worker = FakeWorker(storage, vectors, kb.data.collection_name)

    report = await reindex_knowledge_base(kb, [document], vectors, worker, storage)

    assert report.skipped == 1
    assert worker.calls == []


@pytest.mark.asyncio
async def test_reindex_reports_chunk_mismatch_and_unexpected_document():
    kb = make_kb()
    document = make_document(chunk_count=2)
    storage = FakeStorage([document])
    vectors = FakeVectorStore()
    vectors.summaries[kb.data.collection_name] = {"other-kb-document": 9}
    worker = FakeWorker(storage, vectors, kb.data.collection_name, actual_count=1)

    report = await reindex_knowledge_base(kb, [document], vectors, worker, storage)

    assert report.documents["doc-1"] == {"expected": 2, "actual": 1}
    assert any("chunk count mismatch" in failure for failure in report.failures)
    assert any("unexpected documents" in failure for failure in report.failures)


@pytest.mark.asyncio
async def test_smoke_result_count_uses_flat_search_results():
    class FakeKnowledge:
        async def search(self, queries, top_k):
            assert queries == ["ZXQ-7391-OMEGA"]
            assert top_k == 5
            return [object(), object(), object()]

    assert await _smoke_result_count(FakeKnowledge(), "ZXQ-7391-OMEGA") == 3
