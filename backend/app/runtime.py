"""API 与独立 Worker 共用的运行时装配工厂。"""

from dataclasses import dataclass
from urllib.parse import urlparse

from aiobotocore.config import AioConfig
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.rag.blob_store import LocalBlobStore, S3BlobStore
from agentscope.app.storage import AsyncSQLAlchemyStorage
from agentscope.rag import MilvusLiteStore, QdrantStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import Settings
from .platform.hybrid_knowledge import HybridKnowledgeBaseManager
from .platform.workspace_leases import RedisWorkspaceCreationLock
from .platform.workspace_manager import IsolatedWorkspaceManager


@dataclass(frozen=True)
class RoleFlags:
    """控制当前进程拥有的内嵌后台任务。"""

    enable_index_worker: bool
    enable_channel_worker: bool
    enable_scheduler: bool


@dataclass(frozen=True)
class Runtime:
    """一次进程装配中必须共享的存储与运行时组件。"""

    storage: AsyncSQLAlchemyStorage
    message_bus: RedisMessageBus
    workspace_manager: IsolatedWorkspaceManager
    vector_store: QdrantStore | MilvusLiteStore
    blob_store: LocalBlobStore | S3BlobStore
    knowledge_base_manager: HybridKnowledgeBaseManager
    role_flags: RoleFlags


def build_role_flags(settings: Settings) -> RoleFlags:
    """后台任务由独立角色运行，API 副本不重复启动。"""
    return RoleFlags(
        enable_index_worker=False,
        enable_channel_worker=False,
        enable_scheduler=settings.SERVICE_ROLE == "scheduler",
    )


def build_vector_store(settings: Settings) -> QdrantStore | MilvusLiteStore:
    """按配置构造向量后端，保留 Qdrant 回滚路径。"""
    if settings.VECTOR_BACKEND == "qdrant":
        return QdrantStore(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
        )
    if settings.VECTOR_BACKEND == "milvus":
        client_kwargs = {}
        if settings.MILVUS_TOKEN:
            client_kwargs["token"] = settings.MILVUS_TOKEN
        return MilvusLiteStore(
            uri=settings.MILVUS_URI,
            metric_type=settings.MILVUS_METRIC_TYPE,
            index_type=settings.MILVUS_INDEX_TYPE,
            client_kwargs=client_kwargs,
        )
    raise ValueError(f"不支持的 VECTOR_BACKEND: {settings.VECTOR_BACKEND}")


def build_blob_store(settings: Settings) -> LocalBlobStore | S3BlobStore:
    """按配置构造 Blob 后端，MinIO 使用 path-style 寻址。"""
    if settings.BLOB_BACKEND == "local":
        return LocalBlobStore(root_dir=settings.BLOB_DIR)
    if settings.BLOB_BACKEND == "s3":
        endpoint = settings.S3_ENDPOINT or None
        use_ssl = endpoint is None or urlparse(endpoint).scheme != "http"
        return S3BlobStore(
            bucket=settings.S3_BUCKET,
            region_name=settings.S3_REGION,
            endpoint_url=endpoint,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
            use_ssl=use_ssl,
            config=AioConfig(s3={"addressing_style": "path"}),
        )
    raise ValueError(f"不支持的 BLOB_BACKEND: {settings.BLOB_BACKEND}")


def build_runtime(settings: Settings) -> Runtime:
    """集中构造组件；schema 变更只由独立 migrate job 执行。"""
    storage = AsyncSQLAlchemyStorage(
        url=settings.DATABASE_URL,
        create_tables=False,
        auto_migrate=False,
    )
    vector_store = build_vector_store(settings)
    workspace_engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(workspace_engine, expire_on_commit=False)
    message_bus = RedisMessageBus(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
    )

    def creation_lock_factory(workspace_id: str) -> RedisWorkspaceCreationLock:
        redis = message_bus.get_client()
        if redis is None:
            raise RuntimeError("RedisMessageBus 尚未进入运行上下文")
        return RedisWorkspaceCreationLock(redis, workspace_id)

    workspace_manager = IsolatedWorkspaceManager(
        basedir=settings.WORKSPACE_DIR,
        session_factory=session_factory,
        creation_lock_factory=creation_lock_factory,
    )
    return Runtime(
        storage=storage,
        message_bus=message_bus,
        workspace_manager=workspace_manager,
        vector_store=vector_store,
        blob_store=build_blob_store(settings),
        knowledge_base_manager=HybridKnowledgeBaseManager(
            storage,
            vector_store,
            session_factory,
        ),
        role_flags=build_role_flags(settings),
    )
