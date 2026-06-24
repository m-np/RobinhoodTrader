"""
Export / import all app data as a single JSON bundle.

GET  /api/export  — streams a dated .json file for download
POST /api/import  — accepts the same JSON and upserts into the local DB

What is included
----------------
  Postgres: watchlist, blocklist, config_knobs, mirror_sources,
            trades, alerts, reports, portfolio_snapshots, stock_discoveries
  SQLite  : journal_entries, positions   (brain/data/trader.db)

What is excluded
----------------
  robinhood_tokens   — encrypted and tied to ENCRYPTION_KEY; re-authenticate
                       on the new machine via /auth/robinhood
  watchlist_price_snapshots — ephemeral price cache; regenerates automatically
"""

import json
import sqlite3
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import get_db
from brain.journal_store import _DEFAULT_DB, _connect, init_db
from db.models import (
    Alert,
    Blocklist,
    ConfigKnob,
    MirrorSource,
    PortfolioSnapshot,
    Report,
    StockDiscovery,
    Trade,
    Watchlist,
)

EXPORT_VERSION = "1"

transfer_router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATETIME_FMTS = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


def _to_dict(obj, exclude: tuple = ()) -> dict:
    """Serialize a SQLAlchemy row to a plain dict with ISO datetime strings."""
    d = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        v = getattr(obj, col.name)
        d[col.name] = v.isoformat() if isinstance(v, datetime) else v
    return d


def _parse_value(v):
    """Convert ISO datetime strings back to datetime objects; pass everything else through."""
    if not isinstance(v, str):
        return v
    for fmt in _DATETIME_FMTS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return v


