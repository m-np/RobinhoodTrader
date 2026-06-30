"""
Classifies tickers into Core, Growth, or Moon Shot tier by evaluating
fundamentals from yfinance against the criteria in aggressive_growth.md.
Never hardcodes ticker names — criteria only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import yfinance as yf  # type: ignore[import-untyped]

TIER_CONFIG: dict[str, dict] = {
    "core": {
        "max_position_pct": 0.25,
        "stop_loss_pct": 0.08,
        "rsi_range": (30, 60),
        "min_journal_entries": 1,
        "partial_exit_pct": 0.40,
        "full_exit_pct": 0.60,
        "min_hold_days": 30,
    },
    "growth": {
        "max_position_pct": 0.15,
        "stop_loss_pct": 0.15,
        "rsi_range": (35, 60),
        "min_journal_entries": 1,
        "partial_exit_pct": 0.50,
        "full_exit_pct": 0.80,
        "min_hold_days": 21,
    },
    "moonshot": {
        "max_position_pct": 0.05,
        "stop_loss_pct": 0.25,
        "rsi_range": (25, 50),
        "min_journal_entries": 2,
        "partial_exit_pct": 0.60,
        "full_exit_pct": 1.50,
        "min_hold_days": 0,
    },
}

SECTOR_CAPS: dict[str, float] = {
    "AI Infrastructure": 0.35,
    "Memory / Storage": 0.20,
    "Power / Data Center": 0.20,
    "Physical AI / Robotics": 0.15,
    "Healthcare / BioAI": 0.15,
    "Fintech": 0.15,
    "Space / Telecom": 0.10,
    "Consumer": 0.15,
    "moonshot_total": 0.15,
}

# (min_score, core_pct, growth_pct, moonshot_pct)
_SCORE_BANDS: list[tuple[int, float, float, float]] = [
    (9, 0.25, 0.15, 0.05),
    (7, 0.20, 0.13, 0.04),
    (5, 0.15, 0.10, 0.03),
    (3, 0.08, 0.05, 0.02),
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FundamentalSnapshot:
    """Point-in-time fundamentals fetched from yfinance.

    Attributes:
        ticker:             Equity symbol.
        market_cap:         Market cap in USD, or None.
        revenue_ttm:        Trailing-twelve-month revenue in USD, or None.
        revenue_growth_yoy: YoY revenue growth as decimal (0.20=20%), or None.
        pe_ratio:           Trailing P/E, or None.
        years_public:       Approximate years since IPO.
        sector:             Sector string from yfinance, or None.
        industry:           Industry string from yfinance, or None.
    """

    ticker: str
    market_cap: float | None
    revenue_ttm: float | None
    revenue_growth_yoy: float | None
    pe_ratio: float | None
    years_public: float
    sector: str | None
    industry: str | None


@dataclass
class ClassificationResult:
    """Outcome of classify_ticker().

    Attributes:
        ticker:       Equity symbol.
        tier:         'core', 'growth', 'moonshot', or 'unclassified'.
        rationale:    Human-readable explanation of the classification.
        gaps:         Reasons the ticker did not qualify for a higher tier.
        fundamentals: The FundamentalSnapshot used for classification.
    """

    ticker: str
    tier: str
    rationale: str
    gaps: list[str]
    fundamentals: FundamentalSnapshot


# ---------------------------------------------------------------------------
# Fundamentals fetch
# ---------------------------------------------------------------------------

def fetch_fundamentals(ticker: str) -> FundamentalSnapshot:
    """Fetch market cap, revenue, growth rate, PE, and sector from yfinance.

    Args:
        ticker: Equity symbol (e.g. 'NVDA').

    Returns:
        FundamentalSnapshot — some fields may be None if yfinance lacks data.
    """
    t = yf.Ticker(ticker.upper())
    info: dict = t.info or {}

    market_cap = info.get("marketCap") or info.get("market_cap")
    revenue_ttm = info.get("totalRevenue")
    revenue_growth = info.get("revenueGrowth")
    pe_raw = info.get("trailingPE") or info.get("forwardPE")
    sector = info.get("sector")
    industry = info.get("industry")

    years_public = 0.0
    try:
        hist = t.history(period="max", auto_adjust=True)
        if not hist.empty:
            first = hist.index[0].to_pydatetime().replace(tzinfo=timezone.utc)
            years_public = (
                datetime.now(timezone.utc) - first
            ).days / 365.25
    except Exception:
        pass

    return FundamentalSnapshot(
        ticker=ticker.upper(),
        market_cap=float(market_cap) if market_cap else None,
        revenue_ttm=float(revenue_ttm) if revenue_ttm else None,
        revenue_growth_yoy=(
            float(revenue_growth) if revenue_growth is not None else None
        ),
        pe_ratio=float(pe_raw) if pe_raw else None,
        years_public=years_public,
        sector=sector,
        industry=industry,
    )


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------

def _cap_bn(cap: float | None) -> str:
    """Format market cap as '$X.XB' or 'unknown'."""
    if cap is None:
        return "unknown"
    return f"${cap / 1e9:.1f}B"


def classify_ticker(
    ticker: str,
    moat_present: bool = False,
    catalyst_identified: bool = False,
    technology_real: bool = False,
    binary_thesis_written: bool = False,
    exit_condition_written: bool = False,
) -> ClassificationResult:
    """Classify a ticker into its tier using fundamentals + analyst flags.

    Evaluation is criteria-driven per aggressive_growth.md — no ticker
    names are hardcoded.  The boolean flags capture qualitative judgements
    that require human or LLM assessment.

    Args:
        ticker:                 Equity symbol.
        moat_present:           True if a structural moat has been asserted.
        catalyst_identified:    True if a specific named catalyst exists.
        technology_real:        True if the core technology is confirmed real.
        binary_thesis_written:  True if a binary outcome statement is in the
                                journal.
        exit_condition_written: True if an "I will exit if X" statement is in
                                the journal.

    Returns:
        ClassificationResult with tier, rationale, gaps, and fundamentals.
    """
    snap = fetch_fundamentals(ticker)
    gaps: list[str] = []

    # --- Core ---
    core_gaps: list[str] = []
    if snap.market_cap is None or snap.market_cap < 10e9:
        core_gaps.append(
            f"market cap {_cap_bn(snap.market_cap)} < $10B required"
        )
    growth_pct = (
        snap.revenue_growth_yoy * 100
        if snap.revenue_growth_yoy is not None
        else None
    )
    revenue_ok = (
        snap.revenue_ttm is not None
        and snap.revenue_ttm > 0
        and snap.revenue_growth_yoy is not None
        and snap.revenue_growth_yoy >= 0.15
    ) or moat_present
    if not revenue_ok:
        core_gaps.append(
            "revenue not growing >15% YoY and no structural moat asserted"
            + (f" (growth={growth_pct:.1f}%)" if growth_pct is not None else "")
        )
    if snap.years_public < 2.0:
        core_gaps.append(
            f"public {snap.years_public:.1f}y; Core requires 2+"
        )

    if not core_gaps:
        moat_note = ", structural moat asserted" if moat_present else ""
        return ClassificationResult(
            ticker=snap.ticker,
            tier="core",
            rationale=(
                f"Core: {_cap_bn(snap.market_cap)}, "
                f"revenue growth "
                f"{growth_pct:.1f}% " if growth_pct else "Core: "
                f"{snap.years_public:.1f}y public{moat_note}"
            ),
            gaps=[],
            fundamentals=snap,
        )
    gaps.extend(core_gaps)

    # --- Growth ---
    growth_gaps: list[str] = []
    if snap.market_cap is None or snap.market_cap < 2e9:
        growth_gaps.append(
            f"market cap {_cap_bn(snap.market_cap)} < $2B required"
        )
    has_revenue_or_path = (
        snap.revenue_ttm is not None and snap.revenue_ttm > 0
    ) or catalyst_identified
    if not has_revenue_or_path:
        growth_gaps.append(
            "no positive revenue and no dated catalyst identified"
        )
    if snap.years_public < 1.0:
        growth_gaps.append(
            f"public {snap.years_public:.1f}y; Growth requires 1+"
        )
    if not catalyst_identified:
        growth_gaps.append("no specific catalyst — required for Growth tier")

    if not growth_gaps:
        rev_note = (
            "positive revenue"
            if (snap.revenue_ttm and snap.revenue_ttm > 0)
            else "path via catalyst"
        )
        return ClassificationResult(
            ticker=snap.ticker,
            tier="growth",
            rationale=(
                f"Growth: {_cap_bn(snap.market_cap)}, "
                f"{rev_note}, catalyst identified, "
                f"{snap.years_public:.1f}y public"
            ),
            gaps=gaps,
            fundamentals=snap,
        )
    gaps.extend(growth_gaps)

    # --- Moon Shot ---
    moon_gaps: list[str] = []
    if not technology_real:
        moon_gaps.append("technology not confirmed real")
    if not binary_thesis_written:
        moon_gaps.append("binary thesis not written in journal")
    if not exit_condition_written:
        moon_gaps.append("exit condition not written in journal")

    if not moon_gaps:
        return ClassificationResult(
            ticker=snap.ticker,
            tier="moonshot",
            rationale=(
                f"Moon Shot: tech confirmed, binary thesis + exit written, "
                f"{_cap_bn(snap.market_cap)}"
            ),
            gaps=gaps,
            fundamentals=snap,
        )
    gaps.extend(moon_gaps)

    return ClassificationResult(
        ticker=snap.ticker,
        tier="unclassified",
        rationale="Does not meet minimum tier criteria. See gaps.",
        gaps=gaps,
        fundamentals=snap,
    )


# ---------------------------------------------------------------------------
# Config and guards
# ---------------------------------------------------------------------------

def get_tier_config(tier_name: str) -> dict:
    """Return position config dict for a tier.

    Args:
        tier_name: 'core', 'growth', or 'moonshot'.

    Raises:
        ValueError: If tier is 'unclassified' or unknown.
    """
    if tier_name not in TIER_CONFIG:
        raise ValueError(
            f"No config for tier {tier_name!r} — classify the ticker first"
        )
    cfg = dict(TIER_CONFIG[tier_name])
    cfg["min_journal_entries"] = get_min_journal_entries(tier_name)
    return cfg


def get_min_journal_entries(tier: str) -> int:
    """Return minimum journal entries for *tier*, reading from the DB knob.

    Falls back to TIER_CONFIG default so the value is always valid even
    before the knob is first saved.
    """
    from agent.guardrails import get_knob  # late import — avoids circular dep
    default = TIER_CONFIG.get(tier, {}).get("min_journal_entries", 1)
    return int(get_knob(f"min_journal_{tier}", default))


def check_position_size(
    tier_name: str, proposed_pct: float
) -> tuple[bool, str]:
    """Check whether proposed_pct is within the tier's max position size.

    Args:
        tier_name:    'core', 'growth', or 'moonshot'.
        proposed_pct: Proposed size as fraction of portfolio (0–1).

    Returns:
        (allowed, reason) — allowed is True when within limits.
    """
    cfg = get_tier_config(tier_name)
    max_pct = cfg["max_position_pct"]
    if proposed_pct > max_pct:
        return (
            False,
            f"{tier_name} tier: {proposed_pct:.1%} exceeds max {max_pct:.1%}",
        )
    return (True, "")


def check_sector_cap(
    sector: str,
    current_sector_pct: float,
    new_position_pct: float,
) -> tuple[bool, str]:
    """Check whether adding a position would breach the sector cap.

    Args:
        sector:             Sector label (key in SECTOR_CAPS).
        current_sector_pct: Fraction of portfolio already in this sector.
        new_position_pct:   Fraction the new position would add.

    Returns:
        (allowed, reason).
    """
    cap = SECTOR_CAPS.get(sector)
    if cap is None:
        return (True, "")
    projected = current_sector_pct + new_position_pct
    if projected > cap:
        return (
            False,
            f"Sector '{sector}': {projected:.1%} would exceed cap {cap:.1%}",
        )
    return (True, "")


def check_moonshot_total(
    current_moonshot_pct: float,
    new_position_pct: float,
) -> tuple[bool, str]:
    """Check whether total Moon Shot allocation would breach 15%.

    Args:
        current_moonshot_pct: Current fraction of portfolio in all moon shots.
        new_position_pct:     Fraction the new position would add.

    Returns:
        (allowed, reason).
    """
    cap = SECTOR_CAPS["moonshot_total"]
    projected = current_moonshot_pct + new_position_pct
    if projected > cap:
        return (
            False,
            f"Moon shot total: {projected:.1%} would exceed cap {cap:.1%}",
        )
    return (True, "")


def compute_conviction_score(
    journal_entry_count: int,
    latest_sentiment: str,
    is_red_day: bool,
    volume_confirmed: bool,
    signals_fired: int,
    insider_buying: bool,
) -> int:
    """Compute 0–10 conviction score per aggressive_growth.md.

    Components:
    - Journal entries: min(count, 3)                        → 0–3 pts
    - Thesis sentiment: strengthening=2, neutral=1, else=0  → 0–2 pts
    - Red day entry                                         → 0–1 pt
    - Volume confirmation                                   → 0–1 pt
    - Technical signals fired: min(count, 2)                → 0–2 pts
    - Insider buying                                        → 0–1 pt

    Args:
        journal_entry_count: Total journal entries for the ticker.
        latest_sentiment:    Most recent sentiment string.
        is_red_day:          True when broad market is down ≥1.5%.
        volume_confirmed:    True when session volume is 20%+ above 30-day avg.
        signals_fired:       Number of signal categories that fired (0–5).
        insider_buying:      True when insider purchases in last 30 days.

    Returns:
        Integer in [0, 10].
    """
    pts = 0
    pts += min(journal_entry_count, 3)
    if latest_sentiment == "strengthening":
        pts += 2
    elif latest_sentiment == "neutral":
        pts += 1
    if is_red_day:
        pts += 1
    if volume_confirmed:
        pts += 1
    pts += min(signals_fired, 2)
    if insider_buying:
        pts += 1
    return min(pts, 10)


def score_to_size(
    tier_name: str, score: int, portfolio_value: float
) -> float:
    """Convert conviction score to recommended dollar position size.

    Args:
        tier_name:       'core', 'growth', or 'moonshot'.
        score:           Conviction score 0–10.
        portfolio_value: Total current portfolio value in dollars.

    Returns:
        Recommended position size in dollars (0.0 if score < 3).
    """
    if score < 3:
        return 0.0
    idx = {"core": 0, "growth": 1, "moonshot": 2}.get(tier_name)
    if idx is None:
        return 0.0
    for min_score, *pcts in _SCORE_BANDS:
        if score >= min_score:
            return round(pcts[idx] * portfolio_value, 2)
    return 0.0


# ---------------------------------------------------------------------------
# Smoke test (mocked — no live API calls)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pandas as pd  # type: ignore[import-untyped]
    from unittest.mock import MagicMock, patch

    print("=== tier_classifier smoke test ===")

    _mock_hist = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.to_datetime(["2019-01-01"], utc=True),
    )

    def _make_mock(info: dict) -> MagicMock:
        t = MagicMock()
        t.info = info
        t.history.return_value = _mock_hist
        return t

    # Large cap, high growth → Core
    with patch(
        "yfinance.Ticker",
        side_effect=lambda _: _make_mock({
            "marketCap": 3_000_000_000_000,
            "totalRevenue": 100_000_000_000,
            "revenueGrowth": 0.22,
            "trailingPE": 45.0,
            "sector": "Technology",
            "industry": "Semiconductors",
        }),
    ):
        res_core = classify_ticker("TEST_CORE", moat_present=True)
    print(f"  Large cap 22% growth → tier={res_core.tier!r}")
    assert res_core.tier == "core", res_core.gaps

    # Small cap no revenue → Moon Shot
    with patch(
        "yfinance.Ticker",
        side_effect=lambda _: _make_mock({
            "marketCap": 500_000_000,
            "totalRevenue": None,
            "revenueGrowth": None,
            "trailingPE": None,
            "sector": "Industrials",
            "industry": "Aerospace",
        }),
    ):
        res_moon = classify_ticker(
            "TEST_MOON",
            technology_real=True,
            binary_thesis_written=True,
            exit_condition_written=True,
        )
    print(f"  Small cap no revenue → tier={res_moon.tier!r}")
    assert res_moon.tier == "moonshot", res_moon.gaps

    conviction = compute_conviction_score(5, "strengthening", True, True, 2, False)
    print(f"  conviction_score = {conviction}  (expected 9)")
    assert conviction == 9

    sz = score_to_size("core", 9, 100_000)
    print(f"  score_to_size(core, 9, $100k) = ${sz:,.0f}  (expected $25,000)")
    assert sz == 25_000.0

    ok, reason = check_sector_cap("AI Infrastructure", 0.33, 0.05)
    print(f"  check_sector_cap(33%+5%) blocked={not ok}")
    assert not ok

    print("  All assertions passed.")
