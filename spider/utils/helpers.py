import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional, Union
from urllib.parse import urljoin


SAFE_FILENAME_RE = re.compile(r"[^\w\-.\u4e00-\u9fff]+")


_DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y.%m.%d %H:%M",
]


def normalize_space(text):
    # type: (str) -> str
    return re.sub(r"\s+", " ", text or "").strip()


def resolve_url(base_url, maybe_relative):
    # type: (str, str) -> str
    return urljoin(base_url, maybe_relative)


def looks_like_attachment(url, allowed_exts):
    # type: (str, Iterable[str]) -> bool
    lower = url.lower()
    return any(lower.endswith(ext.lower()) for ext in allowed_exts)


def sanitize_filename(name, default="附件"):
    # type: (str, str) -> str
    cleaned = SAFE_FILENAME_RE.sub("_", name).strip("._")
    return cleaned or default


def ensure_dir(path):
    # type: (Union[str, Path]) -> Path
    path_obj = Path(path)
    path_obj.mkdir(parents=True, exist_ok=True)
    return path_obj


def ts_seconds():
    # type: () -> int
    return int(time.time())


def unix_day_seconds(days):
    # type: (int) -> int
    return days * 24 * 60 * 60


def safe_unlink(path):
    # type: (Union[str, Path]) -> None
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def normalize_date_yyyy_mm_dd(raw, default_date=None):
    # type: (Optional[str], Optional[date]) -> str
    if default_date is None:
        default_date = date.today()
    if not raw:
        return default_date.isoformat()

    value = normalize_space(raw)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    m = re.search(r"(\d{4})\D?(\d{1,2})\D?(\d{1,2})", value)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(y, mo, d).isoformat()
        except ValueError:
            return default_date.isoformat()

    return default_date.isoformat()
