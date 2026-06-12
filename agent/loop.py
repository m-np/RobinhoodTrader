import json
import logging
import uuid
from datetime import datetime

import anthropic

from agent.guardrails import GuardrailViolation, check_all, get_knob
from agent.mcp_client import RobinhoodMCPClient
from agent.wallet import check_wallet
from config import settings
from db.models import Alert, Blocklist, ConfigKnob, Trade, Watchlist
from db.session import SessionLocal

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an autonomous trading agent managing a dedicated Robinhood agentic trading account.
Your goal is long-term portfolio growth while strictly respecting all guardrail rules.

Your account is completely isolated from the user's main Robinhood portfolio.
You only trade using funds deposited in this agentic account.

On each cycle you should:
1. Review the current portfolio and recent performance
2. Check watchlist stocks for entry/exit opportunities
3. Identify any market waves affecting held positions
4. Recommend or execute trades within the configured rules
5. Always explain your reasoning concisely

You NEVER:
- Trade tickers on the blocklist
- Exceed position size limits
- Trade asset classes that are toggled off
- Place orders without checking guardrails first

Always be conservative. Preserving capital is more important than chasing gains."""


def run_agent_cycle(mcp_client: RobinhoodMCPClient | None = None, notifier=None) -> None:
    if mcp_client is None:
        mcp_client = RobinhoodMCPClient()

    wallet = check_wallet(mcp_client)
    if not wallet["funded"]:
        logger.info("Agent cycle skipped: wallet not funded ($%.2f)", wallet["balance"])
        return

    context = _build_context(mcp_client)
    portfolio = context["portfolio"]

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    tools = _agent_tools()

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

    logger.info("Starting Claude agent cycle")
    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []

        for block in response.content:
            if block.type != "tool_use":
                continue
            result = _handle_tool_call(block.name, block.input, mcp_client, portfolio, notifier)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str)})

        if response.stop_reason == "end_turn" or not tool_results:
            break

        messages.append({"role": "user", "content": tool_results})

    logger.info("Agent cycle complete")


def _build_context(mcp_client: RobinhoodMCPClient) -> dict:
    db = SessionLocal()
    try:
        watchlist = [r.ticker for r in db.query(Watchlist).all()]
        blocklist = [r.ticker for r in db.query(Blocklist).all()]
        knobs = {r.key: json.loads(r.value) for r in db.query(ConfigKnob).all()}
        recent_alerts = [
            {"type": a.alert_type, "message": a.message, "severity": a.severity}
            for a in db.query(Alert).filter(Alert.acknowledged == False).limit(10).all()
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

    return {
        "portfolio": portfolio,
        "watchlist": watchlist,
        "blocklist": blocklist,
        "knobs": knobs,
        "recent_alerts": recent_alerts,
        "last_trades": last_trades,
    }


def _handle_tool_call(name: str, inputs: dict, mcp_client: RobinhoodMCPClient, portfolio: dict, notifier) -> dict:
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


def _place_order(inputs: dict, mcp_client: RobinhoodMCPClient, portfolio: dict, notifier) -> dict:
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
    except GuardrailViolation as e:
        logger.warning("Guardrail violation for %s %s: %s", action, ticker, e)
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
    except Exception as e:
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
            "description": "Get the current price and change for a ticker",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"}
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
            "description": "Place a buy or sell order. Guardrails are enforced automatically.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "action": {"type": "string", "enum": ["buy", "sell"]},
                    "quantity": {"type": "number"},
                    "asset_class": {"type": "string", "enum": ["stock", "crypto", "options", "futures", "event_contract"]},
                    "rationale": {"type": "string", "description": "Brief explanation of why this trade is recommended"},
                },
                "required": ["ticker", "action", "quantity"],
            },
        },
        {
            "name": "create_alert",
            "description": "Create an alert visible in the dashboard",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "alert_type": {"type": "string", "enum": ["market_wave", "mirror_trade", "approval_request", "wallet_low"]},
                    "message": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                },
                "required": ["message"],
            },
        },
    ]
