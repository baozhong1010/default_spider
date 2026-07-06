import logging
import os
import uuid
from urllib.parse import urlparse

from spider.config.models import OutputConfig, RequestConfig
from spider.fetch.http_client import FetchRequest, HttpFetcher
from spider.utils.helpers import ensure_dir, sanitize_filename
from spider.utils.logging import log_event


class AttachmentDownloader(object):
    def __init__(self, fetcher):
        # type: (HttpFetcher) -> None
        self.fetcher = fetcher
        self.logger = logging.getLogger("default_spider.attachment")

    async def download_many(
        self,
        attachment_urls,
        request_cfg,
        output_cfg,
        bid_type,
        cookie,
        max_bytes,
        site_id="",
        source_url="",
    ):
        # type: (list, RequestConfig, OutputConfig, str, str, int, str, str) -> list
        if not attachment_urls:
            return []

        root = output_cfg.attachment_dir_zhongbiao if bid_type == "zhongbiao" else output_cfg.attachment_dir_zhaobiao
        root_path = ensure_dir(root)

        log_event(
            self.logger,
            logging.DEBUG,
            "attachment.batch.start",
            site_id=site_id,
            source_url=source_url,
            total_urls=len(attachment_urls),
            bid_type=bid_type,
            output_dir=str(root_path),
        )

        output_files = []
        for url in attachment_urls:
            filename = self._build_filename(url)
            fetch_req = FetchRequest(
                url=url,
                method="GET",
                headers=request_cfg.headers,
                timeout_seconds=max(request_cfg.timeout_seconds, 100),
                retries=request_cfg.retries,
                retry_backoff_seconds=request_cfg.retry_backoff_seconds,
                verify_ssl=request_cfg.verify_ssl,
            )
            try:
                response = await self.fetcher.fetch(fetch_req, cookie=cookie)
            except Exception as exc:
                log_event(self.logger, logging.WARNING, "attachment.download.exception", site_id=site_id, url=url, error=str(exc))
                continue
            if response.status_code != 200:
                log_event(self.logger, logging.WARNING, "attachment.download.bad_status", site_id=site_id, url=url, status_code=response.status_code)
                continue
            if len(response.content) == 0 or len(response.content) > max_bytes:
                log_event(
                    self.logger,
                    logging.WARNING,
                    "attachment.download.invalid_size",
                    site_id=site_id,
                    url=url,
                    content_bytes=len(response.content),
                    max_bytes=max_bytes,
                )
                continue

            file_path = root_path / filename
            with file_path.open("wb") as f:
                f.write(response.content)

            output_files.append(str(file_path.resolve()))
            log_event(
                self.logger,
                logging.DEBUG,
                "attachment.download.ok",
                site_id=site_id,
                url=url,
                saved_path=str(file_path.resolve()),
                content_bytes=len(response.content),
            )

        log_event(
            self.logger,
            logging.DEBUG,
            "attachment.batch.end",
            site_id=site_id,
            source_url=source_url,
            downloaded=len(output_files),
            total_urls=len(attachment_urls),
        )
        return output_files

    @staticmethod
    def _build_filename(url):
        # type: (str) -> str
        parsed = urlparse(url)
        base = os.path.basename(parsed.path) or "附件"
        base = sanitize_filename(base)
        uid = str(uuid.uuid4()).replace("-", "")[:8]
        return "%s_%s" % (uid, base)
