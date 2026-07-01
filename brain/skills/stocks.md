# Stock Trading Skill

## Philosophy

Thesis-driven growth investing with a 4–16 week holding horizon. The goal is to buy
structural dislocations — companies with intact long-term theses trading at temporary
discounts due to macro fear, sector rotation, or short-term sentiment — and hold
long enough for the thesis to prove out.

You are not a swing trader chasing momentum. You buy fear on great companies and
hold through the noise. Patience between setups is strategy. A week of doing nothing
while waiting for the right entry is often the highest-value action.

All thesis reasoning lives in the journal (thesis_journal.md). All tier rules live
in aggressive_growth.md. This skill defines signals and exits only.

---

## Pre-Entry Gate — All Must Pass Before Evaluating Signals

If any gate fails: stop, create an alert explaining which gate blocked the trade.
Do not evaluate signals until all gates pass.

- [ ] Ticker has a journal hypothesis entry with all five hypothesis questions answered
      → call `read_journal(ticker)` and verify a hypothesis entry exists
- [ ] Journal latest sentiment is NOT broken and NOT challenged
      → check `journal_status[ticker].latest_sentiment` in context
- [ ] Minimum journal entries for tier: Core 3, Growth 3, Moon Shot 4
      → check `journal_status[ticker].entry_count` in context
- [ ] No earnings announcement within 7 calendar days
      → check `earnings_alerts` in context for this ticker
- [ ] No binary event (FDA, regulatory ruling, major launch) within 14 days
      → visible in earnings_alerts or documented in recent journal entries
- [ ] Sector cap check: new position does not breach sector limit (aggressive_growth.md)
      → compute from portfolio holdings
- [ ] Cash reserve: portfolio stays above 15% cash after this position
      → check portfolio.cash / portfolio.total_value
- [ ] Market conditions: not in confirmed broad downtrend (see Market Conditions below)

---

## Entry Signals — Require 1 of 5

### Signal 1 — Sector alignment
Stock is participating in a broad sector upswing — the company and its sector are moving
together in a positive direction, and the broader market trend is intact.

- Stock change_pct is positive today (from watchlist_quotes)
- Relevant sector ETF is also positive today: SOXX for semis, XLK for broad tech
  (from market_snapshot.soxx_change_pct / xlk_change_pct)
- S&P 500 is above its 50-day moving average (market_snapshot.sp500_above_50ma = true)
- Journal sentiment is neutral or strengthening (journal_status)

### Signal 2 — Intraday dip on macro selling
Stock has pulled back today in line with broad market pressure, not due to company
news, and the thesis is still intact — a classic macro dip on a fundamentally strong company.

- Stock change_pct is negative today, down 2–8%
- S&P 500 is also down today and the stock's decline is proportional
  (stock decline ≤ 1.5× S&P 500 decline — if S&P is down 1%, stock is down ≤ 1.5%)
- Journal sentiment is neutral or strengthening — thesis has not been challenged
- Red day level is 0 or 1 in context (level 2+ triggers Red Day Protocol instead)

### Signal 3 — Journal conviction quality
The thesis has been actively tracked and the sentiment history shows consistent
strengthening. This is a quality filter, not a technical signal.

- Thesis score is 6 or above (journal_status.thesis_score)
- Journal entry count meets tier minimum: Core 3+, Growth 3+, Moon Shot 4+
- Most recent journal sentiment is strengthening (not just neutral)
- No earnings within 14 days (earnings_alerts in context)

### Signal 4 — Catalyst or thesis confirmation
A specific thesis event has occurred or been confirmed since the last observation.
Read the journal before evaluating this signal.

- Call `read_journal(ticker)` — the most recent entries must show a named catalyst:
  earnings beat with raised guidance, product milestone, major contract, policy support,
  or sector capex announcement that directly supports the hypothesis
- Journal latest_sentiment is strengthening (confirms the new information is positive)
- The catalyst is company-specific and thesis-relevant — not just sector rotation

### Signal 5 — Stock-specific dip on a flat or up market
Stock is declining today while the broader market is flat or rising, suggesting
sector rotation or transient selling pressure rather than a broken thesis.

- Stock change_pct is down 3–8% today
- S&P 500 change_pct is flat (within ±0.5%) or positive today
- S&P 500 above 50-day MA (broader trend still intact)
- Journal sentiment is neutral or strengthening — thesis intact through the dip
- After evaluating: write a journal observation confirming whether dip appears
  to be rotation (proceed) or early thesis damage (do not enter)

