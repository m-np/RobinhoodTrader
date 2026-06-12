import json
import logging
import threading

import httpx

from agent.token_manager import McpAuthError, get_token_manager
from config import settings

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class McpConnectionError(Exception):
    pass


class RobinhoodMCPClient:
    """
    Connects to Robinhood's MCP server via Streamable HTTP transport.

    Flow per MCP spec:
      1. initialize  → server returns Mcp-Session-Id header
      2. notifications/initialized  → fire-and-forget
      3. tools/call  → include Mcp-Session-Id on every request
      4. Reinitialize if session expires (404) or token refreshes (401)
    """

    def __init__(self):
        self._url = settings.ROBINHOOD_MCP_URL
        self._tm = get_token_manager()
        self._seq = 0
        self._session_id: str | None = None
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _headers(self, token: str) -> dict:
        h = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _ensure_session(self, token: str) -> None:
        if self._session_id:
            return
        with self._lock:
            if self._session_id:
                return
            self._init_session(token)

    def _init_session(self, token: str) -> None:
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "RobinhoodTrader", "version": "1.0"},
            },
            "id": self._next_id(),
        }
        try:
            resp = httpx.post(
                self._url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=30,
            )
            resp.raise_for_status()
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid
                logger.info("MCP session: %s…", sid[:12])
            # Send initialized notification (fire-and-forget)
            self._notify_initialized(token)
        except httpx.HTTPError as e:
            raise McpConnectionError(f"MCP session init failed: {e}") from e

    def _notify_initialized(self, token: str) -> None:
        try:
            h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if self._session_id:
                h["Mcp-Session-Id"] = self._session_id
            httpx.post(
                self._url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=h,
                timeout=10,
            )
        except Exception:
            pass  # notifications don't need to succeed

    def _call(self, tool_name: str, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        logger.info("MCP → %s %s", tool_name, arguments.get("symbol", arguments.get("ticker", "")))
        try:
            token = self._tm.get_access_token()
        except McpAuthError as e:
            raise McpConnectionError(str(e)) from e
        self._ensure_session(token)
        return self._do_call(tool_name, arguments, token, retry=True)

    def _do_call(self, tool_name: str, arguments: dict, token: str, retry: bool) -> dict:
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
                headers=self._headers(token),
                timeout=30,
            )

            # Token expired — refresh and retry once
            if resp.status_code == 401 and retry:
                logger.warning("MCP 401 on %s — refreshing token", tool_name)
                try:
                    token = self._tm.force_refresh()
                    self._session_id = None
                    self._ensure_session(token)
                    return self._do_call(tool_name, arguments, token, retry=False)
                except McpAuthError as e:
                    raise McpConnectionError(f"Token refresh failed: {e}") from e

            # Session expired — reinit and retry once
            if resp.status_code in (404, 410) and retry:
                logger.warning("MCP session expired (%s) — reinitializing", resp.status_code)
                self._session_id = None
                self._ensure_session(token)
                return self._do_call(tool_name, arguments, token, retry=False)

            resp.raise_for_status()

            # Parse: JSON or SSE stream
            ct = resp.headers.get("content-type", "")
            data = self._parse_sse(resp.text) if "event-stream" in ct else resp.json()

            if "error" in data:
                err = data["error"]
                raise McpConnectionError(
                    f"MCP error {err.get('code', '?')}: {err.get('message', str(err))}"
                )

            return self._unwrap(data.get("result", {}))

        except McpConnectionError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("MCP HTTP %s [%s]: %s", e.response.status_code, tool_name, e.response.text[:300])
            raise McpConnectionError(f"HTTP {e.response.status_code}: {e.response.text[:200]}") from e
        except httpx.RequestError as e:
            logger.error("MCP request error [%s]: %s", tool_name, e)
            raise McpConnectionError(str(e)) from e
        except Exception as e:
            logger.error("MCP unexpected error [%s]: %s", tool_name, e)
            raise McpConnectionError(str(e)) from e

    @staticmethod
    def _parse_sse(text: str) -> dict:
        """Extract the first JSON data event from an SSE stream."""
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
        return {}

    @staticmethod
    def _unwrap(result: dict) -> dict:
        """MCP tool results wrap the payload in content[].text as JSON."""
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, KeyError):
                        return {"text": item.get("text", "")}
        return result

    # ── Public API ────────────────────────────────────────────────────────────

    def get_portfolio(self) -> dict:
        try:
            r = self._call("get_portfolio")
            holdings = []
            total_value = float(r.get("total_equity", r.get("total_value", 0)) or 0)
            for h in r.get("holdings", r.get("positions", [])):
                equity = float(h.get("equity", h.get("market_value", 0)) or 0)
                cost = float(h.get("cost_basis", h.get("average_buy_price", 0)) or 0)
                pnl = equity - cost
                pct = (equity / total_value * 100) if total_value > 0 else 0
                holdings.append({
                    "ticker": h.get("symbol", h.get("ticker", "")),
                    "quantity": float(h.get("quantity", 0) or 0),
                    "market_value": equity,
                    "cost_basis": cost,
                    "pnl": pnl,
                    "pnl_pct": (pnl / cost * 100) if cost > 0 else 0,
                    "pct_of_portfolio": pct,
                })
            return {
                "holdings": holdings,
                "cash": float(r.get("cash", r.get("buying_power", 0)) or 0),
                "total_value": total_value,
                "today_pnl": float(r.get("today_pnl", r.get("intraday_pnl", 0)) or 0),
                "total_return_pct": float(r.get("total_return_pct", r.get("percent_change", 0)) or 0),
            }
        except McpConnectionError:
            return {"holdings": [], "cash": 0.0, "total_value": 0.0, "today_pnl": 0.0, "total_return_pct": 0.0}

    def get_wallet_balance(self) -> float:
        try:
            r = self._call("get_buying_power")
            val = r.get("buying_power", r.get("cash", r.get("amount", 0)))
            return float(val or 0)
        except McpConnectionError:
            return 0.0

    def get_quote(self, ticker: str) -> dict:
        try:
            r = self._call("get_quote", {"symbol": ticker})
            return {
                "ticker": ticker,
                "price": _f(r.get("price", r.get("last_trade_price"))),
                "change_pct": _f(r.get("change_pct", r.get("percent_change"))),
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
            return r.get("orders", r.get("results", [])) if isinstance(r, dict) else []
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


def _f(val) -> float | None:
    """Safe float conversion — returns None if val is None."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
