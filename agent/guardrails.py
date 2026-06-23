import json
import logging
import uuid
from datetime import datetime, date

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


class ApprovalPending(Exception):
    """Raised when a trade is queued for human approval (non-blocking)."""
    pass


def get_knob(key: str, default=None):
    db = SessionLocal()
    try:
        row = db.query(ConfigKnob).filter(ConfigKnob.key == key).first()
        if row is None:
            return default
        return json.loads(row.value)
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
    trade_type: str = "auto",
) -> None:
    """Run all guardrail checks. Raises GuardrailViolation on breach or
    ApprovalPending when the trade needs human sign-off before execution.

    trade_type values: new_position | scale_in | rebalance | stop_loss |
                       profit_take | full_exit | auto (default)
    """
    db = SessionLocal()
    try:
        _check_asset_class(asset_class)
        _check_blocklist(db, ticker)
        _check_daily_trade_limit(db)
        _check_daily_loss_halt(portfolio)
        _check_position_size(ticker, total_usd, portfolio)
        _check_approval_gate(
            db, ticker, action, total_usd, trade_id,
            portfolio, notifier, trade_type,
        )
    finally:
        db.close()


def _check_asset_class(asset_class: str) -> None:
    knob = ASSET_CLASS_KNOB.get(asset_class)
    if knob is None:
        raise GuardrailViolation(f"Unknown asset class: {asset_class}")
    if not get_knob(knob, True):
        raise GuardrailViolation(f"Asset class '{asset_class}' is disabled")


def _check_blocklist(db, ticker: str) -> None:
    entry = (
        db.query(Blocklist)
        .filter(Blocklist.ticker == ticker.upper())
        .first()
    )
    if entry:
        reason = entry.reason or "on blocklist"
        raise GuardrailViolation(f"{ticker} is blocked: {reason}")


def _check_daily_trade_limit(db) -> None:
    max_trades = get_knob("max_trades_per_day", 5)
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = (
        db.query(Trade)
        .filter(
            Trade.created_at >= today_start,
            Trade.status == "executed",
        )
        .count()
    )
    if count >= max_trades:
        raise GuardrailViolation(
            f"Daily trade limit of {max_trades} already reached"
        )


def _check_daily_loss_halt(portfolio: dict) -> None:
    halt_pct = get_knob("daily_loss_halt_pct", 3.0)
    today_pnl_pct = portfolio.get("today_pnl_pct", 0.0)
    if today_pnl_pct <= -abs(halt_pct):
        raise GuardrailViolation(
            f"Portfolio is down {abs(today_pnl_pct):.1f}% today — "
            f"trading halted (limit: {halt_pct}%)"
        )


def _check_position_size(
    ticker: str, total_usd: float, portfolio: dict
) -> None:
    max_pct = get_knob("max_position_pct", 20)
    total_value = portfolio.get("total_value", 0.0)
    if total_value <= 0:
        return
    existing = next(
        (
            h for h in portfolio.get("holdings", [])
            if h.get("ticker") == ticker
        ),
        None,
    )
    existing_value = existing.get("market_value", 0.0) if existing else 0.0
    new_pct = ((existing_value + total_usd) / total_value) * 100
    if new_pct > max_pct:
        raise GuardrailViolation(
            f"Order would put {ticker} at {new_pct:.1f}% of portfolio "
            f"(max: {max_pct}%)"
        )


def _check_approval_gate(
    db, ticker, action, total_usd, trade_id,
    portfolio, notifier, trade_type: str = "auto",
) -> None:
    needs_approval = False
    reasons = []

    threshold = get_knob("approval_threshold_usd", 500)
    if total_usd > threshold:
        needs_approval = True
        reasons.append(
            f"trade value ${total_usd:.2f} exceeds threshold ${threshold}"
        )

    existing = next(
        (h for h in portfolio.get("holdings", []) if h.get("ticker") == ticker),
        None,
    )

    if action == "buy" and get_knob("gate_new_positions", True):
        if not existing:
            needs_approval = True
            reasons.append("opening new position")

    if action == "sell":
        if get_knob("gate_full_exits", True):
            if existing and total_usd >= existing.get("market_value", 0) * 0.95:
                needs_approval = True
                reasons.append("full position exit")

        # gate_rebalance: partial sells that are not full exits
        if get_knob("gate_rebalance", False):
            is_full_exit = (
                existing
                and total_usd >= existing.get("market_value", 0) * 0.95
            )
            is_rebalance = trade_type == "rebalance" or (
                existing and not is_full_exit
            )
            if is_rebalance:
                needs_approval = True
                reasons.append("rebalance / partial trim")

        # gate_stop_loss: sell when position has unrealised loss
        if get_knob("gate_stop_loss", False):
            is_stop = trade_type == "stop_loss" or (
                existing
                and existing.get("unrealized_pnl", 0) < 0
            )
            if is_stop:
                needs_approval = True
                reasons.append("stop-loss sell")

    if not needs_approval:
        return

    trade = db.query(Trade).filter(Trade.id == trade_id).first()
    if trade:
        trade.status = "pending_approval"
        db.commit()

    # Include quantity so the dashboard can display "3.5 shares @ $143.25"
    qty_info = ""
    if trade:
        qty = f"{trade.quantity:.4f}".rstrip("0").rstrip(".")
        qty_info = f" · {qty} shares @ ${trade.price_usd:.2f}"

    reason_str = ", ".join(reasons)
    alert = Alert(
        id=str(uuid.uuid4()),
        ticker=ticker,
        alert_type="approval_request",
        message=(
            f"Trade requires your approval ({reason_str}): "
            f"{action.upper()} {ticker}{qty_info} (~${total_usd:.2f})"
        ),
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
                f"[Trader] Approval needed: {action.upper()} {ticker} "
                f"~${total_usd:.2f}. Reason: {reason_str}. "
                "Approve at your dashboard."
            )
        except Exception as e:
            logger.warning("Failed to send approval SMS: %s", e)

    raise ApprovalPending(
        f"Trade {trade_id} queued for approval: {reason_str}"
    )
