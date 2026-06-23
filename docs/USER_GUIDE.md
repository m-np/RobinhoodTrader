# User Guide — Agentic Trader

This guide is for people who want to understand the **experience** of using the Agentic Trader — not how to install it, but how to think about it, how to use it day-to-day, and how to get the most out of it. If you're looking for setup instructions, start with the [README](../README.md).

---

## The core idea

Most trading bots are reactive. They watch a price, wait for a condition, and execute. They have no opinion about the underlying business — they just follow rules.

This agent is different. It requires you to have an **opinion first**, written in plain English, before it will act. The thesis journal is its memory. If you haven't written a hypothesis for a ticker, the agent won't touch it — even if every technical signal is firing.

This forces a habit that most discretionary investors skip: writing down what you believe and why, and keeping that belief current as new information arrives. The agent then takes that thesis and handles the mechanics — timing entries, sizing positions based on conviction, watching for exits, and managing the portfolio while you're not looking.

---

## The mental model: three layers

Think of the system as three nested layers of control:

```
Watchlist  →  what the agent can see
Journal    →  what the agent is allowed to buy, and how big
Agent      →  when to buy, how much, and when to exit
```

**Watchlist** is a simple list of tickers. The agent only has visibility into tickers on this list — live price, daily change, earnings calendar. Everything else is invisible.

**Journal** is where you decide which of those watchlist tickers the agent is actually allowed to trade. Write a hypothesis → the ticker is unlocked. Mark the thesis broken → it's locked again immediately. The journal also controls position size: the more entries you've written (with strengthening sentiment), the larger the position the agent can take.

**Agent** is the autonomous layer. Every 15 minutes it checks the portfolio, reads the journal, looks at market conditions, and decides whether to act. It handles timing and execution. You handle the thesis. When those two things are in sync, the system works very well.

---

## The thesis journal in practice

### What a good hypothesis looks like

A hypothesis isn't a price target or a trade setup. It's a statement about **why the business creates durable value**, written in a way that can be proven true or false over time.

Bad hypothesis:
> "NVDA looks good technically, RSI oversold, buying the dip"

This is a trade setup, not a thesis. The agent can observe price action itself. What it can't do is reason about business fundamentals.

Good hypothesis:
> "NVDA's Blackwell GPU architecture is the only platform that can efficiently train large foundation models at scale. Sovereign AI programs (UAE, Japan, Saudi Arabia) are creating demand that's structurally separate from US hyperscaler capex cycles. The moat is the ecosystem: CUDA, NIM, and the developer toolchain make switching costs extremely high for anyone who has already trained on NVIDIA hardware."

This tells the agent:
- Why the business is valuable (moat, switching costs)
- What the thesis is predicated on (sovereign AI demand, Blackwell cycle)
- What would break the thesis (a competitive CUDA alternative, sovereign capex cuts)

When you write observations and updates later, you're tracking whether these specific things are playing out.

### The sentiment → conviction → size chain

Every time you write a journal entry with a sentiment value, you're voting on the thesis:

```
Strengthening →  thesis is playing out better than expected
Neutral       →  thesis intact, no new information
Challenged    →  something has changed that tests a key assumption
Broken        →  the core thesis assumption has been proven wrong
```

The agent reads your last 5 sentiment votes and computes a thesis score (0–10). Combined with live market signals (volume, red day, technical patterns), it produces a conviction score that directly determines how much capital it deploys:

| Your entries (all strengthening) | Max conviction | Core position (on $100k) |
|---|---|---|
| 1 entry | ~4/10 | $8,000 |
| 2 entries | ~5/10 | $15,000 |
| 3+ entries | ~7–10/10 | $20,000–$25,000 |

So if you add your initial hypothesis and then never write another entry, the agent will only ever take a small position in that ticker — even if it's your highest-conviction idea. The journal rewards active tracking.

### What to write and when

**After initial research (Day 1):**
Write the hypothesis. Set the tier (`core`, `growth`, or `moonshot`). This is the most important entry — it unlocks the ticker and defines how the agent sizes positions.

**After earnings:**
Write an observation with updated sentiment. Did the quarter validate the thesis or challenge it? This is the most common journal update.

**When macro changes:**
Write an update. Interest rate environment changed, sector rotation underway, geopolitical risk emerged — these are worth capturing even if your core thesis is unchanged, because they affect the sentiment signal.

**When the thesis is under pressure:**
Write an update with `challenged` sentiment. This immediately blocks new buys. You're saying "I'm not ready to abandon this, but I want to pause before adding more." When you regain confidence, write another update with `strengthening` or `neutral` to re-enable.

**When the thesis breaks:**
Write an update with `broken`. The agent will immediately stop buying and — if the stop-loss gate is off — will start looking for an exit. This is the fastest control lever you have.

### Tier selection

| Tier | Who it's for | Max single position | Journal minimum |
|---|---|---|---|
| `core` | Durable businesses with wide moats, proven models | 25% of portfolio | 2 entries |
| `growth` | High-growth companies where the thesis is still being proven | 13% of portfolio | 2 entries |
| `moonshot` | Binary outcomes — transformational potential, high failure risk | 5% of portfolio | 1 entry |

Set the tier on the hypothesis entry. The agent will never put more than the tier cap into a single ticker regardless of how high conviction gets.

---

## The dashboard day-to-day

### What you'll actually look at

**Dashboard (/)** — your daily check-in. The key things to watch:
- Wallet balance — if this hits zero, the agent stops. Fund the agentic account to resume.
- Today's P&L — how is the portfolio performing today
- Pending decisions — if any trades need your approval, they're here as cards
- Recent alerts — market waves, earnings alerts, system notices

**Journal (/journal)** — your weekly check-in. Review:
- Are any tickers with `challenged` sentiment resolved? Update them.
- Have any tickers moved significantly? Worth adding an observation.
- Are there tickers with only 1 entry? If they're high-conviction, add 2 more to unlock larger positions.

**Watchlist (/watchlist)** — live prices. This is mostly informational during the day. The agent is already watching these prices every 5 minutes.

**Reports (/reports)** — read after close. Claude's daily summary explains what it did and why. This is the best place to understand whether the agent's reasoning matches yours. If it's making moves that don't make sense given your thesis, check the journal entries — the agent may be reading a different sentiment than you intended.

### Pending decisions — approve or reject

When a trade needs your approval, a card appears on the Dashboard showing:
- Whether it's a buy or sell (green / red)
- Ticker and timestamp
- Exact quantity, price, and total dollar value
- The agent's rationale for the trade

**Approve** → the trade executes immediately via Robinhood MCP.
**Reject** → the trade is cancelled.
**No response for 10 minutes** → auto-cancelled.

You don't need to hover over the dashboard. If SMS notifications are configured, you'll get a text message when a decision is waiting. Tap a link to open the dashboard and decide.

---

## Tuning for your style

Every gate is a toggle in **Settings**. All changes take effect on the next agent cycle — no restart needed.

### The six approval gates

| Gate | What triggers it | Default |
|---|---|---|
| New position opens | Agent buys a ticker not currently held | ON |
| Full position exits | Agent sells 95%+ of a holding | ON |
| Rebalance / partial trim | Agent sells a partial position (not a full exit) | OFF |
| Stop-loss sells | Agent sells a position that is currently at a loss | OFF |
| Approval threshold | Any single trade above this dollar value | $500 |
| Approval timeout | Cancel the pending trade if no response within this time | 10 min |

The agent also labels every trade with a **trade type** (`new_position`, `scale_in`, `rebalance`, `stop_loss`, `profit_take`, `full_exit`) so the gates can fire precisely. You can see the trade type in the rationale on each pending decision card.

### High-touch (good for the first month)
You review every entry and exit decision manually.

```
gate_new_positions  →  ON
gate_full_exits     →  ON
gate_rebalance      →  ON
gate_stop_loss      →  ON
approval_threshold  →  $500
```

### Balanced (recommended after the first month)
New positions and scale-ins execute automatically — the journal already vetted them. You still confirm full liquidations and large trades.

```
gate_new_positions  →  OFF   (journal gates the entry; agent times it)
gate_full_exits     →  ON    (always confirm full liquidations)
gate_rebalance      →  OFF   (let agent trim freely)
gate_stop_loss      →  OFF   (let agent protect downside automatically)
approval_threshold  →  $2000 (routine buys auto-execute; outliers still ask)
```

### High-autonomy
The agent acts fully within its hard limits. You only get notified about outlier trades.

```
gate_new_positions  →  OFF
gate_full_exits     →  OFF
gate_rebalance      →  OFF
gate_stop_loss      →  OFF
approval_threshold  →  $5000
```

### Hard stops that always apply regardless of gate settings
- Portfolio down more than 3% today → all trading halts for the rest of the session
- No single ticker can exceed 20% of the portfolio
- Maximum 5 trades executed per calendar day
- No buys within 7 days of a ticker's earnings date — automatic, no setting needed

---

## Working with mirrors

Mirrors let the agent shadow trades from public figures (congressional members via Capitol Trades) or institutions (13F filings via SEC EDGAR).

### Setup
1. Go to **Mirrors** → enable a source (e.g. "Nancy Pelosi")
2. Set an allocation percentage (e.g. 3% of portfolio)
3. When a new disclosure appears, an alert card appears on the dashboard

### How sizing works
The allocation percentage determines the exact dollar size of every mirror trade, not a total budget across all trades from that source:

```
Mirror position size = portfolio_value × scale_factor
e.g. $100,000 portfolio × 3% = $3,000 per disclosed trade
```

### The journal and mirrors — an important distinction

Mirror trades **do not require a journal entry** and **do not check thesis sentiment**. The mirror's signal is the disclosure itself — you're shadowing a position someone else has already taken. The journal is your opinion layer; mirrors are an external signal layer.

However, mirrors **do respect your blocklist** and **do run through four hard guardrails** before executing:

| Check | What it does |
|---|---|
| Blocklist | If the ticker is on your Don't Buy list, the mirror is silently skipped |
| Daily loss halt | If the portfolio is already down 3%+ today, no mirror trades execute |
| Daily trade cap | Mirrors count toward your 5-trades-per-day limit |
| Position size cap | Mirror position cannot breach your max position % per ticker |

If a mirror disclosure is for a ticker you also have in your journal with `broken` sentiment, the mirror will still execute (the journal gate only applies to the main agent cycle). Add that ticker to your **Blocklist** if you want to prevent mirror trades on it entirely.

### Manual approval vs auto-execute

By default, every mirror disclosure creates an **alert card on the dashboard** — you read it and decide whether to approve. This is the recommended mode: you see what was disclosed, decide if it fits your view, and approve or reject.

If you turn on **Settings → Mirror trading → Auto-execute mirror trades**, disclosures are queued immediately and executed within 30 seconds — still subject to the four guardrails above, but without a dashboard approval step. Only enable this once you trust the source and your hard limits are correctly set.

---

## Understanding reports

Reports are generated by Claude at 4:05 PM ET. They contain:
- Portfolio performance (total return, today's P&L)
- Trades executed during the period with rationale
- Holdings summary
- Commentary on the portfolio's overall health

The rationale section is the most useful part. It shows you how Claude is interpreting the journal entries you've written. If it mentions a thesis assumption you didn't intend to highlight, update the journal to be more specific. The agent's reasoning is only as good as what you've written.

Reports are stored in the database and always accessible at `/reports`. They can be delivered by email, SMS, or both.

---

## Frequently asked questions

**The agent is not trading even though I have watchlist tickers. Why?**

Check the journal: every ticker that the agent should buy needs a hypothesis entry with sentiment `strengthening` or `neutral`. Go to `/journal` and look at the status table. Tickers with no entries show up with score 0 — the agent won't touch them.

**Can I add more than one hypothesis for the same ticker?**

Yes, but you don't need to. The hypothesis sets the tier — if you want to change the tier, add a new hypothesis entry with the updated tier. The most recent hypothesis wins. You're more likely to want `observation` and `update` entries rather than multiple hypotheses.

**What happens if I remove a ticker from the watchlist but it still has journal entries?**

The agent won't see the ticker anymore (it only fetches journal data for watchlist tickers). The journal entries remain in the database. If you re-add the ticker to the watchlist, the journal history comes back.

**Can the agent write to the journal on its own?**

Not currently. The journal is intentionally human-authored — it represents your reasoning, not the agent's. The agent reads and acts on it but does not write to it. This keeps the thesis layer under your full control.

**How do I know if the agent is working?**

Check the Reports page for the most recent daily summary. If the agent ran a cycle, you'll see a report. The Dashboard also shows trade history. If the scheduler is running, the agent cycle fires every 15 minutes even if no trades happen.

**The agent bought something I didn't expect. What happened?**

Check the trade's rationale on the Dashboard → Trades. Then check the journal for that ticker — the agent may have acted on a sentiment you set earlier. If the thesis has changed, update the journal immediately. The journal is live — the next cycle will read the updated sentiment.

**How do I pause the agent completely?**

Set `daily_loss_halt_pct` to `0` — this triggers the halt immediately and suspends all trading. Or set `max_trades_per_day` to `0`. To resume, restore the original values in Settings.

**A mirror trade executed on a ticker I don't want to hold. How do I prevent that?**

Add the ticker to your **Blocklist** (Watchlist page → Don't Buy). The blocklist is the master veto for both the main agent and mirror auto-execute. The journal's `broken` sentiment only gates the main agent cycle — it does not affect mirrors.

**The agent sold part of my position without asking. Is that expected?**

Yes, if `gate_rebalance` is OFF (the default). Partial trims — where the agent reduces a position but doesn't fully exit — are considered routine rebalancing and execute automatically. Turn `gate_rebalance` ON in Settings if you want to approve all partial sells.

**Why did the agent ask for approval on a stop-loss sell?**

`gate_stop_loss` is ON in your settings. When the agent wants to sell a position that is currently at a loss, it will ask for your confirmation first. Turn it OFF if you want stop-loss protection to execute automatically without a dashboard step.

---

## Journal quick reference

```bash
# Add initial hypothesis (required before any buy)
python scripts/journal_cli.py add TICKER hypothesis "your thesis" \
  --sentiment strengthening --tier core|growth|moonshot

# Add after earnings / news
python scripts/journal_cli.py add TICKER observation "what happened" \
  --sentiment strengthening|neutral|challenged

# Update conviction
python scripts/journal_cli.py add TICKER update "what changed" \
  --sentiment strengthening|neutral|challenged|broken

# Hard block a ticker immediately
python scripts/journal_cli.py add TICKER update "thesis broken" --sentiment broken

# See all tickers with scores and sentiment
python scripts/journal_cli.py status

# See full history for one ticker
python scripts/journal_cli.py list TICKER
```

Sentiment values:
- `strengthening` — thesis playing out better than expected, agent buys freely
- `neutral` — thesis intact, agent buys at reduced size
- `challenged` — thesis under pressure, agent pauses new buys
- `broken` — thesis failed, agent hard-blocked immediately
