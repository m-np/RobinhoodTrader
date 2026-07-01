"""
Catalyst checker — earnings countdown gate and FOMC calendar.

Earnings dates are fetched at most once per calendar day and persisted to
SQLite so server restarts do not trigger new network calls. The lookup
priority is: in-memory cache → DB (same day) → Robinhood MCP seed → yfinance.
"""
from __future__ import annotations

import logging
import sqlite3
import time as _time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf  # type: ignore[import]

logging.getLogger("yfinance").setLevel(logging.WARNING)

_DB_PATH = "data/trader.db"

# In-memory cache: ticker → (earnings_date | None, expires_monotonic)
# Populated from DB on first access and from MCP/yfinance on cache miss.
_earnings_cache: dict[str, tuple[Optional[date], float]] = {}
_CACHE_TTL = 24 * 3600  # seconds — matches one calendar day


# ---------------------------------------------------------------------------
# DB persistence — once-per-day, survives restarts
# ---------------------------------------------------------------------------

def _db_connect(db_path: str = _DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_earnings_table(db_path: str = _DB_PATH) -> None:
    with _db_connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS earnings_dates (
                ticker       TEXT PRIMARY KEY,
                earnings_date TEXT,
                fetched_date TEXT NOT NULL
            )
        """)
        conn.commit()


def _load_db_cache(db_path: str = _DB_PATH) -> dict[str, Optional[date]]:
    """Return all rows whose fetched_date == today. Empty dict if none."""
    today_str = _today().isoformat()
    try:
        with _db_connect(db_path) as conn:
            rows = conn.execute(
                "SELECT ticker, earnings_date FROM earnings_dates "
                "WHERE fetched_date = ?",
                (today_str,),
            ).fetchall()
        return {
            r["ticker"]: (
                date.fromisoformat(r["earnings_date"])
                if r["earnings_date"] else None
            )
            for r in rows
        }
    except Exception:  # noqa: BLE001
        return {}


def _save_db_cache(
    data: dict[str, Optional[date]],
    db_path: str = _DB_PATH,
) -> None:
    """Upsert earnings dates into the DB tagged with today's date."""
    today_str = _today().isoformat()
    try:
        with _db_connect(db_path) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO earnings_dates "
                "(ticker, earnings_date, fetched_date) VALUES (?, ?, ?)",
                [
                    (t, ed.isoformat() if ed else None, today_str)
                    for t, ed in data.items()
                ],
            )
            conn.commit()
    except Exception:  # noqa: BLE001
        pass


def _warm_memory_cache_from_db(db_path: str = _DB_PATH) -> None:
    """Load today's DB rows into the in-memory cache (called once on init)."""
    _ensure_earnings_table(db_path)
    rows = _load_db_cache(db_path)
    if not rows:
        return
    now = _time.monotonic()
    for ticker, ed in rows.items():
        _earnings_cache[ticker] = (ed, now + _CACHE_TTL)
    logger.debug("Earnings cache warmed from DB: %d tickers", len(rows))


logger = logging.getLogger(__name__)

_FOMC_2026: list[date] = [
    date(2026, 1, 29),
    date(2026, 3, 19),
    date(2026, 5, 7),
    date(2026, 6, 18),
    date(2026, 7, 30),
    date(2026, 9, 17),
    date(2026, 11, 5),
    date(2026, 12, 17),
]

_BLOCK_DAYS = 7
_WARN_14 = 14
_WARN_21 = 21


def _today() -> date:
    return datetime.now(timezone.utc).date()


# Warm in-memory cache from DB at import time (server restart recovery).
_warm_memory_cache_from_db()


def _coerce_to_date(item: object) -> date | None:
    """Convert a yfinance calendar item to a plain date, or None."""
    if item is None:
        return None
    if hasattr(item, "date"):
        d = item.date() if callable(item.date) else item.date
        return d if isinstance(d, date) else None
    if isinstance(item, date):
        return item
    return None


def _raw_earnings_list(ticker: str) -> list | None:
    """Return the raw earnings list from yfinance calendar, or None."""
    cal = yf.Ticker(ticker).calendar
    if cal is None:
        return None
    if isinstance(cal, dict):
        raw = cal.get("Earnings Date")
        return [raw] if raw is not None and not hasattr(
            raw, "__iter__"
        ) else raw
    try:
        raw = cal.loc["Earnings Date"].tolist()
        return raw
    except (KeyError, AttributeError):
        return None


def _parse_earnings(ticker: str) -> date | None:
    """Return the next upcoming earnings date, or None.

    Lookup order: in-memory cache → yfinance (last resort).
    Writes yfinance results to both memory cache and DB so the next
    restart does not trigger another network call today.
    """
    sym = ticker.upper()
    cached_val, expires = _earnings_cache.get(sym, (None, 0.0))
    if _time.monotonic() < expires:
        return cached_val

    try:
        raw = _raw_earnings_list(sym)
    except Exception:  # noqa: BLE001
        _earnings_cache[sym] = (None, _time.monotonic() + _CACHE_TTL)
        return None
    if raw is None:
        _earnings_cache[sym] = (None, _time.monotonic() + _CACHE_TTL)
        return None
    today = _today()
    candidates = [
        d for item in raw
        if (d := _coerce_to_date(item)) is not None and d >= today
    ]
    result = min(candidates) if candidates else None
    _earnings_cache[sym] = (result, _time.monotonic() + _CACHE_TTL)
    # Persist so server restarts don't re-query yfinance today
    _save_db_cache({sym: result})
    return result


def get_earnings_date(ticker: str) -> date | None:
    """Return the next earnings date for *ticker*, or None.

    Args:
        ticker: Equity symbol.

    Returns:
        date object or None if unavailable from yfinance.
    """
    return _parse_earnings(ticker)


def days_to_earnings(ticker: str) -> int | None:
    """Return calendar days until next earnings, or None.

    Args:
        ticker: Equity symbol.

    Returns:
        Non-negative integer days, or None if earnings date unknown.
    """
    ed = _parse_earnings(ticker.upper())
    if ed is None:
        return None
    return max(0, (ed - _today()).days)


def check_earnings_gate(ticker: str) -> tuple[bool, str]:
    """Gate: block new positions when earnings are within 7 days.

    Args:
        ticker: Equity symbol.

    Returns:
        (can_trade, reason). can_trade is False when blocked.
    """
    dte = days_to_earnings(ticker)
    if dte is None:
        return (
            True,
            f"{ticker}: earnings date unknown — verify manually",
        )
    if dte <= _BLOCK_DAYS:
        return (
            False,
            f"{ticker}: earnings in {dte} day(s) — "
            f"hard block (no new positions within {_BLOCK_DAYS} days)",
        )
    return (True, f"{ticker}: {dte} days to earnings — gate clear")


def _alert_for_days(sym: str, dte: int) -> dict:
    """Build an alert dict for a ticker given its days-to-earnings."""
    if dte <= 3:
        level = "IMMINENT"
        action = (
            f"Earnings in {dte} day(s) — "
            "evaluate exit of binary positions"
        )
    elif dte <= _BLOCK_DAYS:
        level = "7D_WARNING"
        action = (
            f"Earnings in {dte} days — "
            "no new entries; close options before IV crush"
        )
    elif dte <= _WARN_14:
        level = "14D_NOTICE"
        action = (
            f"Earnings in {dte} days — "
            "review size; trim if 30%+ profit"
        )
    else:
        level = "21D_NOTE"
        action = f"Earnings in {dte} days — flag in journal"
    return {
        "ticker": sym,
        "days_to_earnings": dte,
        "level": level,
        "action_required": action,
    }


def seed_earnings_cache(mcp_items: list[dict]) -> None:
    """Pre-populate the earnings cache from Robinhood MCP data.

    Writes to both the in-memory cache and the DB so subsequent restarts
    today do not trigger any network calls.

    Args:
        mcp_items: Raw dicts from mcp_client.get_earnings_calendar_raw().
    """
    from datetime import datetime as _dt
    now = _time.monotonic()
    today = _today()
    to_persist: dict[str, Optional[date]] = {}
    for item in mcp_items:
        sym = (item.get("symbol") or item.get("ticker") or "").upper()
        raw = (
            item.get("report_date")
            or item.get("date")
            or item.get("earnings_date")
        )
        if not sym or not raw:
            continue
        try:
            d = _dt.fromisoformat(str(raw)[:10]).date()
        except (ValueError, TypeError):
            continue
        if d < today:
            continue
        existing, _ = _earnings_cache.get(sym, (None, 0.0))
        if existing is None or d < existing:
            _earnings_cache[sym] = (d, now + _CACHE_TTL)
            to_persist[sym] = d
    if to_persist:
        _save_db_cache(to_persist)


def get_earnings_alerts(symbols: list[str]) -> list[dict]:
    """Build countdown alerts for tickers with upcoming earnings.

    Call seed_earnings_cache() first to avoid yfinance rate limits.
    The cache (whether seeded from MCP or from prior yfinance calls) is
    checked before any network request is made.

    Args:
        symbols: Equity symbols to check.

    Returns:
        List of dicts: {ticker, days_to_earnings, level, action_required}.
    """
    alerts: list[dict] = []
    for sym in symbols:
        dte = days_to_earnings(sym.upper())
        if dte is None or dte > _WARN_21:
            continue
        alerts.append(_alert_for_days(sym.upper(), dte))
    return alerts


def get_fomc_dates_2026() -> list[date]:
    """Return hardcoded 2026 FOMC meeting dates. Update annually.

    Returns:
        List of date objects for all 2026 FOMC meetings.
    """
    return list(_FOMC_2026)


def days_to_next_fomc() -> int | None:
    """Return days until the next FOMC meeting, or None if none remain.

    Returns:
        Non-negative integer, or None if no upcoming dates this year.
    """
    today = _today()
    future = [d for d in _FOMC_2026 if d >= today]
    if not future:
        return None
    return (min(future) - today).days


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== catalyst_checker smoke test ===")

    test_syms = ["NVDA", "AAPL", "PLTR"]
    for sym in test_syms:
        dte_val = days_to_earnings(sym)
        can, reason = check_earnings_gate(sym)
        gate = "CLEAR" if can else "BLOCKED"
        print(f"  {sym}: days={dte_val}  gate={gate}")

    fomc_d = days_to_next_fomc()
    print(f"  days_to_next_fomc() = {fomc_d}")
    assert fomc_d is None or fomc_d >= 0

    alerts_out = get_earnings_alerts(test_syms)
    print(f"  earnings alerts: {len(alerts_out)}")
    for a in alerts_out:
        print(f"    [{a['level']}] {a['ticker']}: {a['action_required']}")

    print("  Smoke test passed.")
