import json
import logging
import uuid
from datetime import datetime

import anthropic

from agent.guardrails import ApprovalPending, GuardrailViolation, check_all
from agent.mcp_client import McpConnectionError, RobinhoodMCPClient
from agent.token_manager import McpAuthError, get_token_manager
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
            logger.info("Agent cycle skipped: wallet not funded ($%.2f)", wallet["balance"])
        return

    context = _build_context(mcp_client)
    portfolio = context["portfolio"]

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    local_tools = _agent_tools()

    # Build MCP server config if tokens are available
    tm = get_token_manager()
    mcp_servers = []
    if tm.is_connected():
        try:
            token = tm.get_access_token()
            mcp_servers = [{
                "type": "url",
                "url": settings.ROBINHOOD_MCP_URL,
                "name": "robinhood-trading",
                "authorization_token": token,
            }]
        except McpAuthError as e:
            logger.warning("Could not get MCP token for agent loop: %s", e)

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
        tools=local_tools,
        messages=messages,
    )
    if mcp_servers:
        create_kwargs["mcp_servers"] = mcp_servers

    logger.info("Starting Claude agent cycle (MCP: %s)", "enabled" if mcp_servers else "disabled")

    while True:
        if mcp_servers:
            response = client.beta.messages.create(
                **create_kwargs, betas=["mcp-client-2025-04-04"]
            )
        else:
            response = client.messages.create(**create_kwargs)

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

    logger.info("Agent cycle complete")


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

    return {
        "portfolio": portfolio,
        "watchlist": watchlist,
        "blocklist": blocklist,
        "knobs": knobs,
        "recent_alerts": recent_alerts,
        "last_trades": last_trades,
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


def _handle_tool_call(
    name: str,
    inputs: dict,
    mcp_client: RobinhoodMCPClient,
    portfolio: dict,
    notifier,
) -> dict:
    if name == "get_quote":
        return mcp_client.get_quote(inputs["ticker"])
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

    quote = mcp_client.get_quote(ticker)
    price = quote.get("price") or 0.0
    total_usd = price * quantity

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

    try:
        result = mcp_client.place_order(ticker, action, quantity, asset_class)
        db = SessionLocal()
        try:
            t = db.query(Trade).filter(Trade.id == trade_id).first()
            if t:
                t.status = "executed"
                t.executed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        logger.info("Order placed: %s %s x%.4f @ $%.2f", action, ticker, quantity, price)
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
            "name": "get_quote",
            "description": "Get current price and daily change for a ticker",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "get_portfolio",
            "description": "Get current portfolio holdings, cash, and total value",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "place_order",
            "description": (
                "Place a buy or sell order. Guardrails are enforced before execution. "
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
                    "rationale": {
                        "type": "string",
                        "description": "Brief explanation of why this trade is recommended",
                    },
                },
                "required": ["ticker", "action", "quantity"],
            },
        },
        {
            "name": "create_alert",
            "description": "Create an alert visible on the dashboard",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "alert_type": {
                        "type": "string",
                        "enum": ["market_wave", "mirror_trade", "approval_request", "wallet_low"],
                    },
                    "message": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                },
                "required": ["message"],
            },
        },
    ]
