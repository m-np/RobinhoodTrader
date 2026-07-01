import json
import logging
import time
import uuid
from datetime import datetime

import anthropic

from agent.guardrails import ApprovalPending, GuardrailViolation, check_all
from agent.mcp_client import McpConnectionError, RobinhoodMCPClient
from agent.wallet import check_wallet
from brain import build_system_prompt
from config import settings
from db.models import Alert, Blocklist, ConfigKnob, PortfolioSnapshot, Trade, Watchlist
from db.session import SessionLocal

logger = logging.getLogger(__name__)


def run_agent_cycle(mcp_client: RobinhoodMCPClient | None = None, notifier=None) -> None:
    if mcp_client is None:
        mcp_client = RobinhoodMCPClient()

    wallet = check_wallet(mcp_client)
    if not wallet["funded"]:
        reason = wallet.get("reason", "")
        if reason == "not_connected":
            logger.info("Agent cycle skipped: Robinhood not connected")
        else:
            logger.info("Agent cycle skipped: wallet not funded")
        return

    context = _build_context(mcp_client)
    portfolio = context["portfolio"]

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    messages = [
        {
            "role": "user",
            "content": (
                "Please review the current portfolio and market conditions, "
                "then decide if any trades should be made.\n\n"
                f"Context:\n{json.dumps(context, indent=2, default=str)}"
            ),
        }
    ]

    create_kwargs = dict(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=build_system_prompt(context["knobs"]),
        tools=_agent_tools(),
        messages=messages,
    )

    logger.info("Starting Claude agent cycle")

    max_iterations = 10
    for iteration in range(max_iterations):
        response = _call_claude_with_retry(client, create_kwargs)

        messages.append({"role": "assistant", "content": response.content})
        create_kwargs["messages"] = messages
        tool_results = []

        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _handle_tool_call(
                block.name, block.input, mcp_client, portfolio, notifier
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })

        if response.stop_reason == "end_turn" or not tool_results:
            break

        messages.append({"role": "user", "content": tool_results})
        create_kwargs["messages"] = messages

        if iteration == max_iterations - 1:
            logger.warning("Agent cycle hit max iterations (%d) — terminating", max_iterations)

    logger.info("Agent cycle complete")


def _call_claude_with_retry(client: anthropic.Anthropic, kwargs: dict, max_retries: int = 3):
    """Call Claude with exponential backoff on transient API errors."""
    for attempt in range(max_retries):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            logger.warning("Claude rate limited — retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code >= 500 and attempt < max_retries - 1:
                wait = 2 ** attempt * 2  # 2s, 4s
                logger.warning("Claude API error %d — retrying in %ds", e.status_code, wait)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Claude API failed after all retries")


def _build_context(mcp_client: RobinhoodMCPClient) -> dict:
    db = SessionLocal()
    try:
        watchlist = [r.ticker for r in db.query(Watchlist).all()]
        blocklist = [r.ticker for r in db.query(Blocklist).all()]
        knobs = {r.key: json.loads(r.value) for r in db.query(ConfigKnob).all()}
        recent_alerts = [
            {"type": a.alert_type, "message": a.message, "severity": a.severity}
            for a in db.query(Alert).filter(
                Alert.acknowledged.is_(False)
            ).limit(10).all()
        ]
        last_trades = [
            {
                "ticker": t.ticker,
                "action": t.action,
                "total_usd": t.total_usd,
                "status": t.status,
                "rationale": t.rationale,
                "created_at": t.created_at,
            }
            for t in db.query(Trade).order_by(Trade.created_at.desc()).limit(5).all()
        ]
    finally:
        db.close()

    portfolio = mcp_client.get_portfolio()
    portfolio = _enrich_today_pnl(portfolio)

    # Pre-fetch watchlist quotes in one batch so Claude doesn't need to call
    # get_quote 22 times individually — cuts cycle time from ~90s to ~15s
    watchlist_quotes = mcp_client.get_quotes_batch(watchlist) if watchlist else {}

    # Brain signals — market conditions, earnings alerts, thesis scores
    market = _brain_market_snapshot()
    earnings_alerts: list = []
    journal_status: list = []
    try:
        from brain.catalyst_checker import (  # noqa: PLC0415
            get_earnings_alerts,
        )
        from brain.journal_store import (  # noqa: PLC0415
            get_watchlist_with_status,
            init_db,
        )
        init_db()
        earnings_alerts = get_earnings_alerts(watchlist)
        journal_status = get_watchlist_with_status(
            tickers=watchlist
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Brain context signals failed: %s", exc)

    return {
        "portfolio": portfolio,
        "watchlist": watchlist,
        "watchlist_quotes": watchlist_quotes,
        "blocklist": blocklist,
        "knobs": knobs,
        "recent_alerts": recent_alerts,
        "last_trades": last_trades,
        "market_snapshot": market,
        "earnings_alerts": earnings_alerts,
        "journal_status": journal_status,
    }


def _enrich_today_pnl(portfolio: dict) -> dict:
    """Patch today_pnl/pnl_pct using the first intraday portfolio snapshot.

    Robinhood's API doesn't expose intraday P&L, so we derive it from the
    earliest PortfolioSnapshot recorded today. Without this the daily-loss-halt
    guardrail would never fire (it would always see 0.0%).
    """
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db = SessionLocal()
    try:
        first = (
            db.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.created_at >= today_start)
            .order_by(PortfolioSnapshot.created_at.asc())
            .first()
        )
        if first and first.total_value > 0:
            current = portfolio.get("total_value", 0.0)
            pnl = current - first.total_value
            portfolio["today_pnl"] = round(pnl, 2)
            portfolio["today_pnl_pct"] = round(
                (pnl / first.total_value) * 100, 2
            )
    finally:
        db.close()
    return portfolio


def _brain_market_snapshot() -> dict:
    """Fetch live market conditions; return safe defaults on failure."""
    try:
        from brain.red_day_detector import (  # noqa: PLC0415
            classify_red_day,
            get_market_snapshot,
        )
        snap = get_market_snapshot()
        rd = classify_red_day(
            snap["sp500_change_pct"], snap["vix"]
        )
        return {
            **snap,
            "red_day_level": rd["level"],
            "red_day_label": rd["label"],
            "max_cash_deploy_pct": rd["max_cash_deploy_pct"],
            "eligible_tiers": rd["eligible_tiers"],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Market snapshot failed: %s", exc)
        return {
            "sp500_change_pct": 0.0,
            "vix": 15.0,
            "red_day_level": 0,
            "red_day_label": "none",
        }


def _brain_gates(ticker: str, action: str) -> tuple[bool, str]:
    """Extra pre-trade gates: earnings proximity and thesis sentiment.

    Returns (True, 'ok') when the trade may proceed, or
    (False, reason) when it should be blocked.
    Only applies to BUY orders.
    """
    if action != "buy":
        return True, "ok"
    try:
        from brain.catalyst_checker import (  # noqa: PLC0415
            check_earnings_gate,
        )
        can_trade, reason = check_earnings_gate(ticker)
        if not can_trade:
            return False, f"EARNINGS GATE: {reason}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Earnings gate check failed for %s: %s", ticker, exc)

    try:
        from brain.journal_store import (  # noqa: PLC0415
            get_latest_sentiment,
            has_hypothesis,
        )
        if has_hypothesis(ticker):
            sent = get_latest_sentiment(ticker) or "neutral"
            if sent == "broken":
                return False, f"THESIS BROKEN: {ticker}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Journal check failed for %s: %s", ticker, exc)

    return True, "ok"


