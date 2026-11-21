"""基于 Redis 的工作区创建锁。"""

import secrets

import redis.asyncio as aioredis


_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class RedisWorkspaceCreationLock:
    """使用唯一所有者 token 防止续约或释放其他副本的锁。"""

    def __init__(
        self,
        redis: aioredis.Redis,
        workspace_id: str,
        ttl_seconds: int = 30,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        self._redis = redis
        self._ttl_seconds = ttl_seconds
        self._token: str | None = None
        self.key = f"lock:workspace:create:{workspace_id}"

    async def acquire(self) -> bool:
        """以 NX + TTL 获取锁，成功后记录本次获取的随机 token。"""
        token = secrets.token_urlsafe(32)
        acquired = await self._redis.set(
            self.key,
            token,
            nx=True,
            ex=self._ttl_seconds,
        )
        if not acquired:
            return False
        self._token = token
        return True

    async def renew(self) -> bool:
        """仅当 token 仍匹配时，在同一 Redis 命令内续上 TTL。"""
        if self._token is None:
            return False
        renewed = bool(
            await self._redis.eval(
                _RENEW_SCRIPT,
                1,
                self.key,
                self._token,
                self._ttl_seconds,
            )
        )
        if not renewed:
            self._token = None
        return renewed

    async def release(self) -> bool:
        """仅删除仍由本实例持有的锁，避免误删后续所有者的锁。"""
        if self._token is None:
            return False
        released = bool(
            await self._redis.eval(
                _RELEASE_SCRIPT,
                1,
                self.key,
                self._token,
            )
        )
        self._token = None
        return released