def _parse_row(row: dict) -> dict:
    return {k: _parse_value(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@transfer_router.get("/api/export")
def export_data(db: Session = Depends(get_db)):
    """Download all app data as a JSON file."""
    payload: dict = {
        "version": EXPORT_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "note": (
            "robinhood_tokens excluded — re-authenticate on the new machine "
            "via /auth/robinhood after import."
        ),
        "data": {
            "watchlist": [_to_dict(r) for r in db.query(Watchlist).all()],
            "blocklist": [_to_dict(r) for r in db.query(Blocklist).all()],
            "config_knobs": [_to_dict(r) for r in db.query(ConfigKnob).all()],
            "mirror_sources": [
                _to_dict(r, exclude=("last_checked_at",))
                for r in db.query(MirrorSource).all()
            ],
            "trades": [_to_dict(r) for r in db.query(Trade).all()],
            "alerts": [_to_dict(r) for r in db.query(Alert).all()],
            "reports": [_to_dict(r) for r in db.query(Report).all()],
            "portfolio_snapshots": [
                _to_dict(r) for r in db.query(PortfolioSnapshot).all()
            ],
            "stock_discoveries": [
                _to_dict(r) for r in db.query(StockDiscovery).all()
            ],
            "journal_entries": [],
            "positions": [],
        },
    }

    # Pull SQLite journal
    try:
        init_db()
        with _connect(_DEFAULT_DB) as conn:
            conn.row_factory = sqlite3.Row
            payload["data"]["journal_entries"] = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM journal_entries ORDER BY id"
                ).fetchall()
            ]
            payload["data"]["positions"] = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM positions ORDER BY id"
                ).fetchall()
            ]
    except Exception as exc:
        payload["warnings"] = [f"journal export partial: {exc}"]

    blob = json.dumps(payload, indent=2, default=str).encode()
    filename = (
        f"trader_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    )
    return StreamingResponse(
        BytesIO(blob),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@transfer_router.post("/api/import")
async def import_data(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a trader_export_*.json file and merge its data into this instance."""
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    if payload.get("version") != EXPORT_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported export version {payload.get('version')!r}. "
                f"Expected {EXPORT_VERSION!r}."
            ),
        )

    data = payload.get("data", {})
    report: dict = {"imported": {}, "skipped": {}, "errors": []}

    # -- helpers ---------------------------------------------------------------

    def upsert_by_id(Model, rows: list) -> tuple[int, int]:
        n_new = n_skip = 0
        for row in rows:
            if db.get(Model, row["id"]):
                n_skip += 1
            else:
                db.add(Model(**_parse_row(row)))
                n_new += 1
        return n_new, n_skip

    def upsert_by_field(Model, rows: list, field: str) -> tuple[int, int]:
        n_new = n_skip = 0
        for row in rows:
            exists = (
                db.query(Model)
                .filter(getattr(Model, field) == row[field])
                .first()
            )
            if exists:
                n_skip += 1
            else:
                db.add(Model(**_parse_row(row)))
                n_new += 1
        return n_new, n_skip

    # -- Postgres tables -------------------------------------------------------

    table_map = [
        # (data_key, Model, strategy, unique_field)
        ("watchlist",          Watchlist,         "field", "ticker"),
        ("blocklist",          Blocklist,          "field", "ticker"),
        ("config_knobs",       ConfigKnob,         "field", "key"),
        ("trades",             Trade,              "id",    None),
        ("alerts",             Alert,              "id",    None),
        ("reports",            Report,             "id",    None),
        ("portfolio_snapshots",PortfolioSnapshot,  "id",    None),
        ("stock_discoveries",  StockDiscovery,     "id",    None),
    ]

    for key, Model, strategy, field in table_map:
        rows = data.get(key, [])
        try:
            if strategy == "field":
                n_new, n_skip = upsert_by_field(Model, rows, field)
            else:
                n_new, n_skip = upsert_by_id(Model, rows)
            report["imported"][key] = n_new
            report["skipped"][key] = n_skip
        except Exception as exc:
            report["errors"].append(f"{key}: {exc}")

    # mirror_sources — upsert by slug; update enabled/scale_factor if exists
    n_new = n_skip = 0
    for row in data.get("mirror_sources", []):
        existing = (
            db.query(MirrorSource)
            .filter(MirrorSource.slug == row["slug"])
            .first()
        )
        if existing:
            existing.enabled = row.get("enabled", existing.enabled)
            existing.scale_factor = row.get(
                "scale_factor", existing.scale_factor
            )
            n_skip += 1
        else:
            db.add(MirrorSource(**_parse_row(row)))
            n_new += 1
    report["imported"]["mirror_sources"] = n_new
    report["skipped"]["mirror_sources"] = n_skip

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database commit failed: {exc}"
        ) from exc

    # -- SQLite journal --------------------------------------------------------
    try:
        init_db()
        with _connect(_DEFAULT_DB) as conn:
            conn.row_factory = sqlite3.Row

            # journal_entries — dedup by (ticker, entry_type, created_at)
            n_new = 0
            for row in data.get("journal_entries", []):
                exists = conn.execute(
                    "SELECT 1 FROM journal_entries "
                    "WHERE ticker=? AND entry_type=? AND created_at=?",
                    (row["ticker"], row["entry_type"], row["created_at"]),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO journal_entries "
                        "(ticker, entry_type, sentiment, text, tier, created_at) "
                        "VALUES (:ticker, :entry_type, :sentiment, :text, "
                        ":tier, :created_at)",
                        {k: row.get(k) for k in (
                            "ticker", "entry_type", "sentiment",
                            "text", "tier", "created_at",
                        )},
                    )
                    n_new += 1
            report["imported"]["journal_entries"] = n_new

            # positions — dedup by (ticker, entry_date, entry_price)
            n_new = 0
            for row in data.get("positions", []):
                exists = conn.execute(
                    "SELECT 1 FROM positions "
                    "WHERE ticker=? AND entry_date=? AND entry_price=?",
                    (row["ticker"], row["entry_date"], row["entry_price"]),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO positions "
                        "(ticker, tier, entry_price, entry_date, shares, "
                        "amount_usd, status, exit_price, exit_date, "
                        "pnl_pct, exit_reason) "
                        "VALUES (:ticker, :tier, :entry_price, :entry_date, "
                        ":shares, :amount_usd, :status, :exit_price, "
                        ":exit_date, :pnl_pct, :exit_reason)",
                        {k: row.get(k) for k in (
                            "ticker", "tier", "entry_price", "entry_date",
                            "shares", "amount_usd", "status", "exit_price",
                            "exit_date", "pnl_pct", "exit_reason",
                        )},
                    )
                    n_new += 1
            report["imported"]["positions"] = n_new

            conn.commit()

    except Exception as exc:
        report["errors"].append(f"journal: {exc}")

    return report
