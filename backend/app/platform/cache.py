"""Redis 缓存封装（平台侧通用缓存 / 分布式锁基础）。"""

from typing import Any

import redis.asyncio as aioredis


class RedisCache:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 1):
        self._r = aioredis.Redis(host=host, port=port, db=db, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        await self._r.set(key, value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._r.delete(*keys)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        val = await self._r.incr(key)
        if ttl_seconds is not None and val == 1:
            await self._r.expire(key, ttl_seconds)
        return int(val)

    async def close(self) -> None:
        await self._r.aclose()
