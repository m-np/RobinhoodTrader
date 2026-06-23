import base64
import hashlib
import json
import secrets
import threading
import time as _time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.guardrails import (
    ApprovalPending, GuardrailViolation, check_all, get_knob, set_knob,
)
from agent.loop import _enrich_today_pnl
from agent.mcp_client import RobinhoodMCPClient
from api.deps import get_db
from config import settings
from db.models import (
    Alert, Blocklist, ConfigKnob, MirrorSource,
    Report, Trade, Watchlist,
    get_tokens, save_tokens,
)

router = APIRouter()
templates = Jinja2Templates(directory="ui/templates")
_mcp = None


def _get_mcp() -> RobinhoodMCPClient:
    global _mcp
    if _mcp is None:
        _mcp = RobinhoodMCPClient()
    return _mcp


# ── HTML pages ────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request, "dashboard.html", {"active": "dashboard"}
    )


@router.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page(request: Request):
    return templates.TemplateResponse(
        request, "watchlist.html", {"active": "watchlist"}
    )


@router.get("/mirrors", response_class=HTMLResponse)
async def mirrors_page(request: Request):
    return templates.TemplateResponse(
        request, "mirrors.html", {"active": "mirrors"}
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(
        request, "settings.html", {"active": "settings"}
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse(
        request, "reports.html", {"active": "reports"}
    )


@router.get("/discover", response_class=HTMLResponse)
async def discover_page(request: Request):
    return templates.TemplateResponse(
        request, "discover.html", {"active": "discover"}
    )


# ── Portfolio / wallet ────────────────────────────────────

@router.get("/api/portfolio")
async def api_portfolio(db: Session = Depends(get_db)):
    mcp = _get_mcp()
    portfolio = _enrich_today_pnl(mcp.get_portfolio())
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    trades_today = db.query(Trade).filter(
        Trade.created_at >= today_start,
        Trade.status == "executed",
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


@router.get("/api/portfolio/history")
async def api_portfolio_history(
    period: str = "7d", db: Session = Depends(get_db)
):
    """Time-series snapshots for chart. period: 1d | 7d | 30d | 90d"""
    from db.models import PortfolioSnapshot
    days = {"1d": 1, "7d": 7, "30d": 30, "90d": 90}.get(period, 7)
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.created_at >= cutoff)
        .order_by(PortfolioSnapshot.created_at)
        .all()
    )
    return [
        {
            "ts": r.created_at.isoformat() + "Z",
            "total_value": r.total_value,
            "equity_value": r.equity_value,
            "cash": r.cash,
        }
        for r in rows
    ]


@router.get("/api/search")
async def api_search(q: str = ""):
    """Search tickers/companies via Robinhood MCP."""
    if not q or len(q) < 1:
        return []
    mcp = _get_mcp()
    try:
        result = mcp._call(
            "search", {"query": q, "asset_type": "instrument", "limit": 8}
        )
        items = result.get(
            "data", {}
        ).get("results", result.get("results", []))
        return [
            {
                "symbol": i.get("symbol", i.get("ticker", "")),
                "name": i.get(
                    "name", i.get("simple_name", i.get("symbol", ""))
                ),
                "type": i.get("type", "equity"),
            }
            for i in items
            if i.get("symbol") or i.get("ticker")
        ]
    except Exception:
        return []


class QuickTradeInput(BaseModel):
    ticker: str
    action: str       # "buy" | "sell"
    amount_usd: float = 0.0
    quantity: float = 0.0
    note: str = ""


@router.post("/api/trades/quick")
async def quick_trade(
    body: QuickTradeInput, db: Session = Depends(get_db)
):
    """Execute a quick buy/sell from a signal card."""
    from agent.mcp_client import McpConnectionError
    mcp = _get_mcp()
    ticker = body.ticker.upper()

    quote = mcp.get_quote(ticker)
    price = quote.get("price") or 0.0
    qty = body.quantity or ((body.amount_usd / price) if price else 0)
    if qty <= 0:
        raise HTTPException(
            status_code=400,
            detail="quantity or amount_usd required",
        )

    total_usd = price * qty
    portfolio = mcp.get_portfolio()

    trade = Trade(
        id=str(uuid.uuid4()),
        ticker=ticker,
        action=body.action,
        asset_class="stock",
        quantity=qty,
        price_usd=price,
        total_usd=total_usd,
        status="pending_approval",
        rationale=body.note or f"Quick {body.action} from signal",
        created_at=datetime.utcnow(),
    )
    db.add(trade)
    db.commit()

    try:
        check_all(
            ticker=ticker,
            action=body.action,
            asset_class="stock",
            total_usd=total_usd,
            portfolio=portfolio,
            trade_id=trade.id,
            notifier=None,
        )
    except ApprovalPending:
        db.refresh(trade)
        return {
            "status": "pending_approval",
            "trade_id": trade.id,
            "qty": qty,
            "price": price,
        }
    except GuardrailViolation as e:
        trade.status = "rejected"
        db.commit()
        raise HTTPException(status_code=409, detail=str(e))

    try:
        mcp.place_order(ticker, body.action, qty, "stock")
        trade.status = "executed"
        trade.executed_at = datetime.utcnow()
        db.commit()
        return {
            "status": "executed",
            "trade_id": trade.id,
            "qty": qty,
            "price": price,
        }
    except McpConnectionError as e:
        trade.status = "rejected"
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))


