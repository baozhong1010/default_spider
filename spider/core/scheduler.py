import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from spider.config.models import AppConfig
from spider.core.engine import SpiderEngine
from spider.utils.logging import log_event


def _spawn_background_task(coro):
    # type: (object) -> object
    create_task = getattr(asyncio, 'create_task', None)
    if create_task is not None:
        return create_task(coro)
    return asyncio.ensure_future(coro)


class SpiderScheduler(object):
    DEFAULT_RELOAD_INTERVAL_SECONDS = 30

    def __init__(self, app_config, engine, config_loader=None, reload_interval_seconds=None):
        # type: (AppConfig, SpiderEngine, object, object) -> None
        self.app_config = app_config
        self.engine = engine
        self.logger = logging.getLogger('default_spider.scheduler')
        self.scheduler = AsyncIOScheduler(timezone='Asia/Shanghai')
        self._config_loader = config_loader
        if reload_interval_seconds is None:
            reload_interval_seconds = self.DEFAULT_RELOAD_INTERVAL_SECONDS
        self._reload_interval_seconds = float(reload_interval_seconds)
        self._job_signatures = {}

    @staticmethod
    def _site_job_id(site_id):
        # type: (str) -> str
        return 'site:%s' % site_id

    @staticmethod
    def _build_trigger(site):
        # type: (object) -> object
        if site.schedule.cron:
            return CronTrigger.from_crontab(site.schedule.cron), 'cron:%s' % site.schedule.cron
        interval = site.schedule.interval_seconds or 600
        return IntervalTrigger(seconds=interval), 'interval:%s' % interval

    @staticmethod
    def _build_job_signature(site):
        # type: (object) -> tuple
        return (site.schedule.cron or '', site.schedule.interval_seconds or 600, site.schedule.jitter_seconds)

    def _iter_scheduled_sites(self):
        # type: () -> object
        for site in self.app_config.sites:
            if not site.enabled or not site.schedule.enabled:
                continue
            yield site

    def _sync_jobs(self):
        # type: () -> list
        active_sites = {}
        for site in self._iter_scheduled_sites():
            active_sites[site.id] = site

        active_ids = set(active_sites.keys())
        known_ids = set(self._job_signatures.keys())

        remove_job = getattr(self.scheduler, 'remove_job', None)
        for site_id in sorted(known_ids - active_ids):
            if remove_job is not None:
                try:
                    remove_job(self._site_job_id(site_id))
                except Exception:
                    pass
            self._job_signatures.pop(site_id, None)
            log_event(self.logger, logging.INFO, 'scheduler.job.removed', site_id=site_id)

        new_site_ids = []
        for site_id, site in active_sites.items():
            signature = self._build_job_signature(site)
            if self._job_signatures.get(site_id) == signature:
                continue

            trigger, trigger_desc = self._build_trigger(site)
            is_new_site = site_id not in self._job_signatures
            self.scheduler.add_job(
                self._run_site_job,
                trigger=trigger,
                args=[site.id],
                id=self._site_job_id(site.id),
                max_instances=1,
                coalesce=True,
                replace_existing=True,
                jitter=site.schedule.jitter_seconds,
            )
            self._job_signatures[site_id] = signature
            log_event(
                self.logger,
                logging.INFO,
                'scheduler.job.added',
                site_id=site.id,
                trigger=trigger_desc,
                jitter_seconds=site.schedule.jitter_seconds,
            )
            if is_new_site:
                new_site_ids.append(site_id)

        return new_site_ids

    def add_jobs(self):
        # type: () -> None
        self._sync_jobs()

    async def _run_site_job(self, site_id):
        # type: (str) -> None
        log_event(self.logger, logging.INFO, 'scheduler.job.start', site_id=site_id)
        try:
            await self.engine.run_site(site_id)
            log_event(self.logger, logging.INFO, 'scheduler.job.end', site_id=site_id)
        except Exception as exc:
            log_event(self.logger, logging.ERROR, 'site.job.error', site_id=site_id, error=str(exc))

    async def reload_config(self):
        # type: () -> list
        if self._config_loader is None:
            return []

        new_config = self._config_loader()
        self.app_config = new_config
        self.engine.app_config = new_config

        new_site_ids = self._sync_jobs()
        if new_site_ids:
            log_event(self.logger, logging.INFO, 'scheduler.config.reloaded', added_sites=new_site_ids)
            for site_id in new_site_ids:
                await self._run_site_job(site_id)
        return new_site_ids

    async def _run_startup_jobs(self):
        # type: () -> None
        # schedule 启动后先补跑一轮，避免首轮必须等待完整 interval 才开始抓取。
        for site in self._iter_scheduled_sites():
            await self._run_site_job(site.id)

    async def _reload_loop(self):
        # type: () -> None
        if self._config_loader is None or self._reload_interval_seconds <= 0:
            return

        while True:
            await asyncio.sleep(self._reload_interval_seconds)
            try:
                await self.reload_config()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(self.logger, logging.ERROR, 'scheduler.reload.failed', error=str(exc))

    async def run_forever(self):
        # type: () -> None
        self.add_jobs()
        self.scheduler.start()
        log_event(self.logger, logging.INFO, 'scheduler.started', jobs=len(self.scheduler.get_jobs()))
        await self._run_startup_jobs()

        reload_task = None
        if self._config_loader is not None and self._reload_interval_seconds > 0:
            reload_task = _spawn_background_task(self._reload_loop())

        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            if reload_task is not None:
                reload_task.cancel()
                try:
                    await reload_task
                except asyncio.CancelledError:
                    pass
            self.scheduler.shutdown(wait=False)
            log_event(self.logger, logging.INFO, 'scheduler.stopped')
