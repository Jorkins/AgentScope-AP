import pytest

from app.config import Settings
from app.platform.hybrid_knowledge import HybridKnowledgeBaseManager
from app.platform.workspace_leases import RedisWorkspaceCreationLock
from app.runtime import (
    build_blob_store,
    build_role_flags,
    build_runtime,
    build_vector_store,
)
from agentscope.app.rag.blob_store import LocalBlobStore, S3BlobStore
from agentscope.rag import MilvusLiteStore, QdrantStore


def make_settings(**overrides):
    values = {
        "_env_file": None,
        "JWT_SECRET": "test-secret-0123456789abcdef0123456789abcdef",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("api", (False, False, False)),
        ("index", (False, False, False)),
        ("channel", (False, False, False)),
        ("scheduler", (False, False, True)),
        ("realtime", (False, False, False)),
    ],
)
def test_role_flags_keep_background_owners_out_of_api(role, expected):
    flags = build_role_flags(make_settings(SERVICE_ROLE=role))

    assert (
        flags.enable_index_worker,
        flags.enable_channel_worker,
        flags.enable_scheduler,
    ) == expected


def test_qdrant_remains_available_for_rollback():
    store = build_vector_store(make_settings(VECTOR_BACKEND="qdrant"))

    assert isinstance(store, QdrantStore)


def test_milvus_uses_remote_uri_and_authentication():
    store = build_vector_store(
        make_settings(
            VECTOR_BACKEND="milvus",
            MILVUS_URI="http://milvus:19530",
            MILVUS_TOKEN="user:password",
        )
    )

    assert isinstance(store, MilvusLiteStore)
    assert store._uri == "http://milvus:19530"
    assert store._client_kwargs["token"] == "user:password"


def test_s3_blob_store_uses_minio_path_style():
    store = build_blob_store(
        make_settings(
            BLOB_BACKEND="s3",
            S3_ENDPOINT="http://minio:9000",
            S3_ACCESS_KEY="app",
            S3_SECRET_KEY="secret",
        )
    )

    assert isinstance(store, S3BlobStore)
    assert store._config.s3["addressing_style"] == "path"
    assert store._use_ssl is False


def test_local_blob_store_remains_available_for_rollback():
    store = build_blob_store(make_settings(BLOB_BACKEND="local"))

    assert isinstance(store, LocalBlobStore)


def test_runtime_shares_backends_without_startup_schema_changes():
    runtime = build_runtime(make_settings())

    assert runtime.storage._create_tables is False
    assert runtime.storage._auto_migrate is False
    assert runtime.knowledge_base_manager._vector_store is runtime.vector_store
    assert isinstance(runtime.knowledge_base_manager, HybridKnowledgeBaseManager)
    assert runtime.role_flags.enable_index_worker is False
    assert runtime.role_flags.enable_channel_worker is False
    assert runtime.role_flags.enable_scheduler is False


def test_workspace_creation_lock_reuses_message_bus_redis_client():
    runtime = build_runtime(make_settings())
    redis_client = object()
    runtime.message_bus._client = redis_client

    lock = runtime.workspace_manager._creation_lock_factory("workspace-1")

    assert isinstance(lock, RedisWorkspaceCreationLock)
    assert lock._redis is redis_client
