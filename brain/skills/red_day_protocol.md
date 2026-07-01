# Red Day Protocol

## What is a Red Day

A red day is a broad market selloff driven by macro fear — not company-specific news.
The distinction is the entire basis of the strategy: macro fear creates buying
opportunities on great companies. Company-specific bad news creates exits, not entries.

Red day = the market is punishing good companies for reasons that do not affect
their thesis. This is when the aggressive-disciplined investor acts.

---

## Red Day Levels

### Level 1 — Mild (observe only)
- S&P 500 down 0.8%–1.5% OR sector ETF (SOXX/XLK/XBI) down 1.5%–2.5%
- Action: scan watchlist, write journal observations noting which tickers are
  approaching entry zones. No buying yet.

### Level 2 — Confirmed (primary entry trigger)
- S&P 500 down 1.5%–3% on macro event (Fed, tariffs, geopolitical, macro data)
- OR: Sector ETF down 2.5%–4%
- Action: run full entry evaluation on all Core and Growth watchlist tickers
- Core tier: signal requirement drops to 1 of 5
- Growth tier: still require 2 of 5
- Moon Shot: red day alone is not enough — full criteria still required

### Level 3 — High Fear
- S&P 500 down 3%+ OR VIX spikes above 25 intraday
- Action: Core tier only — deploy up to 50% of daily dry powder
- Moon Shots: blocked on Level 3 days — fear amplifies binary risk
- Write journal alert noting the fear level and your dry powder deployment

### Level 4 — Extreme Fear (VIX > 35)
- Market down 4%+ in a session or VIX crosses 35
- These occur 5–6 times per year and historically represent the best annual entry points
- Action: deploy up to 20% of total cash reserve into highest journal-score Core tickers
- Write a journal entry for every trade today — these entries matter most for future learning

---

## Verification — Macro or Company?

Before any red day entry, confirm the selloff is macro, not company-specific:

1. Is the stock down roughly the same percentage as the sector ETF?
   - Compare watchlist_quotes[ticker].change_pct to market_snapshot.soxx_change_pct
     (for semis) or xlk_change_pct (for broad tech)
   - Stock decline ≤ 1.5× sector decline → macro selloff, proceed
   - Stock down significantly MORE than the sector → company-specific, do not buy

2. Is there company-specific news today?
   - Call `read_journal(ticker)` — check the most recent entries for: earnings release,
     guidance change, executive departure, product failure, regulatory action
   - Also review `recent_alerts` in context for any alerts flagging this ticker
   - If company-specific bad news is present → NOT a macro dip. Do not buy.
     Write a journal observation entry instead.

3. Was the stock already underperforming before today?
   - Check journal_status[ticker].latest_sentiment — if it is challenged or broken,
     the stock had accumulated negative sentiment before today's macro move
   - If thesis_score is below 4, multiple prior observations flagged deterioration
   - Either condition → do not buy; this is a weakening stock getting hit harder on
     a macro day, not a fundamentally strong company being unfairly punished

4. Read the latest journal entry for the ticker:
   - Call `read_journal(ticker)` and read the most recent observation or update entry
   - If latest sentiment is challenged or broken → do not buy regardless of macro

All four checks must pass before treating the day as a macro entry opportunity.

---

## Dry Powder Rules

| Level | Max cash to deploy | Tier restriction |
|---|---|---|
| Level 1 | 0% — observe only | N/A |
| Level 2 | 25% of cash reserve | Core and Growth |
| Level 3 | 50% of cash reserve | Core only |
| Level 4 | 66% of cash reserve | Core only, highest journal score |

After deploying on a red day: replenish cash reserve from next profit-taking event.
Never deploy all cash on a single red day — there may be more red days in sequence.
Reserve dry powder for the second red day, which is often better than the first.

The 15% minimum cash reserve is never breached regardless of red day level.

---

## Red Day Journal Entry (required)

After any red day trade, write a journal entry for that ticker:

```
Type: entry (or observation if no trade)
Date: [date]
Sentiment: [based on thesis check]
Text:
  Red day entry. Market down [X]% on [macro cause].
  Verified: stock moved with sector, no company news, thesis intact.
  Journal score at entry: [N]/10.
  Entry $[price], stop $[price], target $[price].
  Dry powder deployed: $[amount] of $[reserve].
```

---

## Post-Red-Day Review (next cycle)

The cycle after a red day trade must include:

1. Was the selloff cause correctly identified as macro? If wrong, note in journal.
2. Has the stock recovered relative to the sector? (confirms macro interpretation)
3. Is the thesis still intact? Write a journal observation entry.
4. If stock continued lower: is it now in a deeper tier stop zone? Check stops.

This review is part of the agent's standard cycle responsibilities when red day
trades were placed the prior session.

---

## What the Cash Reserve Represents

The 15% minimum cash reserve is not laziness or missed opportunity.
It is the weapon that makes red day entries possible.

A fully-deployed portfolio cannot buy anything when the market falls 2%.
The investor who holds 15% cash and has written journal hypotheses for 10 tickers
is the one who buys PLTR at $118 while everyone else panic-sells.

If you find yourself fully deployed with no cash during a red day: write a journal
alert noting which positions you would trim to create buying power, and execute those
trims before the next opportunity. Do not force red day entries by breaching cash rules.