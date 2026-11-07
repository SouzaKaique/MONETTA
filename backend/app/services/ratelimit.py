"""Limite de requisições em memória; suficiente para um processo único do servidor."""
import time
from collections import defaultdict, deque

from flask import current_app


class RateLimiter:
    def __init__(self) -> None:
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, limit: int, window: int = 60) -> bool:
        now = time.monotonic()
        recent = self.hits[key]
        while recent and recent[0] <= now - window:
            recent.popleft()
        if len(recent) >= limit:
            return False
        recent.append(now)
        return True


def allow(key: str, limit: int, window: int = 60) -> bool:
    return current_app.extensions["rate_limiter"].allow(key, limit, window)
