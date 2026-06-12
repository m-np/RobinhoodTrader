import logging
import uuid
from datetime import datetime

from db.models import Alert, Watchlist
from db.session import SessionLocal

logger = logging.getLogger(__name__)

WAVE_THRESHOLD_PCT = 3.0


def check_market_waves(mcp_client) -> None:
    db = SessionLocal()
    try:
        tickers = [r.ticker for r in db.query(Watchlist).all()]
        portfolio = mcp_client.get_portfolio()
        held = {h.get("ticker"): h for h in portfolio.get("holdings", [])}
        all_tickers = list(set(tickers) | set(held.keys()))

        for ticker in all_tickers:
            quote = mcp_client.get_quote(ticker)
            change_pct = quote.get("change_pct")
            if change_pct is None:
                continue
            if abs(change_pct) < WAVE_THRESHOLD_PCT:
                continue

            existing = db.query(Alert).filter(
                Alert.ticker == ticker,
                Alert.alert_type == "market_wave",
                Alert.acknowledged == False,
            ).first()
            if existing:
                continue

            direction = "up" if change_pct > 0 else "down"
            severity = "critical" if abs(change_pct) >= 7 else "warning"
            holding_note = ""
            if ticker in held:
                h = held[ticker]
                holding_note = f" Your position is {'+' if h.get('pnl', 0) >= 0 else ''}{h.get('pnl_pct', 0):.1f}%."

            alert = Alert(
                id=str(uuid.uuid4()),
                ticker=ticker,
                alert_type="market_wave",
                message=(
                    f"{ticker} is {direction} {abs(change_pct):.1f}% today.{holding_note}"
                ),
                severity=severity,
                created_at=datetime.utcnow(),
            )
            db.add(alert)
            logger.info("Market wave alert: %s %+.1f%%", ticker, change_pct)

        db.commit()
    except Exception as e:
        logger.error("Market wave check failed: %s", e)
        db.rollback()
    finally:
        db.close()