# ── Trades ────────────────────────────────────────────────

@router.get("/api/trades")
async def api_trades(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Trade)
        .order_by(Trade.created_at.desc())
        .limit(limit)
        .all()
    )
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
            "created_at": (
                t.created_at.isoformat() if t.created_at else None
            ),
            "executed_at": (
                t.executed_at.isoformat() if t.executed_at else None
            ),
        }
        for t in rows
    ]


@router.post("/api/trades/{trade_id}/approve")
async def approve_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.status = "approved"
    db.query(Alert).filter(Alert.trade_id == trade_id).update(
        {"acknowledged": True}
    )
    db.commit()
    return {"status": "approved"}


@router.post("/api/trades/{trade_id}/reject")
async def reject_trade(trade_id: str, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    trade.status = "rejected"
    db.query(Alert).filter(Alert.trade_id == trade_id).update(
        {"acknowledged": True}
    )
    db.commit()
    return {"status": "rejected"}


# ── Alerts ────────────────────────────────────────────────

@router.get("/api/alerts")
async def api_alerts(db: Session = Depends(get_db)):
    rows = (
        db.query(Alert)
        .filter(Alert.acknowledged.is_(False))
        .order_by(Alert.created_at.desc())
        .all()
    )
    # Pre-fetch trade details so the frontend never needs to parse message text
    trade_ids = [a.trade_id for a in rows if a.trade_id]
    trades: dict = {}
    if trade_ids:
        for t in db.query(Trade).filter(Trade.id.in_(trade_ids)).all():
            trades[t.id] = t

    result = []
    for a in rows:
        item: dict = {
            "id": a.id,
            "ticker": a.ticker,
            "alert_type": a.alert_type,
            "message": a.message,
            "severity": a.severity,
            "trade_id": a.trade_id,
            "created_at": (
                a.created_at.isoformat() if a.created_at else None
            ),
        }
        t = trades.get(a.trade_id) if a.trade_id else None
        if t:
            item["action"] = t.action
            item["quantity"] = t.quantity
            item["price_usd"] = t.price_usd
            item["total_usd"] = t.total_usd
        result.append(item)
    return result


@router.post("/api/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = True
    db.commit()
    return {"status": "acknowledged"}


# ── Watchlist ─────────────────────────────────────────────

class WatchlistAdd(BaseModel):
    ticker: str
    notes: Optional[str] = None


@router.get("/api/watchlist")
async def api_watchlist(db: Session = Depends(get_db)):
    from agent.price_cache import (
        get as cache_get,
        is_empty as cache_empty,
        update as cache_update,
    )
    rows = db.query(Watchlist).order_by(Watchlist.added_at.desc()).all()
    if not rows:
        return []
    # Cold-start: fill cache if scheduler hasn't run yet
    if cache_empty():
        quotes = _get_mcp().get_quotes_batch([r.ticker for r in rows])
        cache_update(quotes)
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "notes": r.notes,
            "added_at": r.added_at.isoformat() if r.added_at else None,
            **cache_get(r.ticker),
        }
        for r in rows
    ]


