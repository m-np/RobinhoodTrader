import os
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Use same DB as dev — tests restore any data they touch
os.environ.setdefault("DATABASE_URL", "postgresql:///robinhoodtrader")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DEPLOYMENT_MODE", "local")
# Keep the real ENCRYPTION_KEY if set so token decryption works in tests;
# fall back to a generated key only when running in a clean CI environment.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(scope="session")
def client():
    with patch("agent.scheduler.start_scheduler"), \
         patch("agent.scheduler.stop_scheduler"):
        from main import app
        with TestClient(app) as c:
            yield c


@pytest.fixture(scope="session", autouse=True)
def _preserve_robinhood_tokens():
    """
    Snapshot the robinhood_tokens table before the session starts and
    restore it exactly after all tests finish.

    This prevents pytest from logging you out of Robinhood — tests may
    add/delete rows freely during the session, but the real tokens are
    always put back at the end.
    """
    from db.models import RobinhoodToken
    from db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(RobinhoodToken).all()
        snapshot = [
            {col.name: getattr(row, col.name) for col in RobinhoodToken.__table__.columns}
            for row in rows
        ]
    finally:
        db.close()

    yield  # ← tests run here

    db = SessionLocal()
    try:
        db.query(RobinhoodToken).delete()
        for data in snapshot:
            db.add(RobinhoodToken(**data))
        db.commit()
    finally:
        db.close()
