"""
SQLite-backed journal for all thesis tracking, trade notes, and position history.
The journal is the agent's only persistent memory. All classification, thesis
reasoning, sentiment tracking, and trade autopsies live here.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB = "data/trader.db"

VALID_ENTRY_TYPES = {"hypothesis", "observation", "entry", "update", "exit", "alert"}
VALID_SENTIMENTS = {"strengthening", "neutral", "challenged", "broken"}
VALID_TIERS = {"core", "growth", "moonshot"}
VALID_POSITION_STATUS = {"open", "closed"}
VALID_EXIT_REASONS = {"stop_loss", "profit_target", "thesis_break", "rebalance"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def init_db(db_path: str = _DEFAULT_DB) -> None:
    """Create tables if they do not exist. Enable WAL mode for concurrent reads.

    Args:
        db_path: Path to the SQLite database file.
    """
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                sentiment  TEXT,
                text       TEXT NOT NULL,
                tier       TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_je_ticker ON journal_entries(ticker)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT NOT NULL,
                tier        TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_date  TEXT NOT NULL,
                shares      REAL NOT NULL,
                amount_usd  REAL NOT NULL,
                status      TEXT NOT NULL DEFAULT 'open',
                exit_price  REAL,
                exit_date   TEXT,
                pnl_pct     REAL,
                exit_reason TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pos_ticker ON positions(ticker)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker     TEXT,
                alert_type TEXT NOT NULL,
                message    TEXT NOT NULL,
                resolved   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------

def write_entry(
    ticker: str,
    entry_type: str,
    text: str,
    sentiment: str | None = None,
    tier: str | None = None,
    db_path: str = _DEFAULT_DB,
) -> int:
    """Write a journal entry. Return the new entry id.

    Args:
        ticker:     Equity symbol (stored upper-case).
        entry_type: One of 'hypothesis', 'observation', 'entry', 'update', 'exit', 'alert'.
        text:       Free-form content.
        sentiment:  Optional — 'strengthening', 'neutral', 'challenged', or 'broken'.
        tier:       Optional — 'core', 'growth', or 'moonshot' (set on hypothesis entries).
        db_path:    Path to the SQLite database.

    Returns:
        The auto-assigned row id.
    """
    ticker = ticker.upper()
    if entry_type not in VALID_ENTRY_TYPES:
        raise ValueError(f"Invalid entry_type {entry_type!r}")
    if sentiment is not None and sentiment not in VALID_SENTIMENTS:
        raise ValueError(f"Invalid sentiment {sentiment!r}")
    if tier is not None and tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier {tier!r}")

    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO journal_entries (ticker, entry_type, sentiment, text, tier, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker, entry_type, sentiment, text, tier, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid or 0


def read_journal(ticker: str, db_path: str = _DEFAULT_DB, limit: int = 0) -> list[dict]:
    """Return journal entries for a ticker, newest first.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.
        limit:   Max entries to return (0 = all).

    Returns:
        List of row dicts with keys: id, ticker, entry_type, sentiment, text, tier, created_at.
    """
    with _connect(db_path) as conn:
        sql = (
            "SELECT id, ticker, entry_type, sentiment, text, tier, created_at "
            "FROM journal_entries WHERE ticker = ? ORDER BY id DESC"
        )
        if limit > 0:
            sql += f" LIMIT {limit}"
        rows = conn.execute(sql, (ticker.upper(),)).fetchall()
    return [dict(r) for r in rows]


def get_latest_sentiment(ticker: str, db_path: str = _DEFAULT_DB) -> str | None:
    """Return the most recent sentiment value for a ticker, or None.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.

    Returns:
        Sentiment string or None if no entry with a sentiment value exists.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT sentiment FROM journal_entries "
            "WHERE ticker = ? AND sentiment IS NOT NULL ORDER BY id DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return row["sentiment"] if row else None


