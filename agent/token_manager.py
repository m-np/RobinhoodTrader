import logging
from datetime import datetime, timedelta

import httpx

from config import settings
from db.models import get_tokens, save_tokens
from db.session import SessionLocal

logger = logging.getLogger(__name__)

ROBINHOOD_TOKEN_URL = "https://agent.robinhood.com/oauth/token"
EXPIRY_BUFFER = timedelta(minutes=5)


class McpAuthError(Exception):
    pass


class TokenManager:
    def is_connected(self) -> bool:
        """True if tokens exist in DB (does not validate expiry)."""
        db = SessionLocal()
        try:
            return get_tokens(db) is not None
        except Exception:
            return False
        finally:
            db.close()

    def get_access_token(self) -> str:
        """
        Returns a valid access token.
        Proactively refreshes if the token expires within EXPIRY_BUFFER.
        Raises McpAuthError if no tokens are stored.
        """
        db = SessionLocal()
        try:
            tokens = get_tokens(db)
        finally:
            db.close()

        if tokens is None:
            raise McpAuthError(
                "Robinhood is not connected. Complete OAuth at /auth/robinhood "
                "or paste tokens via POST /api/robinhood/token."
            )

        expires_at = tokens.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow() + EXPIRY_BUFFER:
            logger.info("Access token expiring soon — refreshing proactively")
            return self.force_refresh(tokens["refresh_token"])

        return tokens["access_token"]

    def force_refresh(self, refresh_token: str | None = None) -> str:
        """
        Forces a token refresh using the stored (or provided) refresh token.
        Saves the new tokens to DB and returns the new access token.
        """
        if refresh_token is None:
            db = SessionLocal()
            try:
                tokens = get_tokens(db)
            finally:
                db.close()
            if tokens is None:
                raise McpAuthError("No tokens to refresh")
            refresh_token = tokens["refresh_token"]

        if not settings.ROBINHOOD_CLIENT_ID:
            raise McpAuthError(
                "ROBINHOOD_CLIENT_ID not configured — cannot refresh token automatically. "
                "Paste a new token via POST /api/robinhood/token."
            )

        try:
            resp = httpx.post(
                ROBINHOOD_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.ROBINHOOD_CLIENT_ID,
                    "client_secret": settings.ROBINHOOD_CLIENT_SECRET,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise McpAuthError(f"Token refresh HTTP error {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            raise McpAuthError(f"Token refresh request failed: {e}") from e

        access_token = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)
        expires_in = int(data.get("expires_in", 3600))
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        db = SessionLocal()
        try:
            save_tokens(db, access_token, new_refresh, expires_at)
        finally:
            db.close()

        logger.info("Token refreshed — expires at %s", expires_at.isoformat())
        return access_token


_instance: TokenManager | None = None


def get_token_manager() -> TokenManager:
    global _instance
    if _instance is None:
        _instance = TokenManager()
    return _instance
