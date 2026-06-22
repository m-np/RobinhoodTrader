import logging
import uuid
from datetime import datetime

from agent.token_manager import McpAuthError
from config import settings
from db.models import Alert, get_tokens
from db.session import SessionLocal

logger = logging.getLogger(__name__)


def check_wallet(mcp_client) -> dict:
    """
    Returns {"balance": float, "funded": bool, "reason": str|None}.
    Skips MCP call and returns not-funded if Robinhood is not connected.
    Creates a wallet_low alert if balance is below the configured minimum.
    """
    db = SessionLocal()
    try:
        tokens = get_tokens(db)
    except Exception:
        tokens = None
    finally:
        db.close()

    if tokens is None:
        logger.info("Wallet check skipped: Robinhood not connected")
        _create_not_connected_alert()
        return {"balance": 0.0, "funded": False, "reason": "not_connected"}

    try:
        balance = mcp_client.get_wallet_balance()
    except McpAuthError as e:
        logger.warning("Wallet check auth error: %s", e)
        _create_not_connected_alert()
        return {"balance": 0.0, "funded": False, "reason": "auth_error"}

    funded = balance >= settings.MIN_WALLET_BALANCE_USD
    if funded:
        # Wallet is healthy — clear any stale wallet_low alerts
        _clear_wallet_low_alerts()
    else:
        logger.warning(
            "Wallet $%.2f below minimum $%.2f", balance, settings.MIN_WALLET_BALANCE_USD
        )
        _create_low_balance_alert(balance)

    return {"balance": balance, "funded": funded, "reason": None}


def _clear_wallet_low_alerts() -> None:
    db = SessionLocal()
    try:
        db.query(Alert).filter(
            Alert.alert_type == "wallet_low",
            Alert.acknowledged.is_(False),
        ).update({"acknowledged": True})
        db.commit()
    except Exception as e:
        logger.error("Failed to clear wallet_low alerts: %s", e)
        db.rollback()
    finally:
        db.close()


def _create_not_connected_alert() -> None:
    db = SessionLocal()
    try:
        existing = db.query(Alert).filter(
            Alert.alert_type == "wallet_low",
            Alert.message.contains("not connected"),
            Alert.acknowledged.is_(False),
        ).first()
        if existing:
            return
        db.add(Alert(
            id=str(uuid.uuid4()),
            alert_type="wallet_low",
            message=(
                "Robinhood MCP is not connected — agent cannot trade. "
                "Connect at /auth/robinhood."
            ),
            severity="warning",
            acknowledged=False,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception as e:
        logger.error("Failed to create not-connected alert: %s", e)
        db.rollback()
    finally:
        db.close()


def _create_low_balance_alert(balance: float) -> None:
    db = SessionLocal()
    try:
        existing = db.query(Alert).filter(
            Alert.alert_type == "wallet_low",
            Alert.acknowledged == False,
        ).first()
        if existing:
            return
        db.add(Alert(
            id=str(uuid.uuid4()),
            alert_type="wallet_low",
            message=(
                f"Agentic wallet balance is ${balance:.2f}, below the minimum "
                f"${settings.MIN_WALLET_BALANCE_USD:.2f}. "
                "Fund your Robinhood agentic account to resume trading."
            ),
            severity="warning",
            acknowledged=False,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception as e:
        logger.error("Failed to create wallet_low alert: %s", e)
        db.rollback()
    finally:
        db.close()
