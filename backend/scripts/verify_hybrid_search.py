"""对指定真实知识库分别验证 Milvus 语义、PostgreSQL 关键词与 RRF。"""

import argparse
import asyncio
import json
import math

from app.config import settings
from app.runtime import build_runtime


def _key(result):
    return result.document_id, result.chunk.chunk_index


def _view(results):
    return [
        {
            "document_id": result.document_id,
            "chunk_index": result.chunk.chunk_index,
            "score": result.score,
            "text": getattr(result.chunk.content, "text", ""),
        }
        for result in results
    ]


def _independent_rrf_score(rankings, target):
    return sum(
        1.0 / (60 + rank)
        for ranking in rankings
        for rank, result in enumerate(ranking, start=1)
        if _key(result) == target
    )


async def run(args):
    milvus_settings = settings.model_copy(update={"VECTOR_BACKEND": "milvus"})
    runtime = build_runtime(milvus_settings)
    async with runtime.storage, runtime.vector_store:
        knowledge = await runtime.knowledge_base_manager.get_knowledge(
            args.user_id,
            args.knowledge_base_id,
        )
        semantic_query = "无人飞船在恶劣天气下怎样安全入港？"
        keyword_query = "ZXQ-7391-OMEGA"

        semantic = await knowledge._published_semantic_search(
            [semantic_query],
            top_k=3,
            score_threshold=None,
        )
        keyword = await knowledge._keyword_search([keyword_query], top_k=3)
        semantic_for_keyword = await knowledge._published_semantic_search(
            [keyword_query],
            top_k=3,
            score_threshold=None,
        )
        hybrid_semantic = await knowledge.search([semantic_query], top_k=3)
        hybrid_keyword = await knowledge.search([keyword_query], top_k=3)

        assert semantic[0].document_id == args.semantic_document_id
        assert keyword[0].document_id == args.keyword_document_id
        assert hybrid_semantic[0].document_id == args.semantic_document_id
        assert hybrid_keyword[0].document_id == args.keyword_document_id

        target = _key(hybrid_keyword[0])
        expected_rrf = _independent_rrf_score(
            [semantic_for_keyword, keyword],
            target,
        )
        assert math.isclose(hybrid_keyword[0].score, expected_rrf, rel_tol=1e-9)

        evidence = {
            "vector_store": type(runtime.vector_store).__name__,
            "collection": knowledge.collection,
            "semantic_query": semantic_query,
            "semantic": _view(semantic),
            "hybrid_semantic": _view(hybrid_semantic),
            "keyword_query": keyword_query,
            "semantic_for_keyword": _view(semantic_for_keyword),
            "keyword": _view(keyword),
            "hybrid_keyword": _view(hybrid_keyword),
            "independent_rrf_score": expected_rrf,
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
