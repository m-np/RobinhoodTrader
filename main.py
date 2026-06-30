import base64
import json
import logging
import re
import secrets
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette_csrf import CSRFMiddleware

from api.limiter import limiter
from api.routes import router
from api.transfer import transfer_router
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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
    "report_frequency": "off",
    "report_weekly_day": "Friday",
    "report_delivery": "email",
    "report_depth": "brief",
    "report_include_rationale": True,
    "report_include_pnl": True,
    "wave_threshold_pct": 3.0,
    "wave_critical_pct": 7.0,
    "mirror_auto_execute": False,
    "notify_email": "",
    "notify_phone": "",
    "discover_enabled": True,
}

MIRROR_SEEDS = [
    {"name": "Nancy Pelosi",        "slug": "nancy_pelosi",      "source_type": "congressional"},
    {"name": "Dan Crenshaw",        "slug": "dan_crenshaw",      "source_type": "congressional"},
    {"name": "Tommy Tuberville",    "slug": "tommy_tuberville",  "source_type": "congressional"},
    {"name": "Austin Scott",        "slug": "austin_scott",      "source_type": "congressional"},
    {"name": "Berkshire Hathaway",  "slug": "berkshire_hathaway","source_type": "institutional"},
    {"name": "Soros Fund Management","slug": "soros_fund",       "source_type": "institutional"},
    {"name": "Renaissance Technologies","slug": "renaissance_tech","source_type": "institutional"},
]


def check_encryption_key() -> None:
    if settings.ENCRYPTION_KEY:
        return
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    print("\n" + "=" * 60)
    print("ERROR: ENCRYPTION_KEY is not set in your .env file.")
    print("Token storage requires an encryption key.")
    print("\nAdd this line to your .env and restart:")
    print(f"\n  ENCRYPTION_KEY={key}\n")
    print("=" * 60 + "\n")
    sys.exit(1)


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
        # Insert defaults only for missing keys — never overwrite user changes
        added = 0
        for key, value in DEFAULT_KNOBS.items():
            exists = db.query(ConfigKnob).filter(ConfigKnob.key == key).first()
            if not exists:
                db.add(ConfigKnob(
                    id=str(uuid.uuid4()),
                    key=key,
                    value=json.dumps(value),
                    updated_at=datetime.utcnow(),
                ))
                added += 1
        if added:
            logger.info("Seeded %d missing config knob(s)", added)
            db.commit()

        for seed in MIRROR_SEEDS:
            exists = (
                db.query(MirrorSource)
                .filter(MirrorSource.slug == seed["slug"])
                .first()
            )
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
    check_encryption_key()
    run_migrations()
    seed_defaults()

    from agent.scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    yield

    stop_scheduler()


app = FastAPI(title="Agentic Trader", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CSRFMiddleware,
    secret=settings.DASHBOARD_SECRET or "fallback-csrf-key",
    exempt_urls=[
        # All API routes: session cookie is samesite=strict + httponly,
        # so cross-site forgery is already blocked at the cookie layer.
        re.compile(r"^/api/"),
        re.compile(r"^/auth/robinhood/callback"),
    ],
)


_SESSION_COOKIE = "trader_session"


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/static"):
        return await call_next(request)
    if not settings.DASHBOARD_SECRET:
        return Response(
            content=(
                "DASHBOARD_SECRET not configured. "
                "Set it in .env and restart."
            ),
            status_code=503,
        )
    # Accept valid session cookie set after first successful Basic Auth
    cookie_val = request.cookies.get(_SESSION_COOKIE, "")
    if cookie_val and secrets.compare_digest(cookie_val, settings.DASHBOARD_SECRET):
        return await call_next(request)

    # Fall back to Basic Auth header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        try:
            _, password = (
                base64.b64decode(auth[6:]).decode().split(":", 1)
            )
            if secrets.compare_digest(password, settings.DASHBOARD_SECRET):
                response = await call_next(request)
                response.set_cookie(
                    _SESSION_COOKIE,
                    settings.DASHBOARD_SECRET,
                    httponly=True,
                    samesite="strict",
                    max_age=86400,  # 24 hours
                )
                return response
        except Exception:
            pass
    return Response(
        content="Unauthorized",
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Agentic Trader"'},
    )


app.mount("/static", StaticFiles(directory="ui/static"), name="static")
app.include_router(router)
app.include_router(transfer_router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=(settings.DEPLOYMENT_MODE == "local"),
    )