def _handle_tool_call(
    name: str,
    inputs: dict,
    mcp_client: RobinhoodMCPClient,
    portfolio: dict,
    notifier,
) -> dict:
    if name == "get_portfolio":
        return mcp_client.get_portfolio()
    if name == "create_alert":
        return _create_alert(inputs)
    if name == "place_order":
        return _place_order(inputs, mcp_client, portfolio, notifier)
    return {"error": f"Unknown tool: {name}"}


def _create_alert(inputs: dict) -> dict:
    db = SessionLocal()
    try:
        alert = Alert(
            id=str(uuid.uuid4()),
            ticker=inputs.get("ticker"),
            alert_type=inputs.get("alert_type", "info"),
            message=inputs["message"],
            severity=inputs.get("severity", "info"),
            created_at=datetime.utcnow(),
        )
        db.add(alert)
        db.commit()
        return {"created": True, "id": alert.id}
    finally:
        db.close()


def _place_order(
    inputs: dict,
    mcp_client: RobinhoodMCPClient,
    portfolio: dict,
    notifier,
) -> dict:
    ticker = inputs["ticker"].upper()
    action = inputs["action"]
    quantity = float(inputs["quantity"])
    asset_class = inputs.get("asset_class", "stock")
    rationale = inputs.get("rationale", "")
    trade_type = inputs.get("trade_type", "auto")

    quote = mcp_client.get_quote(ticker)
    price = quote.get("price") or 0.0
    total_usd = price * quantity

    # Brain gates run first — before creating a trade record or hitting guardrails.
    # This prevents approval-gated trades from bypassing thesis/earnings checks.
    ok, brain_reason = _brain_gates(ticker, action)
    if not ok:
        logger.warning("Brain gate blocked %s %s: %s", action, ticker, brain_reason)
        return {"success": False, "reason": brain_reason}

    db = SessionLocal()
    try:
        trade = Trade(
            id=str(uuid.uuid4()),
            ticker=ticker,
            action=action,
            asset_class=asset_class,
            quantity=quantity,
            price_usd=price,
            total_usd=total_usd,
            status="pending_approval",
            rationale=rationale,
            created_at=datetime.utcnow(),
        )
        db.add(trade)
        db.commit()
        trade_id = trade.id
    finally:
        db.close()

    try:
        check_all(
            ticker=ticker,
            action=action,
            asset_class=asset_class,
            total_usd=total_usd,
            portfolio=portfolio,
            trade_id=trade_id,
            notifier=notifier,
            trade_type=trade_type,
        )
    except ApprovalPending:
        logger.info("Trade %s queued for human approval", trade_id)
        return {"pending": True, "trade_id": trade_id}
    except GuardrailViolation as e:
        logger.warning(
            "Guardrail violation for %s %s: %s", action, ticker, e
        )
        db = SessionLocal()
        try:
            t = db.query(Trade).filter(Trade.id == trade_id).first()
            if t and t.status not in ("executed", "cancelled"):
                t.status = "rejected"
                db.commit()
        finally:
            db.close()
        return {"success": False, "reason": str(e)}

    # Fractional share routing: check tradability, then decide how to call the API
    is_fractional_qty = (quantity % 1) != 0 or quantity < 1
    dollar_amount: float | None = None

    if is_fractional_qty:
        tradability = mcp_client.check_tradability(ticker)
        if tradability["fractional_supported"]:
            # Use dollar_amount (notional) — Robinhood agentic API prefers this
            # over a fractional quantity field for fractional-enabled symbols
            dollar_amount = total_usd
            logger.info(
                "%s supports fractional trading — placing $%.2f notional order",
                ticker, dollar_amount,
            )
        elif tradability["closing_only"] and action == "sell":
            # Can still close a fractional position even without full support
            dollar_amount = total_usd
            logger.info(
                "%s fractional closing-only — placing $%.2f notional sell",
                ticker, dollar_amount,
            )
        else:
            # No fractional support: floor to whole shares
            whole = int(quantity)
            if whole == 0:
                logger.warning(
                    "Fractional trading not supported for %s and $%.2f buys < 1 share "
                    "(raw=%s) — order rejected",
                    ticker, total_usd, tradability["raw"],
                )
                db = SessionLocal()
                try:
                    t = db.query(Trade).filter(Trade.id == trade_id).first()
                    if t and t.status not in ("executed", "cancelled"):
                        t.status = "rejected"
                        db.commit()
                finally:
                    db.close()
                return {
                    "success": False,
                    "reason": (
                        f"{ticker} does not support fractional shares "
                        f"(tradability={tradability['raw']}) and ${total_usd:.2f} "
                        "is less than the cost of one whole share"
                    ),
                }
            # Enough for whole shares — adjust quantity and recalculate total
            logger.info(
                "%s: no fractional support, rounding %.4f → %d shares",
                ticker, quantity, whole,
            )
            quantity = float(whole)
            total_usd = price * quantity

    try:
        result = mcp_client.place_order(
            ticker, action, quantity, asset_class,
            dollar_amount=dollar_amount,
        )
        db = SessionLocal()
        try:
            t = db.query(Trade).filter(Trade.id == trade_id).first()
            if t:
                t.status = "executed"
                t.executed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        size_label = f"${dollar_amount:.2f}" if dollar_amount else f"x{quantity:.4f}"
        logger.info("Order placed: %s %s %s @ $%.2f", action, ticker, size_label, price)
        return {"success": True, "trade_id": trade_id, "result": result}
    except (McpConnectionError, Exception) as e:
        logger.error("Order failed for %s %s: %s", action, ticker, e)
        db = SessionLocal()
        try:
            t = db.query(Trade).filter(Trade.id == trade_id).first()
            if t:
                t.status = "rejected"
                db.commit()
        finally:
            db.close()
        return {"success": False, "reason": str(e)}