def get_entry_count(ticker: str, db_path: str = _DEFAULT_DB) -> int:
    """Return the number of journal entries for a ticker.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM journal_entries WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
    return row["cnt"] if row else 0


def compute_thesis_score(ticker: str, db_path: str = _DEFAULT_DB) -> int:
    """Score from the last 5 entries that have a sentiment field.

    strengthening=2, neutral=1, challenged/broken=0. Maximum score: 10.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.

    Returns:
        Integer score in [0, 10].
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT sentiment FROM journal_entries "
            "WHERE ticker = ? AND sentiment IS NOT NULL ORDER BY id DESC LIMIT 5",
            (ticker.upper(),),
        ).fetchall()
    score = 0
    for row in rows:
        if row["sentiment"] == "strengthening":
            score += 2
        elif row["sentiment"] == "neutral":
            score += 1
    return min(score, 10)


def has_hypothesis(ticker: str, db_path: str = _DEFAULT_DB) -> bool:
    """Return True if ticker has at least one hypothesis entry.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM journal_entries WHERE ticker = ? AND entry_type = 'hypothesis' LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return row is not None


def get_tier(ticker: str, db_path: str = _DEFAULT_DB) -> str | None:
    """Return tier from the most recent hypothesis entry, or None.

    Args:
        ticker:  Equity symbol.
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT tier FROM journal_entries "
            "WHERE ticker = ? AND entry_type = 'hypothesis' AND tier IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
    return row["tier"] if row else None


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

def open_position(
    ticker: str,
    tier: str,
    entry_price: float,
    shares: float,
    amount_usd: float,
    db_path: str = _DEFAULT_DB,
) -> int:
    """Record a new open position. Return position id.

    Args:
        ticker:     Equity symbol.
        tier:       'core', 'growth', or 'moonshot'.
        entry_price: Purchase price per share.
        shares:     Number of shares (may be fractional).
        amount_usd: Total dollars deployed.
        db_path:    Path to the SQLite database.

    Returns:
        Auto-assigned position id.
    """
    if tier not in VALID_TIERS:
        raise ValueError(f"Invalid tier {tier!r}")
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO positions (ticker, tier, entry_price, entry_date, shares, amount_usd, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open')",
            (ticker.upper(), tier, entry_price, _now_iso(), shares, amount_usd),
        )
        conn.commit()
        return cur.lastrowid or 0


