"""从 MinIO 原文实测 Qdrant 回滚，并复查 Milvus 数据未受影响。"""

import argparse
import asyncio
from dataclasses import asdict
import json
import os
import socket

from agentscope.app._service import IndexWorker
from agentscope.rag import ApproxTokenChunker, TextParser

from app.config import settings
from app.runtime import build_runtime
from scripts.reindex_milvus import reindex_knowledge_base


def _view(results):
    return [
        {
            "document_id": result.document_id,
            "chunk_index": result.chunk.chunk_index,
            "score": result.score,
        }
        for result in results
    ]


async def _milvus_evidence(args):
    runtime = build_runtime(settings.model_copy(update={"VECTOR_BACKEND": "milvus"}))
    async with runtime.storage, runtime.vector_store:
        knowledge = await runtime.knowledge_base_manager.get_knowledge(
            args.user_id,
            args.knowledge_base_id,
        )
        summaries = await runtime.vector_store.list_documents(knowledge.collection)
        results = await knowledge.search(["ZXQ-7391-OMEGA"], top_k=3)
        assert results[0].document_id == args.keyword_document_id
        return {
            "vector_store": type(runtime.vector_store).__name__,
            "document_chunks": {
                item.document_id: item.chunk_count for item in summaries
            },
            "keyword_top": _view(results)[0],
        }


async def run(args):
    runtime = build_runtime(settings.model_copy(update={"VECTOR_BACKEND": "qdrant"}))
    async with runtime.storage, runtime.blob_store, runtime.vector_store:
        knowledge_base = await runtime.storage.get_knowledge_base(
            args.user_id,
            args.knowledge_base_id,
        )
        assert knowledge_base is not None
        documents = await runtime.storage.list_knowledge_documents(
            args.user_id,
            args.knowledge_base_id,
        )
        worker = IndexWorker(
            storage=runtime.storage,
            blob_store=runtime.blob_store,
            knowledge_base_manager=runtime.knowledge_base_manager,
            parsers=[TextParser()],
            chunkers=[ApproxTokenChunker],
            node_id=f"qdrant-rollback:{socket.gethostname()}:{os.getpid()}",
            max_concurrency=1,
        )
        report = await reindex_knowledge_base(
            knowledge_base,
            documents,
            runtime.vector_store,
            worker,
            runtime.storage,
            resume=False,
        )
        assert report.failures == []
        assert report.indexed == len(documents) == 3
        assert report.expected_chunks == report.actual_chunks == 3

        knowledge = await runtime.knowledge_base_manager.get_knowledge(
            args.user_id,
            args.knowledge_base_id,
        )
        semantic = await knowledge.search(
            ["无人飞船在恶劣天气下怎样安全入港？"],
            top_k=3,
        )
        keyword = await knowledge.search(["ZXQ-7391-OMEGA"], top_k=3)
        assert semantic[0].document_id == args.semantic_document_id
        assert keyword[0].document_id == args.keyword_document_id

        evidence = {
            "qdrant": {
                "vector_store": type(runtime.vector_store).__name__,
                "report": asdict(report),
                "semantic_top": _view(semantic)[0],
                "keyword_top": _view(keyword)[0],
            },
            "milvus_after_rollback": await _milvus_evidence(args),
        }
        print(json.dumps(evidence, ensure_ascii=True, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--semantic-document-id", required=True)
    parser.add_argument("--keyword-document-id", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