@router.post("/api/watchlist")
async def add_watchlist(
    body: WatchlistAdd, db: Session = Depends(get_db)
):
    ticker = body.ticker.upper().strip()
    existing = (
        db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already on watchlist")
    db.add(Watchlist(
        id=str(uuid.uuid4()),
        ticker=ticker,
        notes=body.notes,
        added_at=datetime.utcnow(),
    ))
    db.commit()
    return {"status": "added", "ticker": ticker}


@router.get("/api/watchlist/prices/history")
async def api_watchlist_price_history(
    period: str = "1d", db: Session = Depends(get_db)
):
    """Price history for sparklines. period: 1d | 7d | 30d"""
    from db.models import WatchlistPriceSnapshot
    days = {"1d": 1, "7d": 7, "30d": 30}.get(period, 1)
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(WatchlistPriceSnapshot)
        .filter(WatchlistPriceSnapshot.recorded_at >= cutoff)
        .order_by(
            WatchlistPriceSnapshot.ticker,
            WatchlistPriceSnapshot.recorded_at,
        )
        .all()
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r.ticker, []).append({
            "ts": r.recorded_at.isoformat() + "Z",
            "price": r.price,
        })
    return result


@router.delete("/api/watchlist/{ticker}")
async def remove_watchlist(ticker: str, db: Session = Depends(get_db)):
    row = (
        db.query(Watchlist)
        .filter(Watchlist.ticker == ticker.upper())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "removed"}


# ── Blocklist ─────────────────────────────────────────────

class BlocklistAdd(BaseModel):
    ticker: str
    reason: Optional[str] = None


@router.get("/api/blocklist")
async def api_blocklist(db: Session = Depends(get_db)):
    rows = db.query(Blocklist).order_by(Blocklist.added_at.desc()).all()
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "reason": r.reason,
            "added_at": r.added_at.isoformat() if r.added_at else None,
        }
        for r in rows
    ]


@router.post("/api/blocklist")
async def add_blocklist(
    body: BlocklistAdd, db: Session = Depends(get_db)
):
    ticker = body.ticker.upper().strip()
    existing = (
        db.query(Blocklist).filter(Blocklist.ticker == ticker).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Already on blocklist")
    db.add(Blocklist(
        id=str(uuid.uuid4()),
        ticker=ticker,
        reason=body.reason,
        added_at=datetime.utcnow(),
    ))
    db.commit()
    return {"status": "added"}


@router.delete("/api/blocklist/{ticker}")
async def remove_blocklist(
    ticker: str, db: Session = Depends(get_db)
):
    row = (
        db.query(Blocklist)
        .filter(Blocklist.ticker == ticker.upper())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "removed"}


# ── Config knobs ──────────────────────────────────────────

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


# ── Mirror sources ────────────────────────────────────────

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
            "last_checked_at": (
                m.last_checked_at.isoformat()
                if m.last_checked_at else None
            ),
        }
        for m in rows
    ]


@router.patch("/api/mirrors/{slug}")
async def update_mirror(
    slug: str, body: MirrorUpdate, db: Session = Depends(get_db)
):
    mirror = (
        db.query(MirrorSource)
        .filter(MirrorSource.slug == slug)
        .first()
    )
    if not mirror:
        raise HTTPException(status_code=404, detail="Mirror not found")
    if body.enabled is not None:
        mirror.enabled = body.enabled
    if body.scale_factor is not None:
        mirror.scale_factor = body.scale_factor
    db.commit()
    return {"status": "updated"}


# ── Reports ───────────────────────────────────────────────

@router.get("/api/reports")
async def api_reports(db: Session = Depends(get_db)):
    rows = db.query(Report).order_by(Report.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "pnl_usd": r.pnl_usd,
            "pnl_pct": r.pnl_pct,
            "report_type": r.report_type,
            "created_at": (
                r.created_at.isoformat() if r.created_at else None
            ),
        }
        for r in rows
    ]


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
        "created_at": (
            report.created_at.isoformat() if report.created_at else None
        ),
    }


# ── Notifications ─────────────────────────────────────────

class NotifyConfigInput(BaseModel):
    notify_email: Optional[str] = None
    notify_phone: Optional[str] = None


class NotifyTestInput(BaseModel):
    type: str = "email"  # "email" | "sms" | "both"


