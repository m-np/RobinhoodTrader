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
- [ ] Journal latest sentiment is NOT broken and NOT challenged
- [ ] Minimum journal entries for tier: Core 1, Growth 1, Moon Shot 2
- [ ] No earnings announcement within 7 calendar days (catalyst_calendar.md)
- [ ] No binary event (FDA, regulatory ruling, major launch) within 14 days
- [ ] Sector cap check: new position does not breach sector limit (aggressive_growth.md)
- [ ] Cash reserve: portfolio stays above 15% cash after this position
- [ ] Market conditions: not in confirmed broad downtrend (see Market Conditions below)

---

## Entry Signals — Require 2 of 5 (1 of 5 for Core on a red day)

### Signal 1 — Trend
- Price is above its 20-day moving average AND the MA is sloping upward
- Stock is making higher highs and higher lows over the last 10 sessions
- Relevant sector ETF (SOXX, XLK, XBI) is in uptrend

### Signal 2 — Momentum and oversold
RSI (14-period) thresholds vary by tier — lower tiers need deeper oversold to compensate
for higher fundamental risk:
- Core: RSI 30–60 (buy oversold dips on structurally dominant companies)
- Growth: RSI 35–60 (moderate oversold)
- Moon Shot: RSI 25–50 (deep oversold only — binary bets need a clear fear discount)
- Price is down 5–15% from a recent high on LOW volume (no institutional selling)
- Stock has held a key support level: prior resistance now support, MA confluence

### Signal 3 — Volume confirmation
- Current session volume is 20%+ above the 30-day average
- Volume expanded on recent up days, contracted on down days (healthy accumulation)
- Unusual volume on an up day without news — potential dark pool accumulation

### Signal 4 — Catalyst or thesis confirmation
- Journal shows strengthening sentiment in the last 3 entries
- Earnings beat with raised guidance within the last 10 sessions
- Analyst upgrade or meaningful price target increase
- Sector tailwind confirmed: major capex announcement, policy support, technology milestone
- Insider buying filed via SEC Form 4 in the last 30 days

### Signal 5 — Pullback setup
- Stock pulled back 8–20% from a recent high on below-average volume
- Pullback is into a known support zone
- Broader market trend is still intact: S&P 500 above 50-day MA
- This is a dip within an uptrend — not a breakdown or a downtrend continuation

---

## Red Day Protocol Override

When the broad market is down 1.5%+ today on MACRO news (not company news):
- Core tier: signal requirement drops to 1 of 5 — the macro dip is itself the entry signal
- Growth tier: still require 2 of 5, but Signal 2 (oversold) counts double
- Moon Shot tier: red day is NOT a standalone trigger — still require full criteria

Full red day decision tree lives in red_day_protocol.md.

---

## Exit Criteria

### Immediate exit — same cycle, do not wait
- Position hits tier stop loss: Core -8%, Growth -15%, Moon Shot -25%
- Journal sentiment changes to broken (any source: news, earnings, SEC filing)
- Original thesis is broken: earnings miss AND guidance cut, key executive departure,
  product failure, regulatory block — any event that voids the original hypothesis
- Do not hold. Do not hope. Do not average down. Exit and write the exit journal entry.

### Profit-taking exit (by tier)
- Core: take 50% off at +40%, move stop to breakeven, full exit at +60%
- Growth: take 40% off at +50%, full exit at +80%
- Moon Shot: take 30% off at +60%, take 30% more at +100%, let 40% ride to thesis resolution

### Deterioration exit — not yet stop, but trend reversing
- Price crosses below the 20-day MA on above-average volume
- Broader market shifts to confirmed downtrend AND the position is in a cyclical sector
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
- High institutional ownership trending upward (from yfinance fundamentals)
- Insider ownership above 5% — aligned incentives

### Avoid
- Stocks under $5 — manipulation risk, wide spreads, low liquidity
- Stocks with earnings within 7 days — pre-entry gate blocks this anyway
- Short interest above 30% of float unless the journal includes a specific squeeze thesis
  supported independently by fundamental analysis
- Any ticker with no journal hypothesis

---

## Market Conditions Override

Do NOT open new positions if ALL three are simultaneously true:
- S&P 500 is below its 50-day MA AND falling
- VIX is above 35
- Portfolio unrealized loss exceeds 15% of total value

In this scenario: hold existing positions (unless stops trigger), hold cash,
write an alert explaining conditions. Do not add exposure into a confirmed downtrend.

### VIX interpretation for aggressive growth style
- VIX 15–20: normal market — trade freely per signals
- VIX 20–30: elevated — reduce Moon Shot entries, Core and Growth acceptable
- VIX 30–35: high fear — Moon Shots off, Core entries only on confirmed red days
- VIX 35+: extreme fear — no new positions; update journal observations for all holdings
- VIX above 40: historically a generational entry for Core — deploy up to 20% of
  cash reserve into highest journal-score Core tickers only

VIX above 30 is NOT an exit signal for existing positions.
It is a signal to stop opening new positions while waiting for stabilization.
Existing positions with intact journal thesis: hold.

---

## Watchlist Usage

Your watchlist is the set of tickers with journal hypotheses written.
Every cycle: evaluate each watchlist ticker. State clearly why you are acting or not.

If a ticker has been on the watchlist for 5+ cycles with no setup materializing:
- Write an observation entry: what catalyst is still needed?
- Do not remove from watchlist — thesis may still be valid
- Consider: is capital better deployed elsewhere while waiting?