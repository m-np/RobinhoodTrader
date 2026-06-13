import os
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Use same DB as dev — fixtures restore all data they touch
os.environ.setdefault("DATABASE_URL", "postgresql:///robinhoodtrader")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DEPLOYMENT_MODE", "local")
# Keep the real ENCRYPTION_KEY so token decryption works;
# fall back to a generated key only in clean CI environments.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(scope="session")
def client():
    with patch("agent.scheduler.start_scheduler"), \
         patch("agent.scheduler.stop_scheduler"):
        from main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture(scope="session", autouse=True)
def _isolate_live_db():
    """
    Snapshot trades, alerts, and robinhood_tokens before the test session
    and restore them exactly after all tests finish.

    This means pytest never permanently modifies live data — running tests
    will not log you out of Robinhood, will not add fake trades to your
    history, and will not leave stale alerts on the dashboard.
    """
    from db.models import Alert, ConfigKnob, RobinhoodToken, Trade
    from db.session import SessionLocal

    def _snapshot(db, model):
        rows = db.query(model).all()
        return [
            {col.name: getattr(row, col.name) for col in model.__table__.columns}
            for row in rows
        ]

    def _restore(db, model, snapshot):
        db.query(model).delete()
        for data in snapshot:
            db.add(model(**data))
        db.commit()

    db = SessionLocal()
    try:
        tokens_snap = _snapshot(db, RobinhoodToken)
        trades_snap = _snapshot(db, Trade)
        alerts_snap = _snapshot(db, Alert)
        knobs_snap = _snapshot(db, ConfigKnob)
    finally:
        db.close()

    yield  # ← all tests run here

    db = SessionLocal()
    try:
        _restore(db, RobinhoodToken, tokens_snap)
        _restore(db, Trade, trades_snap)
        _restore(db, Alert, alerts_snap)
        _restore(db, ConfigKnob, knobs_snap)
    finally:
        db.close()
