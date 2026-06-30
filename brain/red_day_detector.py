"""
Red day detector — classifies broad-market selloffs per
red_day_protocol.md and fetches live market conditions via yfinance.
"""
from __future__ import annotations

import time as _time

import yfinance as yf  # type: ignore[import]

# Cache market snapshot for 30 minutes to avoid yfinance 429 rate-limits
_snapshot_cache: dict = {}
_snapshot_expires: float = 0.0
_SNAPSHOT_TTL = 30 * 60  # 30 minutes

_LEVEL_META: dict[int, dict] = {
    0: {
        "label": "none",
        "max_cash_deploy_pct": 0.0,
        "eligible_tiers": [],
        "description": "Normal conditions — trade freely per signals",
    },
    1: {
        "label": "mild",
        "max_cash_deploy_pct": 0.0,
        "eligible_tiers": [],
        "description": "Mild red day — scan and prepare, no buys yet",
    },
    2: {
        "label": "confirmed",
        "max_cash_deploy_pct": 0.25,
        "eligible_tiers": ["core", "growth"],
        "description": (
            "Confirmed red day — core and growth eligible "
            "at 25% of cash reserve"
        ),
    },
    3: {
        "label": "high_fear",
        "max_cash_deploy_pct": 0.50,
        "eligible_tiers": ["core"],
        "description": (
            "High fear — core tier only, up to 50% of cash reserve"
        ),
    },
    4: {
        "label": "extreme_fear",
        "max_cash_deploy_pct": 0.66,
        "eligible_tiers": ["core"],
        "description": (
            "Extreme fear — generational core entry; "
            "up to 66% of reserve"
        ),
    },
}

_COMPANY_KEYWORDS = frozenset({
    "earnings", "guidance", "miss", "beat", "ceo", "cfo", "resign",
    "departure", "sec", "lawsuit", "fraud", "recall", "downgrade",
    "bankruptcy", "cut", "layoff",
})


def classify_red_day(
    sp500_change: float,
    vix: float,
    sector_etf_change: float | None = None,
) -> dict:
    """Classify the current broad-market selloff level.

    Args:
        sp500_change:      S&P 500 day change as a fraction (e.g. -0.02).
        vix:               Current VIX value.
        sector_etf_change: Optional sector ETF day change fraction.
                           Used to escalate level via the sector rule.

    Returns:
        Dict with keys: level (int 0-4), label (str),
        max_cash_deploy_pct (float), eligible_tiers (list[str]),
        description (str).
    """
    sp = sp500_change
    etf = sector_etf_change
    level = 0

    if sp <= -0.04 or vix > 35:
        level = 4
    elif sp <= -0.03 and vix > 25:
        level = 3
    elif sp <= -0.015:
        level = 2
    elif etf is not None and etf <= -0.025:
        level = 2
    elif sp <= -0.008:
        level = 1
    elif etf is not None and etf <= -0.015:
        level = 1

    result = dict(_LEVEL_META[level])
    result["level"] = level
    return result


def verify_macro_cause(
    ticker: str,
    stock_change_pct: float,
    sector_etf_change_pct: float,
    news_headlines: list[str],
) -> tuple[bool, str]:
    """Verify that a selloff is macro-driven, not company-specific.

    Logic per red_day_protocol.md:
    - Company-specific news keywords present  → False
    - Stock down >1.5x the sector move        → False
    - Otherwise                               → True

    Args:
        ticker:                Equity symbol (for messaging).
        stock_change_pct:      Stock's day change as a fraction.
        sector_etf_change_pct: Sector ETF's day change as a fraction.
        news_headlines:        News headlines for the stock today.

    Returns:
        (is_macro, explanation).
    """
    text = " ".join(news_headlines).lower()
    matched = [kw for kw in _COMPANY_KEYWORDS if kw in text]
    if matched:
        return (
            False,
            f"{ticker}: company keywords detected "
            f"({', '.join(matched[:3])}) — not a macro dip",
        )

    if sector_etf_change_pct == 0:
        return (
            False,
            f"{ticker}: sector change is 0 — cannot confirm macro cause",
        )

    ratio = stock_change_pct / sector_etf_change_pct
    if ratio > 1.5:
        return (
            False,
            f"{ticker}: down {stock_change_pct:.1%} vs sector "
            f"{sector_etf_change_pct:.1%} (ratio {ratio:.2f}x) "
            "— company-specific pressure suspected",
        )

    return (
        True,
        f"{ticker}: {stock_change_pct:.1%} tracks sector "
        f"{sector_etf_change_pct:.1%} (ratio {ratio:.2f}x), "
        "no company news — macro selloff confirmed",
    )


