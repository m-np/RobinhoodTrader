"""Pre-trade checklist: every buy must pass all gates."""
from __future__ import annotations

from dataclasses import dataclass, field

from brain.catalyst_checker import check_earnings_gate
from brain.journal_store import (
    compute_thesis_score,
    get_entry_count,
    get_latest_sentiment,
    has_hypothesis,
    init_db,
)
from brain.tier_classifier import (
    TIER_CONFIG,
    check_moonshot_total,
    check_sector_cap,
    compute_conviction_score,
    score_to_size,
)

_CASH_FLOOR = 0.15
_EMPTY_SET: frozenset[str] = frozenset()


@dataclass
class PreTradeResult:
    """Outcome of the full pre-trade checklist.

    Attributes:
        approved:             True only when all hard gates pass.
        blocks:               Gate failures (empty if approved).
        warnings:             Non-blocking observations.
        conviction_score:     0-10 score from aggressive_growth.md.
        recommended_size_usd: Dollar size at conviction-score band.
        rationale_template:   Pre-filled stub the agent completes.
    """

    approved: bool
    blocks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    conviction_score: int = 0
    recommended_size_usd: float = 0.0
    rationale_template: str = ""


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------

def _journal_gates(
    ticker: str,
    tier: str,
    blocks: list[str],
    db_path: str,
) -> tuple[str, int]:
    """Run journal gates; return (latest_sentiment, entry_count)."""
    if not has_hypothesis(ticker, db_path):
        blocks.append(
            f"NO HYPOTHESIS: {ticker} has no journal entry"
        )
        return ("neutral", 0)

    min_req = TIER_CONFIG[tier]["min_journal_entries"]
    count = get_entry_count(ticker, db_path)
    if count < min_req:
        word = "entry" if count == 1 else "entries"
        blocks.append(
            f"THIN JOURNAL: {ticker} has {count} {word}, "
            f"needs {min_req} for {tier} tier"
        )

    sentiment = get_latest_sentiment(ticker, db_path) or "neutral"
    if sentiment == "broken":
        blocks.append(
            f"THESIS BROKEN: {ticker} -- "
            "do not open new position"
        )
    elif sentiment == "challenged":
        blocks.append(
            f"THESIS CHALLENGED: {ticker} -- "
            "human confirmation required"
        )
    return (sentiment, count)


def _cash_gate(
    portfolio_value: float,
    portfolio_cash: float,
    blocks: list[str],
) -> None:
    """Block if cash would drop below the floor after position."""
    cash_pct = (
        portfolio_cash / portfolio_value if portfolio_value else 1.0
    )
    if cash_pct < _CASH_FLOOR:
        blocks.append(
            f"CASH RESERVE: {cash_pct:.1%} cash, "
            f"must keep >={_CASH_FLOOR:.0%}"
        )


def _allocation_gates(
    sym: str,
    tier: str,
    sector_allocations: dict[str, float],
    moonshot_total_pct: float,
    market_data: dict,
    blocks: list[str],
    warnings: list[str],
) -> None:
    """Sector cap and moon shot total gates."""
    ticker_sector = market_data.get("ticker_sector")
    if ticker_sector:
        cur = sector_allocations.get(ticker_sector, 0.0)
        new_pct = TIER_CONFIG[tier]["max_position_pct"]
        ok, msg = check_sector_cap(ticker_sector, cur, new_pct)
        if not ok:
            blocks.append(f"SECTOR CAP: {msg}")
    else:
        warnings.append(
            f"No sector for {sym} -- cap check skipped"
        )

    if tier == "moonshot":
        new_pct = TIER_CONFIG["moonshot"]["max_position_pct"]
        ok, msg = check_moonshot_total(moonshot_total_pct, new_pct)
        if not ok:
            blocks.append(f"MOONSHOT TOTAL: {msg}")


def _market_gates(
    market_data: dict,
    blocks: list[str],
    warnings: list[str],
) -> None:
    """VIX and bear-market lockout gates."""
    vix = market_data.get("vix", 15.0)
    above_50ma = market_data.get("sp500_above_50ma", True)
    port_loss = market_data.get(
        "portfolio_unrealized_loss_pct", 0.0
    )

    if (not above_50ma) and vix > 35 and port_loss > 0.15:
        blocks.append(
            "MARKET LOCKOUT: S&P below 50MA + VIX>35 "
            "+ portfolio down >15%"
        )
        return

    if vix > 35:
        warnings.append(
            f"VIX {vix:.1f} -- extreme fear; "
            "core only, highest conviction"
        )
    elif vix > 30:
        warnings.append(
            f"VIX {vix:.1f} -- high fear; moon shots blocked"
        )
    elif vix > 20:
        warnings.append(
            f"VIX {vix:.1f} -- elevated; "
            "reduce moon shot entries"
        )


