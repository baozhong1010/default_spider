import logging
import random
import time
from typing import List

from spider.config.models import DedupConfig
from spider.utils.logging import log_event


class RedisDeduper(object):
    def __init__(self, redis_client, cfg):
        # type: (object, DedupConfig) -> None
        self.redis = redis_client
        self.cfg = cfg
        self.logger = logging.getLogger("default_spider.dedup")

    async def is_duplicate(self, url):
        # type: (str) -> bool
        exists = await self.redis.hexists(self.cfg.redis_hash_key, url)
        if exists:
            log_event(self.logger, logging.DEBUG, "dedup.hit", redis_hash_key=self.cfg.redis_hash_key, url=url)
            return True

        now_ts = str(int(time.time()))
        await self.redis.hset(self.cfg.redis_hash_key, url, now_ts)
        log_event(self.logger, logging.DEBUG, "dedup.miss", redis_hash_key=self.cfg.redis_hash_key, url=url)

        if self.cfg.prune_probability > 0 and random.random() < self.cfg.prune_probability:
            removed = await self.prune_expired()
            log_event(self.logger, logging.DEBUG, "dedup.prune.triggered", removed=removed)
        return False

    async def prune_expired(self):
        # type: () -> int
        cutoff = int(time.time()) - self.cfg.ttl_days * 24 * 60 * 60
        cursor = 0
        removed = 0

        while True:
            cursor, data = await self.redis.hscan(self.cfg.redis_hash_key, cursor=cursor, count=200)
            to_delete = []  # type: List[str]
            for key, value in data.items():
                try:
                    if int(value) < cutoff:
                        to_delete.append(key)
                except (TypeError, ValueError):
                    to_delete.append(key)

            if to_delete:
                await self.redis.hdel(self.cfg.redis_hash_key, *to_delete)
                removed += len(to_delete)

            if cursor == 0:
                break

        if removed:
            log_event(self.logger, logging.INFO, "dedup.prune.done", redis_hash_key=self.cfg.redis_hash_key, removed=removed)
        return removed
