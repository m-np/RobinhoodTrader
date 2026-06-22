"""
In-memory price cache for watchlist tickers.

Populated by the scheduler every 5 s so that /api/watchlist
can respond instantly without waiting for an MCP round-trip.
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_cache: dict[str, dict] = {}   # {TICKER: {price, change_pct}}
_last_updated: datetime | None = None


def update(quotes: dict[str, dict]) -> None:
    global _last_updated
    with _lock:
        _cache.update(quotes)
        _last_updated = datetime.utcnow()


def get(ticker: str) -> dict:
    with _lock:
        return dict(_cache.get(ticker.upper(), {"price": None, "change_pct": None}))


def get_all() -> dict:
    with _lock:
        return dict(_cache)


def last_updated() -> datetime | None:
    with _lock:
        return _last_updated


def is_empty() -> bool:
    with _lock:
        return not _cache
