import logging
import uuid
from datetime import datetime, timedelta

import anthropic

from agent.guardrails import get_knob
from config import settings
from db.models import Report, Trade
from db.session import SessionLocal
from notifications.notifier import get_notifier

logger = logging.getLogger(__name__)


def generate_report(report_type: str = "weekly") -> Report | None:
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
        trades = (
            db.query(Trade)
            .filter(Trade.created_at >= cutoff, Trade.status == "executed")
            .order_by(Trade.created_at.desc())
            .all()
        )

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

        title = f"{'Daily' if report_type == 'daily' else 'Weekly'} report — {datetime.utcnow().strftime('%b %d, %Y')}"
        report = Report(
            id=str(uuid.uuid4()),
            title=title,
            summary=summary,
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
