"""Stock discovery engine.

Searches Google (via Serper.dev API) for what the investor community is
talking about, combines that with Robinhood trending data, then asks
Claude to surface 4-6 stocks with genuine growth potential.

Requires SERPER_API_KEY in .env for Google search.
Falls back to Robinhood-only mode if no API key is set.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta

import anthropic
import httpx

from config import settings
from db.models import StockDiscovery, Watchlist
from db.session import SessionLocal

logger = logging.getLogger(__name__)

_SEARCH_QUERIES = [
    "stocks analysts upgrading strong momentum {month} {year}",
    "breakout growth stocks investor community picking up {month} {year}",
    "hidden gem stocks gaining traction wall street {month} {year}",
    "best stocks upcoming catalyst earnings growth {month} {year}",
]

_CLAUDE_PROMPT = """You are a research analyst reviewing investor community signals to identify stocks with genuine growth potential.

Below is recent data from Google searches and Robinhood trending lists. Analyze it carefully and identify 4-6 specific, publicly traded US stocks that stand out.

For each stock, output a JSON object:
- ticker: string (uppercase, e.g. "NVDA")
- company_name: string
- rationale: string (2-3 sentences: what specific signal makes this interesting RIGHT NOW, what trend or catalyst is behind it)
- category: one of "momentum" | "analyst_pick" | "emerging" | "value"
- confidence: one of "high" | "medium" | "speculative"
- source_summary: string (brief label for what surfaced this, e.g. "Multiple analyst upgrades + Robinhood trending" or "Investor community buzz + earnings catalyst")

Rules:
- Only include stocks where there is a SPECIFIC, identifiable reason — no generic blue-chips.
- "speculative" = interesting signal but high uncertainty or early stage.
- "high" = multiple corroborating signals from credible sources.
- Exclude stocks already on the user's watchlist: {watchlist_tickers}
- Return ONLY valid JSON: a flat array of objects. No prose, no markdown fences.

DATA:
{data}"""


def _search_serper(query: str) -> list[dict]:
    """Search Google via Serper.dev API. Returns list of title/snippet dicts."""
    if not settings.SERPER_API_KEY:
        return []
    try:
        res = httpx.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": settings.SERPER_API_KEY,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": 8},
            timeout=15,
        )
        res.raise_for_status()
        return [
            {"title": r.get("title", ""), "snippet": r.get("snippet", "")}
            for r in res.json().get("organic", [])[:6]
        ]
    except Exception as e:
        logger.warning("Serper search error for '%s': %s", query, e)
        return []


def _get_robinhood_signals(mcp) -> list[str]:
    """Get lines of context from Robinhood trending / popular watchlists."""
    lines = []
    if mcp is None:
        return lines
    try:
        data = mcp._call("get_popular_watchlists", {})
        wlists = data.get("data", {}).get("results", data.get("results", []))
        for wl in wlists[:4]:
            name = wl.get("name", "trending")
            tickers = [
                i.get("symbol") or i.get("ticker", "")
                for i in wl.get("items", [])[:8]
                if i.get("symbol") or i.get("ticker")
            ]
            if tickers:
                lines.append(f"Robinhood '{name}': {', '.join(tickers)}")
    except Exception as e:
        logger.debug("Robinhood popular watchlists unavailable: %s", e)

    try:
        cal = mcp._call("get_earnings_calendar", {"range": "week"})
        events = cal.get("data", {}).get("results", cal.get("results", []))
        upcoming = [
            e.get("symbol") or e.get("ticker", "")
            for e in events[:10]
            if e.get("symbol") or e.get("ticker")
        ]
        if upcoming:
            lines.append(f"Upcoming earnings this week: {', '.join(upcoming)}")
    except Exception as e:
        logger.debug("Robinhood earnings calendar unavailable: %s", e)

    return lines


def run_discovery(mcp=None) -> list[dict]:
    """Run the full discovery pipeline. Returns list of discovered stock dicts."""
    now = datetime.utcnow()
    month = now.strftime("%B")
    year = now.strftime("%Y")

    db = SessionLocal()
    try:
        watchlist_tickers = [r.ticker for r in db.query(Watchlist).all()]
    finally:
        db.close()

    if not settings.SERPER_API_KEY and mcp is None:
        logger.info(
            "Discovery skipped: no SERPER_API_KEY and Robinhood not connected. "
            "Add SERPER_API_KEY to .env to enable Google search."
        )
        return []

    data_lines: list[str] = []

    # ── 1. Google search results ──────────────────────────────────────────────
    if settings.SERPER_API_KEY:
        for q_template in _SEARCH_QUERIES:
            q = q_template.format(month=month, year=year)
            results = _search_serper(q)
            if results:
                data_lines.append(f"\n=== Google: {q} ===")
                for r in results:
                    data_lines.append(f"• {r['title']}: {r['snippet']}")
    else:
        logger.info("Discovery: no SERPER_API_KEY — using Robinhood data only")

    # ── 2. Robinhood trending signals ─────────────────────────────────────────
    rh_lines = _get_robinhood_signals(mcp)
    if rh_lines:
        data_lines.append("\n=== Robinhood trending / upcoming ===")
        data_lines.extend(f"• {line}" for line in rh_lines)

    if not data_lines:
        logger.warning("Discovery: no data gathered from any source")
        return []

    # ── 3. Claude analysis ────────────────────────────────────────────────────
    prompt = _CLAUDE_PROMPT.format(
        watchlist_tickers=", ".join(watchlist_tickers) if watchlist_tickers else "none",
        data="\n".join(data_lines),
    )

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        discoveries = json.loads(raw)
        if not isinstance(discoveries, list):
            discoveries = []
        logger.info("Discovery: Claude identified %d stocks", len(discoveries))
    except Exception as e:
        logger.error("Discovery analysis failed: %s", e)
        return []

    return discoveries


def save_discoveries(discoveries: list[dict]) -> int:
    """Persist new discoveries to DB, skipping duplicates from the last 7 days."""
    if not discoveries:
        return 0
    db = SessionLocal()
    saved = 0
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        recent = {
            r.ticker
            for r in db.query(StockDiscovery)
            .filter(StockDiscovery.created_at >= cutoff)
            .all()
        }
        for d in discoveries:
            ticker = (d.get("ticker") or "").upper().strip()
            if not ticker or ticker in recent:
                continue
            db.add(StockDiscovery(
                id=str(uuid.uuid4()),
                ticker=ticker,
                company_name=d.get("company_name"),
                rationale=d.get("rationale"),
                category=d.get("category", "momentum"),
                confidence=d.get("confidence", "medium"),
                source_summary=d.get("source_summary"),
                created_at=datetime.utcnow(),
            ))
            recent.add(ticker)
            saved += 1
        db.commit()
        logger.info("Discovery: saved %d new stock(s)", saved)
    except Exception as e:
        logger.exception("Discovery save error: %s", e)
    finally:
        db.close()
    return saved


def check_and_run_discovery(mcp=None) -> None:
    """Entry point for the scheduler."""
    from agent.guardrails import get_knob
    if not get_knob("discover_enabled", True):
        logger.info("Discovery: disabled via knob")
        return
    discoveries = run_discovery(mcp)
    save_discoveries(discoveries)
