import logging
import os
import re
import uuid
from urllib.parse import quote, unquote_to_bytes, urlparse

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
        attachment_names=None,
        reject_login_pages=True,
    ):
        # type: (list, RequestConfig, OutputConfig, str, str, int, str, str, Optional[list], bool) -> list
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
        for i, url in enumerate(attachment_urls):
            # 源站 href 可能含未编码空格或中文（对象名），urllib 会因此失败，统一做百分号编码
            url = self._encode_url(url or "")
            name = ""
            if attachment_names and i < len(attachment_names):
                name = attachment_names[i] or ""
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

            # 附件接口对匿名请求常返回 200 + 登录页/错误页 HTML，校验后跳过，避免落盘假附件
            if reject_login_pages and self._looks_like_login_page(response):
                log_event(
                    self.logger,
                    logging.WARNING,
                    "attachment.download.skipped_login_page",
                    site_id=site_id,
                    url=url,
                    content_bytes=len(response.content),
                    content_type=response.headers.get("Content-Type", ""),
                )
                continue

            # 文件名优先级：配置的 filename_selectors > 响应 Content-Disposition > URL 末段
            response_name = self._filename_from_headers(response.headers)
            filename = self._build_filename(url, name or response_name)

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
    def _encode_url(url):
        # type: (str) -> str
        """百分号编码 URL 中的空格式/中文等非安全字符。

        保留 URL 结构字符与**已有的 %XX 转义**（safe 里含 %），因此重复调用是幂等的；
        不做这一步时，含中文对象名（未编码）的附件 URL 会让 urllib 抛
        `'ascii' codec can't encode characters`。
        """
        if not url:
            return url
        try:
            return quote(url, safe=":/?#[]@!$&'()*+,;=%~")
        except Exception:
            return url

    @staticmethod
    def _looks_like_login_page(response):
        # type: (object) -> bool
        """判断响应是否是「登录页/错误页」而非真实附件。

        判据：文本类响应（html/json）+ 含两组以上登录特征词；
        若响应带 Content-Disposition 文件名，则认为服务端确实在回附件，不拦截。
        """
        headers = getattr(response, "headers", None) or {}
        content_type = ""
        try:
            for key, value in headers.items():
                if str(key).lower() == "content-type":
                    content_type = (value or "").lower()
                    break
        except Exception:
            content_type = ""

        if content_type and ("html" not in content_type and "json" not in content_type):
            return False
        if AttachmentDownloader._filename_from_headers(headers):
            return False

        text = (getattr(response, "text", "") or "")[:8000].lower()
        if not text:
            return False
        if "<form" not in text and "login" not in text:
            return False

        score = 0
        for marker in ("<form", "login", "password", "passwd", "验证码", "captcha",
                       "请登录", "用户登录", "身份认证", "统一认证", "sso", "session is time out"):
            if marker in text:
                score += 1
        return score >= 2

    @staticmethod
    def _filename_from_headers(headers):
        # type: (dict) -> str
        """从响应头 Content-Disposition 解析真实文件名（源站附件常是 fileid 形式、无后缀）。"""
        if not headers:
            return ""
        raw_header = ""
        try:
            for key, value in headers.items():
                if str(key).lower() == "content-disposition":
                    raw_header = value or ""
                    break
        except Exception:
            return ""
        if not raw_header:
            return ""

        # RFC 5987: filename*=UTF-8''%E4%B8%AD%E6%96%87.doc
        match = re.search(r"filename\*\s*=\s*([^;]+)", raw_header, flags=re.I)
        if match:
            raw = match.group(1).strip().strip('"')
            charset = "utf-8"
            payload = raw
            if "''" in raw:
                charset, payload = raw.split("''", 1)
            name = AttachmentDownloader._decode_percent_name(payload, charset)
            if name:
                return name

        match = re.search(r'filename\s*=\s*"?([^";]+)"?', raw_header, flags=re.I)
        if match:
            candidate = match.group(1).strip()
            # 不少源站把中文名做了 URL 编码（如 %E7%AB%9E%E4%BA%89...）
            if "%" in candidate:
                decoded = AttachmentDownloader._decode_percent_name(candidate, "utf-8")
                if decoded:
                    return decoded
            return AttachmentDownloader._decode_header_text(candidate)
        return ""

    @staticmethod
    def _decode_percent_name(payload, charset="utf-8"):
        # type: (str, str) -> str
        try:
            data = unquote_to_bytes(payload)
        except Exception:
            data = (payload or "").encode("latin-1", "ignore")
        if not data:
            return ""
        encodings = [charset, "utf-8", "gbk"]
        for encoding in encodings:
            if not encoding:
                continue
            try:
                decoded = data.decode(encoding)
                if decoded:
                    return decoded
            except Exception:
                continue
        return ""

    @staticmethod
    def _decode_header_text(value):
        # type: (str) -> str
        """响应头按 latin-1 解码时中文会变乱码，这里尝试按 utf-8/gbk 还原。"""
        value = (value or "").strip()
        if not value:
            return ""
        try:
            raw = value.encode("latin-1", errors="strict")
        except Exception:
            return value
        for encoding in ("utf-8", "gbk"):
            try:
                decoded = raw.decode(encoding)
                if decoded:
                    return decoded
            except Exception:
                continue
        return value

    @staticmethod
    def _build_filename(url, name=""):
        # type: (str, str) -> str
        if name:
            base = sanitize_filename(name)
        else:
            parsed = urlparse(url)
            base = os.path.basename(parsed.path) or "附件"
            base = sanitize_filename(base)
        uid = str(uuid.uuid4()).replace("-", "")[:8]
        return "%s_%s" % (uid, base)
