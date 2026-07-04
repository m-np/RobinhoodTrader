import logging
import uuid
from datetime import datetime, timedelta

import anthropic

from agent.guardrails import get_knob
from config import settings
from db.models import CycleStat, PortfolioSnapshot, Report, Trade
from db.session import SessionLocal
from notifications.notifier import get_notifier

logger = logging.getLogger(__name__)


def generate_report(report_type: str = "weekly") -> Report | None:
    if report_type == "monthly":
        return _generate_monthly_report()

    depth = get_knob("report_depth", "brief")
    include_rationale = get_knob("report_include_rationale", True)
    include_pnl = get_knob("report_include_pnl", True)

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=1 if report_type == "daily" else 7)
        trades = (
            db.query(Trade)
            .filter(Trade.created_at >= cutoff, Trade.status == "executed")
            .order_by(Trade.created_at.desc())
            .all()
        )
        if not trades:
            logger.info("No executed trades in period — skipping %s report", report_type)
            return None

        trade_lines = []
        for t in trades:
            line = f"- {t.action.upper()} {t.ticker}: {t.quantity:.4f} @ ${t.price_usd:.2f} (${t.total_usd:.2f})"
            if include_rationale and t.rationale:
                line += f"\n  Rationale: {t.rationale}"
            trade_lines.append(line)

        period = "today" if report_type == "daily" else "this week"
        depth_instruction = {
            "brief": "Write a concise 2-3 paragraph summary.",
            "full": "Write a detailed summary covering each trade, overall performance, and key observations.",
            "deep": "Write a deep analytical report covering trade decisions, market context, performance attribution, and forward-looking observations.",
        }.get(depth, "Write a concise summary.")

        prompt = (
            f"Generate a {report_type} trading report for {period}.\n\n"
            f"{'Executed trades:' if trades else 'No trades were executed this period.'}\n"
            + "\n".join(trade_lines)
            + f"\n\n{depth_instruction}"
            + ("\n\nInclude a P&L summary section." if include_pnl else "")
        )

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system="You are a trading analyst summarising the performance of an autonomous trading agent. Be factual, clear, and concise.",
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text

        # Derive P&L for the period from portfolio snapshots
        first_snap = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.created_at >= cutoff)
            .order_by(PortfolioSnapshot.created_at.asc())
            .first()
        )
        last_snap = (
            db.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.created_at.desc())
            .first()
        )
        if first_snap and last_snap and first_snap.total_value > 0:
            pnl_usd = round(last_snap.total_value - first_snap.total_value, 2)
            pnl_pct = round((pnl_usd / first_snap.total_value) * 100, 2)
        else:
            pnl_usd = None
            pnl_pct = None

        title = f"{'Daily' if report_type == 'daily' else 'Weekly'} report — {datetime.utcnow().strftime('%b %d, %Y')}"
        report = Report(
            id=str(uuid.uuid4()),
            title=title,
            summary=summary,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            report_type=report_type,
            created_at=datetime.utcnow(),
        )
        db.add(report)
        db.commit()
        logger.info("Report generated: %s", title)

        notifier = get_notifier()
        notifier.notify(title, summary)

        return report
    except Exception as e:
        logger.error("Report generation failed: %s", e)
        db.rollback()
        return None
    finally:
        db.close()


def _generate_monthly_report() -> Report | None:
    """Generate a combined portfolio + AI cost report for the previous calendar month."""
    now = datetime.utcnow()
    # Previous month window
    first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = first_of_this_month - timedelta(seconds=1)
    month_start = month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_label = month_start.strftime("%B %Y")

    db = SessionLocal()
    try:
        # Trades executed in the month
        trades = (
            db.query(Trade)
            .filter(
                Trade.created_at >= month_start,
                Trade.created_at <= month_end,
                Trade.status == "executed",
            )
            .order_by(Trade.created_at.asc())
            .all()
        )

        # AI cost for the month
        cycle_rows = (
            db.query(CycleStat)
            .filter(
                CycleStat.created_at >= month_start,
                CycleStat.created_at <= month_end,
            )
            .all()
        )
        total_ai_cost = sum(r.estimated_cost_usd for r in cycle_rows)
        total_cycles = len(cycle_rows)
        avg_cost = (total_ai_cost / total_cycles) if total_cycles else 0.0

        # Portfolio P&L: first snapshot at/after month start vs last before/at month end
        first_snap = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.created_at >= month_start)
            .order_by(PortfolioSnapshot.created_at.asc())
            .first()
        )
        last_snap = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.created_at <= month_end)
            .order_by(PortfolioSnapshot.created_at.desc())
            .first()
        )
        if first_snap and last_snap and first_snap.total_value > 0:
            pnl_usd = round(last_snap.total_value - first_snap.total_value, 2)
            pnl_pct = round((pnl_usd / first_snap.total_value) * 100, 2)
            portfolio_start = round(first_snap.total_value, 2)
            portfolio_end = round(last_snap.total_value, 2)
        else:
            pnl_usd = pnl_pct = portfolio_start = portfolio_end = None

        # Build prompt
        pnl_section = (
            f"Portfolio value: ${portfolio_start:,.2f} → ${portfolio_end:,.2f} "
            f"({'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%, "
            f"{'+'if pnl_usd >= 0 else ''}${pnl_usd:,.2f})"
            if pnl_usd is not None else "Portfolio snapshots unavailable for this month."
        )
        cost_section = (
            f"AI agent cost: ${total_ai_cost:.4f} total across {total_cycles} cycles "
            f"(avg ${avg_cost:.4f}/cycle)"
            if total_cycles else "No agent cycles recorded for this month."
        )
        trade_lines = [
            f"- {t.action.upper()} {t.ticker}: {t.quantity:.4f} shares @ ${t.price_usd:.2f} "
            f"(${t.total_usd:.2f}) — {t.rationale or 'no rationale'}"
            for t in trades
        ]
        trades_section = (
            "\n".join(trade_lines) if trades
            else "No trades were executed this month."
        )

        roi_vs_cost = ""
        if pnl_usd is not None and total_ai_cost > 0:
            net = pnl_usd - total_ai_cost
            roi_vs_cost = (
                f"\nNet portfolio gain after AI cost: "
                f"{'+'if net >= 0 else ''}${net:,.2f}"
            )

        prompt = (
            f"Generate a monthly trading report for {month_label}.\n\n"
            f"## Portfolio performance\n{pnl_section}{roi_vs_cost}\n\n"
            f"## AI agent cost\n{cost_section}\n\n"
            f"## Trades executed ({len(trades)})\n{trades_section}\n\n"
            "Write a 3-4 paragraph summary covering: portfolio performance vs AI cost "
            "(was the agent worth it?), notable trades, what went well and what didn't, "
            "and one forward-looking observation. Be direct and factual."
        )

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=(
                "You are a trading analyst summarising the monthly performance of an "
                "autonomous AI trading agent. Evaluate both portfolio returns AND the "
                "AI operational cost. Be factual, direct, and concise."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text

        title = f"Monthly report — {month_label}"
        report = Report(
            id=str(uuid.uuid4()),
            title=title,
            summary=summary,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            report_type="monthly",
            created_at=now,
        )
        db.add(report)
        db.commit()
        logger.info("Monthly report generated: %s | P&L $%.2f | AI cost $%.4f",
                    month_label, pnl_usd or 0, total_ai_cost)

        notifier = get_notifier()
        notifier.notify(title, summary[:500] + ("…" if len(summary) > 500 else ""))

        return report
    except Exception as e:
        logger.error("Monthly report generation failed: %s", e)
        db.rollback()
        return None
    finally:
        db.close()
