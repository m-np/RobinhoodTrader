# RobinhoodTrader

An AI-powered trading agent that uses [Claude](https://anthropic.com) as its decision-making brain, connected to Robinhood via their official MCP server. Unlike rule-based bots, this agent trades from your **written investment thesis** — it can only act on tickers you've researched, sized by how much evidence you've documented.

> **This is a personal tool.** Your API keys and credentials never leave your machine (or your own cloud deployment). No shared backend, no telemetry, no third-party service beyond the APIs you configure yourself.

> **New here?** Read the [User Guide](docs/USER_GUIDE.md) first — it explains the full experience, day-to-day workflow, and the thesis journal in depth before you touch any config.

---

## What makes this different

Most trading bots react to price signals. This one requires you to **write why you believe in a stock** before it will touch it. The thesis journal is the agent's memory — sentiment you write today gates what it can buy tomorrow. Tickers with strong, growing thesis entries get larger positions. Tickers with broken theses are hard-blocked.

- **Thesis-driven** — the agent cannot buy a ticker without a written hypothesis entry for it
- **Conviction-sized** — the more journal entries you write, the larger the position the agent is allowed to take
- **Your veto** — mark a thesis `broken` and the agent immediately stops buying that ticker, no code change needed
- **Fully autonomous within your rules** — once the journal is healthy, the agent times entries, sizes positions, and manages exits on its own

---

## How it works — the three layers

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1 — WATCHLIST  (what the agent can see)                   │
│                                                                  │
│  Add tickers to your watchlist via the UI. The agent monitors    │
│  live prices, daily moves, and earnings calendars for these      │
│  tickers every cycle. Tickers NOT on the watchlist are invisible │
│  to the agent.                                                   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 2 — THESIS JOURNAL  (what the agent can buy)              │
│                                                                  │
│  For each watchlist ticker, you write a hypothesis: why you      │
│  believe in it, which tier it belongs to (core / growth /        │
│  moonshot), and how your conviction is trending. The agent       │
│  reads this every cycle and uses it to:                          │
│                                                                  │
│    • Gate buys  — no hypothesis = no buy, broken = hard block    │
│    • Size positions — more entries + strengthening = bigger size │
│    • Prioritise — highest conviction tickers get first capital   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 3 — AGENT CYCLE  (timing, sizing, execution)              │
│                                                                  │
│  Every 15 minutes, Claude receives:                              │
│    • Portfolio state (holdings, cash, P&L)                       │
│    • Watchlist prices + daily moves                              │
│    • Journal status per ticker (tier, score, sentiment)          │
│    • Market conditions (S&P change, VIX, red day level)          │
│    • Earnings calendar (blocks buys within 7 days of earnings)   │
│                                                                  │
│  Claude decides whether to buy, sell, or hold. Guardrails        │
│  enforce hard limits. Orders within your threshold execute       │
│  automatically. Large trades or full exits surface as approval   │
│  cards on the dashboard.                                         │
└──────────────────────────────────────────────────────────────────┘
```

---

## Features

**Dashboard**
Live wallet balance, today's P&L, holdings with position bars, pending buy/sell decision cards, last report summary, and a portfolio chart that always extends to the current moment.

**Watchlist**
Add any ticker Claude should monitor. Live prices refresh every 5 seconds. Shows daily change %, a 24h sparkline, and market open/closed status. Prices freeze at close and show "Market closed" until the next session.

**Thesis Journal**
The heart of the system. Write investment hypotheses for your watchlist tickers, track how your conviction evolves over time, and see per-ticker thesis scores that directly drive position sizing. Available via the web UI, a CLI script, or the REST API.

**Mirrors**
Track congressional disclosures (Capitol Trades) and institutional 13F filings (SEC EDGAR). Enable a source in Settings, set a portfolio allocation percentage, and the agent scales into those positions proportionally when filings appear.

**Discover**
Scan and filter tickers by fundamentals, sector, and momentum to find new candidates for your watchlist.

**Reports**
Claude writes plain-English daily and weekly summaries: P&L, trade rationale, and portfolio commentary. Delivered as HTML email or SMS on a schedule you configure.

**Notifications**
Configure email and phone number from the dashboard. Test buttons verify both channels before you go live. SMTP and Twilio credentials stay in `.env`; recipient addresses are stored in the database and can be changed without a restart.

---

## The Thesis Journal

The journal is your investment reasoning layer. The agent reads it every cycle and uses it to decide whether to buy, how much to buy, and which tickers to prioritise.

### Journal entry types

| Type | When to write it |
|---|---|
| `hypothesis` | Your initial thesis — **required before any buy.** Sets the ticker's tier. |
| `observation` | A new data point (earnings beat, product launch, analyst upgrade) |
| `update` | A change in your conviction — the most important entry to keep current |
| `entry` | Narrative note when you or the agent opens a position |
| `exit` | Close note with outcome and lesson learned |
| `alert` | Time-sensitive flag (earnings tomorrow, news breaking) |

### Sentiment controls what the agent can do

| Sentiment | Effect |
|---|---|
| `strengthening` | Full conviction — agent can buy, largest size allowed |
| `neutral` | Reduced conviction — agent can buy, smaller size |
| `challenged` | **Blocked** — pre-trade check prevents new buys |
| `broken` | **Hard blocked** — brain gate rejects at the order level, ignored until you update |

### Thesis score and conviction sizing

The thesis score (0–10) uses the **last 5 entries that carry a sentiment value**:
`strengthening = 2 pts`, `neutral = 1 pt`, `challenged / broken = 0 pts`

Combined with market signals, it produces a conviction score that sets position size:

| Conviction | Core tier | Growth tier | Moonshot tier |
|---|---|---|---|
| 9–10 | 25% of portfolio | 15% | 5% |
| 7–8 | 20% | 13% | 4% |
| 5–6 | 15% | 10% | 3% |
| 3–4 | 8% | 5% | 2% |
| 0–2 | no trade | no trade | no trade |

**You need at least 3 journal entries per ticker to unlock the upper size bands.** A ticker with only a hypothesis entry caps out at conviction 4 regardless of market signals.

### Managing the journal

**Web UI** (`/journal`) — overview table with scores, sentiment, and position badges. Click any ticker to see its full entry history. Add entries via the form at the top.

**CLI** — faster for bulk updates:
```bash
# Add initial hypothesis (required before any buy)
python scripts/journal_cli.py add NVDA hypothesis \
  "Blackwell GPU ramp + sovereign AI demand creates durable moat" \
  --sentiment strengthening --tier core

# Add an observation after earnings
python scripts/journal_cli.py add NVDA observation \
  "Q2 data center beat by 18% — Blackwell demand pull-in confirmed" \
  --sentiment strengthening

# Update when thesis is challenged
python scripts/journal_cli.py add NVDA update \
  "Export restrictions tightening — monitoring, thesis intact" \
  --sentiment neutral

# Hard block a ticker immediately
python scripts/journal_cli.py add CELH update \
  "Distribution deteriorating, guidance cut" --sentiment broken

# See all tickers with scores
python scripts/journal_cli.py status

# See full history for one ticker
python scripts/journal_cli.py list NVDA
```

**API**
```
POST   /api/journal/{ticker}      Add an entry
GET    /api/journal               All tickers with scores
GET    /api/journal/{ticker}      Full entry history
DELETE /api/journal/{ticker}/{id} Delete an entry
```

---

## Autonomy and the approval gate

The agent acts **immediately** (no approval needed) when:
- The ticker has a valid hypothesis and sentiment is `strengthening` or `neutral`
- The trade is a scale-in to an existing position (not a new open)
- The trade value is below your approval threshold (default: $500, configurable)
- The relevant gate is turned off in Settings

The agent **asks for your approval** when:
- `gate_new_positions` is ON and the ticker is not yet held
- `gate_full_exits` is ON and the agent wants to sell the entire position
- The trade value exceeds `approval_threshold_usd`

Recommended starting config for higher autonomy:
```
gate_new_positions    → OFF   (trust the journal to vet new opens)
approval_threshold    → $2000 (routine buys auto-execute; large ones still ask)
gate_full_exits       → ON    (always confirm full liquidations)
```

Hard stops that always apply regardless of gate settings:
- **Daily loss halt** — trading suspends if portfolio is down more than X% today (default 3%)
- **Max position size** — hard cap per ticker as % of portfolio (default 20%)
- **Max trades per day** — hard stop on total executed orders (default 5)
- **Earnings gate** — all buys blocked within 7 days of earnings automatically

---

## Setup

### Prerequisites

- Python 3.11+ (Anaconda / Miniconda recommended)
- PostgreSQL 14+
- [Anthropic API key](https://console.anthropic.com)
- [Robinhood account](https://robinhood.com) with the agentic trading feature enabled
- (Optional) [Twilio](https://twilio.com) for SMS alerts
- (Optional) SMTP credentials for email reports

### 1. Clone and install

```bash
git clone https://github.com/m-np/RobinhoodTrader.git
cd RobinhoodTrader
conda create -n robinhoodtrader python=3.11 -y
conda activate robinhoodtrader
pip install -r requirements.txt
```

### 2. Generate an encryption key

Robinhood OAuth tokens are encrypted at rest. Generate once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://localhost/robinhoodtrader
ENCRYPTION_KEY=<key from step 2>
ROBINHOOD_REDIRECT_URI=http://localhost:8000/auth/robinhood/callback

# Optional — SMS
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...

# Optional — email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=...          # Gmail: use an App Password

# Optional — tuning
AGENT_INTERVAL_MINUTES=15
PORT=8000
DASHBOARD_SECRET=          # Set for Basic Auth (needed for public deployments)
```

### 4. Create the database

```bash
# Mac
brew install postgresql@14 && brew services start postgresql@14

# Ubuntu
sudo apt install -y postgresql && sudo systemctl start postgresql

createdb robinhoodtrader
```

Migrations run automatically on startup — no manual `alembic upgrade` needed.

### 5. Start

```bash
python main.py
```

```
INFO  Running database migrations...
INFO  Migrations complete
INFO  Seeded 20 missing config knob(s)
INFO  Scheduler started
INFO  Uvicorn running on http://0.0.0.0:8000
```

Open **http://localhost:8000**.

### 6. Connect Robinhood

Go to **Settings → Robinhood connection → Connect Robinhood**. This starts the OAuth2 PKCE flow. On success you are redirected to the dashboard with a live portfolio.

### 7. Add your watchlist and journal

1. Go to **Watchlist** → add the tickers you want the agent to monitor
2. Go to **Journal** → add a hypothesis for each ticker you want the agent to trade
3. The agent will begin trading on the next cycle (up to 15 minutes)

### 8. Set up notifications (optional)

Go to **Settings → Notification delivery**. Enter your email and/or phone number, then click **Send test** to verify each channel before going live.

---

## Background jobs

| Job | Interval | Purpose |
|---|---|---|
| Agent cycle | 15 min (configurable) | Claude reviews portfolio + watchlist, places or queues trades |
| Approved trade executor | 30 s | Executes trades you approved from the dashboard |
| Market wave check | 5 min | Detects watchlist moves ≥3% and creates alerts |
| Watchlist price cache | 5 s | Fetches live quotes for all watchlist tickers |
| Price snapshots | 5 min | Writes prices to DB for sparklines and history charts |
| Congressional mirrors | 1 hr | Polls Capitol Trades for new disclosure filings |
| Institutional mirrors | 6 hr | Polls SEC EDGAR for new 13F filings |
| Daily report | 4:05 PM ET | Claude writes a P&L + trade summary (if enabled) |
| Weekly report | 4:05 PM ET | Claude writes a weekly summary (if enabled) |

---

## Settings reference

### Guardrails

| Knob | Default | What it controls |
|---|---|---|
| `approval_threshold_usd` | $500 | Trades above this require dashboard approval |
| `gate_new_positions` | On | Require approval when opening a position not currently held |
| `gate_full_exits` | On | Require approval when selling an entire position |
| `gate_rebalance` | Off | Require approval for routine weight adjustments |
| `gate_stop_loss` | Off | Require approval for stop-loss triggered sells |
| `approval_timeout_minutes` | 10 min | Auto-cancel pending trades with no response |
| `max_position_size_pct` | 20% | Hard cap per ticker as % of total portfolio |
| `max_trades_per_day` | 5 | Hard stop on total executed orders per day |
| `daily_loss_halt_pct` | 3% | Suspend trading if portfolio is down more than this today |

### Asset classes

Stocks are enabled by default. Enable crypto, options, futures, and event contracts independently from Settings.

### Reports

| Knob | Options |
|---|---|
| Frequency | Daily / Weekly / Both / Off |
| Delivery | Email / SMS / Both |
| Depth | Brief / Full / Deep analysis |
| Include trade rationale | On / Off |
| Include P&L breakdown | On / Off |

---

## Troubleshooting

| Error | Fix |
|---|---|
| `No such file or directory` (socket) | PostgreSQL not running — `sudo systemctl start postgresql` |
| `database "robinhoodtrader" does not exist` | `createdb robinhoodtrader` |
| `FATAL: role "..." does not exist` | `sudo -u postgres createuser --superuser $USER` |
| `ANTHROPIC_API_KEY` missing | `.env` not saved or not in `RobinhoodTrader/` directory |
| `ENCRYPTION_KEY is not set` | Generate with the command in step 2 |
| Port 8000 in use | Add `PORT=8001` to `.env` |
| Watchlist prices not updating | Robinhood not connected — Settings → Connect Robinhood |
| Today's P&L shows $0 | Robinhood not connected or no portfolio data yet |
| Agent not trading | Check journal: every watchlist ticker needs a hypothesis entry |

---

## Deploying to Railway

Railway is the easiest hosted option — managed PostgreSQL and a public URL included.

```bash
npm i -g @railway/cli
railway login && railway init
railway add          # add PostgreSQL plugin
railway up
```

Set the same environment variables as your `.env` in the Railway dashboard. Make sure `ROBINHOOD_REDIRECT_URI` matches your Railway public URL. Set `DASHBOARD_SECRET` to a strong password — Railway deployments are publicly reachable.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Your browser                        │
│           FastAPI + Jinja2 dashboard (port 8000)         │
└──────────────────────┬───────────────────────────────────┘
                       │  REST API
┌──────────────────────▼───────────────────────────────────┐
│                    FastAPI app                            │
│  ┌───────────────────────────────────────────────────┐   │
│  │                  APScheduler jobs                 │   │
│  │  agent cycle · approved trade executor · waves   │   │
│  │  price cache (5s) · mirror checks · reports      │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                 │
│  ┌──────────────────────▼────────────────────────────┐   │
│  │               Claude agent loop                   │   │
│  │  context → brain signals → Claude → tool calls   │   │
│  │  → guardrails → brain gates → MCP execution      │   │
│  └──────────────────────┬────────────────────────────┘   │
└─────────────────────────┼────────────────────────────────┘
                          │ MCP (OAuth2 PKCE)
          ┌───────────────▼───────────────┐
          │   Robinhood Agentic Account   │
          │  (isolated from main account) │
          └───────────────────────────────┘

PostgreSQL ── trades, watchlist, blocklist, alerts, knobs, snapshots
SQLite     ── thesis journal, positions, local alerts (data/trader.db)
Twilio / SMTP ── approval alerts + HTML email reports
Capitol Trades / SEC EDGAR ── mirror source polling
```

The Robinhood agentic account is **completely isolated** from your main Robinhood brokerage account. Only funds you explicitly deposit into the agentic account are accessible to this agent.

### Project structure

```
RobinhoodTrader/
  main.py              entry point — migrations, seeding, FastAPI + scheduler
  config.py            pydantic Settings loaded from .env

  agent/
    loop.py            Claude agent cycle — context build, tool-use, execution
    guardrails.py      pre-trade rule checks, approval gate, knob helpers
    mcp_client.py      Robinhood MCP wrapper (quotes, portfolio, orders)
    scheduler.py       APScheduler job definitions (9 jobs)
    wallet.py          agentic wallet balance check
    token_manager.py   OAuth token refresh

  brain/
    loader.py          assembles Claude's system prompt from skill files
    journal_store.py   SQLite thesis journal (read/write/score)
    tier_classifier.py dynamic tier classification via yfinance fundamentals
    red_day_detector.py market condition signals (VIX, S&P change, red day level)
    catalyst_checker.py earnings proximity gate
    pre_trade_check.py  full pre-trade gate stack (blocklist → journal → earnings → cash → sector → market)
    skills/            Markdown files that define Claude's trading mandate

  scripts/
    journal_cli.py     CLI for managing journal entries (add, list, status, delete)

  api/
    routes.py          all FastAPI endpoints

  db/
    models.py          SQLAlchemy ORM models
    migrations/        Alembic migration scripts

  ui/
    templates/         Jinja2 HTML pages
    static/            CSS design system + frontend JS

  notifications/
    notifier.py        Twilio SMS + SMTP email
  mirrors/
    capitol_trades.py  congressional disclosure polling
    sec_edgar.py       13F institutional filing polling
  reports/
    generator.py       Claude-generated daily/weekly summaries
  alerts/
    market_waves.py    watchlist price move detection
```

---

## Security model

| Concern | How it is handled |
|---|---|
| API keys | Local `.env` only — `.gitignore` enforced, never committed |
| Robinhood access | OAuth2 PKCE via Robinhood's official MCP server — no client secret |
| Token storage | Encrypted at rest with a Fernet key you generate |
| Account isolation | Agentic account is separate from your main Robinhood portfolio by design |
| Guardrails | Position cap, daily trade limit, daily loss halt — enforced before any MCP call |
| Dashboard auth | Optional HTTP Basic Auth via `DASHBOARD_SECRET` in `.env` |

---

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/portfolio` | Live holdings + today's P&L |
| `GET` | `/api/portfolio/history` | Time-series chart data (`?period=1d\|7d\|30d\|90d`) |
| `GET` | `/api/watchlist` | Watchlist tickers with live cached prices |
| `POST` | `/api/watchlist` | Add a ticker |
| `DELETE` | `/api/watchlist/{ticker}` | Remove a ticker |
| `GET` | `/api/journal` | All tickers with thesis scores |
| `GET` | `/api/journal/{ticker}` | Entry history for one ticker |
| `POST` | `/api/journal/{ticker}` | Add a journal entry |
| `DELETE` | `/api/journal/{ticker}/{id}` | Delete an entry |
| `GET` | `/api/alerts` | Unacknowledged alerts and pending trade decisions |
| `POST` | `/api/alerts/{id}/ack` | Dismiss an alert |
| `POST` | `/api/trades/{id}/approve` | Approve a pending trade |
| `POST` | `/api/trades/{id}/reject` | Reject a pending trade |
| `GET` | `/api/trades` | Trade history |
| `GET` | `/api/knobs` | All config knob values |
| `POST` | `/api/knobs` | Update a config knob |
| `GET` | `/api/mirrors` | Mirror sources |
| `PATCH` | `/api/mirrors/{slug}` | Toggle a mirror or change allocation |
| `GET` | `/api/reports` | All generated reports |
| `POST` | `/api/notify/config` | Save recipient email / phone |
| `POST` | `/api/notify/test` | Send test email, SMS, or both |
| `GET` | `/auth/robinhood` | Start Robinhood OAuth2 PKCE flow |
| `GET` | `/auth/robinhood/callback` | OAuth callback |

---

## Current limitations

### Asset classes

The settings UI has toggles for stocks, crypto, options, futures, and event contracts. Only **stocks are fully implemented end-to-end**. The others are in various states:

| Asset class | Toggle | Skill file | Order execution | What's missing |
|---|---|---|---|---|
| Stocks | ✓ | ✓ `stocks.md` | ✓ `place_equity_order` | Nothing — fully working |
| Options | ✓ | ✓ `options.md` | ✗ | `place_option_order` call with strategy params (strike, expiry, legs, call/put). The current order layer only calls the equity endpoint regardless of asset class. |
| Crypto | ✓ | ✗ | ✗ | `crypto.md` skill file; verify whether Robinhood MCP uses the equity or a separate crypto endpoint for BTC/ETH orders. |
| Futures | ✓ | ✗ | ✗ | `futures.md` skill file; futures-specific MCP order call. |
| Event contracts | ✓ | ✗ | ✗ | Skill file; event contract MCP order call. |

Until these are implemented, enabling crypto/options/futures/events in Settings will let Claude discuss those asset classes but **any order it tries to place will fail silently** because the MCP layer routes everything through `place_equity_order`.

### Agent data access

Claude only sees what the Robinhood MCP exposes per cycle:
- **Live quote** (price + daily % change) — no OHLCV bars, no intraday data
- **Portfolio state** (holdings, cash, market value, daily P&L)
- **Earnings calendar** — from yfinance, not Robinhood MCP

Claude cannot compute RSI, MACD, Bollinger Bands, or any indicator that requires historical price series. Its technical analysis is limited to what it can infer from the current price, daily move, and volume relative to the 30-day average.

### Mirror sources

Currently supports:
- Congressional disclosures via [Capitol Trades](https://capitoltrades.com) (real-time)
- Institutional 13F filings via [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar) (quarterly)

Not yet supported:
- Insider Form 4 filings (executives buying/selling their own company stock)
- ETF holdings (tracking what major ETFs hold and rebalance into)
- Activist positions (13D/13G filings signalling activist entry)

### Other gaps

| Feature | Status |
|---|---|
| Backtesting / paper trading | Not implemented. The agent loop always places real orders against the live agentic account. |
| Stop-loss levels per position | The `gate_stop_loss` gate exists but there is no per-position stop price stored. The agent uses its own judgement on exit timing. |
| Sector allocation tracking | `pre_trade_check.py` has sector cap logic but the agent loop does not currently pass live sector allocation data into it. |
| Multi-account support | Single Robinhood agentic account only. |
| Mobile / PWA | The dashboard is responsive but there is no push notification support or installable PWA manifest. |
| Auth beyond Basic Auth | `DASHBOARD_SECRET` enables HTTP Basic Auth. No OAuth2, SSO, or per-user access control. |

---

## Contributing

Forks and contributions welcome. The gaps above are good starting points. Other ideas:

- Multi-broker support (Alpaca, Interactive Brokers via their MCP servers)
- Options strategy execution — the skill and knob are wired; the order layer needs `place_option_order` with strategy params
- Crypto execution — skill file + verify correct MCP endpoint
- Backtesting mode — replay a context snapshot through the agent loop without placing real orders
- Mobile-friendly PWA with push notifications for approval requests
- Richer mirror sources — insider Form 4, ETF holdings, activist 13D/13G
- Telegram / Discord bot for approvals instead of SMS
- Sector allocation live data fed into the pre-trade check
- More skill files — macro regime filters, sector rotation, earnings momentum plays

Open an issue before starting large changes.

---

## Disclaimer

This software is for personal use and educational purposes only. It is not financial advice. Automated trading carries significant risk. You are solely responsible for any trades placed through this tool and any resulting gains or losses. Always review your guardrail settings before enabling live trading.

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Mandar Narendra Parab.
