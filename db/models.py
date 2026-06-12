import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.utcnow()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker = Column(String, nullable=False)
    action = Column(String, nullable=False)  # "buy" | "sell"
    asset_class = Column(String, nullable=False)  # "stock" | "crypto" | "options" | "futures" | "event_contract"
    quantity = Column(Float, nullable=False)
    price_usd = Column(Float, nullable=False)
    total_usd = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="pending_approval")  # "pending_approval" | "executed" | "rejected" | "cancelled"
    rationale = Column(Text, nullable=True)
    mirror_source = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    executed_at = Column(DateTime, nullable=True)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker = Column(String, unique=True, nullable=False)
    notes = Column(Text, nullable=True)
    added_at = Column(DateTime, default=_now, nullable=False)


class Blocklist(Base):
    __tablename__ = "blocklist"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker = Column(String, unique=True, nullable=False)
    reason = Column(String, nullable=True)
    added_at = Column(DateTime, default=_now, nullable=False)


class ConfigKnob(Base):
    __tablename__ = "config_knobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class MirrorSource(Base):
    __tablename__ = "mirror_sources"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    source_type = Column(String, nullable=False)  # "congressional" | "institutional"
    enabled = Column(Boolean, default=False, nullable=False)
    scale_factor = Column(Float, default=0.02, nullable=False)
    last_checked_at = Column(DateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    ticker = Column(String, nullable=True)
    alert_type = Column(String, nullable=False)  # "market_wave" | "mirror_trade" | "approval_request" | "wallet_low"
    message = Column(Text, nullable=False)
    severity = Column(String, nullable=False, default="info")  # "info" | "warning" | "critical"
    acknowledged = Column(Boolean, default=False, nullable=False)
    trade_id = Column(UUID(as_uuid=False), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    pnl_usd = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    report_type = Column(String, nullable=False, default="weekly")  # "daily" | "weekly"
    created_at = Column(DateTime, default=_now, nullable=False)
