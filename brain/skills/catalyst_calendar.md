# Catalyst Calendar Skill

## Purpose

Forward-looking event tracking for all watchlist tickers. The agent is never
caught by surprise by an earnings report, Fed meeting, or binary decision. Every
event is identified in advance, logged in the journal, and handled per protocol.

Time-sensitive events are the most dangerous moments in aggressive growth investing:
a great thesis can be destroyed by holding through a binary event you knew was coming.
A great buying opportunity can be missed by not knowing when the fear resolves.

---

## Event Types

### Type 1 — Earnings (highest priority)
Binary outcome per stock. Most dangerous event for individual positions.
Source: `yfinance ticker.calendar` — fetch at cycle start for every watchlist ticker.

### Type 2 — Fed Meetings (macro)
FOMC decisions move the entire market. Eight per year.
VIX typically rises 2–3 days before and falls after (unless there is a surprise).
Strategy: do not open new positions 2 days before FOMC.
Red day often follows a surprise decision — dry powder opportunity.

Approximate 2026 FOMC dates: Jan 29, Mar 19, May 7, Jun 18, Jul 30, Sep 17, Nov 5, Dec 17.
Update this list at the start of each year.

### Type 3 — Sector ETF Rebalance (quarterly)
SOXX, XLK, XBI, QQQ rebalance quarterly. Creates mechanical selling in removed
names and mechanical buying in added names. These moves are not fundamental.
Strategy: dips caused by rebalance selling are macro-dip-protocol eligible.

### Type 4 — Company Binary Events
FDA decisions, regulatory rulings, analyst days, product launches, major contract
announcements. Similar binary risk profile to earnings for individual tickers.
Source: journal entries (agent writes these when research uncovers them),
SEC 8-K filings fetched via EDGAR.

### Type 5 — Macro Data Releases
CPI, PCE, jobs report, GDP revisions. Move the market broadly but are not binary
for individual stocks the way earnings are. Awareness only — do not time individual
trades specifically around macro data releases.

---

## Earnings Countdown Protocol

Fetch earnings dates at the start of every cycle for all watchlist tickers.
Write a journal alert entry at each threshold.

### 21 days before earnings
- Write journal alert: "Earnings in ~21 days — note upcoming catalyst"
- No position changes required yet

### 14 days before earnings
- Write journal alert: "Earnings in ~14 days — no new entries from here"
- Block new position entries (enforced by pre-entry gate in stocks.md)
- Evaluate: is current position sized appropriately for binary risk?
- If large position with significant gains: consider taking 20–30% off now

### 7 days before earnings
- Hard block: pre-entry gate prevents new entries
- Close any long options to avoid IV crush (see options.md)
- Do not open new covered calls — buyback risk too high
- For Moon Shot positions: consider full exit — small size means small upside
  but binary risk is amplified

### 3 days before earnings
- Write journal alert with consensus estimates from yfinance
- For Growth and Core with 30%+ profit: consider 20% partial exit to lock in gains
- For Moon Shots: evaluate full exit — binary risk, position is already small

### Earnings day
- No new orders on the ticker today
- For positions held through: have exit criteria ready based on the report

### 1–3 days after earnings
- Write journal observation immediately with full assessment:
  - Reported vs consensus EPS and revenue
  - Guidance raised / maintained / cut
  - Thesis impact: does this strengthen, challenge, or break the hypothesis?
  - New sentiment field based on the above
- Do not buy options for 2–3 sessions post-earnings (IV crush window)
- "Buy the dip" rule: a beat that sold off may be an entry IF guidance was also raised.
  A beat with unchanged or cut guidance is NOT bullish.

---

## Calendar Fetch Procedure (Run Each Cycle)

```python
import yfinance as yf
from datetime import datetime, date

def check_earnings_calendar(tickers: list[str]) -> list[dict]:
    alerts = []
    today = date.today()
    
    for ticker in tickers:
        try:
            cal = yf.Ticker(ticker).calendar
            if cal is None or cal.empty:
                continue
            earnings_date = cal.iloc[0].get("Earnings Date")
            if earnings_date is None:
                continue
            days = (earnings_date.date() - today).days
            
            if 0 <= days <= 3:
                alerts.append({"ticker": ticker, "days": days,
                                "level": "IMMINENT", "action": "No new entries. Evaluate exit."})
            elif days <= 7:
                alerts.append({"ticker": ticker, "days": days,
                                "level": "7D_WARNING", "action": "No new entries. Review options."})
            elif days <= 14:
                alerts.append({"ticker": ticker, "days": days,
                                "level": "14D_NOTICE", "action": "No new entries from here."})
            elif days <= 21:
                alerts.append({"ticker": ticker, "days": days,
                                "level": "21D_NOTE", "action": "Note upcoming catalyst."})
        except Exception:
            pass
    return alerts
```

---

## Monthly Calendar (Create at Start of Each Month)

At the first cycle of each calendar month, write a journal alert:

```
Type: alert
Text:
  MONTHLY CALENDAR — [Month Year]
  
  Upcoming earnings: [list of watchlist tickers with dates]
  FOMC meeting: [date if this month, or "none this month"]
  ETF rebalance: [approximate date if this month]
  Other binary events: [any known from journal research]
  
  Highest risk week: [week with most events]
  Dry powder recommendation: maintain 20%+ cash heading into [risk week]
```

This gives the agent a forward view at the start of each month so the
cash reserve and position sizing are calibrated in advance of known risks.