"""
Core logic tests for the standalone trading agent.

All tests use temporary SQLite files and mock yfinance to avoid
live network calls. Run with: pytest tests/test_agent.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import brain.journal_store as js
import brain.tier_classifier as tc
from brain.pre_trade_check import run_pre_trade_check
from brain.red_day_detector import classify_red_day


# Override the autouse PostgreSQL fixture from tests/conftest.py.
@pytest.fixture(scope="session", autouse=True)
def _isolate_live_db():  # noqa: F811
    """No-op: these tests use SQLite only, no PostgreSQL."""
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    """Provide a fresh SQLite database path per test."""
    path = str(tmp_path / "test.db")
    js.init_db(path)
    return path


def _seed(
    ticker: str,
    count: int,
    sentiment: str,
    db_path: str,
    tier: str = "core",
) -> None:
    """Seed *count* journal entries for *ticker*."""
    for idx in range(count):
        etype = "hypothesis" if idx == 0 else "observation"
        js.write_entry(
            ticker, etype, f"Entry {idx + 1}",
            sentiment=sentiment,
            tier=tier,
            db_path=db_path,
        )


# ---------------------------------------------------------------------------
# 1. Journal write and read
# ---------------------------------------------------------------------------

def test_journal_write_and_read(db):
    """Write hypothesis, observation, entry, exit; read back in order."""
    js.write_entry("NVDA", "hypothesis", "AIP thesis",
                   sentiment="strengthening", tier="core",
                   db_path=db)
    js.write_entry("NVDA", "observation", "Q1 beat",
                   sentiment="strengthening", db_path=db)
    js.write_entry("NVDA", "entry", "Opened position",
                   db_path=db)
    js.write_entry("NVDA", "exit", "Closed at profit",
                   db_path=db)

    entries = js.read_journal("NVDA", db_path=db)
    assert len(entries) == 4
    # newest first
    assert entries[0]["entry_type"] == "exit"
    assert entries[-1]["entry_type"] == "hypothesis"
    assert js.has_hypothesis("NVDA", db_path=db)
    assert js.get_tier("NVDA", db_path=db) == "core"


# ---------------------------------------------------------------------------
# 2. Thesis score computation
# ---------------------------------------------------------------------------

def test_thesis_score_computation(db):
    """2 strengthening + 2 neutral + 1 challenged -> score = 2*2+2*1+0 = 6."""
    sentiments = [
        "strengthening", "strengthening",
        "neutral", "neutral", "challenged",
    ]
    for idx, sent in enumerate(sentiments):
        etype = "hypothesis" if idx == 0 else "update"
        js.write_entry(
            "TSM", etype, f"Entry {idx + 1}",
            sentiment=sent, tier="core", db_path=db,
        )
    score = js.compute_thesis_score("TSM", db_path=db)
    assert score == 6, f"Expected 6, got {score}"


# ---------------------------------------------------------------------------
# 3. Core tier classification (mocked yfinance)
# ---------------------------------------------------------------------------

_MOCK_HIST = pd.DataFrame(
    {"Close": [100.0]},
    index=pd.to_datetime(["2019-01-01"], utc=True),
)


def _core_ticker_mock(_sym: str) -> MagicMock:
    t = MagicMock()
    t.info = {
        "marketCap": 3_000_000_000_000,
        "totalRevenue": 80_000_000_000,
        "revenueGrowth": 0.22,
        "trailingPE": 45.0,
        "sector": "Technology",
        "industry": "Semiconductors",
    }
    t.history.return_value = _MOCK_HIST
    return t


def test_core_tier_classification():
    """Large cap + 22% growth -> Core tier."""
    with patch("yfinance.Ticker", side_effect=_core_ticker_mock):
        result = tc.classify_ticker("TEST", moat_present=True)
    assert result.tier == "core", result.gaps


# ---------------------------------------------------------------------------
# 4. Moon shot classification (mocked yfinance)
# ---------------------------------------------------------------------------

def _moon_ticker_mock(_sym: str) -> MagicMock:
    t = MagicMock()
    t.info = {
        "marketCap": 400_000_000,
        "totalRevenue": None,
        "revenueGrowth": None,
        "trailingPE": None,
        "sector": "Industrials",
        "industry": "Aerospace",
    }
    t.history.return_value = _MOCK_HIST
    return t


def test_moonshot_classification():
    """Small cap, no revenue, assertions provided -> Moon Shot."""
    with patch("yfinance.Ticker", side_effect=_moon_ticker_mock):
        result = tc.classify_ticker(
            "MOON",
            technology_real=True,
            binary_thesis_written=True,
            exit_condition_written=True,
        )
    assert result.tier == "moonshot", result.gaps


# ---------------------------------------------------------------------------
# 5. Conviction score and sizing
# ---------------------------------------------------------------------------

def test_conviction_score_and_sizing():
    """Score 8, core tier, $100k -> $20k position."""
    score = tc.compute_conviction_score(
        journal_entry_count=5,
        latest_sentiment="strengthening",
        is_red_day=True,
        volume_confirmed=False,
        signals_fired=2,
        insider_buying=False,
    )
    # 3 (entries) + 2 (strengthening) + 1 (red day) + 2 (signals) = 8
    assert score == 8, f"Expected 8, got {score}"
    size = tc.score_to_size("core", score, 100_000)
    assert size == 20_000.0, f"Expected $20k, got ${size}"


# ---------------------------------------------------------------------------
# 6. Pre-trade check: blocked when no hypothesis
# ---------------------------------------------------------------------------

def test_pre_trade_check_blocks_no_hypothesis(db):
    """No journal entry -> blocked."""
    result = run_pre_trade_check(
        ticker="AAPL",
        tier="core",
        portfolio_value=100_000,
        portfolio_cash=20_000,
        sector_allocations={},
        moonshot_total_pct=0.0,
        market_data={"vix": 15.0, "sp500_above_50ma": True},
        signals_fired=["Trend"],
        volume_confirmed=False,
        insider_buying=False,
        is_red_day=False,
        db_path=db,
    )
    assert not result.approved
    assert any("HYPOTHESIS" in b for b in result.blocks)


# ---------------------------------------------------------------------------
# 7. Pre-trade check: blocked near earnings
# ---------------------------------------------------------------------------

def test_pre_trade_check_blocks_earnings(db):
    """Earnings in 5 days -> blocked."""
    _seed("NVDA", 5, "strengthening", db)

    with patch(
        "brain.pre_trade_check.check_earnings_gate",
        return_value=(
            False,
            "NVDA: earnings in 5 day(s) -- hard block",
        ),
    ):
        result = run_pre_trade_check(
            ticker="NVDA",
            tier="core",
            portfolio_value=100_000,
            portfolio_cash=20_000,
            sector_allocations={},
            moonshot_total_pct=0.0,
            market_data={"vix": 15.0, "sp500_above_50ma": True},
            signals_fired=["Trend"],
            volume_confirmed=False,
            insider_buying=False,
            is_red_day=False,
            db_path=db,
        )
    assert not result.approved
    assert any("EARNINGS" in b for b in result.blocks)


# ---------------------------------------------------------------------------
# 8. Pre-trade check: blocked on broken thesis
# ---------------------------------------------------------------------------

def test_pre_trade_check_blocks_broken_thesis(db):
    """Latest sentiment = broken -> blocked."""
    _seed("PLTR", 4, "strengthening", db)
    js.write_entry(
        "PLTR", "update", "AIP churn confirmed",
        sentiment="broken", db_path=db,
    )
    result = run_pre_trade_check(
        ticker="PLTR",
        tier="core",
        portfolio_value=100_000,
        portfolio_cash=20_000,
        sector_allocations={},
        moonshot_total_pct=0.0,
        market_data={"vix": 15.0, "sp500_above_50ma": True},
        signals_fired=["Trend"],
        volume_confirmed=False,
        insider_buying=False,
        is_red_day=False,
        db_path=db,
    )
    assert not result.approved
    assert any("BROKEN" in b for b in result.blocks)


# ---------------------------------------------------------------------------
# 9. Pre-trade check: approved on valid setup
# ---------------------------------------------------------------------------

def test_pre_trade_check_approves_valid_setup(db):
    """All gates pass -> approved with score and rationale."""
    _seed("NVDA", 5, "strengthening", db)

    with patch(
        "brain.pre_trade_check.check_earnings_gate",
        return_value=(True, "NVDA: 30 days to earnings"),
    ):
        result = run_pre_trade_check(
            ticker="NVDA",
            tier="core",
            portfolio_value=100_000,
            portfolio_cash=20_000,
            sector_allocations={"AI Infrastructure": 0.10},
            moonshot_total_pct=0.0,
            market_data={
                "vix": 20.0,
                "sp500_above_50ma": True,
                "ticker_sector": "AI Infrastructure",
            },
            signals_fired=["Trend", "Pullback Setup"],
            volume_confirmed=True,
            insider_buying=False,
            is_red_day=True,
            db_path=db,
        )
    assert result.approved, result.blocks
    assert result.conviction_score > 0
    assert result.recommended_size_usd > 0
    assert len(result.rationale_template) > 10


# ---------------------------------------------------------------------------
# 10. Red day classification
# ---------------------------------------------------------------------------

def test_red_day_classification():
    """S&P down 2.1% -> Level 2 confirmed, core+growth eligible."""
    rd = classify_red_day(-0.021, 20.0)
    assert rd["level"] == 2
    assert rd["label"] == "confirmed"
    assert "core" in rd["eligible_tiers"]
    assert "growth" in rd["eligible_tiers"]
    assert rd["max_cash_deploy_pct"] == 0.25

    assert classify_red_day(0.005, 15.0)["level"] == 0
    assert classify_red_day(-0.035, 27.0)["level"] == 3
    assert classify_red_day(-0.005, 36.0)["level"] == 4


# ---------------------------------------------------------------------------
# 11. Sector cap enforcement
# ---------------------------------------------------------------------------

def test_sector_cap_enforcement():
    """AI Infra at 33% + 5% -> blocked (would exceed 35% cap)."""
    ok, msg = tc.check_sector_cap(
        "AI Infrastructure",
        current_sector_pct=0.33,
        new_position_pct=0.05,
    )
    assert not ok
    assert "35%" in msg or "cap" in msg.lower()

    ok2, _ = tc.check_sector_cap(
        "AI Infrastructure",
        current_sector_pct=0.20,
        new_position_pct=0.05,
    )
    assert ok2


# ---------------------------------------------------------------------------
# 12. Position lifecycle
# ---------------------------------------------------------------------------

def test_position_lifecycle(db):
    """open -> close computes pnl_pct correctly."""
    pos_id = js.open_position(
        "NVDA", "core", 120.0, 10, 1200.0, db_path=db
    )
    assert pos_id > 0

    open_pos = js.get_open_positions(db_path=db)
    assert len(open_pos) == 1
    assert open_pos[0]["ticker"] == "NVDA"

    closed = js.close_position(
        "NVDA", 150.0, "profit_target", db_path=db
    )
    assert abs(closed["pnl_pct"] - 25.0) < 0.01
    assert js.get_open_positions(db_path=db) == []