def _build_rationale(
    sym: str,
    tier: str,
    conviction: int,
    size_usd: float,
    thesis_sc: int,
    sentiment: str,
    is_red_day: bool,
    signals_fired: list[str],
) -> str:
    """Build the pre-filled rationale template string."""
    cfg = TIER_CONFIG[tier]
    stop_pct = cfg["stop_loss_pct"]
    partial_pct = cfg["partial_exit_pct"]
    sigs = ", ".join(signals_fired) if signals_fired else "none"
    return (
        f"{sym} ({tier}) | signals: {sigs} | "
        f"conviction: {conviction}/10 | "
        f"thesis_score: {thesis_sc} | "
        f"sentiment: {sentiment} | "
        f"red_day: {is_red_day} | "
        f"size: ${size_usd:,.0f} | "
        f"stop: {stop_pct:.0%} below entry | "
        f"partial exit at: +{partial_pct:.0%} | "
        "[complete: entry, stop, target, sector_impact]"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_pre_trade_check(
    ticker: str,
    tier: str,
    portfolio_value: float,
    portfolio_cash: float,
    sector_allocations: dict[str, float],
    moonshot_total_pct: float,
    market_data: dict,
    signals_fired: list[str],
    volume_confirmed: bool,
    insider_buying: bool,
    is_red_day: bool,
    db_path: str = "data/trader.db",
    blocked_tickers: set[str] | frozenset[str] = _EMPTY_SET,
) -> PreTradeResult:
    """Run all pre-entry gates and return a structured result.

    Gates (in order):
    0. Ticker not on the "Don't buy" blocklist.
    1. Hypothesis exists in journal.
    2. Minimum journal entries for tier.
    3. Latest sentiment not broken or challenged.
    4. No earnings within 7 days.
    5. Cash reserve >= 15% after position.
    6. Sector cap not breached.
    7. Moon shot total cap (moonshot tier only).
    8. Market lockout not triggered.

    Args:
        ticker:             Equity symbol.
        tier:               'core', 'growth', or 'moonshot'.
        portfolio_value:    Total portfolio value in USD.
        portfolio_cash:     Current cash balance in USD.
        sector_allocations: {sector: current_pct_of_portfolio}.
        moonshot_total_pct: Fraction of portfolio in moon shots.
        market_data:        Dict with vix, sp500_above_50ma,
                            portfolio_unrealized_loss_pct,
                            ticker_sector (optional).
        signals_fired:      Signal category names that fired.
        volume_confirmed:   Session volume 20%+ above 30-day avg.
        insider_buying:     Insider purchases in last 30 days.
        is_red_day:         Broad market down >=1.5% today.
        db_path:            Path to the trader SQLite database.
        blocked_tickers:    Tickers from the UI "Don't buy" list.

    Returns:
        PreTradeResult with all gate outcomes.
    """
    init_db(db_path)
    sym = ticker.upper()
    blocks: list[str] = []
    warnings: list[str] = []

    if sym in blocked_tickers:
        blocks.append(
            f"BLOCKLIST: {sym} is on the Don't Buy list"
        )
        return PreTradeResult(approved=False, blocks=blocks)

    sentiment, count = _journal_gates(sym, tier, blocks, db_path)

    can_trade, reason = check_earnings_gate(sym)
    if not can_trade:
        blocks.append(f"EARNINGS GATE: {reason}")

    _cash_gate(portfolio_value, portfolio_cash, blocks)
    _allocation_gates(
        sym, tier, sector_allocations, moonshot_total_pct,
        market_data, blocks, warnings,
    )
    _market_gates(market_data, blocks, warnings)

    conviction = compute_conviction_score(
        journal_entry_count=count,
        latest_sentiment=sentiment,
        is_red_day=is_red_day,
        volume_confirmed=volume_confirmed,
        signals_fired=len(signals_fired),
        insider_buying=insider_buying,
    )
    size_usd = score_to_size(tier, conviction, portfolio_value)
    thesis_sc = compute_thesis_score(sym, db_path)
    rationale = _build_rationale(
        sym, tier, conviction, size_usd,
        thesis_sc, sentiment, is_red_day, signals_fired,
    )

    return PreTradeResult(
        approved=len(blocks) == 0,
        blocks=blocks,
        warnings=warnings,
        conviction_score=conviction,
        recommended_size_usd=size_usd,
        rationale_template=rationale,
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import tempfile

    from brain.journal_store import write_entry

    print("=== pre_trade_check smoke test ===")

    _fd, _db = tempfile.mkstemp(suffix=".db")
    os.close(_fd)

    try:
        for _i in range(5):
            _et = "hypothesis" if _i == 0 else "observation"
            write_entry(
                "NVDA", _et, f"Entry {_i + 1}",
                sentiment="strengthening",
                tier="core",
                db_path=_db,
            )

        _res = run_pre_trade_check(
            ticker="NVDA",
            tier="core",
            portfolio_value=100_000,
            portfolio_cash=20_000,
            sector_allocations={"AI Infrastructure": 0.18},
            moonshot_total_pct=0.0,
            market_data={
                "vix": 22.0,
                "sp500_above_50ma": True,
                "ticker_sector": "AI Infrastructure",
            },
            signals_fired=["Trend", "Pullback Setup"],
            volume_confirmed=True,
            insider_buying=False,
            is_red_day=True,
            db_path=_db,
        )
        print(f"  approved={_res.approved}")
        print(f"  blocks={_res.blocks}")
        print(f"  conviction={_res.conviction_score}")
        print(f"  size=${_res.recommended_size_usd:,.0f}")
        assert _res.approved, _res.blocks

        # Blocklist gate
        _res2 = run_pre_trade_check(
            ticker="AMZN",
            tier="core",
            portfolio_value=100_000,
            portfolio_cash=20_000,
            sector_allocations={},
            moonshot_total_pct=0.0,
            market_data={"vix": 15.0, "sp500_above_50ma": True},
            signals_fired=[],
            volume_confirmed=False,
            insider_buying=False,
            is_red_day=False,
            db_path=_db,
            blocked_tickers={"AMZN", "META"},
        )
        assert not _res2.approved
        assert any("BLOCKLIST" in b for b in _res2.blocks)
        print("  Blocklist gate: OK")

    finally:
        os.unlink(_db)

    print("  Smoke test passed.")
