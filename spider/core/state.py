import asyncio
import time
from dataclasses import dataclass


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    open_until_ts: float = 0.0

    def is_open(self):
        # type: () -> bool
        return self.open_until_ts > time.time()


class SiteRateLimiter(object):
    def __init__(self, interval_seconds):
        # type: (float) -> None
        self.interval = max(0.0, interval_seconds)
        self._lock = asyncio.Lock()
        self._next_ts = 0.0

    async def wait_turn(self):
        # type: () -> None
        if self.interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if now < self._next_ts:
                await asyncio.sleep(self._next_ts - now)
            self._next_ts = max(now, self._next_ts) + self.interval
