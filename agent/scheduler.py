import logging
import threading
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent.guardrails import get_knob
from agent.loop import run_agent_cycle
from agent.mcp_client import RobinhoodMCPClient
from alerts.market_waves import check_market_waves
from config import settings
from discover.engine import check_and_run_discovery
from mirrors.capitol_trades import check_and_queue_mirror_trades
from mirrors.sec_edgar import check_and_queue_institutional_mirrors
from reports.generator import generate_report

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
_mcp_client: RobinhoodMCPClient | None = None
_scheduler: BackgroundScheduler | None = None

_AGENT_JOB_PREFIX = "agent_cycle"

_cycle_state: dict = {
    "status": "idle",   # "running" | "idle" | "error"
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def get_cycle_state() -> dict:
    return dict(_cycle_state)


def trigger_manual_run() -> bool:
    """Spawn _run_agent in a background thread. Returns False if already running."""
    if _cycle_state["status"] == "running":
        return False
    threading.Thread(target=_run_agent, daemon=True).start()
    return True


def _get_mcp() -> RobinhoodMCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = RobinhoodMCPClient()
    return _mcp_client


def _run_agent():
    global _cycle_state
    started = datetime.utcnow()
    _cycle_state["status"] = "running"
    _cycle_state["started_at"] = started.isoformat()
    _cycle_state["error"] = None
    try:
        mcp = _get_mcp()
        stats = run_agent_cycle(mcp_client=mcp)
        _save_portfolio_snapshot(mcp)
        finished = datetime.utcnow()
        if stats:
            _save_cycle_stat(stats, started, finished)
            _cycle_state["last_stat"] = stats
        _cycle_state["status"] = "idle"
    except Exception as e:
        _cycle_state["status"] = "error"
        _cycle_state["error"] = str(e)
        logger.exception("Agent cycle error: %s", e)
    finally:
        _cycle_state["finished_at"] = datetime.utcnow().isoformat()


def _save_cycle_stat(stats: dict, started: datetime, finished: datetime) -> None:
    try:
        import uuid as _uuid
        from db.models import CycleStat
        from db.session import SessionLocal
        db = SessionLocal()
        try:
            db.add(CycleStat(
                id=str(_uuid.uuid4()),
                started_at=started,
                finished_at=finished,
                iterations=stats.get("iterations", 0),
                input_tokens=stats.get("input_tokens", 0),
                output_tokens=stats.get("output_tokens", 0),
                cache_write_tokens=stats.get("cache_write_tokens", 0),
                cache_read_tokens=stats.get("cache_read_tokens", 0),
                estimated_cost_usd=stats.get("estimated_cost_usd", 0.0),
                created_at=finished,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("Failed to save cycle stat: %s", e)


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


def _refresh_price_cache():
    """Fetch live quotes for all watchlist tickers and store in the in-memory cache."""
    try:
        from db.models import Watchlist
        from db.session import SessionLocal
        from agent.price_cache import update as cache_update

        db = SessionLocal()
        try:
            tickers = [r.ticker for r in db.query(Watchlist).all()]
        finally:
            db.close()

        if not tickers:
            return
        quotes = _get_mcp().get_quotes_batch(tickers)
        cache_update(quotes)
        logger.debug("Price cache refreshed: %d tickers", len(quotes))
    except Exception as e:
        logger.warning("Price cache refresh error: %s", e)


def _track_watchlist_prices():
    """Snapshot current cached quotes to DB every 5 min for sparkline history."""
    try:
        import uuid as _uuid
        from datetime import datetime as _dt
        from db.models import Watchlist, WatchlistPriceSnapshot
        from db.session import SessionLocal
        from agent.price_cache import get_all as cache_get_all

        db = SessionLocal()
        try:
            tickers = [r.ticker for r in db.query(Watchlist).all()]
            if not tickers:
                return
            cache = cache_get_all()
            if not cache:
                return
            now = _dt.utcnow()
            added = 0
            for ticker in tickers:
                q = cache.get(ticker)
                if q and q.get("price") is not None:
                    db.add(WatchlistPriceSnapshot(
                        id=str(_uuid.uuid4()),
                        ticker=ticker,
                        price=q["price"],
                        change_pct=q.get("change_pct"),
                        recorded_at=now,
                    ))
                    added += 1
            db.commit()
            if added:
                logger.info("Watchlist price snapshot: %d tickers recorded", added)
        finally:
            db.close()
    except Exception as e:
        logger.exception("Watchlist price tracking error: %s", e)


def _process_approved_trades():
    """Execute dashboard-approved trades and cancel timed-out pending ones."""
    try:
        from datetime import timedelta
        from db.models import Trade
        from db.session import SessionLocal

        timeout_minutes = get_knob("approval_timeout_minutes", 10)
        cutoff = datetime.utcnow() - timedelta(minutes=timeout_minutes)

        db = SessionLocal()
        try:
            pending = (
                db.query(Trade)
                .filter(Trade.status.in_(["pending_approval", "approved"]))
                .all()
            )
        finally:
            db.close()

        if not pending:
            return

        mcp = _get_mcp()

        for trade in pending:
            if trade.status == "pending_approval" and trade.created_at < cutoff:
                db = SessionLocal()
                try:
                    t = db.query(Trade).filter(Trade.id == trade.id).first()
                    if t and t.status == "pending_approval":
                        t.status = "cancelled"
                        db.commit()
                        logger.info(
                            "Trade %s timed out after %d min, cancelled",
                            trade.id, timeout_minutes,
                        )
                finally:
                    db.close()

            elif trade.status == "approved":
                try:
                    qty = trade.quantity
                    dollar_amount: float | None = None
                    is_fractional = (qty % 1) != 0 or qty < 1
                    if is_fractional:
                        tradability = mcp.check_tradability(trade.ticker)
                        if tradability["fractional_supported"] or (
                            tradability["closing_only"] and trade.action == "sell"
                        ):
                            dollar_amount = trade.total_usd
                        else:
                            whole = int(qty)
                            if whole == 0:
                                logger.warning(
                                    "Approved trade %s: %s no fractional support, "
                                    "< 1 share — rejecting",
                                    trade.id, trade.ticker,
                                )
                                db = SessionLocal()
                                try:
                                    t = db.query(Trade).filter(
                                        Trade.id == trade.id
                                    ).first()
                                    if t and t.status == "approved":
                                        t.status = "rejected"
                                        db.commit()
                                finally:
                                    db.close()
                                continue
                            qty = float(whole)
                    mcp.place_order(
                        trade.ticker,
                        trade.action,
                        qty,
                        trade.asset_class or "stock",
                        dollar_amount=dollar_amount,
                    )
                    db = SessionLocal()
                    try:
                        t = db.query(Trade).filter(
                            Trade.id == trade.id
                        ).first()
                        if t:
                            t.status = "executed"
                            t.executed_at = datetime.utcnow()
                            db.commit()
                        size_label = f"${dollar_amount:.2f}" if dollar_amount else f"x{qty:.4f}"
                        logger.info(
                            "Approved trade executed: %s %s %s",
                            trade.action, trade.ticker, size_label,
                        )
                    finally:
                        db.close()
                except Exception as e:
                    logger.error(
                        "Failed to execute approved trade %s: %s",
                        trade.id, e,
                    )
                    db = SessionLocal()
                    try:
                        t = db.query(Trade).filter(
                            Trade.id == trade.id
                        ).first()
                        if t and t.status == "approved":
                            t.status = "rejected"
                            db.commit()
                    finally:
                        db.close()
    except Exception as e:
        logger.exception("Pending trade processor error: %s", e)


def _run_congressional_mirrors():
    try:
        check_and_queue_mirror_trades(_get_mcp())
    except Exception as e:
        logger.exception("Congressional mirror check error: %s", e)


def _run_institutional_mirrors():
    try:
        check_and_queue_institutional_mirrors(_get_mcp())
    except Exception as e:
        logger.exception("Institutional mirror check error: %s", e)


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


def _run_monthly_report():
    try:
        generate_report(report_type="monthly")
    except Exception as e:
        logger.exception("Monthly report error: %s", e)


def _check_missed_monthly_report() -> None:
    """Run on startup: generate last month's report if the app was offline on the 1st."""
    from db.models import CycleStat, Report
    from db.session import SessionLocal

    now = datetime.now(ET)
    first_of_this_month = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    prev_month_end = first_of_this_month - timedelta(seconds=1)
    prev_month_start = prev_month_end.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    # DB stores naive UTC — convert ET bounds to UTC for queries
    utc_start = prev_month_start.astimezone(pytz.utc).replace(tzinfo=None)
    utc_end = prev_month_end.astimezone(pytz.utc).replace(tzinfo=None)
    month_label = prev_month_start.strftime("%B %Y")

    db = SessionLocal()
    try:
        existing = (
            db.query(Report)
            .filter(
                Report.report_type == "monthly",
                Report.created_at >= utc_start,
                Report.created_at <= utc_end,
            )
            .first()
        )
        if existing:
            logger.debug("Monthly report for %s already exists", month_label)
            return

        has_data = (
            db.query(CycleStat)
            .filter(
                CycleStat.created_at >= utc_start,
                CycleStat.created_at <= utc_end,
            )
            .first()
        )
        if not has_data:
            logger.debug("No cycle data for %s — skipping backfill", month_label)
            return
    finally:
        db.close()

    logger.info("Monthly report for %s missed — generating on startup", month_label)

    logger.info(
        "Monthly report for %s was missed — generating on startup",
        prev_month_start.strftime("%B %Y"),
    )
    _run_monthly_report()


def _run_discovery():
    try:
        check_and_run_discovery(_get_mcp())
    except Exception as e:
        logger.exception("Stock discovery error: %s", e)


def reschedule_agent() -> None:
    """Hot-swap the agent cycle job based on current knob values.

    Called at startup and whenever schedule knobs change via the UI.
    Mode "interval": run every N minutes (existing behaviour).
    Mode "fixed": run at specific ET times on market days only.
    """
    if _scheduler is None:
        return

    # Remove all existing agent cycle jobs
    for job in list(_scheduler.get_jobs()):
        if job.id.startswith(_AGENT_JOB_PREFIX):
            job.remove()

    mode = get_knob("agent_schedule_mode", "interval")

    if mode == "fixed":
        times_raw = get_knob(
            "agent_schedule_times", "09:30,12:00,15:30"
        )
        times = [
            t.strip() for t in times_raw.split(",") if t.strip()
        ] or ["09:30", "12:00", "15:30"]
        for i, t in enumerate(times):
            h, m = map(int, t.split(":"))
            _scheduler.add_job(
                _run_agent,
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour=h,
                    minute=m,
                    timezone=ET,
                ),
                id=f"{_AGENT_JOB_PREFIX}_{i}",
                name=f"Agent cycle {t} ET",
            )
        logger.info(
            "Agent schedule: fixed times %s ET (mon-fri)",
            ", ".join(times),
        )
    else:
        minutes = get_knob(
            "agent_interval_minutes", settings.AGENT_INTERVAL_MINUTES
        )
        _scheduler.add_job(
            _run_agent,
            trigger=IntervalTrigger(minutes=minutes, jitter=30),
            id=_AGENT_JOB_PREFIX,
            name="Agent trading cycle",
        )
        logger.info("Agent schedule: every %d min", minutes)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    scheduler = BackgroundScheduler(timezone=ET)
    # Assign early so reschedule_agent() can add the agent job below
    _scheduler = scheduler

    scheduler.add_job(
        _process_approved_trades,
        trigger=IntervalTrigger(seconds=30, jitter=5),
        id="pending_trade_processor",
        name="Approved trade executor",
        next_run_time=datetime.now(ET),
        replace_existing=True,
    )

    scheduler.add_job(
        _run_market_waves,
        trigger=IntervalTrigger(minutes=5, jitter=20),
        id="market_waves",
        name="Market wave check",
        replace_existing=True,
    )

    scheduler.add_job(
        _refresh_price_cache,
        trigger=IntervalTrigger(seconds=5),
        id="price_cache_refresh",
        name="Watchlist live price cache",
        next_run_time=datetime.now(ET),
        replace_existing=True,
    )

    scheduler.add_job(
        _track_watchlist_prices,
        trigger=IntervalTrigger(minutes=5, jitter=20),
        id="watchlist_price_tracker",
        name="Watchlist price snapshot (sparklines)",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_congressional_mirrors,
        trigger=IntervalTrigger(hours=1, jitter=120),
        id="congressional_mirrors",
        name="Congressional trade mirror check",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_institutional_mirrors,
        trigger=IntervalTrigger(hours=6, jitter=300),
        id="institutional_mirrors",
        name="SEC EDGAR 13F institutional mirror check",
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
        trigger=CronTrigger(
            day_of_week=day_map.get(weekly_day, "fri"),
            hour=16, minute=5, timezone=ET,
        ),
        id="weekly_report",
        name="Weekly report",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_monthly_report,
        trigger=CronTrigger(day=1, hour=8, minute=0, timezone=ET),
        id="monthly_report",
        name="Monthly portfolio + AI cost report",
        replace_existing=True,
    )

    scheduler.add_job(
        _run_discovery,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=35, timezone=ET,
        ),
        id="stock_discovery",
        name="Stock discovery (Google + Robinhood trending)",
        replace_existing=True,
    )

    reschedule_agent()
    scheduler.start()
    logger.info("Scheduler started")

    # Backfill any missed monthly report before starting normal operations
    threading.Thread(target=_check_missed_monthly_report, daemon=True).start()

    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
