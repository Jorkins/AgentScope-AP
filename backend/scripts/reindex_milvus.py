"""从 Blob 原文重建 Milvus 索引，并对账 document/chunk 数量。"""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import socket

from agentscope.app._service import IndexWorker
from agentscope.rag import (
    ApproxTokenChunker,
    ExcelParser,
    ImageParser,
    PDFParser,
    PPTParser,
    TextParser,
    WordParser,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.platform.models import User
from app.runtime import build_runtime


@dataclass
class ReindexReport:
    knowledge_base_id: str
    collection: str
    indexed: int = 0
    skipped: int = 0
    expected_chunks: int = 0
    actual_chunks: int = 0
    documents: dict[str, dict[str, int]] = field(default_factory=dict)
    smoke_results: int | None = None
    failures: list[str] = field(default_factory=list)


async def _summaries(vector_store, collection: str) -> dict[str, int]:
    return {
        summary.document_id: summary.chunk_count
        for summary in await vector_store.list_documents(collection)
    }


async def _smoke_result_count(knowledge, query: str) -> int:
    results = await knowledge.search([query], top_k=5)
    return len(results)


async def reindex_knowledge_base(
    knowledge_base,
    documents,
    vector_store,
    worker,
    storage,
    resume: bool = True,
) -> ReindexReport:
    """复用 IndexWorker 重建单 KB；任何对账差异都显式进入报告。"""
    collection = knowledge_base.data.collection_name
    report = ReindexReport(knowledge_base.id, collection)
    dimensions = knowledge_base.data.embedding_model_config.dimensions
    if not await vector_store.has_collection(collection):
        await vector_store.create_collection(collection, dimensions)

    counts = await _summaries(vector_store, collection)
    for document in documents:
        expected = document.data.chunk_count
        if resume and document.status == "ready" and counts.get(document.id, 0) == expected:
            report.skipped += 1
            report.documents[document.id] = {
                "expected": expected,
                "actual": counts.get(document.id, 0),
            }
            continue

        await storage.update_knowledge_document_status(
            document.user_id,
            knowledge_base.id,
            document.id,
            "pending",
        )
        try:
            await worker.process(document.user_id, knowledge_base.id, document.id)
        except Exception as exc:  # 保留其他文档的续跑机会
            report.failures.append(f"{document.id}: {type(exc).__name__}")

        current = await storage.get_knowledge_document(
            document.user_id,
            knowledge_base.id,
            document.id,
        )
        counts = await _summaries(vector_store, collection)
        actual = counts.get(document.id, 0)
        expected = current.data.chunk_count if current is not None else expected
        report.documents[document.id] = {"expected": expected, "actual": actual}
        document_failed = False
        if current is None or current.status != "ready":
            report.failures.append(f"{document.id}: indexing did not reach ready")
            document_failed = True
        if actual != expected:
            report.failures.append(f"{document.id}: chunk count mismatch")
            document_failed = True
        if not document_failed:
            report.indexed += 1

    expected_ids = {
        document.id
        for document in documents
        if report.documents.get(document.id, {}).get("expected", 0) > 0
    }
    unexpected = set(counts) - expected_ids
    if unexpected:
        report.failures.append(
            "unexpected documents: " + ",".join(sorted(unexpected))
        )
    report.expected_chunks = sum(item["expected"] for item in report.documents.values())
    report.actual_chunks = sum(counts.values())
    return report


async def load_knowledge_bases(storage, session_factory):
    async with session_factory() as session:
        usernames = (await session.execute(select(User.username))).scalars().all()
    result = []
    for username in usernames:
        result.extend(await storage.list_knowledge_bases(username))
    return result


async def run(args) -> int:
    milvus_settings = settings.model_copy(update={"VECTOR_BACKEND": "milvus"})
    runtime = build_runtime(milvus_settings)
    engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    worker = IndexWorker(
        storage=runtime.storage,
        blob_store=runtime.blob_store,
        knowledge_base_manager=runtime.knowledge_base_manager,
        parsers=[
            TextParser(),
            PDFParser(),
            WordParser(),
            ExcelParser(),
            PPTParser(),
            ImageParser(),
        ],
        chunkers=[ApproxTokenChunker],
        node_id=f"reindex:{socket.gethostname()}:{os.getpid()}",
        max_concurrency=1,
    )
    reports = []
    try:
        async with runtime.storage, runtime.blob_store, runtime.vector_store:
            knowledge_bases = await load_knowledge_bases(runtime.storage, session_factory)
            if args.knowledge_base_id:
                knowledge_bases = [
                    item for item in knowledge_bases if item.id == args.knowledge_base_id
                ]
                if not knowledge_bases:
                    raise ValueError("指定知识库不存在或不属于 AP 用户")
            for knowledge_base in knowledge_bases:
                documents = await runtime.storage.list_knowledge_documents(
                    knowledge_base.user_id,
                    knowledge_base.id,
                )
                report = await reindex_knowledge_base(
                    knowledge_base,
                    documents,
                    runtime.vector_store,
                    worker,
                    runtime.storage,
                    resume=not args.no_resume,
                )
                if not args.skip_smoke_test:
                    try:
                        knowledge = await runtime.knowledge_base_manager.get_knowledge(
                            knowledge_base.user_id,
                            knowledge_base.id,
                        )
                        report.smoke_results = await _smoke_result_count(
                            knowledge,
                            args.smoke_query,
                        )
                    except Exception as exc:
                        report.failures.append(f"smoke test: {type(exc).__name__}")
                reports.append(report)
    finally:
        await engine.dispose()

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps([asdict(report) for report in reports], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps([asdict(report) for report in reports], ensure_ascii=False, indent=2))
    return 1 if not reports or any(report.failures for report in reports) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-base-id")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--smoke-query", default="AgentScope")
    parser.add_argument("--skip-smoke-test", action="store_true")
    parser.add_argument("--report", default="milvus-reindex-report.json")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
