"""集中配置：读取根 `.env` 与 `backend/.env`。

优先级：环境变量 > backend/.env > 根 .env > 默认值。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> parents[0]=app, [1]=backend, [2]=项目根
_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_ROOT / ".env"), str(_BACKEND / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 模型凭据（至少一个）----
    DASHSCOPE_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # ---- PostgreSQL 主库 ----
    DATABASE_URL: str = (
        "postgresql+asyncpg://ap:ap_password@localhost:5432/agentscope_ap"
    )

    # ---- Redis ----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # ---- 运行角色与可回滚后端 ----
    SERVICE_ROLE: str = "api"
    VECTOR_BACKEND: str = "qdrant"
    BLOB_BACKEND: str = "s3"
    WORKSPACE_BACKEND: str = "local"

    # ---- Qdrant / Milvus ----
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_TOKEN: str = ""
    MILVUS_METRIC_TYPE: str = "COSINE"
    MILVUS_INDEX_TYPE: str = "AUTOINDEX"

    # ---- 本地 Blob / MinIO / S3 ----
    BLOB_DIR: str = "./blobs"
    S3_ENDPOINT: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "ap-knowledge"
    S3_REGION: str = "us-east-1"

    # ---- 平台认证 ----
    AUTH_ENABLED: bool = True
    JWT_SECRET: str = "change-me-to-a-long-random-string"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080
    AUTH_RATE_LIMIT: int = 10
    AUTH_RATE_WINDOW_SECONDS: int = 60

    # ---- 本地工作区 ----
    WORKSPACE_DIR: str = str(_ROOT / "workspace")

    # ---- 服务 ----
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    CORS_METHODS: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    CORS_HEADERS: str = "Authorization,Content-Type,X-User-ID,X-Request-ID"

    # ---- 可选 Hub ----
    AMAP_API_KEY: str = ""
    CLAWHUB_API_TOKEN: str = ""

    @staticmethod
    def _csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return self._csv(self.CORS_ORIGINS)

    @property
    def cors_method_list(self) -> list[str]:
        return self._csv(self.CORS_METHODS)

    @property
    def cors_header_list(self) -> list[str]:
        return self._csv(self.CORS_HEADERS)

    @model_validator(mode="after")
    def validate_auth_secret(self):
        if self.AUTH_ENABLED and (
            self.JWT_SECRET == "change-me-to-a-long-random-string"
            or len(self.JWT_SECRET.encode("utf-8")) < 32
        ):
            raise ValueError("JWT_SECRET 必须更换默认值且至少包含 32 字节")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