def get_market_snapshot() -> dict:
    """Fetch current market conditions using yfinance (cached 30 min).

    Uses SPY for S&P 500, ^VIX for volatility index, SOXX for semis,
    XLK for broad tech. Falls back gracefully on network errors.

    Returns:
        Dict with keys:
            sp500_change_pct  (float): SPY day change fraction.
            vix               (float): Current VIX level.
            soxx_change_pct   (float | None): SOXX day change.
            xlk_change_pct    (float | None): XLK day change.
            sp500_above_50ma  (bool): SPY above its 50-day MA.
    """
    global _snapshot_cache, _snapshot_expires
    if _snapshot_cache and _time.monotonic() < _snapshot_expires:
        return dict(_snapshot_cache)

    snapshot: dict = {
        "sp500_change_pct": 0.0,
        "vix": 15.0,
        "soxx_change_pct": None,
        "xlk_change_pct": None,
        "sp500_above_50ma": True,
    }

    def _day_change(sym: str) -> float | None:
        try:
            fi = yf.Ticker(sym).fast_info
            prev = getattr(fi, "previous_close", None)
            last = getattr(fi, "last_price", None)
            if prev and last and prev > 0:
                return (last - prev) / prev
        except Exception:
            pass
        return None

    sp_chg = _day_change("SPY")
    if sp_chg is not None:
        snapshot["sp500_change_pct"] = sp_chg

    try:
        vix_fi = yf.Ticker("^VIX").fast_info
        vix_price = getattr(vix_fi, "last_price", None)
        if vix_price:
            snapshot["vix"] = float(vix_price)
    except Exception:
        pass

    soxx_chg = _day_change("SOXX")
    if soxx_chg is not None:
        snapshot["soxx_change_pct"] = soxx_chg

    xlk_chg = _day_change("XLK")
    if xlk_chg is not None:
        snapshot["xlk_change_pct"] = xlk_chg

    try:
        hist = yf.Ticker("SPY").history(period="60d", auto_adjust=True)
        if len(hist) >= 50:
            ma50 = hist["Close"].iloc[-50:].mean()
            last_close = float(hist["Close"].iloc[-1])
            snapshot["sp500_above_50ma"] = last_close > ma50
    except Exception:
        pass

    _snapshot_cache = dict(snapshot)
    _snapshot_expires = _time.monotonic() + _SNAPSHOT_TTL
    return snapshot


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== red_day_detector smoke test ===")

    cases: list[tuple] = [
        (0.003, 15.0, None, 0),
        (-0.010, 18.0, None, 1),
        (-0.020, 20.0, -0.030, 2),
        (-0.035, 27.0, None, 3),
        (-0.045, 38.0, None, 4),
        (-0.005, 15.0, -0.030, 2),
    ]
    for sp_val, vix_val, etf_val, expected in cases:
        rd = classify_red_day(sp_val, vix_val, etf_val)
        ok = rd["level"] == expected
        print(
            f"  sp={sp_val:+.1%} vix={vix_val} etf={etf_val!r:7} "
            f"→ level={rd['level']} ({rd['label']}) "
            f"{'OK' if ok else 'FAIL'}"
        )
        assert ok, f"Expected level {expected}, got {rd['level']}"

    m1, _ = verify_macro_cause("NVDA", -0.025, -0.022, [])
    assert m1
    m2, _ = verify_macro_cause("NVDA", -0.08, -0.022, ["earnings miss"])
    assert not m2
    print("  verify_macro_cause: OK")

    print("  All assertions passed.")
    print(
        "\n  Fetching live snapshot "
        "(may fail if markets closed)..."
    )
    try:
        snap = get_market_snapshot()
        print(f"  SPY: {snap['sp500_change_pct']:+.2%}")
        print(f"  VIX: {snap['vix']:.1f}")
    except Exception as exc:
        print(f"  (skipped: {exc})")
