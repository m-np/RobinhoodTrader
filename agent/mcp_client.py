import json
import logging

import httpx

from agent.token_manager import McpAuthError, get_token_manager
from config import settings

logger = logging.getLogger(__name__)


class McpConnectionError(Exception):
    pass


class RobinhoodMCPClient:
    """
    Calls Robinhood's MCP server directly via JSON-RPC 2.0 over HTTP.
    Used for utility calls outside the agent loop (wallet balance, quotes,
    portfolio data for the UI). The agent loop passes the MCP server to
    Claude natively via mcp_servers, so Claude can call tools autonomously.
    """

    def __init__(self):
        self._url = settings.ROBINHOOD_MCP_URL
        self._tm = get_token_manager()
        self._seq = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _call(self, tool_name: str, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        log_ctx = arguments.get("symbol", arguments.get("ticker", ""))
        logger.info("MCP → %s %s", tool_name, log_ctx)

        try:
            token = self._tm.get_access_token()
        except McpAuthError as e:
            raise McpConnectionError(str(e)) from e

        return self._http_call(tool_name, arguments, token, retry_on_401=True)

    def _http_call(
        self,
        tool_name: str,
        arguments: dict,
        token: str,
        retry_on_401: bool = True,
    ) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
            "id": self._next_id(),
        }
        try:
            resp = httpx.post(
                self._url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            if resp.status_code == 401 and retry_on_401:
                logger.warning("MCP 401 on %s — refreshing token and retrying", tool_name)
                try:
                    new_token = self._tm.force_refresh()
                    return self._http_call(tool_name, arguments, new_token, retry_on_401=False)
                except McpAuthError as e:
                    raise McpConnectionError(f"Token refresh after 401 failed: {e}") from e

            resp.raise_for_status()
            data = resp.json()

            if "error" in data:
                err = data["error"]
                raise McpConnectionError(
                    f"MCP error {err.get('code', '?')}: {err.get('message', str(err))}"
                )

            return self._unwrap(data.get("result", {}))

        except McpConnectionError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("MCP HTTP %s on %s: %s", e.response.status_code, tool_name, e.response.text)
            raise McpConnectionError(f"HTTP {e.response.status_code}: {e.response.text}") from e
        except httpx.RequestError as e:
            logger.error("MCP request error [%s]: %s", tool_name, e)
            raise McpConnectionError(str(e)) from e

    @staticmethod
    def _unwrap(result: dict) -> dict:
        """MCP tool results nest the payload inside content[].text as JSON."""
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, KeyError):
                        return {"text": item.get("text", "")}
        return result

    # ── Public methods ────────────────────────────────────────────────────────

    def get_portfolio(self) -> dict:
        try:
            r = self._call("get_portfolio")
            return {
                "holdings": r.get("holdings", []),
                "cash": float(r.get("cash", 0.0)),
                "total_value": float(r.get("total_value", 0.0)),
                "today_pnl": float(r.get("today_pnl", 0.0)),
                "total_return_pct": float(r.get("total_return_pct", 0.0)),
            }
        except McpConnectionError:
            return {
                "holdings": [],
                "cash": 0.0,
                "total_value": 0.0,
                "today_pnl": 0.0,
                "total_return_pct": 0.0,
            }

    def get_wallet_balance(self) -> float:
        try:
            r = self._call("get_buying_power")
            return float(r.get("buying_power", r.get("cash", 0.0)))
        except McpConnectionError:
            return 0.0

    def get_quote(self, ticker: str) -> dict:
        try:
            r = self._call("get_quote", {"symbol": ticker})
            return {
                "ticker": ticker,
                "price": r.get("price"),
                "change_pct": r.get("change_pct"),
                "volume": r.get("volume"),
                "market_cap": r.get("market_cap"),
            }
        except McpConnectionError:
            return {"ticker": ticker, "price": None, "change_pct": None}

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: float,
        asset_class: str,
        order_type: str = "market",
    ) -> dict:
        return self._call("place_order", {
            "symbol": ticker,
            "side": action,
            "quantity": quantity,
            "asset_type": asset_class,
            "order_type": order_type,
        })

    def cancel_order(self, order_id: str) -> dict:
        return self._call("cancel_order", {"order_id": order_id})

    def get_order_history(self, limit: int = 20) -> list:
        try:
            r = self._call("get_order_history", {"limit": limit})
            return r.get("orders", []) if isinstance(r, dict) else []
        except McpConnectionError:
            return []

    def analyze_concentration(self) -> dict:
        try:
            return self._call("analyze_concentration")
        except McpConnectionError:
            return {}

    def read_analyst_notes(self, ticker: str) -> dict:
        try:
            return self._call("read_analyst_notes", {"symbol": ticker})
        except McpConnectionError:
            return {}
