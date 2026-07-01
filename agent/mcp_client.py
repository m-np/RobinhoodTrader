"""
Robinhood MCP client — Streamable HTTP transport.

Correct tool names discovered from Robinhood's live tools/list:
  get_accounts, get_portfolio, get_equity_positions, get_equity_quotes,
  get_equity_orders, place_equity_order, cancel_equity_order,
  review_equity_order, get_equity_tradability, search, ...

Always uses the agentic account (agentic_allowed=True) — never the
main brokerage account.
"""
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
    def __init__(self):
        self._url = settings.ROBINHOOD_MCP_URL
        self._tm = get_token_manager()
        self._seq = 0
        self._session_id: str | None = None
        self._session_lock = threading.Lock()
        self._agentic_account: str | None = None

    # ── Transport ─────────────────────────────────────────────────────────────

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
        with self._session_lock:
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
        resp = httpx.post(
            self._url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=settings.MCP_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
            logger.info("MCP session: %s…", sid[:12])
        # Fire-and-forget initialized notification
        try:
            h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            if self._session_id:
                h["Mcp-Session-Id"] = self._session_id
            httpx.post(
                self._url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=h,
                timeout=settings.MCP_CALL_TIMEOUT,
            )
        except Exception:
            pass

    def _call(self, tool: str, args: dict | None = None) -> dict:
        args = args or {}
        logger.info("MCP → %s", tool)
        try:
            token = self._tm.get_access_token()
        except McpAuthError as e:
            raise McpConnectionError(str(e)) from e
        self._ensure_session(token)
        return self._do_call(tool, args, token, retry=True)

    def _do_call(self, tool: str, args: dict, token: str, retry: bool) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
            "id": self._next_id(),
        }
        try:
            resp = httpx.post(
                self._url,
                json=payload,
                headers=self._headers(token),
                timeout=settings.MCP_CALL_TIMEOUT,
            )
            if resp.status_code == 401 and retry:
                logger.warning("MCP 401 — refreshing token")
                token = self._tm.force_refresh()
                self._session_id = None
                self._ensure_session(token)
                return self._do_call(tool, args, token, retry=False)

            if resp.status_code in (404, 410) and retry:
                logger.warning("MCP session expired — reinitializing")
                self._session_id = None
                self._ensure_session(token)
                return self._do_call(tool, args, token, retry=False)

            resp.raise_for_status()

            ct = resp.headers.get("content-type", "")
            data = _parse_sse(resp.text) if "event-stream" in ct else resp.json()

            if "error" in data:
                err = data["error"]
                raise McpConnectionError(
                    f"MCP {err.get('code','?')}: {err.get('message', str(err))}"
                )

            raw_result = data.get("result", {})
            # MCP tools signal application errors via isError=true instead of
            # JSON-RPC "error" — HTTP stays 200, so we must check explicitly.
            if raw_result.get("isError"):
                err_text = next(
                    (
                        item["text"]
                        for item in raw_result.get("content", [])
                        if item.get("type") == "text"
                    ),
                    "MCP tool returned isError=true",
                )
                raise McpConnectionError(f"MCP tool error: {err_text[:400]}")

            return _unwrap(raw_result)

        except McpConnectionError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(
                "MCP HTTP %s [%s]: %s",
                e.response.status_code, tool, e.response.text[:200],
            )
            raise McpConnectionError(f"HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise McpConnectionError(str(e)) from e
        except Exception as e:
            logger.error("MCP unexpected [%s]: %s", tool, e)
            raise McpConnectionError(str(e)) from e

    # ── Account resolution ────────────────────────────────────────────────────

    def _get_agentic_account(self) -> str:
        """
        Returns the agentic account number (agentic_allowed=True).
        Cached in memory and persisted to config_knobs across restarts.
        """
        if self._agentic_account:
            return self._agentic_account

        # Try cached DB value first
        from agent.guardrails import get_knob, set_knob
        cached = get_knob("robinhood_agentic_account")
        if cached:
            self._agentic_account = str(cached)
            return self._agentic_account

        # Fetch from Robinhood
        result = self._call("get_accounts")
        accounts = result.get("data", {}).get("accounts", [])
        agentic = next(
            (a for a in accounts if a.get("agentic_allowed")),
            None,
        )
        if not agentic:
            raise McpConnectionError(
                "No agentic account found on this Robinhood profile. "
                "Enable agentic trading in the Robinhood app first."
            )
        acct_num = str(agentic["account_number"])
        set_knob("robinhood_agentic_account", acct_num)
        self._agentic_account = acct_num
        logger.info("Agentic account resolved: •••%s", acct_num[-4:])
        return acct_num

    # ── Public API ────────────────────────────────────────────────────────────

    def get_portfolio(self) -> dict:
        """Holdings, cash, total value, and P&L from the agentic account."""
        try:
            acct = self._get_agentic_account()
            port = self._call("get_portfolio", {"account_number": acct})
            pos_result = self._call("get_equity_positions", {"account_number": acct})

            data = port.get("data", {})
            total_value = _f(data.get("total_value", 0)) or 0.0
            cash = _f(data.get("cash", 0)) or 0.0
            buying_power = _f(
                data.get("buying_power", {}).get("buying_power", cash)
            ) or 0.0

            positions = pos_result.get("data", {}).get("positions", [])
            holdings = []
            symbols = [p.get("symbol", "") for p in positions if p.get("symbol")]

            # Fetch live quotes for all held positions in one call
            quotes = {}
            if symbols:
                q_result = self._call("get_equity_quotes", {"symbols": symbols})
                for item in q_result.get("data", {}).get("results", []):
                    q = item.get("quote", {})
                    sym = q.get("symbol", "")
                    price = _f(q.get("last_trade_price")) or _f(q.get("last_non_reg_trade_price"))
                    prev = _f(q.get("adjusted_previous_close")) or _f(q.get("previous_close"))
                    quotes[sym] = {"price": price, "prev_close": prev}

            for pos in positions:
                sym = pos.get("symbol", "")
                qty = _f(pos.get("quantity", 0)) or 0.0
                avg_cost = _f(pos.get("average_buy_price", 0)) or 0.0
                q = quotes.get(sym, {})
                price = q.get("price") or avg_cost
                market_val = price * qty
                cost_basis = avg_cost * qty
                pnl = market_val - cost_basis
                pct_portfolio = (market_val / total_value * 100) if total_value > 0 else 0.0
                holdings.append({
                    "ticker": sym,
                    "quantity": qty,
                    "market_value": market_val,
                    "cost_basis": cost_basis,
                    "pnl": pnl,
                    "pnl_pct": (pnl / cost_basis * 100) if cost_basis > 0 else 0.0,
                    "pct_of_portfolio": pct_portfolio,
                    "current_price": price,
                    "avg_cost": avg_cost,
                })

            return {
                "holdings": holdings,
                "cash": cash,
                "buying_power": buying_power,
                "total_value": total_value,
                "equity_value": _f(data.get("equity_value", 0)) or 0.0,
                "today_pnl": 0.0,      # Robinhood doesn't expose this per-day
                "total_return_pct": 0.0,
            }
        except McpConnectionError:
            return {
                "holdings": [], "cash": 0.0, "buying_power": 0.0,
                "total_value": 0.0, "equity_value": 0.0,
                "today_pnl": 0.0, "total_return_pct": 0.0,
            }

    def get_wallet_balance(self) -> float:
        """Buying power from the agentic account."""
        try:
            acct = self._get_agentic_account()
            result = self._call("get_portfolio", {"account_number": acct})
            data = result.get("data", {})
            bp = data.get("buying_power", {}).get("buying_power")
            if bp is not None:
                return float(bp)
            return _f(data.get("cash", 0)) or 0.0
        except McpConnectionError:
            return 0.0

    def get_quotes_batch(self, tickers: list) -> dict:
        """Live prices for multiple tickers in one MCP call.

        Mirrors the exact approach used inside get_portfolio() so it runs with
        the same account context and response-parsing logic.
        Returns {TICKER: {price, change_pct}} for each ticker found.
        Missing or failed tickers get {price: None, change_pct: None}.
        """
        if not tickers:
            return {}
        upper = [t.upper() for t in tickers]
        empty = {t: {"price": None, "change_pct": None} for t in upper}
        try:
            result = self._call(
                "get_equity_quotes",
                {"symbols": upper},
            )
            # Use the same parsing path as get_portfolio()
            items = result.get("data", {}).get("results", [])
            quotes = dict(empty)
            for item in items:
                q = item.get("quote", {})
                sym = q.get("symbol", "").upper()
                if not sym:
                    continue
                price = _f(q.get("last_trade_price")) or _f(q.get("last_non_reg_trade_price"))
                prev = _f(q.get("adjusted_previous_close")) or _f(q.get("previous_close"))
                change_pct = ((price - prev) / prev * 100) if price and prev and prev != 0 else None
                quotes[sym] = {
                    "price": price,
                    "change_pct": round(change_pct, 2) if change_pct is not None else None,
                }
            # If batch returned nothing, fall back to individual calls
            if not any(v["price"] is not None for v in quotes.values()):
                logger.warning(
                    "get_quotes_batch: batch returned no prices, "
                    "falling back to individual calls",
                )
                for t in upper:
                    q = self.get_quote(t)
                    quotes[t] = {"price": q.get("price"), "change_pct": q.get("change_pct")}
            return quotes
        except Exception as e:
            logger.warning("get_quotes_batch failed: %s", e)
            return empty

    def get_quote(self, ticker: str) -> dict:
        """Live price and daily change % for a ticker."""
        try:
            result = self._call("get_equity_quotes", {"symbols": [ticker.upper()]})
            items = result.get("data", {}).get("results", [])
            if not items:
                return {"ticker": ticker, "price": None, "change_pct": None}
            q = items[0].get("quote", {})
            price = _f(q.get("last_trade_price")) or _f(q.get("last_non_reg_trade_price"))
            prev = _f(q.get("adjusted_previous_close")) or _f(q.get("previous_close"))
            change_pct = ((price - prev) / prev * 100) if price and prev and prev != 0 else None
            return {
                "ticker": ticker,
                "price": price,
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
                "bid": _f(q.get("bid_price")),
                "ask": _f(q.get("ask_price")),
                "prev_close": prev,
            }
        except McpConnectionError:
            return {"ticker": ticker, "price": None, "change_pct": None}

    def check_tradability(self, ticker: str) -> dict:
        """Check whether a ticker supports fractional share trading.

        Calls get_equity_tradability on the Robinhood MCP.  Returns a dict with:
          fractional_supported  bool   — True when new fractional buys are allowed
          closing_only          bool   — True when only closing fractional sells work
          raw                   str    — raw fractional_tradability value from API
        """
        try:
            acct = self._get_agentic_account()
            result = self._call("get_equity_tradability", {
                "account_number": acct,
                "symbols": [ticker.upper()],
            })
            items = result.get("data", {}).get("results", [])
            for item in items:
                if item.get("symbol", "").upper() == ticker.upper():
                    ft = item.get("fractional_tradability", "not_tradable")
                    return {
                        "fractional_supported": ft == "tradable",
                        "closing_only": ft == "position_closing_only",
                        "raw": ft,
                    }
            return {"fractional_supported": False, "closing_only": False, "raw": "not_found"}
        except McpConnectionError as e:
            logger.warning("Tradability check failed for %s: %s", ticker, e)
            return {"fractional_supported": False, "closing_only": False, "raw": "unknown"}

    def place_order(
        self,
        ticker: str,
        action: str,
        quantity: float,
        asset_class: str = "stock",
        order_type: str = "market",
        dollar_amount: float | None = None,
    ) -> dict:
        """Place an equity order.

        For fractional shares pass dollar_amount (notional) instead of quantity.
        Robinhood's agentic API accepts dollar_amount for fractional-enabled symbols.
        """
        acct = self._get_agentic_account()
        args: dict = {
            "account_number": acct,
            "symbol": ticker.upper(),
            "side": action,
            "type": order_type,
            "time_in_force": "gfd",
        }
        if dollar_amount is not None:
            args["dollar_amount"] = str(round(dollar_amount, 2))
            label = f"${dollar_amount:.2f} notional"
        else:
            args["quantity"] = quantity
            label = f"x{quantity:.4f}"

        result = self._call("place_equity_order", args)
        order_id = (
            result.get("data", {}).get("order", {}).get("id")
            or result.get("data", {}).get("id")
        )
        logger.info(
            "Order submitted: %s %s %s — RH order_id=%s",
            action, ticker.upper(), label, order_id or "unknown",
        )
        return result

    def get_earnings_calendar_raw(self, days_ahead: int = 30) -> list[dict]:
        """Fetch upcoming earnings events from Robinhood MCP.

        Returns a list of raw dicts — field names vary by API version, so callers
        must check multiple keys (symbol/ticker, report_date/date/earnings_date).
        Falls back gracefully to an empty list on any error.
        """
        from datetime import date, timedelta
        today = date.today()
        end = today + timedelta(days=days_ahead)
        try:
            result = self._call("get_earnings_calendar", {
                "start_date": today.isoformat(),
                "end_date": end.isoformat(),
            })
            data = result.get("data", result)
            items = (
                data.get("earnings")
                or data.get("results")
                or data.get("items")
                or []
            )
            if isinstance(items, list):
                return items
        except Exception as e:  # noqa: BLE001
            logger.warning("MCP get_earnings_calendar failed: %s", e)
        return []

    def cancel_order(self, order_id: str) -> dict:
        acct = self._get_agentic_account()
        return self._call("cancel_equity_order", {
            "account_number": acct,
            "order_id": order_id,
        })

    def get_order_history(self, limit: int = 20) -> list:
        try:
            acct = self._get_agentic_account()
            result = self._call("get_equity_orders", {"account_number": acct})
            return result.get("data", {}).get("orders", [])
        except McpConnectionError:
            return []

    def analyze_concentration(self) -> dict:
        """Use get_portfolio as a proxy — no dedicated concentration tool."""
        try:
            return self.get_portfolio()
        except McpConnectionError:
            return {}

    def read_analyst_notes(self, ticker: str) -> dict:
        """Search for analyst information via the search tool."""
        try:
            return self._call("search", {"query": ticker, "asset_type": "equity", "limit": 3})
        except McpConnectionError:
            return {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_sse(text: str) -> dict:
    """Extract the first JSON data: event from an SSE stream."""
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                return json.loads(line[5:].strip())
            except json.JSONDecodeError:
                pass
    return {}


def _unwrap(result: dict) -> dict:
    """MCP tool results wrap the payload in content[].text as JSON."""
    # Prefer structuredContent when available (already parsed)
    if "structuredContent" in result:
        return result["structuredContent"]
    content = result.get("content", [])
    for item in content:
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except (json.JSONDecodeError, KeyError):
                return {"text": item.get("text", "")}
    return result


def _f(val) -> float | None:
    """Null-safe float conversion — Robinhood returns prices as strings."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
