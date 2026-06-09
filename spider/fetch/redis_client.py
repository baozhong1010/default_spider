import asyncio
from functools import partial


class SyncRedisAsyncAdapter(object):
    def __init__(self, redis_client):
        self._redis = redis_client

    async def _call(self, method, *args, **kwargs):
        loop = asyncio.get_event_loop()
        func = partial(method, *args, **kwargs)
        return await loop.run_in_executor(None, func)

    async def hget(self, *args, **kwargs):
        return await self._call(self._redis.hget, *args, **kwargs)

    async def hexists(self, *args, **kwargs):
        return await self._call(self._redis.hexists, *args, **kwargs)

    async def hset(self, *args, **kwargs):
        return await self._call(self._redis.hset, *args, **kwargs)

    async def hscan(self, *args, **kwargs):
        return await self._call(self._redis.hscan, *args, **kwargs)

    async def hdel(self, *args, **kwargs):
        return await self._call(self._redis.hdel, *args, **kwargs)

    async def lpush(self, *args, **kwargs):
        return await self._call(self._redis.lpush, *args, **kwargs)

    async def lpop(self, *args, **kwargs):
        return await self._call(self._redis.lpop, *args, **kwargs)

    async def aclose(self):
        close = getattr(self._redis, "close", None)
        if close is None:
            return
        await self._call(close)


def create_redis_client(redis_cfg):
    try:
        from redis.asyncio import Redis as AsyncRedis

        return AsyncRedis(
            host=redis_cfg.host,
            port=redis_cfg.port,
            db=redis_cfg.db,
            password=redis_cfg.password,
            decode_responses=redis_cfg.decode_responses,
        )
    except Exception:
        import redis

        sync_client = redis.StrictRedis(
            host=redis_cfg.host,
            port=redis_cfg.port,
            db=redis_cfg.db,
            password=redis_cfg.password,
            decode_responses=redis_cfg.decode_responses,
        )
        return SyncRedisAsyncAdapter(sync_client)
