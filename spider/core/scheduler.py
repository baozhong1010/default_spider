import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from spider.config.models import AppConfig
from spider.core.engine import SpiderEngine
from spider.utils.logging import log_event


class SpiderScheduler(object):
    def __init__(self, app_config, engine):
        # type: (AppConfig, SpiderEngine) -> None
        self.app_config = app_config
        self.engine = engine
        self.logger = logging.getLogger("default_spider.scheduler")
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    def add_jobs(self):
        # type: () -> None
        for site in self.app_config.sites:
            if not site.enabled or not site.schedule.enabled:
                continue

            if site.schedule.cron:
                trigger = CronTrigger.from_crontab(site.schedule.cron)
                trigger_desc = "cron:%s" % site.schedule.cron
            else:
                interval = site.schedule.interval_seconds or 600
                trigger = IntervalTrigger(seconds=interval)
                trigger_desc = "interval:%s" % interval

            self.scheduler.add_job(
                self._run_site_job,
                trigger=trigger,
                args=[site.id],
                id="site:%s" % site.id,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                jitter=site.schedule.jitter_seconds,
            )
            log_event(
                self.logger,
                logging.INFO,
                "scheduler.job.added",
                site_id=site.id,
                trigger=trigger_desc,
                jitter_seconds=site.schedule.jitter_seconds,
            )

    async def _run_site_job(self, site_id):
        # type: (str) -> None
        log_event(self.logger, logging.INFO, "scheduler.job.start", site_id=site_id)
        try:
            await self.engine.run_site(site_id)
            log_event(self.logger, logging.INFO, "scheduler.job.end", site_id=site_id)
        except Exception as exc:
            log_event(self.logger, logging.ERROR, "site.job.error", site_id=site_id, error=str(exc))

    async def run_forever(self):
        # type: () -> None
        self.add_jobs()
        self.scheduler.start()
        log_event(self.logger, logging.INFO, "scheduler.started", jobs=len(self.scheduler.get_jobs()))

        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            self.scheduler.shutdown(wait=False)
            log_event(self.logger, logging.INFO, "scheduler.stopped")
