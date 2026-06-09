import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # type: (logging.LogRecord) -> str
        payload = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }  # type: Dict[str, Any]
        if hasattr(record, "event"):
            payload["event"] = getattr(record, "event")
        if hasattr(record, "extra_data"):
            payload.update(getattr(record, "extra_data"))
        return json.dumps(payload, ensure_ascii=False)


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
    formatter = JsonFormatter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = DailyFileHandler(log_dir=log_dir, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(parsed_level)
    root.handlers[:] = []
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Keep third-party libraries from overwhelming spider debug logs.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.INFO)


def log_event(logger, level, event, **kwargs):
    # type: (logging.Logger, int, str, Any) -> None
    logger.log(level, event, extra={"event": event, "extra_data": kwargs})
