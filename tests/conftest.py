import os
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

# Use same DB as dev — tests clean up after themselves
os.environ.setdefault("DATABASE_URL", "postgresql:///robinhoodtrader")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("DEPLOYMENT_MODE", "local")
# Generate a fresh Fernet key for each test session so token encryption works
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture(scope="session")
def client():
    # Patch the scheduler so it doesn't spawn background jobs during tests
    with patch("agent.scheduler.start_scheduler"), \
         patch("agent.scheduler.stop_scheduler"):
        from main import app
        with TestClient(app) as c:
            _clear_stale_tokens()
            yield c


def _clear_stale_tokens():
    """
    Delete any tokens left from a previous test session.
    They were encrypted with a different key and would cause
    decryption failures in tests that hit the MCP client.
    """
    from db.models import RobinhoodToken
    from db.session import SessionLocal
    db = SessionLocal()
    try:
        db.query(RobinhoodToken).delete()
        db.commit()
    finally:
        db.close()
