import logging
from datetime import datetime, timedelta

import httpx

from config import settings
from db.models import get_tokens, save_tokens
from db.session import SessionLocal

logger = logging.getLogger(__name__)

ROBINHOOD_TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
EXPIRY_BUFFER = timedelta(minutes=5)


class McpAuthError(Exception):
    pass


class TokenManager:
    def is_connected(self) -> bool:
        """True if valid tokens exist in DB."""
        db = SessionLocal()
        try:
            return get_tokens(db) is not None
        except Exception:
            return False
        finally:
            db.close()

    def get_access_token(self) -> str:
        """
        Returns a valid access token, refreshing proactively if close to expiry.
        Raises McpAuthError if no tokens exist.
        """
        db = SessionLocal()
        try:
            tokens = get_tokens(db)
        finally:
            db.close()

        if tokens is None:
            raise McpAuthError(
                "Robinhood is not connected. "
                "Open http://localhost:8000 and click 'Connect Robinhood'."
            )

        expires_at = tokens.get("expires_at")
        if expires_at and expires_at <= datetime.utcnow() + EXPIRY_BUFFER:
            logger.info("Access token expiring soon — refreshing proactively")
            return self.force_refresh(tokens["refresh_token"])

        return tokens["access_token"]

    def force_refresh(self, refresh_token: str | None = None) -> str:
        """
        Refreshes the access token using the stored refresh token.
        Uses the client_id stored in config_knobs (set during dynamic registration).
        No client_secret required — Robinhood uses public client OAuth.
        """
        if refresh_token is None:
            db = SessionLocal()
            try:
                tokens = get_tokens(db)
            finally:
                db.close()
            if tokens is None:
                raise McpAuthError("No tokens to refresh — reconnect at /auth/robinhood")
            refresh_token = tokens["refresh_token"]

        client_id = _get_client_id()
        if not client_id:
            raise McpAuthError(
                "No client_id found. Re-authenticate at /auth/robinhood "
                "to re-register and get new tokens."
            )

        try:
            resp = httpx.post(
                ROBINHOOD_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
                timeout=settings.OAUTH_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise McpAuthError(
                f"Token refresh failed ({e.response.status_code}): {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise McpAuthError(f"Token refresh request failed: {e}") from e

        access_token = data["access_token"]
        new_refresh = data.get("refresh_token", refresh_token)
        expires_in = int(data.get("expires_in", 86400))
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        db = SessionLocal()
        try:
            save_tokens(db, access_token, new_refresh, expires_at)
        finally:
            db.close()

        logger.info("Token refreshed — expires at %s", expires_at.isoformat())
        return access_token


def _get_client_id() -> str | None:
    """Read the dynamically registered client_id from config_knobs."""
    from agent.guardrails import get_knob
    return get_knob("robinhood_client_id")


_token_manager: TokenManager | None = None


def get_token_manager() -> TokenManager:
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
