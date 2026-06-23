import logging
import uuid
from datetime import datetime

import httpx

from agent.guardrails import (
    GuardrailViolation,
    _check_blocklist,
    _check_daily_loss_halt,
    _check_daily_trade_limit,
    _check_position_size,
    get_knob,
)
from db.models import Alert, Blocklist, MirrorSource, Trade
from db.session import SessionLocal

logger = logging.getLogger(__name__)

CAPITOL_TRADES_API = "https://capitoltrades.com/api/trades"

KNOWN_MEMBERS = [
    {
        "name": "Nancy Pelosi",
        "slug": "nancy_pelosi",
        "politician_id": "P000197",
    },
    {
        "name": "Dan Crenshaw",
        "slug": "dan_crenshaw",
        "politician_id": "C001120",
    },
    {
        "name": "Tommy Tuberville",
        "slug": "tommy_tuberville",
        "politician_id": "T000277",
    },
    {
        "name": "Austin Scott",
        "slug": "austin_scott",
        "politician_id": "S001189",
    },
]


def seed_congressional_mirrors() -> None:
    db = SessionLocal()
    try:
        for member in KNOWN_MEMBERS:
            existing = (
                db.query(MirrorSource)
                .filter(MirrorSource.slug == member["slug"])
                .first()
            )
            if not existing:
                db.add(MirrorSource(
                    id=str(uuid.uuid4()),
                    name=member["name"],
                    slug=member["slug"],
                    source_type="congressional",
                    enabled=False,
                    scale_factor=0.02,
                ))
        db.commit()
    finally:
        db.close()


def fetch_recent_disclosures(slug: str) -> list[dict]:
    member = next((m for m in KNOWN_MEMBERS if m["slug"] == slug), None)
    if not member:
        return []
    try:
        resp = httpx.get(
            CAPITOL_TRADES_API,
            params={"politician": member["politician_id"], "page": 1},
            timeout=10,
            headers={"User-Agent": "trader-bot/1.0"},
        )
        resp.raise_for_status()
        trades = resp.json().get("trades", [])
        return [
            {
                "ticker": t.get("issuer", {}).get("ticker", ""),
                "action": (
                    "buy"
                    if t.get("type", "").lower() in ("purchase", "buy")
                    else "sell"
                ),
                "reported_at": t.get("publishedAt", ""),
                "transaction_date": t.get("txDate", ""),
                "amount": t.get("value", "unknown"),
                "politician": member["name"],
            }
            for t in trades
            if t.get("issuer", {}).get("ticker")
        ]
    except Exception as e:
        logger.warning("Capitol Trades fetch failed for %s: %s", slug, e)
        return []


def check_and_queue_mirror_trades(mcp_client=None) -> None:
    auto_execute = get_knob("mirror_auto_execute", False)

    db = SessionLocal()
    try:
        sources = db.query(MirrorSource).filter(
            MirrorSource.source_type == "congressional",
            MirrorSource.enabled.is_(True),
        ).all()

        for source in sources:
            for d in fetch_recent_disclosures(source.slug):
                ticker = d.get("ticker", "").upper()
                if not ticker:
                    continue

                # Dedup: skip if an unacknowledged alert already exists for
                # this ticker + source combination.
                existing = db.query(Alert).filter(
                    Alert.ticker == ticker,
                    Alert.alert_type == "mirror_trade",
                    Alert.acknowledged.is_(False),
                    Alert.message.contains(source.name),
                ).first()
                if existing:
                    continue

                db.add(Alert(
                    id=str(uuid.uuid4()),
                    ticker=ticker,
                    alert_type="mirror_trade",
                    message=(
                        f"{source.name} disclosed a {d['action'].upper()} "
                        f"of {ticker} "
                        f"(transaction: {d['transaction_date']}, "
                        f"amount: {d['amount']}). "
                        f"Mirror enabled at "
                        f"{source.scale_factor * 100:.1f}% scale."
                    ),
                    severity="info",
                    created_at=datetime.utcnow(),
                ))

                if auto_execute and mcp_client:
                    _queue_mirror_trade(
                        db, source, ticker, d["action"], mcp_client
                    )

            source.last_checked_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _queue_mirror_trade(
    db, source, ticker: str, action: str, mcp_client
) -> None:
    """Size and queue a mirror trade for auto-execution.

    Runs blocklist, daily-loss-halt, daily-trade-limit, and position-size
    guardrails before queuing. Position sized as:
        portfolio_value * scale_factor / current_price

    Trade is created with status='approved' so the pending-trade executor
    picks it up within 30 seconds without dashboard interaction.
    """
    try:
        # Blocklist — never mirror a ticker on the Don't Buy list
        try:
            _check_blocklist(db, ticker)
        except GuardrailViolation as gv:
            logger.info("Mirror skipped (blocklist): %s — %s", ticker, gv)
            return

        portfolio = mcp_client.get_portfolio()
        total_value = portfolio.get("total_value", 0.0)
        if total_value <= 0:
            return

        # Daily loss halt — don't add exposure if we're already down badly
        try:
            _check_daily_loss_halt(portfolio)
        except GuardrailViolation as gv:
            logger.info("Mirror skipped (loss halt): %s — %s", ticker, gv)
            return

        # Daily trade limit — mirrors count toward the daily cap
        try:
            _check_daily_trade_limit(db)
        except GuardrailViolation as gv:
            logger.info("Mirror skipped (trade limit): %s — %s", ticker, gv)
            return

        quote = mcp_client.get_quote(ticker)
        price = quote.get("price")
        if not price or price <= 0:
            logger.warning(
                "Mirror auto-execute: no price for %s, skipping", ticker
            )
            return

        total_usd = round(total_value * source.scale_factor, 2)
        quantity = round(total_usd / price, 4)
        if quantity < 0.0001:
            logger.info(
                "Mirror auto-execute: quantity too small for %s (%.6f)",
                ticker, quantity,
            )
            return

        # Position size cap — scale_factor must not breach max_position_pct
        try:
            _check_position_size(ticker, total_usd, portfolio)
        except GuardrailViolation as gv:
            logger.info(
                "Mirror skipped (position cap): %s — %s", ticker, gv
            )
            return

        db.add(Trade(
            id=str(uuid.uuid4()),
            ticker=ticker,
            action=action,
            asset_class="stock",
            quantity=quantity,
            price_usd=price,
            total_usd=total_usd,
            status="approved",
            rationale=(
                f"Auto-mirror: {source.name} disclosed "
                f"{action.upper()} {ticker} — "
                f"{source.scale_factor * 100:.1f}% portfolio scale "
                f"(${total_usd:,.0f})"
            ),
            mirror_source=source.name,
            created_at=datetime.utcnow(),
        ))
        logger.info(
            "Mirror trade queued: %s %s x%.4f @ $%.2f (source: %s)",
            action, ticker, quantity, price, source.name,
        )
    except Exception as e:
        logger.warning("Failed to queue mirror trade for %s: %s", ticker, e)
