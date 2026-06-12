import json
import logging
import threading
import uuid
from datetime import datetime, date

from config import settings
from db.session import SessionLocal
from db.models import Alert, Blocklist, ConfigKnob, Trade

logger = logging.getLogger(__name__)

ASSET_CLASS_KNOB = {
    "stock": "asset_stocks",
    "crypto": "asset_crypto",
    "options": "asset_options",
    "futures": "asset_futures",
    "event_contract": "asset_events",
}


class GuardrailViolation(Exception):
    pass


def get_knob(key: str, default=None):
    db = SessionLocal()
    try:
        row = db.query(ConfigKnob).filter(ConfigKnob.key == key).first()
        if row is None:
            return default
        val = json.loads(row.value)
        return val
    finally:
        db.close()


def set_knob(key: str, value) -> None:
    db = SessionLocal()
    try:
        row = db.query(ConfigKnob).filter(ConfigKnob.key == key).first()
        if row:
            row.value = json.dumps(value)
            row.updated_at = datetime.utcnow()
        else:
            row = ConfigKnob(
                id=str(uuid.uuid4()),
                key=key,
                value=json.dumps(value),
                updated_at=datetime.utcnow(),
            )
            db.add(row)
        db.commit()
    finally:
        db.close()


def check_all(
    ticker: str,
    action: str,
    asset_class: str,
    total_usd: float,
    portfolio: dict,
    trade_id: str,
    notifier=None,
) -> None:
    """
    Runs all guardrail checks. Raises GuardrailViolation on any breach.
    For approval-gated trades, sets status=pending_approval and blocks until
    approved/rejected or the timeout expires.
    """
    db = SessionLocal()
    try:
        _check_asset_class(asset_class)
        _check_blocklist(db, ticker)
        _check_daily_trade_limit(db)
        _check_daily_loss_halt(portfolio)
        _check_position_size(ticker, total_usd, portfolio)
        _check_approval_gate(db, ticker, action, total_usd, trade_id, portfolio, notifier)
    finally:
        db.close()


def _check_asset_class(asset_class: str) -> None:
    knob = ASSET_CLASS_KNOB.get(asset_class)
    if knob is None:
        raise GuardrailViolation(f"Unknown asset class: {asset_class}")
    if not get_knob(knob, True):
        raise GuardrailViolation(f"Asset class '{asset_class}' is disabled")


def _check_blocklist(db, ticker: str) -> None:
    entry = db.query(Blocklist).filter(Blocklist.ticker == ticker.upper()).first()
    if entry:
        reason = entry.reason or "on blocklist"
        raise GuardrailViolation(f"{ticker} is blocked: {reason}")


def _check_daily_trade_limit(db) -> None:
    max_trades = get_knob("max_trades_per_day", 5)
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = (
        db.query(Trade)
        .filter(Trade.created_at >= today_start, Trade.status == "executed")
        .count()
    )
    if count >= max_trades:
        raise GuardrailViolation(f"Daily trade limit of {max_trades} already reached")


def _check_daily_loss_halt(portfolio: dict) -> None:
    halt_pct = get_knob("daily_loss_halt_pct", 3.0)
    today_pnl_pct = portfolio.get("today_pnl_pct", 0.0)
    if today_pnl_pct <= -abs(halt_pct):
        raise GuardrailViolation(
            f"Portfolio is down {abs(today_pnl_pct):.1f}% today — trading halted (limit: {halt_pct}%)"
        )


def _check_position_size(ticker: str, total_usd: float, portfolio: dict) -> None:
    max_pct = get_knob("max_position_pct", 20)
    total_value = portfolio.get("total_value", 0.0)
    if total_value <= 0:
        return
    existing = next(
        (h for h in portfolio.get("holdings", []) if h.get("ticker") == ticker),
        None,
    )
    existing_value = existing.get("market_value", 0.0) if existing else 0.0
    new_total = existing_value + total_usd
    new_pct = (new_total / total_value) * 100
    if new_pct > max_pct:
        raise GuardrailViolation(
            f"Order would put {ticker} at {new_pct:.1f}% of portfolio (max: {max_pct}%)"
        )


def _check_approval_gate(db, ticker, action, total_usd, trade_id, portfolio, notifier) -> None:
    needs_approval = False
    reasons = []

    threshold = get_knob("approval_threshold_usd", 500)
    if total_usd > threshold:
        needs_approval = True
        reasons.append(f"trade value ${total_usd:.2f} exceeds threshold ${threshold}")

    if action == "buy" and get_knob("gate_new_positions", True):
        existing = next(
            (h for h in portfolio.get("holdings", []) if h.get("ticker") == ticker),
            None,
        )
        if not existing:
            needs_approval = True
            reasons.append("opening new position")

    if action == "sell" and get_knob("gate_full_exits", True):
        existing = next(
            (h for h in portfolio.get("holdings", []) if h.get("ticker") == ticker),
            None,
        )
        if existing and total_usd >= existing.get("market_value", 0) * 0.95:
            needs_approval = True
            reasons.append("full position exit")

    if not needs_approval:
        return

    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade:
        trade.status = "pending_approval"
        db.commit()

    alert = Alert(
        id=str(uuid.uuid4()),
        ticker=ticker,
        alert_type="approval_request",
        message=f"Trade requires your approval ({', '.join(reasons)}): {action.upper()} {ticker} ~${total_usd:.2f}",
        severity="warning",
        trade_id=trade_id,
        acknowledged=False,
        created_at=datetime.utcnow(),
    )
    db.add(alert)
    db.commit()

    if notifier:
        try:
            notifier.send_sms(
                f"[Trader] Approval needed: {action.upper()} {ticker} ~${total_usd:.2f}. Reason: {', '.join(reasons)}. Approve at your dashboard."
            )
        except Exception as e:
            logger.warning("Failed to send approval SMS: %s", e)

    timeout_minutes = get_knob("approval_timeout_minutes", 10)
    approved_event = threading.Event()
    rejected_event = threading.Event()

    def _wait_for_decision():
        deadline = timeout_minutes * 60
        interval = 5
        elapsed = 0
        while elapsed < deadline:
            db2 = SessionLocal()
            try:
                t = db2.query(Trade).filter(Trade.id == trade_id).first()
                if t and t.status == "executed":
                    approved_event.set()
                    return
                if t and t.status == "rejected":
                    rejected_event.set()
                    return
            finally:
                db2.close()
            import time
            time.sleep(interval)
            elapsed += interval
        rejected_event.set()

    watcher = threading.Thread(target=_wait_for_decision, daemon=True)
    watcher.start()
    watcher.join(timeout=timeout_minutes * 60 + 5)

    if rejected_event.is_set():
        db2 = SessionLocal()
        try:
            t = db2.query(Trade).filter(Trade.id == trade_id).first()
            if t and t.status == "pending_approval":
                t.status = "cancelled"
                db2.commit()
        finally:
            db2.close()
        raise GuardrailViolation(f"Trade not approved within {timeout_minutes} minutes — cancelled")
