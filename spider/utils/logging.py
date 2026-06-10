import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


FIELD_LABELS = {
    "site_id": "站点",
    "detail_url": "详情页",
    "list_url": "列表页",
    "list_source_url": "列表来源",
    "output_file": "输出文件",
    "queue": "队列",
    "queue_length": "队列长度",
    "reason": "原因",
    "error": "错误",
    "phase": "阶段",
    "sample_file": "样本文件",
    "trace_id": "追踪ID",
    "target_queue": "目标队列",
    "content_length": "正文长度",
    "attachments": "附件数",
    "status_code": "状态码",
    "content_type": "响应类型",
    "method": "请求方式",
}

REASON_TEXT = {
    "dedup_skipped": "该记录已去重，跳过处理",
    "detail_fetch_exception": "抓取详情页时发生异常",
    "list_fetch_exception": "抓取列表页时发生异常",
    "publish_exception": "写入 Redis 时发生异常",
    "output_disabled": "输出开关已关闭，未执行入库",
    "pdf_download_failed": "PDF 正文下载失败",
    "pdf_parse_failed": "PDF 正文解析失败",
    "pdf_content_too_short": "PDF 正文过短，未达到最小长度",
    "pdf_text_corrupted": "PDF 文本层损坏，提取结果疑似乱码",
    "content_too_short": "正文过短，未达到最小长度",
}


def _has_value(value):
    # type: (Any) -> bool
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return str(value).strip() != ""


def _stringify_value(value):
    # type: (Any) -> str
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(str(item) for item in value)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            parts.append("%s:%s" % (key, item))
        return "、".join(parts)
    return str(value)


def _site_prefix(site_id):
    # type: (Optional[str]) -> str
    return "站点[%s]" % site_id if site_id else "当前任务"


def _reason_text(reason):
    # type: (Any) -> str
    text = str(reason or "")
    if not text:
        return ""
    if text in REASON_TEXT:
        return REASON_TEXT[text]
    if text.startswith("detail_status_"):
        return "详情页返回异常状态码：%s" % text.split("detail_status_", 1)[1]
    if text.startswith("list_status_"):
        return "列表页返回异常状态码：%s" % text.split("list_status_", 1)[1]
    return text


def _pairs_text(pairs):
    # type: (List[Tuple[str, Any]]) -> str
    output = []
    for label, value in pairs:
        if not _has_value(value):
            continue
        output.append("%s：%s" % (label, _stringify_value(value)))
    return "，".join(output)


def _failure_topn_text(topn):
    # type: (Any) -> str
    if not topn:
        return "无"

    parts = []
    for reason, count in topn:
        parts.append("%s x%s" % (_reason_text(reason), count))
    return "；".join(parts) if parts else "无"