@router.get("/api/notify/status")
async def notify_status():
    """SMTP/Twilio config status + current recipient addresses."""
    from notifications.notifier import (
        _get_notify_email, _get_notify_phone,
    )
    return {
        "smtp_configured": bool(
            settings.SMTP_USER and settings.SMTP_PASSWORD
        ),
        "twilio_configured": bool(
            settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN
        ),
        "notify_email": _get_notify_email(),
        "notify_phone": _get_notify_phone(),
    }


@router.post("/api/notify/config")
async def save_notify_config(body: NotifyConfigInput):
    """Save recipient email/phone to DB (overrides .env values)."""
    if body.notify_email is not None:
        set_knob("notify_email", body.notify_email)
    if body.notify_phone is not None:
        set_knob("notify_phone", body.notify_phone)
    return {"status": "saved"}


@router.post("/api/notify/test")
async def notify_test(body: NotifyTestInput):
    """Send a test notification to verify credentials and recipient."""
    from notifications.notifier import get_notifier
    notifier = get_notifier()
    results: dict[str, bool | None] = {"email": None, "sms": None}
    errors: list[str] = []

    if body.type in ("email", "both"):
        ok = notifier.send_test_email()
        results["email"] = ok
        if not ok:
            errors.append(
                "Email failed — check SMTP credentials and address"
            )

    if body.type in ("sms", "both"):
        ok = notifier.send_test_sms()
        results["sms"] = ok
        if not ok:
            errors.append(
                "SMS failed — check Twilio credentials and phone number"
            )

    return {"results": results, "errors": errors}


# ── Stock discovery ───────────────────────────────────────

@router.get("/api/discoveries")
async def api_discoveries(db: Session = Depends(get_db)):
    from db.models import StockDiscovery
    rows = (
        db.query(StockDiscovery)
        .filter(StockDiscovery.dismissed.is_(False))
        .order_by(StockDiscovery.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "ticker": r.ticker,
            "company_name": r.company_name,
            "rationale": r.rationale,
            "category": r.category,
            "confidence": r.confidence,
            "source_summary": r.source_summary,
            "added_to_watchlist": r.added_to_watchlist,
            "created_at": (
                r.created_at.isoformat() if r.created_at else None
            ),
        }
        for r in rows
    ]


@router.post("/api/discoveries/{discovery_id}/add")
async def discovery_add_to_watchlist(
    discovery_id: str, db: Session = Depends(get_db)
):
    from db.models import StockDiscovery
    disc = (
        db.query(StockDiscovery)
        .filter(StockDiscovery.id == discovery_id)
        .first()
    )
    if not disc:
        raise HTTPException(status_code=404, detail="Discovery not found")
    ticker = disc.ticker.upper()
    existing = (
        db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
    )
    if not existing:
        db.add(Watchlist(
            id=str(uuid.uuid4()),
            ticker=ticker,
            notes=f"Discovered: {disc.source_summary or ''}",
            added_at=datetime.utcnow(),
        ))
    disc.added_to_watchlist = True
    db.commit()
    return {"status": "added", "ticker": ticker}


@router.post("/api/discoveries/{discovery_id}/dismiss")
async def discovery_dismiss(
    discovery_id: str, db: Session = Depends(get_db)
):
    from db.models import StockDiscovery
    disc = (
        db.query(StockDiscovery)
        .filter(StockDiscovery.id == discovery_id)
        .first()
    )
    if not disc:
        raise HTTPException(status_code=404, detail="Discovery not found")
    disc.dismissed = True
    db.commit()
    return {"status": "dismissed"}


@router.post("/api/discoveries/refresh")
async def discovery_refresh():
    """Trigger a new discovery run in the background."""
    from discover.engine import check_and_run_discovery
    mcp = _get_mcp()
    threading.Thread(
        target=check_and_run_discovery, args=(mcp,), daemon=True
    ).start()
    return {"status": "started"}


# ── Robinhood OAuth — PKCE + Dynamic Client Registration ──
#
# Robinhood MCP uses OAuth 2.0 with:
#   - Dynamic Client Registration (RFC 7591) — no pre-registered app
#   - PKCE (RFC 7636) — no client_secret (public client)
#   - Authorization: https://robinhood.com/oauth
#   - Token exchange: https://api.robinhood.com/oauth2/token/
#   - Registration: https://agent.robinhood.com/oauth/trading/register

