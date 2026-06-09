import json
import logging

from spider.config.models import OutputConfig
from spider.utils.logging import log_event


class RedisPublisher(object):
    def __init__(self, redis_client):
        self.redis = redis_client
        self.logger = logging.getLogger("default_spider.publisher")

    async def publish(self, payload, bid_type, output_cfg):
        # type: (dict, str, OutputConfig) -> dict
        if not output_cfg.enabled:
            log_event(self.logger, logging.DEBUG, "publish.skip", reason="output_disabled", bid_type=bid_type)
            return {"queue": None, "queue_length": None, "pushed": False}

        queue = output_cfg.queue_zhongbiao if bid_type == "zhongbiao" else output_cfg.queue_zhaobiao
        queue_length = await self.redis.lpush(queue, json.dumps(payload, ensure_ascii=False))
        log_event(self.logger, logging.DEBUG, "publish.ok", queue=queue, bid_type=bid_type, title=payload.get("标题", ""))
        return {"queue": queue, "queue_length": queue_length, "pushed": True}

    async def publish_failure(self, queue_key, payload):
        # type: (str, dict) -> None
        await self.redis.lpush(queue_key, json.dumps(payload, ensure_ascii=False))
        log_event(self.logger, logging.DEBUG, "publish.failure.ok", queue=queue_key, site_id=payload.get("site_id"))
