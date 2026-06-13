import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.guardrails import get_knob
from agent.loop import run_agent_cycle
from agent.mcp_client import RobinhoodMCPClient
from alerts.market_waves import check_market_waves
from config import settings
from reports.generator import generate_report

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
_mcp_client: RobinhoodMCPClient | None = None
_scheduler: BackgroundScheduler | None = None


def _get_mcp() -> RobinhoodMCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = RobinhoodMCPClient()
    return _mcp_client


def _run_agent():
    try:
        mcp = _get_mcp()
        run_agent_cycle(mcp_client=mcp)
        _save_portfolio_snapshot(mcp)
    except Exception as e:
        logger.exception("Agent cycle error: %s", e)


def _save_portfolio_snapshot(mcp: RobinhoodMCPClient) -> None:
    """Capture a portfolio snapshot after each agent cycle for the time-series chart."""
    try:
        import uuid as _uuid
        from datetime import datetime as _dt
        from db.models import PortfolioSnapshot
        from db.session import SessionLocal
        portfolio = mcp.get_portfolio()
        if portfolio.get("total_value", 0) <= 0:
            return
        db = SessionLocal()
        try:
            db.add(PortfolioSnapshot(
                id=str(_uuid.uuid4()),
                total_value=portfolio["total_value"],
                equity_value=portfolio.get("equity_value", 0.0),
                cash=portfolio.get("cash", 0.0),
                created_at=_dt.utcnow(),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Portfolio snapshot failed: %s", e)


def _run_market_waves():
    try:
        check_market_waves(_get_mcp())
    except Exception as e:
        logger.exception("Market wave check error: %s", e)


def _run_daily_report():
    freq = get_knob("report_frequency", "off")
    if freq in ("daily", "both"):
        try:
            generate_report(report_type="daily")
        except Exception as e:
            logger.exception("Daily report error: %s", e)


def _run_weekly_report():
    freq = get_knob("report_frequency", "off")
    if freq in ("weekly", "both"):
        try:
            generate_report(report_type="weekly")
        except Exception as e:
            logger.exception("Weekly report error: %s", e)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler(timezone=ET)

    scheduler.add_job(
        _run_agent,
        trigger=IntervalTrigger(minutes=settings.AGENT_INTERVAL_MINUTES),
        id="agent_cycle",
        name="Agent trading cycle",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_market_waves,
        trigger=IntervalTrigger(minutes=5),
        id="market_waves",
        name="Market wave check",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_daily_report,
        trigger=CronTrigger(hour=16, minute=5, timezone=ET),
        id="daily_report",
        name="Daily report",
        replace_existing=True,
    )

    weekly_day = get_knob("report_weekly_day", "Friday")
    day_map = {
        "Monday": "mon", "Tuesday": "tue", "Wednesday": "wed",
        "Thursday": "thu", "Friday": "fri", "Saturday": "sat", "Sunday": "sun",
    }
    scheduler.add_job(
        _run_weekly_report,
        trigger=CronTrigger(day_of_week=day_map.get(weekly_day, "fri"), hour=16, minute=5, timezone=ET),
        id="weekly_report",
        name="Weekly report",
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started: agent every %d min, waves every 5 min", settings.AGENT_INTERVAL_MINUTES)
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
