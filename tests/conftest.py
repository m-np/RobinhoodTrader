import base64
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
# Fixed test secret so Basic Auth middleware allows TestClient requests.
_TEST_SECRET = "test-dashboard-secret"
os.environ["DASHBOARD_SECRET"] = _TEST_SECRET


@pytest.fixture(scope="session")
def client():
    with patch("agent.scheduler.start_scheduler"), \
         patch("agent.scheduler.stop_scheduler"):
        from main import app
        _auth = base64.b64encode(f":{_TEST_SECRET}".encode()).decode()
        with TestClient(app, headers={"Authorization": f"Basic {_auth}"}) as c:
            yield c


@pytest.fixture(scope="session", autouse=True)
def _isolate_live_db(client):
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
            {c.name: getattr(row, c.name) for c in model.__table__.columns}
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
