import asyncio
import http.cookiejar
import json as _json
import logging
import re
import ssl as _ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import chardet

from spider.utils.logging import log_event


@dataclass
class FetchRequest:
    url: str
    method: str = "GET"
    headers: Optional[Dict[str, str]] = None
    params: Optional[Dict[str, Any]] = None
    data: Optional[Union[Dict[str, Any], str]] = None
    json: Optional[Union[Dict[str, Any], List[Any]]] = None
    timeout_seconds: float = 20
    retries: int = 2
    retry_backoff_seconds: float = 0.6
    verify_ssl: bool = False
    # 可选加解密对象：提供 encrypt(inner)->str 与 decrypt(text)->str
    crypto: Optional[object] = None
    # 用无头 Chrome 渲染（针对 JS 反爬）
    use_chrome: bool = False


@dataclass
class FetchResponse:
    status_code: int
    text: str
    content: bytes
    headers: Dict[str, str]
    url: str


class HttpFetcher(object):
    """基于标准库 urllib 的异步 HTTP 抓取器。

    说明：某些老环境（如 Python 3.6 + OpenSSL 1.0.2）下 httpx/httpcore 的
    MemoryBIO TLS 握手会失败，而标准库 urllib（wrap_socket）可正常工作。
    因此这里统一用 urllib 执行同步请求，再放到线程池里保持异步并发语义。
    """

    def __init__(self, user_agent, max_connections, transport=None):
        # type: (str, int, Any) -> None
        self.user_agent = user_agent
        self._executor = ThreadPoolExecutor(max_workers=max(4, int(max_connections)))
        # CookieJar：自动处理站点会话/反爬 Cookie（如首次 302 下发 CT6T/CT6TS，需带回才能取到 200）
        self._cookie_jar = http.cookiejar.CookieJar()
        self.logger = logging.getLogger("default_spider.http")

    async def close(self):
        # type: () -> None
        self._executor.shutdown(wait=False)

    async def fetch(self, req, cookie=None):
        # type: (FetchRequest, Optional[str]) -> FetchResponse
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._fetch_sync, req, cookie)

    def _fetch_sync(self, req, cookie=None):
        # type: (FetchRequest, Optional[str]) -> FetchResponse
        last_error = None  # type: Optional[Exception]
        headers = dict(req.headers or {})
        if cookie:
            headers.setdefault("Cookie", cookie)

        for attempt in range(req.retries + 1):
            attempt_no = attempt + 1
            start = time.time()
            try:
                if req.use_chrome:
                    response = self._fetch_chrome(req)
                else:
                    response = self._do_fetch(req, headers)
                # 少数接口会偶发返回 200 + 空响应体（连接被中断但状态码正常），
                # 这种响应后续必然解析失败，当作可重试错误处理。
                if (
                    response.status_code == 200
                    and not response.content
                    and attempt < req.retries
                ):
                    raise RuntimeError("empty response body on HTTP 200 (retrying)")
                cost = round(time.time() - start, 3)
                log_event(
                    self.logger,
                    logging.DEBUG,
                    "http.fetch.ok",
                    method=req.method.upper(),
                    url=req.url,
                    attempt=attempt_no,
                    retries=req.retries,
                    status_code=response.status_code,
                    duration_seconds=cost,
                    content_bytes=len(response.content),
                )
                return response
            except Exception as exc:
                last_error = exc
                cost = round(time.time() - start, 3)
                should_retry = attempt < req.retries
                log_event(
                    self.logger,
                    logging.WARNING if should_retry else logging.ERROR,
                    "http.fetch.exception",
                    method=req.method.upper(),
                    url=req.url,
                    attempt=attempt_no,
                    retries=req.retries,
                    duration_seconds=cost,
                    retrying=should_retry,
                    error=str(exc),
                )
                if attempt >= req.retries:
                    break
                time.sleep(req.retry_backoff_seconds * (attempt + 1))

        if last_error is None:
            raise RuntimeError("fetch failed without explicit exception")
        raise last_error

    _CHROME_CANDIDATES = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]

    @staticmethod
    def _find_chrome():
        import os
        for candidate in HttpFetcher._CHROME_CANDIDATES:
            if os.path.exists(candidate):
                return candidate
        return None

    def _fetch_chrome(self, req):
        # type: (FetchRequest) -> FetchResponse
        import shutil
        import subprocess
        import tempfile

        chrome = self._find_chrome()
        if chrome is None:
            raise RuntimeError("No Chrome/Edge binary found for use_chrome fetch")

        profile = tempfile.mkdtemp(prefix="spider_chrome_")
        try:
            cmd = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
                "--user-agent=" + self.user_agent,
                "--user-data-dir=" + profile,
                "--dump-dom",
                "--virtual-time-budget=12000",
                req.url,
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            out, _ = proc.communicate(timeout=max(req.timeout_seconds + 30, 60))
            text = self._decode_bytes(out, "text/html")
            return FetchResponse(status_code=200, text=text, content=out, headers={}, url=req.url)
        finally:
            shutil.rmtree(profile, ignore_errors=True)

    def _do_fetch(self, req, headers):
        # type: (FetchRequest, Dict[str, str]) -> FetchResponse
        url = req.url
        if req.params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(req.params)

        body = None  # type: Optional[bytes]
        headers.setdefault("User-Agent", self.user_agent)

        if req.crypto is not None and req.json is not None:
            body = req.crypto.encrypt(req.json).encode("utf-8")
            headers.setdefault("encrypt", "1")
            headers.setdefault("Content-Type", "application/json; charset=UTF-8")
        elif req.json is not None:
            body = _json.dumps(req.json, ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=UTF-8")
        elif req.data is not None:
            if isinstance(req.data, dict):
                body = urllib.parse.urlencode(req.data).encode("utf-8")
                headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
            elif isinstance(req.data, str):
                body = req.data.encode("utf-8")
            else:
                body = req.data

        method = req.method.upper()
        if method != "GET" and body is None:
            body = b""

        ssl_context = None
        if not req.verify_ssl:
            ssl_context = _ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = _ssl.CERT_NONE

        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        handlers = [urllib.request.HTTPCookieProcessor(self._cookie_jar)]
        if ssl_context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
        opener = urllib.request.build_opener(*handlers)
        try:
            resp = opener.open(request, timeout=req.timeout_seconds)
        except urllib.error.HTTPError as exc:
            resp = exc

        status_code = resp.getcode()
        content = resp.read()
        content_type = ""
        raw_headers = {}
        try:
            raw_headers = {k: v for k, v in resp.headers.items()}
            content_type = raw_headers.get("Content-Type", "")
        except Exception:
            pass

        text = self._decode_bytes(content, content_type)
        if req.crypto is not None and req.json is not None:
            text = req.crypto.decrypt(text)

        return FetchResponse(
            status_code=status_code,
            text=text,
            content=content,
            headers=raw_headers,
            url=resp.geturl(),
        )

    @staticmethod
    def _decode_bytes(content, content_type=""):
        # type: (bytes, str) -> str
        if not content:
            return ""

        charset = None
        match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type or "", flags=re.I)
        if match:
            charset = match.group(1)
        if charset:
            try:
                return content.decode(charset, errors="ignore")
            except Exception:
                pass

        guess = chardet.detect(content).get("encoding") or "utf-8"
        try:
            return content.decode(guess, errors="ignore")
        except Exception:
            return content.decode("utf-8", errors="ignore")
