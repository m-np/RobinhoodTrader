# Thesis Journal Skill

## Purpose

The thesis journal is the agent's memory. Every ticker the agent watches or trades
has a journal inside data/trader.db. The journal is the only place thesis reasoning
is stored. The agent is fully self-contained — no external research tool required.

The agent reads the journal before every trade. The agent writes to the journal
after every observation, trade entry, position update, and trade exit. Without a
journal entry: no trade.

---

## Journal entry types

Every entry has a type that controls how the agent interprets it:

| Type | When written | What it captures |
|---|---|---|
| hypothesis | When ticker first added to watchlist | Original thesis — why this company, what the bet is |
| observation | During monitoring cycles | Price action, news, sector moves, thesis check |
| entry | When a position is opened | Entry price, size, signals that fired, full rationale |
| update | Mid-hold monitoring | Thesis still intact? Anything changed? |
| exit | When position closed | Exit price, P&L, thesis outcome, what you learned |
| alert | Non-trade observations worth flagging | Upcoming earnings, entry zone forming, risk flag |

Sentiment field (on observation, update, and exit entries):
- `strengthening` — new evidence confirms the thesis is playing out
- `neutral` — no new evidence either way, thesis unchanged
- `challenged` — new evidence raises questions, thesis may be wrong
- `broken` — evidence directly contradicts the thesis

---

## Thesis score

The thesis score (0–10) is computed from the last 5 entries with sentiment fields:
- strengthening = 2 points each
- neutral = 1 point each
- challenged = 0 points
- broken = 0 points (and triggers an exit check)

Score drives conviction sizing in aggressive_growth.md.

---

## Journal rules

### Before any trade
1. Call `read_journal(ticker)` — retrieve all entries for this ticker
2. If no hypothesis entry exists: BLOCK trade.
   Write an alert: "No hypothesis for [ticker]. Add thesis before trading."
3. Read the most recent sentiment entry. If broken: BLOCK new entry, trigger exit check.
4. If challenged: BLOCK new entry. Write alert for human review.
5. Compute thesis score from last 5 sentiment entries.
6. Pass thesis score into conviction scoring (aggressive_growth.md).

### After every monitoring cycle observation
Write an observation entry for every open position:
```
type: observation
sentiment: [strengthening | neutral | challenged | broken]
text: [What happened today relevant to the thesis?
       Is the thesis intact? What specifically changed or confirmed?
       What is the next event to watch for?]
```

### After opening a position
Write an entry entry immediately:
```
type: entry
text: Entry at $[price]. Size: $[amount] ([pct]% of portfolio).
      Tier: [core|growth|moonshot]. Signals fired: [list].
      Stop loss: $[price] (-[pct]%). Target: $[price] (+[pct]%).
      Thesis at entry: [one sentence summary of why right now].
```

### After closing a position
Write an exit entry:
```
type: exit
sentiment: [strengthening if thesis played out | neutral | broken if thesis failed]
text: Exit at $[price]. P&L: [+/-pct]%. Held [N] days.
      Exit reason: [stop loss | profit target | thesis break | rebalance]
      
      Did the original thesis play out?
      [yes — specific confirmation / partially — what worked, what didn't / no — what went wrong]
      
      What would I do differently?
      [specific answer, not 'nothing']
      
      Lesson for next similar setup:
      [one concrete rule or observation]
```

### What counts as a thesis-breaking event
A thesis break is a company-specific event that directly invalidates the original hypothesis:
- Earnings miss combined with guidance cut
- Key executive departure (CEO, CTO, key inventor)
- Loss of a major contract that was central to the thesis
- Regulatory block on a product that was the thesis catalyst
- Technology failure publicly confirmed

What does NOT count as a thesis break:
- Broad market selloff (macro red day)
- Sector rotation out of the stock's category
- Analyst downgrade without new fundamental information
- Short-term price volatility within normal range for the tier

When in doubt: write a challenged entry, create an alert, do not exit automatically.
Exit only on confirmed broken status.

---

## Minimum hypothesis quality

When writing the first hypothesis entry for a ticker, it must answer all of:

1. What does this company do, specifically?
2. Why does the market currently undervalue this or why is it at a good entry point?
3. What specific event or trend proves the thesis right over the next 6-12 months?
4. What specific event proves the thesis wrong? (the falsifiability condition)
5. What tier is this and why?

If any of these five questions cannot be answered: do not add the ticker to the
watchlist yet. Come back when you can answer all five.

---

## Example hypothesis (illustrative — not a ticker recommendation)

```
Ticker: PLTR
Type: hypothesis
Date: 2026-06-23
Tier: core

What it does: Palantir builds AI-powered decision software (AIP) for US government
and enterprise. AIP is a platform that connects an organization's data to large
language models in a governed, auditable way.

Why now: Stock is at its 52-week low of $118, down 43% from $207 highs. The selloff
is macro — rate sensitivity, growth stock rotation — not company-specific. AIP 
commercial revenue grew 55% last quarter with accelerating deal count.

What proves it right: AIP commercial revenue continues growing above 40% YoY for
the next 2 quarters. Government contract wins (which are publicly disclosed via SEC
filings) continue. Boot camp conversion rate (prospect to customer) holds above 30%.

What proves it wrong: AIP commercial growth decelerates below 20% YoY. A major
government contract is cancelled or not renewed. Executive departure (Alex Karp).

Thesis score at entry: 0 — just started watching. Build to 5+ before trading.
```