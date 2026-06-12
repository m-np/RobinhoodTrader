import json
import logging
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_KNOBS = {
    "asset_stocks": True,
    "asset_crypto": False,
    "asset_options": False,
    "asset_futures": False,
    "asset_events": False,
    "approval_threshold_usd": 500,
    "approval_timeout_minutes": 10,
    "gate_new_positions": True,
    "gate_full_exits": True,
    "gate_rebalance": False,
    "gate_stop_loss": False,
    "max_position_pct": 20,
    "max_trades_per_day": 5,
    "daily_loss_halt_pct": 3,
    "report_frequency": "weekly",
    "report_weekly_day": "Friday",
    "report_delivery": "email",
    "report_depth": "brief",
    "report_include_rationale": True,
    "report_include_pnl": True,
}

MIRROR_SEEDS = [
    {"name": "Nancy Pelosi", "slug": "nancy_pelosi", "source_type": "congressional"},
    {"name": "Dan Crenshaw", "slug": "dan_crenshaw", "source_type": "congressional"},
    {"name": "Tommy Tuberville", "slug": "tommy_tuberville", "source_type": "congressional"},
    {"name": "Austin Scott", "slug": "austin_scott", "source_type": "congressional"},
    {"name": "Berkshire Hathaway", "slug": "berkshire_hathaway", "source_type": "institutional"},
    {"name": "Soros Fund Management", "slug": "soros_fund", "source_type": "institutional"},
    {"name": "Renaissance Technologies", "slug": "renaissance_tech", "source_type": "institutional"},
]


def run_migrations() -> None:
    logger.info("Running database migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Migration failed:\n%s", result.stderr)
        raise RuntimeError("Database migration failed")
    logger.info("Migrations complete")


def seed_defaults() -> None:
    from db.models import ConfigKnob, MirrorSource
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        count = db.query(ConfigKnob).count()
        if count == 0:
            logger.info("Seeding default config knobs")
            for key, value in DEFAULT_KNOBS.items():
                row = ConfigKnob(
                    id=str(uuid.uuid4()),
                    key=key,
                    value=json.dumps(value),
                    updated_at=datetime.utcnow(),
                )
                db.add(row)
            db.commit()

        for seed in MIRROR_SEEDS:
            exists = db.query(MirrorSource).filter(MirrorSource.slug == seed["slug"]).first()
            if not exists:
                source = MirrorSource(
                    id=str(uuid.uuid4()),
                    name=seed["name"],
                    slug=seed["slug"],
                    source_type=seed["source_type"],
                    enabled=False,
                    scale_factor=0.02,
                )
                db.add(source)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    seed_defaults()

    from agent.scheduler import start_scheduler, stop_scheduler
    scheduler = start_scheduler()

    yield

    stop_scheduler()


app = FastAPI(title="Agentic Trader", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="ui/static"), name="static")

from api.routes import router
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=(settings.DEPLOYMENT_MODE == "local"),
    )
