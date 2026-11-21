"""在本地 Blob 与 S3/MinIO 之间迁移文档 URI，保留所有原始对象。"""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
import io
import json
from pathlib import Path
from typing import Iterable

from agentscope.app.rag.blob_store import LocalBlobStore
from agentscope.app.storage import AsyncSQLAlchemyStorage, KnowledgeDocumentRecord
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.platform.models import User
from app.runtime import build_blob_store


@dataclass
class BlobMapping:
    document_id: str
    old_uri: str
    new_uri: str
    size: int
    sha256: str
    applied: bool = False


@dataclass
class MigrationReport:
    documents: int = 0
    bytes: int = 0
    migrated: int = 0
    skipped: int = 0
    missing: int = 0
    conflicts: int = 0
    mappings: list[BlobMapping] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class VerificationReport:
    checked: int = 0
    failures: list[str] = field(default_factory=list)


async def _read_bytes(store, uri: str) -> bytes:
    chunks = []
    async with store.open(uri) as stream:
        while chunk := await stream.read(1024 * 1024):
            chunks.append(chunk)
    return b"".join(chunks)


def _target_uri(target, key: str) -> str:
    bucket = getattr(target, "bucket", None) or getattr(target, "_bucket")
    return f"s3://{bucket}/{key}"


async def migrate_blobs(
    documents: Iterable[KnowledgeDocumentRecord],
    source,
    target,
    storage,
    apply: bool = False,
) -> MigrationReport:
    """逐对象复制并校验；只有目标 checksum 一致后才切换数据库 URI。"""
    report = MigrationReport()
    for document in documents:
        report.documents += 1
        old_uri = document.data.blob_uri
        if old_uri.startswith("s3://"):
            report.skipped += 1
            continue
        if not old_uri.startswith("local://"):
            report.failures.append(f"{document.id}: unsupported source URI")
            continue

        key = f"kb/{document.knowledge_base_id}/{document.id}"
        if old_uri != f"local://{key}":
            report.conflicts += 1
            report.failures.append(f"{document.id}: unexpected local blob key")
            continue
        try:
            content = await _read_bytes(source, old_uri)
        except FileNotFoundError:
            report.missing += 1
            report.failures.append(f"{document.id}: local object missing")
            continue

        digest = hashlib.sha256(content).hexdigest()
        new_uri = _target_uri(target, key)
        mapping = BlobMapping(document.id, old_uri, new_uri, len(content), digest)
        report.mappings.append(mapping)
        report.bytes += len(content)

        target_content = None
        if await target.exists(new_uri):
            target_content = await _read_bytes(target, new_uri)
            if hashlib.sha256(target_content).hexdigest() != digest:
                report.conflicts += 1
                report.failures.append(f"{document.id}: target checksum conflict")
                continue

        if not apply:
            continue
        if target_content is None:
            await target.write_stream(key, io.BytesIO(content))
            target_content = await _read_bytes(target, new_uri)
            report.migrated += 1
        else:
            report.skipped += 1

        if len(target_content) != len(content) or hashlib.sha256(
            target_content
        ).hexdigest() != digest:
            report.failures.append(f"{document.id}: target verification failed")
            continue
        document.data.blob_uri = new_uri
        await storage.upsert_knowledge_document(document.user_id, document)
        mapping.applied = True
    return report


async def verify_blobs(documents, target, report: MigrationReport) -> VerificationReport:
    result = VerificationReport()
    mappings = {item.document_id: item for item in report.mappings if item.applied}
    for document in documents:
        mapping = mappings.get(document.id)
        if mapping is None:
            continue
        result.checked += 1
        if document.data.blob_uri != mapping.new_uri:
            result.failures.append(f"{document.id}: URI does not match report")
            continue
        try:
            content = await _read_bytes(target, mapping.new_uri)
        except Exception as exc:  # 网络/权限失败也必须进入对账报告
            result.failures.append(f"{document.id}: {type(exc).__name__}")
            continue
        if len(content) != mapping.size or hashlib.sha256(content).hexdigest() != mapping.sha256:
            result.failures.append(f"{document.id}: checksum mismatch")
    return result


async def rollback_blobs(documents, source, storage, report: MigrationReport) -> int:
    mappings = {item.document_id: item for item in report.mappings if item.applied}
    restored = 0
    for document in documents:
        mapping = mappings.get(document.id)
        if mapping is None or document.data.blob_uri != mapping.new_uri:
            continue
        if not await source.exists(mapping.old_uri):
            raise FileNotFoundError(f"rollback source missing for {document.id}")
        document.data.blob_uri = mapping.old_uri
        await storage.upsert_knowledge_document(document.user_id, document)
        restored += 1
    return restored


async def load_documents(storage, session_factory) -> list[KnowledgeDocumentRecord]:
    documents = []
    async with session_factory() as session:
        usernames = (await session.execute(select(User.username))).scalars().all()
    for username in usernames:
        for knowledge_base in await storage.list_knowledge_bases(username):
            documents.extend(
                await storage.list_knowledge_documents(username, knowledge_base.id)
            )
    return documents


def save_report(report: MigrationReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")


def load_report(path: Path) -> MigrationReport:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["mappings"] = [BlobMapping(**item) for item in raw.get("mappings", [])]
    return MigrationReport(**raw)


async def run(args) -> int:
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = AsyncSQLAlchemyStorage(
        url=settings.DATABASE_URL,
        create_tables=False,
        auto_migrate=False,
    )
    source = LocalBlobStore(settings.BLOB_DIR)
    target = build_blob_store(settings)
    report_path = Path(args.report)
    try:
        async with storage, source, target:
            documents = await load_documents(storage, session_factory)
            if args.rollback:
                report = load_report(Path(args.rollback))
                restored = await rollback_blobs(documents, source, storage, report)
                print(json.dumps({"restored": restored}, ensure_ascii=False))
                return 0
            if args.verify:
                result = await verify_blobs(documents, target, load_report(report_path))
                print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
                return 1 if result.failures else 0
            report = await migrate_blobs(documents, source, target, storage, apply=args.apply)
            save_report(report, report_path)
            print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
            return 1 if report.failures else 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--rollback", metavar="REPORT")
    parser.add_argument("--report", default="blob-migration-report.json")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
