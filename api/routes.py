import base64
import hashlib
import json
import secrets
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

from agent.guardrails import get_knob, set_knob
from agent.mcp_client import RobinhoodMCPClient
from api.deps import get_db
from config import settings
from db.models import (
    Alert, Blocklist, ConfigKnob, MirrorSource,
    Report, RobinhoodToken, Trade, Watchlist,
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


# ── Robinhood OAuth — PKCE + Dynamic Client Registration ─────────────────────
#
# Robinhood's MCP uses standard OAuth 2.0 with:
#   - Dynamic Client Registration (RFC 7591) — no pre-registered app needed
#   - PKCE (RFC 7636) — no client_secret required (public client)
#   - Authorization: https://robinhood.com/oauth
#   - Token exchange: https://api.robinhood.com/oauth2/token/
#   - Registration: https://agent.robinhood.com/oauth/trading/register

_REGISTER_URL = "https://agent.robinhood.com/oauth/trading/register"
_AUTHORIZE_URL = "https://robinhood.com/oauth"
_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"

# In-memory store for PKCE state — keyed by `state` param, short-lived
_pkce_pending: dict[str, dict] = {}


def _pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _get_or_register_client_id(db: Session) -> str:
    """
    Returns the client_id registered with Robinhood.
    Registers dynamically on first call and caches the result in config_knobs.
    """
    row = db.query(ConfigKnob).filter(ConfigKnob.key == "robinhood_client_id").first()
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
        timeout=15,
    )
    resp.raise_for_status()
    client_id = resp.json()["client_id"]
    set_knob("robinhood_client_id", client_id)
    return client_id


@router.get("/auth/robinhood")
async def auth_robinhood(db: Session = Depends(get_db)):
    """
    Starts the Robinhood OAuth flow.
    Dynamically registers this app if not already registered,
    then redirects to Robinhood's consent page with PKCE.
    """
    try:
        client_id = _get_or_register_client_id(db)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Client registration failed: {e}") from e

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    _pkce_pending[state] = {"verifier": verifier, "client_id": client_id}

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
async def auth_robinhood_callback(code: str, state: str, db: Session = Depends(get_db)):
    """
    Receives the OAuth callback code, exchanges it for tokens using PKCE,
    saves them encrypted, and redirects to the dashboard.
    """
    pkce = _pkce_pending.pop(state, None)
    if not pkce:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state. Try connecting again.")

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
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange failed ({e.response.status_code}): {e.response.text}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Token exchange error: {e}") from e

    expires_at = datetime.utcnow() + timedelta(seconds=int(data.get("expires_in", 86400)))
    save_tokens(db, data["access_token"], data.get("refresh_token", ""), expires_at)
    return RedirectResponse(url="/?connected=true")


class ManualTokenInput(BaseModel):
    access_token: str
    refresh_token: str = ""
    expires_at: Optional[str] = None  # ISO datetime; defaults to 24 h from now


@router.post("/api/robinhood/token")
async def set_manual_token(body: ManualTokenInput, db: Session = Depends(get_db)):
    """Fallback: paste tokens obtained externally."""
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="expires_at must be ISO format") from e
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
    return {
        "connected": True,
        "expires_at": tokens["expires_at"].isoformat() if tokens["expires_at"] else None,
        "account_id": None,
    }
