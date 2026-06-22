import logging
import uuid
from datetime import datetime

import httpx

from db.models import Alert, MirrorSource
from db.session import SessionLocal

logger = logging.getLogger(__name__)

EDGAR_API = "https://data.sec.gov/submissions"
EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"

KNOWN_INSTITUTIONS = [
    {"name": "Berkshire Hathaway", "slug": "berkshire_hathaway", "cik": "0001067983"},
    {"name": "Soros Fund Management", "slug": "soros_fund", "cik": "0001029160"},
    {"name": "Renaissance Technologies", "slug": "renaissance_tech", "cik": "0001037389"},
]


def seed_institutional_mirrors() -> None:
    db = SessionLocal()
    try:
        for inst in KNOWN_INSTITUTIONS:
            existing = db.query(MirrorSource).filter(MirrorSource.slug == inst["slug"]).first()
            if not existing:
                source = MirrorSource(
                    id=str(uuid.uuid4()),
                    name=inst["name"],
                    slug=inst["slug"],
                    source_type="institutional",
                    enabled=False,
                    scale_factor=0.02,
                )
                db.add(source)
        db.commit()
    finally:
        db.close()


def fetch_13f_holdings(cik: str) -> list[dict]:
    try:
        cik_padded = cik.lstrip("0").zfill(10)
        resp = httpx.get(
            f"{EDGAR_API}/CIK{cik_padded}.json",
            timeout=15,
            headers={"User-Agent": "trader-bot/1.0 contact@example.com"},
        )
        resp.raise_for_status()
        data = resp.json()
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        indices = [i for i, f in enumerate(forms) if f == "13F-HR"]
        if not indices:
            return []
        latest_idx = indices[0]
        accession = filings.get("accessionNumber", [])[latest_idx].replace("-", "")
        filed_date = filings.get("filingDate", [])[latest_idx]
        return [{"accession": accession, "filed_date": filed_date, "cik": cik}]
    except Exception as e:
        logger.warning("SEC EDGAR 13F fetch failed for CIK %s: %s", cik, e)
        return []


def check_and_queue_institutional_mirrors(mcp_client=None) -> None:
    db = SessionLocal()
    try:
        sources = db.query(MirrorSource).filter(
            MirrorSource.source_type == "institutional",
            MirrorSource.enabled.is_(True),
        ).all()

        inst_map = {i["slug"]: i for i in KNOWN_INSTITUTIONS}

        for source in sources:
            inst = inst_map.get(source.slug)
            if not inst:
                continue
            filings = fetch_13f_holdings(inst["cik"])
            for filing in filings:
                existing = db.query(Alert).filter(
                    Alert.alert_type == "mirror_trade",
                    Alert.message.contains(source.name),
                    Alert.message.contains(filing["accession"]),
                ).first()
                if existing:
                    continue
                alert = Alert(
                    id=str(uuid.uuid4()),
                    alert_type="mirror_trade",
                    message=(
                        f"{source.name} filed a 13F on {filing['filed_date']} "
                        f"(accession: {filing['accession']}). "
                        f"Mirror enabled at {source.scale_factor * 100:.1f}% scale."
                    ),
                    severity="info",
                    created_at=datetime.utcnow(),
                )
                db.add(alert)
            source.last_checked_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