def _agent_tools() -> list:
    return [
        {
            "name": "get_portfolio",
            "description": (
                "Get real-time portfolio holdings, cash, and total value. "
                "Current prices for watchlist tickers are already in the context "
                "under 'watchlist_quotes' — only call this if you need the very "
                "latest portfolio state after a trade."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "place_order",
            "description": (
                "Place a buy or sell order. Guardrails are enforced before execution. "
                "Fractional shares are supported automatically: pass any quantity including "
                "decimals (e.g. 0.1 shares) or small dollar amounts — the system checks "
                "whether the symbol supports fractional trading and routes accordingly. "
                "Always use this tool for trades — never use Robinhood MCP place_order directly."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell"]},
                    "quantity": {"type": "number"},
                    "asset_class": {
                        "type": "string",
                        "enum": ["stock", "crypto", "options", "futures", "event_contract"],
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["core", "growth", "moonshot"],
                        "description": "Conviction tier from thesis journal",
                    },
                    "trade_type": {
                        "type": "string",
                        "enum": [
                            "new_position", "scale_in", "rebalance",
                            "stop_loss", "profit_take", "full_exit",
                        ],
                        "description": "Why this order is being placed",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this trade is recommended",
                    },
                },
                "required": ["ticker", "action", "quantity"],
            },
        },
        {
            "name": "create_alert",
            "description": (
                "Create an informational alert visible on the dashboard. "
                "Use for market observations, wallet warnings, or mirror signals. "
                "Do NOT use alert_type='approval_request' — when place_order returns "
                "{pending: true}, the approval alert and trade record are created "
                "automatically by the guardrails system with the correct trade link. "
                "Creating a second approval_request alert here will break the Approve button."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "alert_type": {
                        "type": "string",
                        "enum": ["market_wave", "mirror_trade", "wallet_low"],
                    },
                    "message": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                },
                "required": ["message"],
            },
        },
    ]