---

## Red Day Protocol Override

When red_day_level in context is 2 or higher (S&P 500 down 1.5%+):
- Core tier: signal requirement drops to 1 of 5 — the macro dip is itself the entry signal
- Growth tier: still require 2 of 5, but Signal 2 (intraday dip) counts double
- Moon Shot tier: red day is NOT a standalone trigger — still require full criteria

Full red day decision tree lives in red_day_protocol.md.

---

## Exit Criteria

### Immediate exit — same cycle, do not wait
- Position hits tier stop loss: Core -8%, Growth -15%, Moon Shot -25%
  → check portfolio holdings for unrealized pnl_pct
- Journal sentiment changes to broken (any source: news, earnings, SEC filing)
  → call `read_journal(ticker)` to confirm, then write an exit entry
- Original thesis is broken: earnings miss AND guidance cut, key executive departure,
  product failure, regulatory block — any event that voids the original hypothesis
- Do not hold. Do not hope. Do not average down. Exit and write the exit journal entry.

### Profit-taking exit (by tier)
- Core: take 50% off at +40%, move stop to breakeven, full exit at +60%
- Growth: take 40% off at +50%, full exit at +80%
- Moon Shot: take 30% off at +60%, take 30% more at +100%, let 40% ride to thesis resolution
→ Check pnl_pct for each position in portfolio holdings each cycle

### Deterioration exit — not yet stop, but trend reversing
- Stock is down more than 5% today while the sector ETF (SOXX/XLK) is flat or positive
  — stock dramatically underperforming its sector without a macro explanation
- Broader market shifts to red_day_level 4 (sp500_above_50ma = false AND VIX above 35)
  AND the position is in a cyclical sector AND journal sentiment is challenged
- A materially better opportunity exists and capital is tied up in a stalled position
  (document both the stalled thesis and the better opportunity before switching)

### Minimum hold rule
Do not exit a position within 21 days of entry for any reason except stop loss or
confirmed thesis break. Growth investing requires time. The thesis was written for
months, not days. Cutting at 2 weeks on noise is the most common retail mistake.

---

## Position Sizing

See aggressive_growth.md for the full conviction scoring formula.
Summary: compute conviction score (0–10), map to tier-specific size range.
Open at score-based size. Add to the position only after 5%+ gain with trend intact.
Never open at maximum size immediately.

---

## Stock and Sector Filters

### Prefer
- Tickers with a complete journal hypothesis (all five questions answered)
- Companies in sectors with identified macro tailwinds in recent journal observations
- High institutional ownership trending upward (visible via yfinance fundamentals if needed)

### Avoid
- Stocks under $5 — manipulation risk, wide spreads, low liquidity
- Stocks with earnings within 7 days — pre-entry gate blocks this anyway
- Short interest above 30% of float unless the journal includes a specific squeeze thesis
  supported independently by fundamental analysis
- Any ticker with no journal hypothesis

---

## Market Conditions Override

Do NOT open new positions if ALL three are simultaneously true:
- market_snapshot.sp500_above_50ma = false
- market_snapshot.vix is above 35
- Portfolio unrealized loss exceeds 15% of total value

In this scenario: hold existing positions (unless stops trigger), hold cash,
write an alert explaining conditions. Do not add exposure into a confirmed downtrend.

### VIX interpretation for aggressive growth style
- VIX 15–20: normal market — trade freely per signals
- VIX 20–30: elevated — reduce Moon Shot entries, Core and Growth acceptable
- VIX 30–35: high fear — Moon Shots off, Core entries only on confirmed red days
- VIX 35+: extreme fear — no new positions; write journal observations for all holdings
- VIX above 40: historically a generational entry for Core — deploy up to 20% of
  cash reserve into highest journal-score Core tickers only

VIX above 30 is NOT an exit signal for existing positions.
It is a signal to stop opening new positions while waiting for stabilization.
Existing positions with intact journal thesis: hold.

---

## Watchlist Usage

Your watchlist is the set of tickers with journal hypotheses written.
Every cycle: evaluate each watchlist ticker. State clearly why you are acting or not.
Write a journal observation entry for every ticker you actively evaluated.

If a ticker has been on the watchlist for 5+ cycles with no setup materializing:
- Write an observation entry: what catalyst is still needed?
- Do not remove from watchlist — thesis may still be valid
- Consider: is capital better deployed elsewhere while waiting?
