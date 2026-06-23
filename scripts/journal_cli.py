#!/usr/bin/env python
"""Journal CLI — add and read thesis journal entries from the terminal.

Usage:
  python scripts/journal_cli.py add NVDA hypothesis "Blackwell GPU moat" \\
      --sentiment strengthening --tier core

  python scripts/journal_cli.py list NVDA
  python scripts/journal_cli.py status
  python scripts/journal_cli.py delete NVDA 7
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from brain.journal_store import (
    VALID_ENTRY_TYPES,
    VALID_SENTIMENTS,
    VALID_TIERS,
    get_watchlist_with_status,
    init_db,
    read_journal,
    write_entry,
)

_DEFAULT_DB = "data/trader.db"


def _fmt_row(entry: dict) -> str:
    parts = [
        f"[{entry['id']:>4}]",
        f"{entry['entry_type']:<12}",
        f"{entry.get('sentiment') or '—':<14}",
        f"{entry.get('tier') or '—':<10}",
        f"{entry['created_at'][:16]}",
        f"  {entry['text']}",
    ]
    return "  ".join(parts)


def cmd_add(args: argparse.Namespace) -> None:
    init_db(args.db)
    entry_id = write_entry(
        ticker=args.ticker,
        entry_type=args.entry_type,
        text=args.text,
        sentiment=args.sentiment,
        tier=args.tier,
        db_path=args.db,
    )
    print(
        f"Added entry #{entry_id} for "
        f"{args.ticker.upper()} ({args.entry_type})"
    )


def cmd_list(args: argparse.Namespace) -> None:
    init_db(args.db)
    entries = read_journal(args.ticker, db_path=args.db)
    if not entries:
        print(f"No journal entries for {args.ticker.upper()}.")
        return
    header = (
        f"  {'ID':>4}  {'TYPE':<12}  {'SENTIMENT':<14}  "
        f"{'TIER':<10}  {'DATE'}  TEXT"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))
    for e in entries:
        print(_fmt_row(e))


def cmd_status(args: argparse.Namespace) -> None:
    init_db(args.db)
    rows = get_watchlist_with_status(db_path=args.db)
    if not rows:
        print("Journal is empty. Add entries with: journal_cli.py add ...")
        return
    print(
        f"  {'TICKER':<8}  {'TIER':<10}  {'ENTRIES':>7}  "
        f"{'SENTIMENT':<14}  {'SCORE':>5}  {'POSITION'}"
    )
    print("  " + "-" * 62)
    for r in rows:
        pos = "OPEN" if r["has_open_position"] else ""
        print(
            f"  {r['ticker']:<8}  "
            f"{r['tier'] or '—':<10}  "
            f"{r['entry_count']:>7}  "
            f"{r['latest_sentiment'] or '—':<14}  "
            f"{r['thesis_score']:>5}  "
            f"{pos}"
        )


def cmd_delete(args: argparse.Namespace) -> None:
    import sqlite3
    from pathlib import Path as _Path
    db_path = args.db
    _Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id, ticker FROM journal_entries WHERE id = ?",
        (args.entry_id,),
    ).fetchone()
    if not row:
        print(f"Entry #{args.entry_id} not found.")
        conn.close()
        return
    confirm = input(
        f"Delete entry #{row[0]} for {row[1]}? [y/N] "
    )
    if confirm.strip().lower() != "y":
        print("Cancelled.")
        conn.close()
        return
    conn.execute(
        "DELETE FROM journal_entries WHERE id = ?", (args.entry_id,)
    )
    conn.commit()
    conn.close()
    print(f"Deleted entry #{args.entry_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="journal_cli.py",
        description="Manage the thesis journal from the terminal.",
    )
    parser.add_argument(
        "--db", default=_DEFAULT_DB, help="Path to SQLite database"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a journal entry")
    p_add.add_argument("ticker", help="Ticker symbol, e.g. NVDA")
    p_add.add_argument(
        "entry_type",
        choices=sorted(VALID_ENTRY_TYPES),
        help="Entry type",
    )
    p_add.add_argument("text", help="Journal text")
    p_add.add_argument(
        "--sentiment",
        choices=sorted(VALID_SENTIMENTS),
        default=None,
        help="Thesis sentiment",
    )
    p_add.add_argument(
        "--tier",
        choices=sorted(VALID_TIERS),
        default=None,
        help="Conviction tier (set on hypothesis entries)",
    )
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", help="List entries for a ticker")
    p_list.add_argument("ticker", help="Ticker symbol")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser(
        "status", help="Show thesis score for all tickers"
    )
    p_status.set_defaults(func=cmd_status)

    # delete
    p_del = sub.add_parser("delete", help="Delete a journal entry by ID")
    p_del.add_argument("ticker", help="Ticker symbol (for confirmation)")
    p_del.add_argument("entry_id", type=int, help="Entry ID from list")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
