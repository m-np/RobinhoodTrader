import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)


class MCPConnectionError(Exception):
    pass


class RobinhoodMCPClient:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._mcp_url = settings.ROBINHOOD_MCP_URL

    def _call(self, tool_name: str, tool_input: dict) -> dict:
        try:
            response = self._client.beta.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                tools=[
                    {
                        "type": "mcp",
                        "server_url": self._mcp_url,
                        "server_name": "robinhood",
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": f"Call the {tool_name} tool with input: {tool_input}",
                    }
                ],
                betas=["mcp-client-2025-04-04"],
            )
            for block in response.content:
                if block.type == "tool_result":
                    return block.content
            return {}
        except anthropic.AuthenticationError as e:
            logger.error("Robinhood MCP auth error: %s", e)
            raise MCPConnectionError("Authentication failed") from e
        except Exception as e:
            logger.error("Robinhood MCP call failed [%s]: %s", tool_name, e)
            raise MCPConnectionError(str(e)) from e

    def get_portfolio(self) -> dict:
        try:
            return self._call("get_portfolio", {})
        except MCPConnectionError:
            return {"holdings": [], "cash": 0.0, "total_value": 0.0}

    def get_wallet_balance(self) -> float:
        try:
            result = self._call("get_wallet_balance", {})
            return float(result.get("balance", 0.0))
        except MCPConnectionError:
            return 0.0

    def get_quote(self, ticker: str) -> dict:
        try:
            return self._call("get_quote", {"symbol": ticker})
        except MCPConnectionError:
            return {"ticker": ticker, "price": None, "change_pct": None}

    def place_order(self, ticker: str, action: str, quantity: float, asset_class: str) -> dict:
        return self._call(
            "place_order",
            {
                "symbol": ticker,
                "side": action,
                "quantity": quantity,
                "asset_type": asset_class,
            },
        )

    def cancel_order(self, order_id: str) -> dict:
        return self._call("cancel_order", {"order_id": order_id})

    def get_activity_feed(self) -> list:
        try:
            result = self._call("get_activity_feed", {})
            return result if isinstance(result, list) else result.get("activities", [])
        except MCPConnectionError:
            return []
