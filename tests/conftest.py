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
            yield c
