import logging
from typing import Optional

from spider.config.models import CookieConfig
from spider.utils.logging import log_event


class RedisCookieProvider(object):
    def __init__(self, redis_client):
        self.redis = redis_client
        self.logger = logging.getLogger("default_spider.cookie")

    async def get_cookie(self, cookie_cfg):
        # type: (CookieConfig) -> Optional[str]
        if not cookie_cfg.enabled or not cookie_cfg.redis_hash_key:
            log_event(self.logger, logging.DEBUG, "cookie.skip", enabled=cookie_cfg.enabled)
            return None

        value = await self.redis.hget(cookie_cfg.redis_hash_key, cookie_cfg.redis_field)
        if value is None and cookie_cfg.redis_field != "default":
            value = await self.redis.hget(cookie_cfg.redis_hash_key, "default")
            log_event(
                self.logger,
                logging.DEBUG,
                "cookie.fallback_default",
                redis_hash_key=cookie_cfg.redis_hash_key,
                requested_field=cookie_cfg.redis_field,
            )

        log_event(
            self.logger,
            logging.DEBUG,
            "cookie.loaded",
            redis_hash_key=cookie_cfg.redis_hash_key,
            field=cookie_cfg.redis_field,
            found=bool(value),
        )
        return value
