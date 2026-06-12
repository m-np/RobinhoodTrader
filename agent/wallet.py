import logging
import uuid
from datetime import datetime

from config import settings
from db.session import SessionLocal
from db.models import Alert

logger = logging.getLogger(__name__)


def check_wallet(mcp_client) -> dict:
    """
    Calls Robinhood MCP to get agentic account balance.
    Returns {"balance": float, "funded": bool}.
    Creates a wallet_low alert if balance is below the configured minimum.
    """
    balance = mcp_client.get_wallet_balance()
    funded = balance >= settings.MIN_WALLET_BALANCE_USD

    if not funded:
        logger.warning("Wallet balance $%.2f is below minimum $%.2f", balance, settings.MIN_WALLET_BALANCE_USD)
        _create_wallet_low_alert(balance)

    return {"balance": balance, "funded": funded}


def _create_wallet_low_alert(balance: float) -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(Alert)
            .filter(
                Alert.alert_type == "wallet_low",
                Alert.acknowledged == False,
            )
            .first()
        )
        if existing:
            return
        alert = Alert(
            id=str(uuid.uuid4()),
            alert_type="wallet_low",
            message=(
                f"Agentic wallet balance is ${balance:.2f}, below the minimum "
                f"${settings.MIN_WALLET_BALANCE_USD:.2f}. Agent trading is paused. "
                "Fund your Robinhood agentic account to resume."
            ),
            severity="warning",
            acknowledged=False,
            created_at=datetime.utcnow(),
        )
        db.add(alert)
        db.commit()
    except Exception as e:
        logger.error("Failed to create wallet_low alert: %s", e)
        db.rollback()
    finally:
        db.close()
