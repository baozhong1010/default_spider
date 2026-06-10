import asyncio
import datetime as dt
import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from spider.config.models import AppConfig, SiteConfig
from spider.core.pagination import build_list_request_tasks
from spider.core.state import CircuitState, SiteRateLimiter
from spider.extract.attachment_downloader import AttachmentDownloader
from spider.extract.detail_extractor import DetailExtractor
from spider.extract.list_extractor import ListExtractor, ListItem
from spider.extract.pdf_content import PdfBodyConverter, PdfBodyDetector
from spider.fetch.cookie_provider import RedisCookieProvider
from spider.fetch.http_client import FetchRequest, HttpFetcher
from spider.fetch.redis_client import create_redis_client
from spider.pipeline.area import detect_area
from spider.pipeline.classify import classify_bid_type
from spider.pipeline.dedup import RedisDeduper
from spider.pipeline.publisher import RedisPublisher
from spider.utils.helpers import normalize_date_yyyy_mm_dd
from spider.utils.logging import log_event
from spider.utils.metrics import SiteMetrics


class SpiderEngine(object):
    def __init__(
        self,
        app_config,
        redis_client=None,
        fetcher=None,
        local_test=False,
        local_test_output_file=None,
    ):
        # type: (AppConfig, object, Optional[HttpFetcher], bool, Optional[Path]) -> None
        self.app_config = app_config
        self.logger = logging.getLogger("default_spider.engine")
        self.local_test = local_test
        self._local_test_lock = asyncio.Lock()

        self.local_test_output_file = None  # type: Optional[Path]
        if self.local_test:
            default_path = Path(self.app_config.root_dir) / "local_test_outputs" / "results.jsonl"
            target = Path(local_test_output_file) if local_test_output_file else default_path
            self.local_test_output_file = target.resolve()
            self.local_test_output_file.parent.mkdir(parents=True, exist_ok=True)
            self.local_test_output_file.write_text("", encoding="utf-8")
            log_event(
                self.logger,
                logging.INFO,
                "local_test.enabled",
                output_file=str(self.local_test_output_file),
            )

        self._own_redis = redis_client is None
        self.redis = redis_client or create_redis_client(app_config.redis)

        self._own_fetcher = fetcher is None
        self.fetcher = fetcher or HttpFetcher(
            user_agent=app_config.runtime.user_agent,
            max_connections=app_config.runtime.max_connections,
        )

        self.cookie_provider = RedisCookieProvider(self.redis)
        self.publisher = RedisPublisher(self.redis)
        self.circuit_state = {}  # type: Dict[str, CircuitState]

    async def aclose(self):
        # type: () -> None
        if self._own_fetcher:
            await self.fetcher.close()
        if self._own_redis:
            redis_aclose = getattr(self.redis, "aclose", None)
            if redis_aclose is not None:
                await redis_aclose()

    async def run_all(self, site_ids=None):
        # type: (Optional[List[str]]) -> Dict[str, SiteMetrics]
        enabled_sites = [site for site in self.app_config.sites if site.enabled]
        if site_ids:
            selected = set(site_ids)
            enabled_sites = [site for site in enabled_sites if site.id in selected]

        result = {}  # type: Dict[str, SiteMetrics]
        for site in enabled_sites:
            result[site.id] = await self.run_site(site.id)
        return result

    async def run_site(self, site_id, override_entry_urls=None):
        # type: (str, Optional[List[str]]) -> SiteMetrics
        site = self._get_site(site_id)
        metrics = SiteMetrics(site_id=site.id)

        state = self.circuit_state.setdefault(site.id, CircuitState())
        if state.is_open():
            log_event(self.logger, logging.WARNING, "site.skipped.circuit_open", site_id=site.id)
            return metrics

        cookie = await self.cookie_provider.get_cookie(site.cookie)
        list_extractor = ListExtractor(site.list_extraction)
        detail_extractor = DetailExtractor(site.detail_extraction, site.attachments)
        pdf_detector = PdfBodyDetector()
        pdf_converter = PdfBodyConverter()
        deduper = RedisDeduper(self.redis, site.dedup)
        attachment_downloader = AttachmentDownloader(self.fetcher)
        limiter = SiteRateLimiter(site.limits.request_interval_seconds)

        entry_urls = override_entry_urls or site.entry_urls
        request_tasks = build_list_request_tasks(entry_urls, site.request, site.pagination)

        # ???????????????? worker ???????????????????
        detail_queue = asyncio.Queue()
        # ??????????????????????????????
        queued_detail_urls = set()
        queued_detail_urls_lock = asyncio.Lock()

        async def enqueue_detail_item(item):
            # type: (ListItem) -> None
            async with queued_detail_urls_lock:
                if item.url in queued_detail_urls:
                    return
                queued_detail_urls.add(item.url)
            await detail_queue.put(item)

        async def fetch_list(task):
            metrics.list_requests += 1
            log_event(
                self.logger,
                logging.INFO,
                "list.page.fetch.start",
                site_id=site.id,
                list_url=task.url,
                method=task.method,
            )
            await limiter.wait_turn()
            req = FetchRequest(
                url=task.url,
                method=task.method,
                headers=task.headers,
                params=task.params,
                data=task.data,
                json=task.json,
                timeout_seconds=site.request.timeout_seconds,
                retries=site.request.retries,
                retry_backoff_seconds=site.request.retry_backoff_seconds,
                verify_ssl=site.request.verify_ssl,
            )
            try:
                resp = await self.fetcher.fetch(req, cookie=cookie)
            except Exception as exc:
                metrics.list_request_failed += 1
                metrics.fail("list_fetch_exception")
                log_event(
                    self.logger,
                    logging.WARNING,
                    "list.page.fetch.failed",
                    site_id=site.id,
                    list_url=task.url,
                    reason="list_fetch_exception",
                    error=str(exc),
                )
                await self._record_failure(site, "list", task.url, str(exc), None)
                return

            if resp.status_code != 200:
                metrics.list_request_failed += 1
                metrics.fail("list_status_%s" % resp.status_code)
                log_event(
                    self.logger,
                    logging.WARNING,
                    "list.page.fetch.failed",
                    site_id=site.id,
                    list_url=task.url,
                    reason="list_status_%s" % resp.status_code,
                    status_code=resp.status_code,
                )
                await self._record_failure(site, "list", task.url, "status=%s" % resp.status_code, resp.text)
                return

            log_event(
                self.logger,
                logging.INFO,
                "list.page.fetch.done",
                site_id=site.id,
                list_url=task.url,
                status_code=resp.status_code,
                response_url=resp.url,
            )

            extracted = list_extractor.extract(resp.text, resp.url)
            for extracted_item in extracted:
                extracted_item.source_url = resp.url
            metrics.list_items += len(extracted)
            log_event(
                self.logger,
                logging.INFO,
                "list.page.parse.done",
                site_id=site.id,
                list_url=resp.url,
                item_count=len(extracted),
            )
            for extracted_item in extracted:
                await enqueue_detail_item(extracted_item)

        list_sem = asyncio.Semaphore(site.limits.max_concurrency)

        async def list_worker(task):
            async with list_sem:
                await fetch_list(task)

        async def process_detail(item):
            # type: (ListItem) -> None
            trace_id = self._build_trace_id(site.id, item.url)
            list_source_url = item.source_url or ""

            log_event(
                self.logger,
                logging.INFO,
                "record.trace.received",
                trace_id=trace_id,
                site_id=site.id,
                title=item.title,
                list_date=item.date,
                list_source_url=list_source_url,
                detail_url=item.url,
            )

            if not self.local_test and await deduper.is_duplicate(item.url):
                metrics.dedup_skipped += 1
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="redis",
                    push_success=False,
                    reason="dedup_skipped",
                )
                return

            metrics.detail_requests += 1
            log_event(
                self.logger,
                logging.INFO,
                "detail.fetch.start",
                trace_id=trace_id,
                site_id=site.id,
                detail_url=item.url,
                title=item.title,
            )
            await limiter.wait_turn()

            req = FetchRequest(
                url=item.url,
                method="GET",
                headers=site.request.headers,
                timeout_seconds=site.request.timeout_seconds,
                retries=site.request.retries,
                retry_backoff_seconds=site.request.retry_backoff_seconds,
                verify_ssl=site.request.verify_ssl,
            )

            try:
                resp = await self.fetcher.fetch(req, cookie=cookie)
            except Exception as exc:
                metrics.detail_request_failed += 1
                metrics.fail("detail_fetch_exception")
                log_event(
                    self.logger,
                    logging.WARNING,
                    "detail.fetch.failed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    reason="detail_fetch_exception",
                    error=str(exc),
                )
                await self._record_failure(site, "detail", item.url, str(exc), None, trace_id=trace_id)
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="redis",
                    push_success=False,
                    reason="detail_fetch_exception",
                    error=str(exc),
                )
                return

            if resp.status_code != 200:
                metrics.detail_request_failed += 1
                metrics.fail("detail_status_%s" % resp.status_code)
                log_event(
                    self.logger,
                    logging.WARNING,
                    "detail.fetch.failed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    reason="detail_status_%s" % resp.status_code,
                    status_code=resp.status_code,
                )
                await self._record_failure(site, "detail", item.url, "status=%s" % resp.status_code, resp.text, trace_id=trace_id)
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="redis",
                    push_success=False,
                    reason="detail_status_%s" % resp.status_code,
                )
                return

            log_event(
                self.logger,
                logging.INFO,
                "detail.fetch.done",
                trace_id=trace_id,
                site_id=site.id,
                detail_url=item.url,
                status_code=resp.status_code,
                content_type=resp.headers.get("Content-Type", ""),
            )
            log_event(
                self.logger,
                logging.INFO,
                "detail.parse.start",
                trace_id=trace_id,
                site_id=site.id,
                detail_url=item.url,
                content_type=resp.headers.get("Content-Type", ""),
            )

            pdf_detection = pdf_detector.detect(resp.url, headers=resp.headers, html_text=resp.text)
            attachment_urls = []
            pdf_content_used = False

            if pdf_detection.is_pdf_body and pdf_detection.pdf_url == resp.url:
                try:
                    content_html = pdf_converter.convert(resp.content, title=item.title)
                    pdf_content_used = True
                except Exception as exc:
                    metrics.extract_failed += 1
                    metrics.fail("pdf_parse_failed")
                    await self._record_failure(site, "extract", item.url, "pdf_parse_failed", None, trace_id=trace_id)
                    log_event(
                        self.logger,
                        logging.INFO,
                        "record.trace.completed",
                        trace_id=trace_id,
                        site_id=site.id,
                        detail_url=item.url,
                        push_target="redis",
                        push_success=False,
                        reason="pdf_parse_failed",
                        error=str(exc),
                    )
                    return
            else:
                parsed = detail_extractor.extract(resp.text, resp.url)
                content_html = parsed.content
                attachment_urls = list(parsed.attachment_urls)
                content_text = detail_extractor.to_plain_text(content_html)

                if len(content_text) < site.detail_extraction.min_content_length and pdf_detection.is_pdf_body and pdf_detection.pdf_url:
                    pdf_req = FetchRequest(
                        url=pdf_detection.pdf_url,
                        method="GET",
                        headers=dict({"Referer": item.url}, **site.request.headers),
                        timeout_seconds=site.request.timeout_seconds,
                        retries=site.request.retries,
                        retry_backoff_seconds=site.request.retry_backoff_seconds,
                        verify_ssl=site.request.verify_ssl,
                    )
                    try:
                        pdf_resp = await self.fetcher.fetch(pdf_req, cookie=cookie)
                    except Exception as exc:
                        metrics.extract_failed += 1
                        metrics.fail("pdf_download_failed")
                        await self._record_failure(site, "extract", item.url, "pdf_download_failed", resp.text, trace_id=trace_id)
                        log_event(
                            self.logger,
                            logging.INFO,
                            "record.trace.completed",
                            trace_id=trace_id,
                            site_id=site.id,
                            detail_url=item.url,
                            push_target="redis",
                            push_success=False,
                            reason="pdf_download_failed",
                            error=str(exc),
                        )
                        return

                    if pdf_resp.status_code != 200:
                        metrics.extract_failed += 1
                        metrics.fail("pdf_download_failed")
                        await self._record_failure(site, "extract", item.url, "pdf_download_failed", resp.text, trace_id=trace_id)
                        log_event(
                            self.logger,
                            logging.INFO,
                            "record.trace.completed",
                            trace_id=trace_id,
                            site_id=site.id,
                            detail_url=item.url,
                            push_target="redis",
                            push_success=False,
                            reason="pdf_download_failed",
                            status_code=pdf_resp.status_code,
                        )
                        return

                    try:
                        content_html = pdf_converter.convert(pdf_resp.content, title=item.title)
                        pdf_content_used = True
                    except Exception as exc:
                        metrics.extract_failed += 1
                        metrics.fail("pdf_parse_failed")
                        await self._record_failure(site, "extract", item.url, "pdf_parse_failed", resp.text, trace_id=trace_id)
                        log_event(
                            self.logger,
                            logging.INFO,
                            "record.trace.completed",
                            trace_id=trace_id,
                            site_id=site.id,
                            detail_url=item.url,
                            push_target="redis",
                            push_success=False,
                            reason="pdf_parse_failed",
                            error=str(exc),
                        )
                        return

                    attachment_urls = [
                        url for url in attachment_urls if url not in set(pdf_detection.matched_urls + [pdf_detection.pdf_url])
                    ]

            content_text = detail_extractor.to_plain_text(content_html)
            content_source = "pdf" if pdf_content_used else "html"
            if pdf_content_used and pdf_converter.is_text_corrupted(content_text):
                metrics.extract_failed += 1
                metrics.fail("pdf_text_corrupted")
                await self._record_failure(site, "extract", item.url, "pdf_text_corrupted", resp.text, trace_id=trace_id)
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="redis",
                    push_success=False,
                    reason="pdf_text_corrupted",
                )
                return

            if len(content_text) < site.detail_extraction.min_content_length:
                reason = "pdf_content_too_short" if pdf_detection.is_pdf_body else "content_too_short"
                metrics.extract_failed += 1
                metrics.fail(reason)
                await self._record_failure(site, "extract", item.url, reason, resp.text, trace_id=trace_id)
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="redis",
                    push_success=False,
                    reason=reason,
                )
                return

            log_event(
                self.logger,
                logging.INFO,
                "detail.parse.done",
                trace_id=trace_id,
                site_id=site.id,
                detail_url=item.url,
                content_source=content_source,
                content_length=len(content_text),
                attachment_count=len(attachment_urls),
            )

            bid_type = classify_bid_type(item.title, content_text, site.classification)
            area = detect_area(item.title, content_text, site.area_extraction)
            publish_date = normalize_date_yyyy_mm_dd(item.date, default_date=dt.date.today())

            attachment_files = await attachment_downloader.download_many(
                attachment_urls=attachment_urls,
                request_cfg=site.request,
                output_cfg=site.output,
                bid_type=bid_type,
                cookie=cookie,
                max_bytes=site.attachments.max_bytes,
                site_id=site.id,
                source_url=item.url,
            )

            payload = {
                "标题": item.title,
                "时间": publish_date,
                "原文链接": item.url,
                "附件": attachment_files,
                "正文内容": content_html,
                "地区": area,
            }

            target_queue = site.output.queue_zhongbiao if bid_type == "zhongbiao" else site.output.queue_zhaobiao
            log_event(
                self.logger,
                logging.INFO,
                "record.trace.ready",
                trace_id=trace_id,
                site_id=site.id,
                detail_url=item.url,
                list_source_url=list_source_url,
                bid_type=bid_type,
                publish_date=publish_date,
                area=area,
                attachments=len(attachment_files),
                content_length=len(content_text),
                target_queue=target_queue,
            )

            if self.local_test:
                await self._write_local_test_result(site.id, bid_type, payload)
                metrics.published += 1
                log_event(
                    self.logger,
                    logging.INFO,
                    "record.trace.completed",
                    trace_id=trace_id,
                    site_id=site.id,
                    detail_url=item.url,
                    push_target="local_test_file",
                    push_success=True,
                    output_file=str(self.local_test_output_file),
                )
            else:
                try:
                    publish_result = await self.publisher.publish(payload, bid_type, site.output)
                except Exception as exc:
                    metrics.fail("publish_exception")
                    await self._record_failure(site, "publish", item.url, str(exc), None, trace_id=trace_id)
                    log_event(
                        self.logger,
                        logging.ERROR,
                        "record.trace.completed",
                        trace_id=trace_id,
                        site_id=site.id,
                        detail_url=item.url,
                        push_target="redis",
                        push_success=False,
                        queue=target_queue,
                        reason="publish_exception",
                        error=str(exc),
                    )
                    return

                if publish_result.get("pushed"):
                    metrics.published += 1
                    log_event(
                        self.logger,
                        logging.INFO,
                        "record.trace.completed",
                        trace_id=trace_id,
                        site_id=site.id,
                        detail_url=item.url,
                        push_target="redis",
                        push_success=True,
                        queue=publish_result.get("queue"),
                        queue_length=publish_result.get("queue_length"),
                    )
                else:
                    metrics.fail("publish_disabled")
                    log_event(
                        self.logger,
                        logging.WARNING,
                        "record.trace.completed",
                        trace_id=trace_id,
                        site_id=site.id,
                        detail_url=item.url,
                        push_target="redis",
                        push_success=False,
                        queue=target_queue,
                        reason="output_disabled",
                    )

        async def detail_worker():
            # type: () -> None
            while True:
                item = await detail_queue.get()
                try:
                    # ? None ???????????????? worker ??????
                    if item is None:
                        return
                    await process_detail(item)
                finally:
                    detail_queue.task_done()

        detail_workers = [asyncio.create_task(detail_worker()) for _ in range(site.limits.max_concurrency)]

        await asyncio.gather(*(list_worker(task) for task in request_tasks))
        for _ in range(site.limits.max_concurrency):
            await detail_queue.put(None)
        await detail_queue.join()
        await asyncio.gather(*detail_workers)
        success = metrics.published > 0 or (metrics.list_items > 0 and metrics.detail_requests > 0)
        self._update_circuit(site.id, success)
        self._log_metrics(metrics)
        return metrics

    def _get_site(self, site_id):
        # type: (str) -> SiteConfig
        site_map = self.app_config.site_map()
        if site_id not in site_map:
            raise KeyError("Site not found: %s" % site_id)
        return site_map[site_id]

    def _update_circuit(self, site_id, success):
        # type: (str, bool) -> None
        state = self.circuit_state.setdefault(site_id, CircuitState())
        if success:
            state.consecutive_failures = 0
            state.open_until_ts = 0
            return

        state.consecutive_failures += 1
        threshold = self.app_config.runtime.circuit_breaker_threshold
        if state.consecutive_failures >= threshold:
            cooldown = self.app_config.runtime.circuit_breaker_cooldown_seconds
            state.open_until_ts = dt.datetime.now().timestamp() + cooldown
            log_event(
                self.logger,
                logging.WARNING,
                "site.circuit.open",
                site_id=site_id,
                consecutive_failures=state.consecutive_failures,
                cooldown_seconds=cooldown,
            )

    async def _record_failure(self, site, phase, url, reason, html_text, trace_id=None):
        # type: (SiteConfig, str, str, str, Optional[str], Optional[str]) -> None
        sample_dir = Path(self.app_config.runtime.failure_sample_dir)
        if not sample_dir.is_absolute():
            sample_dir = Path(self.app_config.root_dir) / sample_dir
        sample_dir.mkdir(parents=True, exist_ok=True)

        failure_id = uuid.uuid4().hex
        created_at = dt.datetime.now(dt.timezone.utc).isoformat()

        sample_file = None  # type: Optional[Path]
        if html_text:
            sample_file = sample_dir / ("%s_%s_%s.html" % (site.id, phase, failure_id))
            sample_file.write_text(html_text, encoding="utf-8", errors="ignore")

        payload = {
            "id": failure_id,
            "trace_id": trace_id,
            "site_id": site.id,
            "phase": phase,
            "url": url,
            "reason": reason,
            "sample_file": str(sample_file.resolve()) if sample_file else None,
            "created_at": created_at,
        }

        if not self.local_test:
            await self.publisher.publish_failure(self.app_config.runtime.failure_queue_key, payload)

        log_event(
            self.logger,
            logging.WARNING,
            "site.failure.recorded",
            pushed_to_redis=not self.local_test,
            **payload
        )

    async def _write_local_test_result(self, site_id, bid_type, payload):
        # type: (str, str, dict) -> None
        if not self.local_test_output_file:
            raise RuntimeError("local_test_output_file is not initialized")

        record = {
            "site_id": site_id,
            "bid_type": bid_type,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload": payload,
        }

        async with self._local_test_lock:
            with self.local_test_output_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _log_metrics(self, metrics):
        # type: (SiteMetrics) -> None
        topn = self.app_config.runtime.metrics_log_topn
        top_failures = metrics.failure_reasons.most_common(topn)
        log_event(
            self.logger,
            logging.INFO,
            "site.metrics",
            site_id=metrics.site_id,
            list_requests=metrics.list_requests,
            list_request_failed=metrics.list_request_failed,
            list_items=metrics.list_items,
            detail_requests=metrics.detail_requests,
            detail_request_failed=metrics.detail_request_failed,
            dedup_skipped=metrics.dedup_skipped,
            extract_failed=metrics.extract_failed,
            published=metrics.published,
            failure_topn=top_failures,
        )
    @staticmethod
    def _build_trace_id(site_id, detail_url):
        # type: (str, str) -> str
        raw = "%s|%s" % (site_id, detail_url)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


