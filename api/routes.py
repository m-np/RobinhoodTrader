import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.guardrails import get_knob, set_knob
from agent.mcp_client import RobinhoodMCPClient
from api.deps import get_db
from db.models import Alert, Blocklist, ConfigKnob, MirrorSource, Report, Trade, Watchlist

router = APIRouter()
templates = Jinja2Templates(directory="ui/templates")
_mcp = None


def _get_mcp() -> RobinhoodMCPClient:
    global _mcp
    if _mcp is None:
        _mcp = RobinhoodMCPClient()
    return _mcp


# ── HTML pages ──────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"active": "dashboard"})


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request):
    return templates.TemplateResponse(request, "watchlist.html", {"active": "watchlist"})


@router.get("/mirrors", response_class=HTMLResponse)
async def mirrors_page(request: Request):
    return templates.TemplateResponse(request, "mirrors.html", {"active": "mirrors"})


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"active": "settings"})


# ── Portfolio / wallet ───────────────────────────────────────────────────────

@router.get("/api/portfolio")
async def api_portfolio(db: Session = Depends(get_db)):
    mcp = _get_mcp()
    portfolio = mcp.get_portfolio()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    trades_today = db.query(Trade).filter(
        Trade.created_at >= today_start, Trade.status == "executed"
    ).count()
    return {
        **portfolio,
        "trades_today": trades_today,
        "today_pnl": portfolio.get("today_pnl", 0.0),
        "total_return_pct": portfolio.get("total_return_pct", 0.0),
        "holdings": portfolio.get("holdings", []),
    }


@router.get("/api/wallet")
async def api_wallet():
    mcp = _get_mcp()
    balance = mcp.get_wallet_balance()
    return {"balance": balance}


# ── Trades ───────────────────────────────────────────────────────────────────

@router.get("/api/trades")
async def api_trades(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(Trade).order_by(Trade.created_at.desc()).limit(limit).all()
    return [
        {
            "id": t.id,
            "ticker": t.ticker,
            "action": t.action,
            "asset_class": t.asset_class,
            "quantity": t.quantity,
            "price_usd": t.price_usd,
            "total_usd": t.total_usd,
            "status": t.status,
            "rationale": t.rationale,
            "mirror_source": t.mirror_source,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
        }
        for t in rows
    ]


@router.post("/api/trades/{trade_id}/approve")
async def approve_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.status = "executed"
    trade.executed_at = datetime.utcnow()
    db.query(Alert).filter(Alert.trade_id == trade_id).update({"acknowledged": True})
    db.commit()
    return {"status": "approved"}


@router.post("/api/trades/{trade_id}/reject")
async def reject_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.status = "rejected"
    db.query(Alert).filter(Alert.trade_id == trade_id).update({"acknowledged": True})
    db.commit()
    return {"status": "rejected"}


# ── Alerts ───────────────────────────────────────────────────────────────────

@router.get("/api/alerts")
async def api_alerts(db: Session = Depends(get_db)):
    rows = db.query(Alert).filter(Alert.acknowledged == False).order_by(Alert.created_at.desc()).all()
    return [
        {
            "id": a.id,
            "ticker": a.ticker,
            "alert_type": a.alert_type,
            "message": a.message,
            "severity": a.severity,
            "trade_id": a.trade_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"status": "acknowledged"}


# ── Watchlist ─────────────────────────────────────────────────────────────────

class WatchlistAdd(BaseModel):
    ticker: str
    notes: Optional[str] = None


@router.get("/api/watchlist")
async def api_watchlist(db: Session = Depends(get_db)):
    rows = db.query(Watchlist).order_by(Watchlist.added_at.desc()).all()
    mcp = _get_mcp()
    result = []
    for r in rows:
        quote = mcp.get_quote(r.ticker)
        result.append({
            "id": r.id,
            "ticker": r.ticker,
            "notes": r.notes,
            "added_at": r.added_at.isoformat() if r.added_at else None,
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct"),
        })
    return result


@router.post("/api/watchlist")
async def add_watchlist(body: WatchlistAdd, db: Session = Depends(get_db)):
    ticker = body.ticker.upper().strip()
    existing = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already on watchlist")
    row = Watchlist(id=str(uuid.uuid4()), ticker=ticker, notes=body.notes, added_at=datetime.utcnow())
    db.add(row)
    db.commit()
    return {"status": "added", "ticker": ticker}


@router.delete("/api/watchlist/{ticker}")
async def remove_watchlist(ticker: str, db: Session = Depends(get_db)):
    row = db.query(Watchlist).filter(Watchlist.ticker == ticker.upper()).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "removed"}


# ── Blocklist ─────────────────────────────────────────────────────────────────

class BlocklistAdd(BaseModel):
    ticker: str
    reason: Optional[str] = None


@router.get("/api/blocklist")
async def api_blocklist(db: Session = Depends(get_db)):
    rows = db.query(Blocklist).order_by(Blocklist.added_at.desc()).all()
    return [{"id": r.id, "ticker": r.ticker, "reason": r.reason, "added_at": r.added_at.isoformat() if r.added_at else None} for r in rows]


@router.post("/api/blocklist")
async def add_blocklist(body: BlocklistAdd, db: Session = Depends(get_db)):
    ticker = body.ticker.upper().strip()
    existing = db.query(Blocklist).filter(Blocklist.ticker == ticker).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already on blocklist")
    row = Blocklist(id=str(uuid.uuid4()), ticker=ticker, reason=body.reason, added_at=datetime.utcnow())
    db.add(row)
    db.commit()
    return {"status": "added"}


@router.delete("/api/blocklist/{ticker}")
async def remove_blocklist(ticker: str, db: Session = Depends(get_db)):
    row = db.query(Blocklist).filter(Blocklist.ticker == ticker.upper()).first()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "removed"}