def render_event_message(event, data):
    # type: (str, Dict[str, Any]) -> str
    site_prefix = _site_prefix(data.get("site_id"))

    if event == "local_test.enabled":
        return "%s已开启本地测试模式，结果将写入：%s" % (site_prefix, data.get("output_file"))

    if event == "cli.command.start":
        return "开始执行命令，%s" % _pairs_text(
            [
                ("命令", data.get("command")),
                ("项目根目录", data.get("root")),
                ("本地测试", "是" if data.get("local_test") else "否"),
            ]
        )

    if event == "cli.command.end":
        return "命令执行结束，%s" % _pairs_text(
            [
                ("命令", data.get("command")),
                ("耗时秒", data.get("duration_seconds")),
            ]
        )

    if event == "site.skipped.circuit_open":
        return "%s已触发熔断，当前轮次跳过抓取" % site_prefix

    if event == "site.circuit.open":
        return "%s连续失败次数达到阈值，开启熔断，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("连续失败次数", data.get("consecutive_failures")),
                    ("冷却秒数", data.get("cooldown_seconds")),
                ]
            ),
        )

    if event == "list.page.fetch.start":
        return "%s开始抓取列表页，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("列表页", data.get("list_url")),
                    ("请求方式", data.get("method")),
                ]
            ),
        )

    if event == "list.page.fetch.done":
        return "%s列表页抓取完成，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("列表页", data.get("list_url")),
                    ("状态码", data.get("status_code")),
                    ("最终地址", data.get("response_url")),
                ]
            ),
        )

    if event == "list.page.fetch.failed":
        return "%s列表页抓取失败，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("列表页", data.get("list_url")),
                    ("原因", _reason_text(data.get("reason"))),
                    ("错误", data.get("error")),
                ]
            ),
        )

    if event == "list.page.parse.done":
        return "%s列表页解析完成，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("列表页", data.get("list_url")),
                    ("提取记录数", data.get("item_count")),
                ]
            ),
        )

    if event == "record.trace.received":
        return "%s列表解析到记录，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("标题", data.get("title")),
                    ("日期", data.get("list_date")),
                    ("详情页", data.get("detail_url")),
                    ("列表来源", data.get("list_source_url")),
                    ("追踪ID", data.get("trace_id")),
                ]
            ),
        )

    if event == "detail.fetch.start":
        return "%s开始抓取详情页，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("标题", data.get("title")),
                    ("追踪ID", data.get("trace_id")),
                ]
            ),
        )

    if event == "detail.fetch.done":
        return "%s详情页抓取完成，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("状态码", data.get("status_code")),
                    ("响应类型", data.get("content_type")),
                ]
            ),
        )

    if event == "detail.fetch.failed":
        return "%s详情页抓取失败，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("原因", _reason_text(data.get("reason"))),
                    ("错误", data.get("error")),
                ]
            ),
        )

    if event == "detail.parse.start":
        return "%s开始解析详情页，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("响应类型", data.get("content_type")),
                ]
            ),
        )

    if event == "detail.parse.done":
        content_source = "PDF 正文" if str(data.get("content_source") or "").lower() == "pdf" else "HTML 正文"
        return "%s详情页解析完成，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("正文来源", content_source),
                    ("正文长度", data.get("content_length")),
                    ("附件候选数", data.get("attachment_count")),
                ]
            ),
        )

    if event == "record.trace.ready":
        return "%s记录已整理完成，准备入库，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("分类", data.get("bid_type")),
                    ("发布时间", data.get("publish_date")),
                    ("地区", data.get("area")),
                    ("附件数", data.get("attachments")),
                    ("正文长度", data.get("content_length")),
                    ("目标队列", data.get("target_queue")),
                ]
            ),
        )

    if event == "record.trace.completed":
        if data.get("push_success"):
            if data.get("push_target") == "local_test_file":
                return "%s写入本地测试结果成功，%s" % (
                    site_prefix,
                    _pairs_text(
                        [
                            ("详情页", data.get("detail_url")),
                            ("输出文件", data.get("output_file")),
                            ("追踪ID", data.get("trace_id")),
                        ]
                    ),
                )
            return "%s入库成功，%s" % (
                site_prefix,
                _pairs_text(
                    [
                        ("详情页", data.get("detail_url")),
                        ("队列", data.get("queue")),
                        ("队列长度", data.get("queue_length")),
                        ("追踪ID", data.get("trace_id")),
                    ]
                ),
            )

        return "%s处理结束但未入库，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("详情页", data.get("detail_url")),
                    ("原因", _reason_text(data.get("reason"))),
                    ("目标", data.get("push_target")),
                    ("队列", data.get("queue")),
                    ("错误", data.get("error")),
                    ("追踪ID", data.get("trace_id")),
                ]
            ),
        )

    if event == "site.failure.recorded":
        return "%s已记录失败样本，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("阶段", data.get("phase")),
                    ("地址", data.get("url")),
                    ("原因", _reason_text(data.get("reason"))),
                    ("样本文件", data.get("sample_file")),
                    ("已推送失败队列", "是" if data.get("pushed_to_redis") else "否"),
                    ("追踪ID", data.get("trace_id")),
                ]
            ),
        )

    if event == "site.metrics":
        return "%s本轮抓取完成，%s" % (
            site_prefix,
            _pairs_text(
                [
                    ("列表请求", data.get("list_requests")),
                    ("列表失败", data.get("list_request_failed")),
                    ("列表记录数", data.get("list_items")),
                    ("详情请求", data.get("detail_requests")),
                    ("详情失败", data.get("detail_request_failed")),
                    ("去重跳过", data.get("dedup_skipped")),
                    ("提取失败", data.get("extract_failed")),
                    ("成功入库", data.get("published")),
                    ("主要失败原因", _failure_topn_text(data.get("failure_topn"))),
                ]
            ),
        )

    extra_pairs = []  # type: List[Tuple[str, Any]]
    for key, value in data.items():
        label = FIELD_LABELS.get(key, key)
        extra_pairs.append((label, value))

    extras_text = _pairs_text(extra_pairs)
    if extras_text:
        return "%s：%s" % (event, extras_text)
    return event


class PlainTextFormatter(logging.Formatter):
    def format(self, record):
        # type: (logging.LogRecord) -> str
        event = getattr(record, "event", None)
        extra_data = getattr(record, "extra_data", {}) or {}
        if event:
            message = render_event_message(event, extra_data)
        else:
            message = record.getMessage()
        timestamp = self.formatTime(record, datefmt="%Y-%m-%d %H:%M:%S")
        return "【%s】%s" % (timestamp, message)


class DailyFileHandler(logging.Handler):
    def __init__(self, log_dir, encoding="utf-8"):
        # type: (Optional[str], str) -> None
        super(DailyFileHandler, self).__init__()
        self.log_dir = Path(log_dir or "log")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.encoding = encoding
        self._current_date = ""
        self._stream = None

    def _ensure_stream(self):
        # type: () -> None
        date_text = datetime.now().strftime("%Y-%m-%d")
        if self._stream is not None and date_text == self._current_date:
            return

        if self._stream is not None:
            self._stream.close()

        self._current_date = date_text
        file_path = self.log_dir / ("%s.log" % date_text)
        self._stream = file_path.open("a", encoding=self.encoding)

    def emit(self, record):
        # type: (logging.LogRecord) -> None
        try:
            self._ensure_stream()
            if self._stream is None:
                return
            message = self.format(record)
            self._stream.write(message + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        # type: () -> None
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            super(DailyFileHandler, self).close()


def parse_log_level(level):
    # type: (Any) -> int
    if isinstance(level, int):
        return level

    text = str(level or "INFO").strip().upper()
    mapping = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
    }
    return mapping.get(text, logging.INFO)


def setup_logging(level=logging.INFO, log_dir=None):
    # type: (Any, Optional[str]) -> None
    parsed_level = parse_log_level(level)
    formatter = PlainTextFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = DailyFileHandler(log_dir=log_dir, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(parsed_level)
    root.handlers[:] = []
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # 第三方库日志过多会淹没抓取链路，所以默认只保留 warning 以上。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def log_event(logger, level, event, **kwargs):
    # type: (logging.Logger, int, str, Any) -> None
    logger.log(level, event, extra={"event": event, "extra_data": kwargs})
