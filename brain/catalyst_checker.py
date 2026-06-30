"""
Catalyst checker — earnings countdown gate and FOMC calendar.

Uses yfinance for earnings dates. FOMC dates are hardcoded and updated
annually per catalyst_calendar.md.
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timezone
from typing import Optional

import yfinance as yf  # type: ignore[import]

# Cache earnings dates for 4 hours to avoid yfinance 429 rate-limits
# when 22 watchlist tickers are checked every 15-minute agent cycle.
_earnings_cache: dict[str, tuple[Optional[date], float]] = {}  # ticker → (date|None, expires_ts)
_CACHE_TTL = 4 * 3600  # 4 hours

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
    """Return the next upcoming earnings date, or None (with 4-hour cache)."""
    sym = ticker.upper()
    cached_val, expires = _earnings_cache.get(sym, (None, 0.0))
    if _time.monotonic() < expires:
        return cached_val

    try:
        raw = _raw_earnings_list(sym)
    except Exception:  # noqa: BLE001
        # Cache None on error to avoid hammering yfinance on 429s
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


def get_earnings_alerts(symbols: list[str]) -> list[dict]:
    """Build countdown alerts for tickers with upcoming earnings.

    Args:
        symbols: Equity symbols to check.

    Returns:
        List of dicts: {ticker, days_to_earnings, level,
        action_required}.
    """
    import time
    alerts: list[dict] = []
    for sym in symbols:
        dte = days_to_earnings(sym.upper())
        if dte is None or dte > _WARN_21:
            time.sleep(0.3)  # avoid Yahoo Finance 429 rate limit on large watchlists
            continue
        alerts.append(_alert_for_days(sym.upper(), dte))
        time.sleep(0.3)
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