# ── Config knobs ──────────────────────────────────────────────────────────────

class KnobUpdate(BaseModel):
    key: str
    value: Any


@router.get("/api/knobs")
async def api_knobs(db: Session = Depends(get_db)):
    rows = db.query(ConfigKnob).all()
    return {r.key: json.loads(r.value) for r in rows}


@router.post("/api/knobs")
async def update_knob(body: KnobUpdate):
    set_knob(body.key, body.value)
    return {"status": "updated", "key": body.key}


# ── Mirror sources ────────────────────────────────────────────────────────────

class MirrorUpdate(BaseModel):
    enabled: Optional[bool] = None
    scale_factor: Optional[float] = None


@router.get("/api/mirrors")
async def api_mirrors(db: Session = Depends(get_db)):
    rows = db.query(MirrorSource).order_by(MirrorSource.name).all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "slug": m.slug,
            "source_type": m.source_type,
            "enabled": m.enabled,
            "scale_factor": m.scale_factor,
            "last_checked_at": m.last_checked_at.isoformat() if m.last_checked_at else None,
        }
        for m in rows
    ]


@router.patch("/api/mirrors/{slug}")
async def update_mirror(slug: str, body: MirrorUpdate, db: Session = Depends(get_db)):
    mirror = db.query(MirrorSource).filter(MirrorSource.slug == slug).first()
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")
    if body.enabled is not None:
        mirror.enabled = body.enabled
    if body.scale_factor is not None:
        mirror.scale_factor = body.scale_factor
    db.commit()
    return {"status": "updated"}


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/api/reports/last")
async def api_last_report(db: Session = Depends(get_db)):
    report = db.query(Report).order_by(Report.created_at.desc()).first()
    if not report:
        return {}
    return {
        "id": report.id,
        "title": report.title,
        "summary": report.summary,
        "pnl_usd": report.pnl_usd,
        "pnl_pct": report.pnl_pct,
        "report_type": report.report_type,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }
