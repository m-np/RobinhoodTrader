# Aggressive Growth Skill

## Philosophy

Aggressive-disciplined growth investing targets structural dislocations in
high-conviction sectors. The edge is buying the right company at the wrong price
— a price depressed by fear, macro noise, or temporary rotation — and holding long
enough for the thesis to prove out.

Every ticker requires a journal hypothesis written before any capital is deployed.
The hypothesis is the prerequisite. The signal is the trigger. Hypothesis lives in
thesis_journal.md. Signals live in stocks.md. This skill defines how tickers are
classified and sized.

---

## Tier Classification Criteria

Tickers are never hardcoded. Any ticker can be any tier. The agent classifies each
ticker by evaluating it against the criteria below, using fundamentals from yfinance.
Classification is recorded as a journal entry and re-evaluated whenever fundamentals
materially change.

### Core Tier — Structural dominance with proven revenue

Qualifies when ALL of the following are true:

Business quality:
- Market cap above $10 billion
- Revenue is positive and growing above 15% year-over-year, OR the company has a
  structural moat so durable that premium valuation is justified independent of
  current growth rate (the only manufacturer of a critical component; a platform with
  switching costs so high that customers cannot realistically leave; a government-
  contract monopoly with multi-year visibility)
- Has been public for at least 2 years with audited financials

Thesis quality (agent must assert in journal):
- A credible 3-year thesis exists that does not depend on a single binary event
- A 30% drawdown in the stock would not change that thesis
- The journal hypothesis answers all five required questions

Position rules:
- Maximum single position: 25% of portfolio
- Stop loss: 8% from entry — no exceptions
- Minimum hold before exiting for non-thesis reasons: 30 days
- Partial exit at +40%, full exit at +60%

What this tier looks like in practice (illustrative, not a list):
A company that makes the only chip capable of performing a critical AI workload at
scale. The world's dominant foundry that every leading chip designer depends on.
A software platform whose installed base of trained operators creates a moat no
competitor can cross quickly. The common thread: structural advantage that compounds
over years, not quarters.

---

### Growth Tier — Real business with meaningful execution risk

Qualifies when ALL of the following are true:

Business quality:
- Market cap above $2 billion
- Revenue is positive OR the company has a specific, dated path to revenue with
  evidence: signed LOIs, pilot customers, regulatory approval pending
- Has been public for at least 1 year

Thesis quality (agent must assert in journal):
- A specific catalyst is named: a product, a regulation, a technology adoption curve
- A 20% drawdown would not change the thesis
- Execution risk is meaningful but not purely binary

Position rules:
- Maximum single position: 15% of portfolio
- Stop loss: 15% from entry
- Minimum hold: 21 days
- Partial exit at +50%, full exit at +80%

What this tier looks like in practice:
A power utility that has signed AI data center contracts but buildout timeline has
uncertainty. A robotics vision chip maker whose market is real but adoption is 2–3
years from scale. A consumer brand taking shelf space from incumbents but distribution
is still expanding. Real product, real market, meaningful pace uncertainty.

---

### Moon Shot Tier — Asymmetric binary bets

Qualifies when ALL of the following are true:

Business quality:
- Any market cap
- Revenue may be zero — the company exists to solve a problem that, if solved,
  creates a very large market
- Technology or product is demonstrably real — hardware exists, launches have
  occurred, or peer-reviewed evidence supports viability. Not a whitepaper.

Thesis quality (agent must write in journal before first trade):
- Binary thesis written explicitly: "if X works, outcome is Y; if X fails, outcome is Z"
- Exit condition written: "I will exit if [specific falsifiable event] occurs"
- Timeline written: "the binary event resolves within [N] months"

Position rules:
- Maximum single position: 5% of portfolio
- Maximum total Moon Shot allocation: 15% across all Moon Shot positions
- Stop loss: 25% from entry — wide because these are volatile and earnings-free
- Minimum journal entries before first trade: 2 (more research precisely because
  fundamentals are thinnest)
- Partial exit at +60%, additional exit at +100%, let remaining 40% ride
- If down 40%+: exit fully unless a specific named catalyst is imminent

What this tier looks like in practice:
A quantum computing company with real hardware but no commercial revenue yet — the
bet is on quantum advantage arriving within a defined window. A space launch company
that has proven its technology but whose revenue does not yet justify its valuation.
A satellite broadband company whose technology works but whose commercial success
depends on carrier partnerships. Technology is real, market is real, timeline is
genuinely uncertain.

---

## How the Agent Classifies a New Ticker

When a ticker first appears on the watchlist, before any trade:

Step 1 — Fetch fundamentals via yfinance:
- Market cap, revenue TTM, revenue growth YoY, PE ratio, years since IPO

Step 2 — Evaluate Core criteria:
- Market cap > $10B? Revenue growing > 15% YoY or structural moat present?
- Public 2+ years? 3-year thesis articulable? 30% drawdown survivable?
- If ALL yes → Core

Step 3 — If not Core, evaluate Growth:
- Market cap > $2B? Revenue positive or dated path? Specific catalyst named?
- Public 1+ year? 20% drawdown survivable?
- If ALL yes → Growth

Step 4 — If not Growth, evaluate Moon Shot:
- Technology demonstrably real? Binary thesis written? Exit condition written?
- If ALL yes → Moon Shot

Step 5 — If none qualify:
- Create alert: "[Ticker] does not meet minimum criteria for any tier. Reason: [specific gap].
  Do not trade until criteria are met and journal hypothesis is complete."

Step 6 — Record classification as a journal entry (type: hypothesis, include tier and rationale)

Re-classify when: market cap crosses a tier threshold, revenue turns positive,
a binary event resolves, or journal shows a fundamental business model change.

---

## Conviction Scoring System

Compute this score before every trade. Score determines position size within the tier range.

| Component | Points |
|---|---|
| Journal entries with sentiment (1pt each, max 3) | 0–3 |
| Latest journal sentiment: strengthening=2, neutral=1, challenged=0 | 0–2 |
| Red day entry: broad market macro dip, not company news | 0–1 |
| Relative strength: stock change_pct ≥ sector ETF change_pct today | 0–1 |
| Entry signal categories fired (1pt each, max 2) | 0–2 |
| Journal depth: thesis_score ≥ 7 with 5+ sentiment entries on record | 0–1 |

Maximum: 10

### Score-to-size mapping

| Score | Core size | Growth size | Moon Shot size |
|---|---|---|---|
| 3–4 | 8% | 5% | 2% |
| 5–6 | 15% | 10% | 3% |
| 7–8 | 20% | 13% | 4% |
| 9–10 | 25% | 15% | 5% |

Open at score-based size. Add the remainder only after 5%+ gain with trend confirmed.
Never go to maximum size immediately on a new entry.

---

## Sector Concentration Caps

Check before every buy. If the new position breaches a cap: do not trade, create alert.

| Sector | Cap |
|---|---|
| AI infrastructure (chips, interconnect, data center hardware) | 35% |
| Memory and storage | 20% |
| Power and data center utilities | 20% |
| Physical AI, robotics, autonomous systems | 15% |
| Healthcare and biotech AI | 15% |
| Fintech and financial services | 15% |
| Space and specialty telecom | 10% |
| Consumer brands and non-durables | 15% |
| Total Moon Shot allocation (all tiers combined) | 15% |

Sector assignment is determined by primary revenue source, not by marketing language.

---

## Adding to Winning Positions

Only add after ALL are true:
- Position is 5%+ above your entry price (check pnl_pct in portfolio holdings)
- Stock is NOT declining today relative to its sector — stock change_pct ≥ sector ETF change_pct
  (not adding into an intraday reversal)
- Latest journal sentiment is neutral or strengthening
- Adding does not breach tier maximum
- You are not chasing: stock has not gapped up 5%+ today without a thesis event

Add size: no more than 50% of the original position in the add.
After adding, the new average cost becomes the new stop loss anchor.