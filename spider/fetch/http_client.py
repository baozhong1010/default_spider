import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import chardet
import httpx

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


@dataclass
class FetchResponse:
    status_code: int
    text: str
    content: bytes
    headers: Dict[str, str]
    url: str


class HttpFetcher(object):
    def __init__(self, user_agent, max_connections, transport=None):
        # type: (str, int, Any) -> None
        limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections)
        self._client = httpx.AsyncClient(
            limits=limits,
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": user_agent},
        )
        self.logger = logging.getLogger("default_spider.http")

    async def close(self):
        # type: () -> None
        await self._client.aclose()

    async def fetch(self, req, cookie=None):
        # type: (FetchRequest, Optional[str]) -> FetchResponse
        last_error = None  # type: Optional[Exception]
        headers = dict(req.headers or {})
        if cookie:
            headers.setdefault("Cookie", cookie)

        for attempt in range(req.retries + 1):
            attempt_no = attempt + 1
            start = time.time()
            try:
                response = await self._client.request(
                    req.method.upper(),
                    req.url,
                    headers=headers,
                    params=req.params,
                    data=req.data,
                    json=req.json,
                    timeout=req.timeout_seconds,
                )
                text = self._decode_text(response)
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
                return FetchResponse(
                    status_code=response.status_code,
                    text=text,
                    content=response.content,
                    headers={k: v for k, v in response.headers.items()},
                    url=str(response.url),
                )
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
                await asyncio.sleep(req.retry_backoff_seconds * (attempt + 1))

        if last_error is None:
            raise RuntimeError("fetch failed without explicit exception")
        raise last_error

    @staticmethod
    def _decode_text(response):
        # type: (httpx.Response) -> str
        if response.encoding:
            return response.text
        if not response.content:
            return ""
        guess = chardet.detect(response.content).get("encoding") or "utf-8"
        try:
            return response.content.decode(guess, errors="ignore")
        except Exception:
            return response.content.decode("utf-8", errors="ignore")