_REGISTER_URL = "https://agent.robinhood.com/oauth/trading/register"
_AUTHORIZE_URL = "https://robinhood.com/oauth"
_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

# In-memory PKCE store: {state: {verifier, client_id, expires_at}}
# Entries expire after 5 minutes.
_pkce_pending: dict[str, dict] = {}
_PKCE_TTL = 300  # seconds


def _purge_stale_pkce() -> None:
    now = _time.monotonic()
    stale = [k for k, v in _pkce_pending.items() if v["expires_at"] < now]
    for k in stale:
        _pkce_pending.pop(k, None)


def _pkce_pair() -> tuple[str, str]:
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(32))
        .rstrip(b"=")
        .decode()
    )
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = (
        base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    )
    return verifier, challenge


def _get_or_register_client_id(db: Session) -> str:
    row = (
        db.query(ConfigKnob)
        .filter(ConfigKnob.key == "robinhood_client_id")
        .first()
    )
    if row:
        return json.loads(row.value)

    resp = httpx.post(
        _REGISTER_URL,
        json={
            "redirect_uris": [settings.ROBINHOOD_REDIRECT_URI],
            "client_name": "RobinhoodTrader",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        timeout=settings.OAUTH_TIMEOUT,
    )
    resp.raise_for_status()
    client_id = resp.json()["client_id"]
    set_knob("robinhood_client_id", client_id)
    return client_id


@router.get("/auth/robinhood")
async def auth_robinhood(db: Session = Depends(get_db)):
    try:
        client_id = _get_or_register_client_id(db)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Client registration failed: {e}",
        ) from e

    _purge_stale_pkce()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    _pkce_pending[state] = {
        "verifier": verifier,
        "client_id": client_id,
        "expires_at": _time.monotonic() + _PKCE_TTL,
    }

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": settings.ROBINHOOD_REDIRECT_URI,
        "scope": "internal",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return RedirectResponse(url=f"{_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/auth/robinhood/callback")
async def auth_robinhood_callback(
    code: str, state: str, db: Session = Depends(get_db)
):
    """Exchange OAuth code for tokens (PKCE), save encrypted, redirect."""
    pkce = _pkce_pending.pop(state, None)
    if not pkce or pkce["expires_at"] < _time.monotonic():
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state. Try connecting again.",
        )

    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": pkce["client_id"],
                "redirect_uri": settings.ROBINHOOD_REDIRECT_URI,
                "code_verifier": pkce["verifier"],
            },
            timeout=settings.OAUTH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Token exchange failed "
                f"({e.response.status_code}): {e.response.text}"
            ),
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502, detail=f"Token exchange error: {e}"
        ) from e

    expires_at = datetime.utcnow() + timedelta(
        seconds=int(data.get("expires_in", 86400))
    )
    save_tokens(
        db,
        data["access_token"],
        data.get("refresh_token", ""),
        expires_at,
    )
    return RedirectResponse(url="/?connected=true")


class ManualTokenInput(BaseModel):
    access_token: str
    refresh_token: str = ""
    expires_at: Optional[str] = None  # ISO datetime; default 24 h from now


@router.post("/api/robinhood/token")
async def set_manual_token(
    body: ManualTokenInput, db: Session = Depends(get_db)
):
    """Fallback: paste tokens obtained externally."""
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail="expires_at must be ISO format",
            ) from e
    else:
        expires_at = datetime.utcnow() + timedelta(hours=24)

    save_tokens(db, body.access_token, body.refresh_token, expires_at)
    return {"status": "saved", "expires_at": expires_at.isoformat()}


@router.get("/api/robinhood/status")
async def robinhood_status(db: Session = Depends(get_db)):
    """Connection status for the dashboard banner."""
    tokens = get_tokens(db)
    if tokens is None:
        return {"connected": False, "expires_at": None, "account_id": None}
    acct = get_knob("robinhood_agentic_account")
    exp = tokens["expires_at"]
    return {
        "connected": True,
        "expires_at": exp.isoformat() if exp else None,
        "account_id": f"•••{str(acct)[-4:]}" if acct else None,
    }
