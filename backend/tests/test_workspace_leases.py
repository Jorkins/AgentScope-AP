import asyncio

import pytest

from app.platform.workspace_leases import RedisWorkspaceCreationLock


class FakeRedis:
    """以 asyncio.Lock 模拟 Redis 单命令的原子性。"""

    def __init__(self):
        self.values = {}
        self._lock = asyncio.Lock()

    async def set(self, key, value, nx=False, ex=None):
        async with self._lock:
            if nx and key in self.values:
                return None
            self.values[key] = [value, ex]
            return True

    async def eval(self, script, numkeys, *keys_and_args):
        del script, numkeys
        key, token, *ttl = keys_and_args
        async with self._lock:
            current = self.values.get(key)
            if current is None or current[0] != token:
                return 0
            if ttl:
                current[1] = ttl[0]
            else:
                del self.values[key]
            return 1

    async def expire_now(self, key):
        async with self._lock:
            self.values.pop(key, None)


@pytest.mark.asyncio
async def test_concurrent_acquire_has_single_owner_and_ttl():
    redis = FakeRedis()
    first = RedisWorkspaceCreationLock(redis, "workspace-1", ttl_seconds=30)
    second = RedisWorkspaceCreationLock(redis, "workspace-1", ttl_seconds=30)

    acquired = await asyncio.gather(first.acquire(), second.acquire())

    assert sorted(acquired) == [False, True]
    token, ttl = redis.values["lock:workspace:create:workspace-1"]
    assert isinstance(token, str) and len(token) >= 32
    assert ttl == 30


@pytest.mark.asyncio
async def test_each_successful_acquisition_uses_a_new_token():
    redis = FakeRedis()
    lock = RedisWorkspaceCreationLock(redis, "workspace-1")
    key = lock.key

    assert await lock.acquire()
    first_token = redis.values[key][0]
    assert await lock.release()
    assert await lock.acquire()

    assert redis.values[key][0] != first_token


@pytest.mark.asyncio
async def test_renew_extends_ttl_only_for_current_owner():
    redis = FakeRedis()
    first = RedisWorkspaceCreationLock(redis, "workspace-1", ttl_seconds=10)
    second = RedisWorkspaceCreationLock(redis, "workspace-1", ttl_seconds=20)
    assert await first.acquire()

    assert not await second.renew()
    assert redis.values[first.key][1] == 10
    assert await first.renew()
    assert redis.values[first.key][1] == 10

    await redis.expire_now(first.key)
    assert await second.acquire()
    second_token = redis.values[first.key][0]
    assert not await first.renew()
    assert redis.values[first.key] == [second_token, 20]


@pytest.mark.asyncio
async def test_stale_owner_cannot_release_new_owners_lock():
    redis = FakeRedis()
    stale = RedisWorkspaceCreationLock(redis, "workspace-1")
    current = RedisWorkspaceCreationLock(redis, "workspace-1")
    assert await stale.acquire()
    await redis.expire_now(stale.key)
    assert await current.acquire()
    current_token = redis.values[current.key][0]

    assert not await stale.release()

    assert redis.values[current.key][0] == current_token
    assert await current.release()
    assert current.key not in redis.values


@pytest.mark.asyncio
async def test_release_without_ownership_does_not_touch_redis():
    redis = FakeRedis()
    lock = RedisWorkspaceCreationLock(redis, "workspace-1")

    assert not await lock.release()
    assert redis.values == {}


@pytest.mark.parametrize("ttl_seconds", [0, -1])
def test_lock_rejects_non_positive_ttl(ttl_seconds):
    with pytest.raises(ValueError, match="ttl_seconds"):
        RedisWorkspaceCreationLock(FakeRedis(), "workspace-1", ttl_seconds)
