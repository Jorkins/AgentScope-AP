"""检查 AP 外部依赖；默认只读，Docker bind 探测需显式开启。"""

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def redact_secret(message: str) -> str:
    """隐藏连接串和键值参数中的凭据，便于安全输出依赖错误。"""
    redacted = re.sub(
        r"://([^:/\s]+):([^@/\s]+)@",
        r"://\1:***@",
        message,
    )
    return re.sub(
        r"(?i)\b(token|password|secret)=([^\s;]+)",
        r"\1=***",
        redacted,
    )


async def check_postgres() -> CheckResult:
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return CheckResult("postgres", True, "SELECT 1 succeeded")
    except Exception as exc:
        return CheckResult("postgres", False, redact_secret(str(exc)))
    finally:
        await engine.dispose()


async def check_redis() -> CheckResult:
    import redis.asyncio as aioredis

    client = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        socket_connect_timeout=3,
    )
    try:
        await client.ping()
        return CheckResult("redis", True, "PING succeeded")
    except Exception as exc:
        return CheckResult("redis", False, redact_secret(str(exc)))
    finally:
        await client.aclose()


async def check_milvus() -> CheckResult:
    try:
        from pymilvus import MilvusClient
    except ImportError:
        return CheckResult("milvus", False, "pymilvus is not installed")

    uri = os.getenv("MILVUS_URI", "http://localhost:19530")
    token = os.getenv("MILVUS_TOKEN", "")
    kwargs = {"token": token} if token else {}
    client = None
    try:
        client = MilvusClient(uri=uri, **kwargs)
        collections = await asyncio.to_thread(client.list_collections)
        return CheckResult(
            "milvus",
            True,
            f"connected; existing_collections={len(collections)}",
        )
    except Exception as exc:
        return CheckResult("milvus", False, redact_secret(str(exc)))
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if close:
                await asyncio.to_thread(close)


async def check_minio() -> CheckResult:
    if not settings.S3_ENDPOINT:
        return CheckResult("minio", True, "skipped: S3_ENDPOINT is empty")
    try:
        import aioboto3
        from aiobotocore.config import AioConfig

        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            use_ssl=settings.S3_ENDPOINT.startswith("https://"),
            config=AioConfig(s3={"addressing_style": "path"}),
        ) as client:
            await client.head_bucket(Bucket=settings.S3_BUCKET)
        return CheckResult("minio", True, f"bucket {settings.S3_BUCKET} is accessible")
    except Exception as exc:
        return CheckResult("minio", False, redact_secret(str(exc)))


async def check_docker() -> CheckResult:
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            return CheckResult("docker", False, redact_secret(completed.stderr.strip()))
        return CheckResult("docker", True, f"server={completed.stdout.strip()}")
    except Exception as exc:
        return CheckResult("docker", False, redact_secret(str(exc)))


async def probe_workspace_bind() -> CheckResult:
    """用临时目录和自动删除容器验证 Daemon 看到的宿主机路径。"""
    root = Path(settings.WORKSPACE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    image = os.getenv("WORKSPACE_PROBE_IMAGE", "alpine:3.20")
    try:
        with tempfile.TemporaryDirectory(prefix="ap-bind-probe-", dir=root) as directory:
            probe = Path(directory) / "probe.txt"
            probe.write_text("ok", encoding="utf-8")
            completed = await asyncio.to_thread(
                subprocess.run,
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{directory}:/workspace:rw",
                    image,
                    "sh",
                    "-c",
                    "test \"$(cat /workspace/probe.txt)\" = ok",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                return CheckResult(
                    "workspace_bind",
                    False,
                    redact_secret(completed.stderr.strip()),
                )
        return CheckResult("workspace_bind", True, "host bind mount round-trip succeeded")
    except Exception as exc:
        return CheckResult("workspace_bind", False, redact_secret(str(exc)))


async def run_checks(workspace_probe: bool = False) -> list[CheckResult]:
    results = [
        await check_postgres(),
        await check_redis(),
        await check_milvus(),
        await check_minio(),
        await check_docker(),
    ]
    if workspace_probe:
        results.append(await probe_workspace_bind())
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-probe", action="store_true")
    args = parser.parse_args()
    results = asyncio.run(run_checks(args.workspace_probe))
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
