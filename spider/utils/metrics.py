from collections import Counter
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SiteMetrics:
    site_id: str
    list_requests: int = 0
    list_request_failed: int = 0
    list_items: int = 0
    detail_requests: int = 0
    detail_request_failed: int = 0
    dedup_skipped: int = 0
    published: int = 0
    extract_failed: int = 0
    failure_reasons: Counter = field(default_factory=Counter)

    def fail(self, reason):
        # type: (str) -> None
        self.failure_reasons[reason] += 1
