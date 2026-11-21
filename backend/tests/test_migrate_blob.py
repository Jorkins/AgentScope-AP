import io
from contextlib import asynccontextmanager

import pytest
from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.storage import KnowledgeDocumentRecord

from scripts.migrate_blob import migrate_blobs, rollback_blobs, verify_blobs


class AsyncBytesIO(io.BytesIO):
    async def read(self, size=-1):
        return super().read(size)


class MemoryBlobStore:
    def __init__(self, bucket="ap-knowledge"):
        self.bucket = bucket
        self.objects = {}
        self.writes = 0

    async def write_stream(self, key, stream):
        self.writes += 1
        self.objects[(self.bucket, key)] = stream.read()
        return f"s3://{self.bucket}/{key}"

    @asynccontextmanager
    async def open(self, uri):
        bucket, key = uri.removeprefix("s3://").split("/", 1)
        yield AsyncBytesIO(self.objects[(bucket, key)])

    async def size(self, uri):
        bucket, key = uri.removeprefix("s3://").split("/", 1)
        value = self.objects.get((bucket, key))
        return len(value) if value is not None else None

    async def exists(self, uri):
        return await self.size(uri) is not None


class MemoryStorage:
    def __init__(self, documents):
        self.documents = {document.id: document for document in documents}

    async def upsert_knowledge_document(self, user_id, record):
        assert user_id == record.user_id
        self.documents[record.id] = record
        return record


def make_document(document_id="doc-1"):
    return KnowledgeDocumentRecord(
        id=document_id,
        user_id="alice",
        knowledge_base_id="kb-1",
        data={
            "filename": "notes.txt",
            "size": 7,
            "blob_uri": f"local://kb/kb-1/{document_id}",
        },
    )


async def seed_local(tmp_path, document, content=b"content"):
    store = LocalBlobStore(tmp_path)
    async with store:
        await store.write_stream(
            f"kb/{document.knowledge_base_id}/{document.id}",
            io.BytesIO(content),
        )
    return store


@pytest.mark.asyncio
async def test_dry_run_reports_without_writing_or_switching_uri(tmp_path):
    document = make_document()
    source = await seed_local(tmp_path, document)
    target = MemoryBlobStore()
    storage = MemoryStorage([document])

    report = await migrate_blobs([document], source, target, storage)

    assert report.documents == 1
    assert report.bytes == 7
    assert target.writes == 0
    assert document.data.blob_uri.startswith("local://")
    assert report.mappings[0].sha256


@pytest.mark.asyncio
async def test_apply_verifies_checksum_and_resumes_without_reupload(tmp_path):
    document = make_document()
    source = await seed_local(tmp_path, document)
    target = MemoryBlobStore()
    storage = MemoryStorage([document])

    report = await migrate_blobs([document], source, target, storage, apply=True)
    resumed = await migrate_blobs([document], source, target, storage, apply=True)

    assert report.migrated == 1
    assert resumed.skipped == 1
    assert target.writes == 1
    assert document.data.blob_uri == "s3://ap-knowledge/kb/kb-1/doc-1"
    assert await source.exists("local://kb/kb-1/doc-1")
    verification = await verify_blobs([document], target, report)
    assert verification.failures == []


@pytest.mark.asyncio
async def test_conflicting_target_never_changes_document_uri(tmp_path):
    document = make_document()
    source = await seed_local(tmp_path, document)
    target = MemoryBlobStore()
    target.objects[("ap-knowledge", "kb/kb-1/doc-1")] = b"different"
    storage = MemoryStorage([document])

    report = await migrate_blobs([document], source, target, storage, apply=True)

    assert report.conflicts == 1
    assert report.migrated == 0
    assert document.data.blob_uri.startswith("local://")


@pytest.mark.asyncio
async def test_rollback_restores_only_recorded_uri_and_keeps_both_copies(tmp_path):
    document = make_document()
    source = await seed_local(tmp_path, document)
    target = MemoryBlobStore()
    storage = MemoryStorage([document])
    report = await migrate_blobs([document], source, target, storage, apply=True)

    restored = await rollback_blobs([document], source, storage, report)

    assert restored == 1
    assert document.data.blob_uri == "local://kb/kb-1/doc-1"
    assert await target.exists("s3://ap-knowledge/kb/kb-1/doc-1")
