import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.utcnow()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)
    asset_class = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price_usd = Column(Float, nullable=False)
    total_usd = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="pending_approval")
    rationale = Column(Text, nullable=True)
    mirror_source = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    executed_at = Column(DateTime, nullable=True)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, unique=True, nullable=False)
    notes = Column(Text, nullable=True)
    added_at = Column(DateTime, default=_now, nullable=False)


class Blocklist(Base):
    __tablename__ = "blocklist"

    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, unique=True, nullable=False)
    reason = Column(String, nullable=True)
    added_at = Column(DateTime, default=_now, nullable=False)


class ConfigKnob(Base):
    __tablename__ = "config_knobs"

    id = Column(String, primary_key=True, default=_uuid)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class MirrorSource(Base):
    __tablename__ = "mirror_sources"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    source_type = Column(String, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    scale_factor = Column(Float, default=0.02, nullable=False)
    last_checked_at = Column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True, default=_uuid)
    ticker = Column(String, nullable=True)
    alert_type = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String, nullable=False, default="info")
    acknowledged = Column(Boolean, default=False, nullable=False)
    trade_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    pnl_usd = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    report_type = Column(String, nullable=False, default="weekly")
    created_at = Column(DateTime, default=_now, nullable=False)


class PortfolioSnapshot(Base):
    """Periodic snapshot of agentic account value — used for the time-series chart."""

    __tablename__ = "portfolio_snapshots"

    id = Column(String, primary_key=True, default=_uuid)
    total_value = Column(Float, nullable=False)
    equity_value = Column(Float, nullable=False, default=0.0)
    cash = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_now, nullable=False)


class RobinhoodToken(Base):
    """Stores exactly one row — the current OAuth tokens, encrypted at rest."""

    __tablename__ = "robinhood_tokens"

    id = Column(String, primary_key=True, default=_uuid)
    access_token_enc = Column(Text, nullable=False)   # Fernet-encrypted, base64
    refresh_token_enc = Column(Text, nullable=False)  # Fernet-encrypted, base64
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


def _fernet():
    from cryptography.fernet import Fernet
    from config import settings
    if not settings.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY is not set — cannot encrypt/decrypt tokens")
    return Fernet(settings.ENCRYPTION_KEY.encode())


def get_tokens(db) -> dict | None:
    """
    Return decrypted token dict or None if no tokens are stored.
    Returns None (treats as not-connected) if decryption fails — this happens
    when ENCRYPTION_KEY has changed since the tokens were saved.
    """
    row = db.query(RobinhoodToken).first()
    if row is None:
        return None
    try:
        f = _fernet()
        return {
            "access_token": f.decrypt(row.access_token_enc.encode()).decode(),
            "refresh_token": f.decrypt(row.refresh_token_enc.encode()).decode(),
            "expires_at": row.expires_at,
        }
    except Exception:
        # Key mismatch or corrupted data — treat as not connected
        import logging
        logging.getLogger(__name__).warning(
            "Token decryption failed — ENCRYPTION_KEY may have changed. "
            "Re-authenticate at /auth/robinhood."
        )
        return None


def save_tokens(db, access_token: str, refresh_token: str, expires_at: datetime) -> None:
    """Encrypt and upsert tokens — always keeps exactly one row."""
    f = _fernet()
    enc_access = f.encrypt(access_token.encode()).decode()
    enc_refresh = f.encrypt(refresh_token.encode()).decode()
    now = datetime.utcnow()

    row = db.query(RobinhoodToken).first()
    if row:
        row.access_token_enc = enc_access
        row.refresh_token_enc = enc_refresh
        row.expires_at = expires_at
        row.updated_at = now
    else:
        db.add(RobinhoodToken(
            id=str(uuid.uuid4()),
            access_token_enc=enc_access,
            refresh_token_enc=enc_refresh,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        ))
    db.commit()