def close_position(
    ticker: str,
    exit_price: float,
    exit_reason: str,
    db_path: str = _DEFAULT_DB,
) -> dict:
    """Close the open position for this ticker. Compute pnl_pct and update status.

    Args:
        ticker:      Equity symbol.
        exit_price:  Price at exit.
        exit_reason: One of 'stop_loss', 'profit_target', 'thesis_break', 'rebalance'.
        db_path:     Path to the SQLite database.

    Returns:
        Full position dict after closure, including pnl_pct.

    Raises:
        ValueError: If no open position exists for this ticker.
    """
    if exit_reason not in VALID_EXIT_REASONS:
        raise ValueError(f"Invalid exit_reason {exit_reason!r}")
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, entry_price FROM positions WHERE ticker = ? AND status = 'open' LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        if not row:
            raise ValueError(f"No open position for {ticker}")
        pnl_pct = (exit_price - row["entry_price"]) / row["entry_price"] * 100
        conn.execute(
            "UPDATE positions SET status='closed', exit_price=?, exit_date=?, pnl_pct=?, exit_reason=? "
            "WHERE id=?",
            (exit_price, _now_iso(), pnl_pct, exit_reason, row["id"]),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM positions WHERE id=?", (row["id"],)).fetchone()
        return dict(updated)


def get_open_positions(db_path: str = _DEFAULT_DB) -> list[dict]:
    """Return all open positions as list of dicts.

    Args:
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_date ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

def create_alert(
    ticker: str | None,
    alert_type: str,
    message: str,
    db_path: str = _DEFAULT_DB,
) -> int:
    """Write an alert. Return alert id.

    Args:
        ticker:     Optional equity symbol this alert relates to.
        alert_type: Short category string (e.g. 'EARNINGS_7D', 'THESIS_BROKEN').
        message:    Human-readable alert body.
        db_path:    Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO alerts (ticker, alert_type, message, resolved, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (ticker.upper() if ticker else None, alert_type, message, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_unresolved_alerts(db_path: str = _DEFAULT_DB) -> list[dict]:
    """Return all unresolved alerts, newest first.

    Args:
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE resolved = 0 ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def resolve_alert(alert_id: int, db_path: str = _DEFAULT_DB) -> None:
    """Mark an alert as resolved.

    Args:
        alert_id: The alert id to resolve.
        db_path:  Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        conn.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Watchlist helpers
# ---------------------------------------------------------------------------

def get_all_watchlist_tickers(db_path: str = _DEFAULT_DB) -> list[str]:
    """Return distinct tickers that have at least one journal entry.

    Args:
        db_path: Path to the SQLite database.
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM journal_entries ORDER BY ticker"
        ).fetchall()
    return [r["ticker"] for r in rows]


def get_watchlist_with_status(
    tickers: list[str] | None = None,
    db_path: str = _DEFAULT_DB,
) -> list[dict]:
    """Return watchlist tickers enriched with journal status.

    Each dict contains: ticker, tier, entry_count, latest_sentiment,
    thesis_score, has_open_position.

    Args:
        tickers: Explicit ticker list (e.g. from the UI watchlist).
                 When None, falls back to tickers that have at least
                 one journal entry in this SQLite database.
        db_path: Path to the SQLite database.
    """
    if tickers is None:
        tickers = get_all_watchlist_tickers(db_path)
    open_pos_tickers = {
        p["ticker"] for p in get_open_positions(db_path)
    }
    result = []
    for ticker in tickers:
        result.append({
            "ticker": ticker,
            "tier": get_tier(ticker, db_path),
            "entry_count": get_entry_count(ticker, db_path),
            "latest_sentiment": get_latest_sentiment(ticker, db_path),
            "thesis_score": compute_thesis_score(ticker, db_path),
            "has_open_position": ticker in open_pos_tickers,
        })
    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db = f.name

    print("=== journal_store smoke test ===")
    init_db(db)

    # Journal entries
    write_entry("NVDA", "hypothesis", "AIP ramp creates structural GPU demand", sentiment="strengthening", tier="core", db_path=db)
    write_entry("NVDA", "observation", "Q1 data centers beat by 12%", sentiment="strengthening", db_path=db)
    write_entry("NVDA", "update", "Supply chain delays — macro noise", sentiment="neutral", db_path=db)
    write_entry("NVDA", "update", "Blackwell ramp confirmed", sentiment="strengthening", db_path=db)
    write_entry("NVDA", "observation", "No new catalyst — monitoring", sentiment="neutral", db_path=db)

    score = compute_thesis_score("NVDA", db)
    print(f"  thesis_score(NVDA) = {score}  (expected 8: 3×2 + 2×1)")
    assert score == 8, f"got {score}"
    assert get_latest_sentiment("NVDA", db) == "neutral"
    assert has_hypothesis("NVDA", db)
    assert get_tier("NVDA", db) == "core"
    assert get_entry_count("NVDA", db) == 5

    # Position lifecycle
    pos_id = open_position("NVDA", "core", 120.0, 10, 1200.0, db)
    assert pos_id > 0
    positions = get_open_positions(db)
    assert len(positions) == 1

    closed = close_position("NVDA", 150.0, "profit_target", db)
    assert abs(closed["pnl_pct"] - 25.0) < 0.01
    assert get_open_positions(db) == []

    # Alerts
    alert_id = create_alert("NVDA", "EARNINGS_7D", "Earnings in 5 days", db)
    unresolved = get_unresolved_alerts(db)
    assert len(unresolved) == 1
    resolve_alert(alert_id, db)
    assert get_unresolved_alerts(db) == []

    # Watchlist
    write_entry("PLTR", "hypothesis", "AIP government momentum", sentiment="strengthening", tier="core", db_path=db)
    watchlist = get_watchlist_with_status(db)
    assert len(watchlist) == 2
    print(f"  watchlist: {[w['ticker'] for w in watchlist]}")

    os.unlink(db)
    print("  All assertions passed.")
