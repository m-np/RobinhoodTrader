import logging
import uuid
from datetime import datetime, timedelta

import httpx

from db.models import Alert, MirrorSource, Trade
from db.session import SessionLocal

logger = logging.getLogger(__name__)

CAPITOL_TRADES_API = "https://capitoltrades.com/api/trades"

KNOWN_MEMBERS = [
    {"name": "Nancy Pelosi", "slug": "nancy_pelosi", "politician_id": "P000197"},
    {"name": "Dan Crenshaw", "slug": "dan_crenshaw", "politician_id": "C001120"},
    {"name": "Tommy Tuberville", "slug": "tommy_tuberville", "politician_id": "T000277"},
    {"name": "Austin Scott", "slug": "austin_scott", "politician_id": "S001189"},
]


def seed_congressional_mirrors() -> None:
    db = SessionLocal()
    try:
        for member in KNOWN_MEMBERS:
            existing = db.query(MirrorSource).filter(MirrorSource.slug == member["slug"]).first()
            if not existing:
                source = MirrorSource(
                    id=str(uuid.uuid4()),
                    name=member["name"],
                    slug=member["slug"],
                    source_type="congressional",
                    enabled=False,
                    scale_factor=0.02,
                )
                db.add(source)
        db.commit()
    finally:
        db.close()


def fetch_recent_disclosures(slug: str, days: int = 45) -> list[dict]:
    member = next((m for m in KNOWN_MEMBERS if m["slug"] == slug), None)
    if not member:
        return []
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        resp = httpx.get(
            CAPITOL_TRADES_API,
            params={"politician": member["politician_id"], "page": 1},
            timeout=10,
            headers={"User-Agent": "trader-bot/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        trades = data.get("trades", [])
        return [
            {
                "ticker": t.get("issuer", {}).get("ticker", ""),
                "action": "buy" if t.get("type", "").lower() in ("purchase", "buy") else "sell",
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
    db = SessionLocal()
    try:
        sources = db.query(MirrorSource).filter(
            MirrorSource.source_type == "congressional",
            MirrorSource.enabled == True,
        ).all()

        for source in sources:
            disclosures = fetch_recent_disclosures(source.slug)
            for d in disclosures:
                ticker = d.get("ticker", "").upper()
                if not ticker:
                    continue
                existing = db.query(Alert).filter(
                    Alert.ticker == ticker,
                    Alert.alert_type == "mirror_trade",
                    Alert.message.contains(source.name),
                    Alert.acknowledged == False,
                ).first()
                if existing:
                    continue
                alert = Alert(
                    id=str(uuid.uuid4()),
                    ticker=ticker,
                    alert_type="mirror_trade",
                    message=(
                        f"{source.name} disclosed a {d['action'].upper()} of {ticker} "
                        f"(transaction: {d['transaction_date']}, amount: {d['amount']}). "
                        f"Mirror is enabled at {source.scale_factor * 100:.1f}% scale."
                    ),
                    severity="info",
                    created_at=datetime.utcnow(),
                )
                db.add(alert)
            source.last_checked_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
