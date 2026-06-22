# RobinhoodTrader

An autonomous, single-user trading agent that uses [Claude](https://anthropic.com) as its decision-making brain, connected to Robinhood via their official MCP server. Comes with a clean web dashboard, configurable guardrails, human approval gates, portfolio mirrors, and email/SMS notifications — all running on your own infrastructure.

> **This is a personal tool.** Your API keys and credentials never leave your machine (or your own cloud deployment). There is no shared backend, no telemetry, and no third-party service beyond the APIs you configure yourself.

---

## What it does

- **Claude agent** (`claude-sonnet-4-6`) runs on a configurable schedule (default: every 15 minutes), reviews your Robinhood agentic portfolio, watchlist, and market conditions, and decides whether to buy or sell
- **Human-in-the-loop** — trades above your approval threshold, new position opens, and full exits queue as pending decisions on the dashboard. You approve or reject with one click. Unanswered requests time out and cancel automatically
- **Guardrails** enforce position size limits, daily trade caps, and a daily loss halt — all configurable without touching code
- **Pending decisions UI** — the dashboard shows focused buy/sell decision cards with exact quantity, price, and total for each trade waiting on your approval
- **Live watchlist prices** refreshed every 5 seconds with a market open/closed status indicator. Prices freeze at close and show a "Market closed" label until the next session
- **Portfolio chart** always extends to the current moment — a live data point is pinned from your real-time portfolio value so the chart never looks stale
- **Mirror trading** tracks congressional disclosures (Capitol Trades) and institutional 13F filings (SEC EDGAR). Enable any source in Settings → Mirrors and set how much of your portfolio to allocate as a percentage
- **Reports** — Claude writes plain-English daily and/or weekly summaries with P&L, trade rationale, and portfolio commentary. Delivered as formatted HTML emails or SMS
- **Notifications** — configure your email address and phone number directly from the dashboard. SMTP and Twilio credentials live in `.env`; the recipient addresses are stored in the database and can be updated without a restart. Test buttons verify both channels before you go live

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
│  │  tool-use loop → guardrails → ApprovalPending     │   │
│  └──────────────────────┬────────────────────────────┘   │
└─────────────────────────┼────────────────────────────────┘
                          │ MCP (OAuth2 PKCE)
          ┌───────────────▼───────────────┐
          │   Robinhood Agentic Account   │
          │  (isolated from main account) │
          └───────────────────────────────┘

PostgreSQL ─── trades, watchlist, alerts, config knobs, snapshots
Twilio / SMTP ── approval SMS + HTML email reports
Capitol Trades / SEC EDGAR ── mirror source polling
```

The Robinhood agentic account is **completely isolated** from your main Robinhood brokerage account. Only funds you explicitly deposit into the agentic account are accessible to this agent.

---

## Background jobs

| Job | Interval | What it does |
|---|---|---|
| Agent cycle | Every 15 min (configurable) | Claude reviews portfolio + watchlist, places or queues trades |
| Approved trade executor | Every 30 s | Picks up `approved` trades and sends orders to Robinhood |
| Market wave check | Every 5 min | Detects price moves ≥3% in the watchlist and creates alerts |
| Watchlist price cache | Every 5 s | Fetches live quotes for all watchlist tickers (1 MCP call) |
| Watchlist price snapshots | Every 5 min | Writes prices to DB for sparklines and historical charts |
| Congressional mirrors | Every 1 hr | Polls Capitol Trades for new disclosure filings |
| Institutional mirrors | Every 6 hr | Polls SEC EDGAR for new 13F institutional filings |
| Daily report | 4:05 PM ET (Mon–Fri) | Claude writes a P&L + trade summary if `report_frequency` is `daily` or `both` |
| Weekly report | 4:05 PM ET (configured day) | Claude writes a weekly summary if `report_frequency` is `weekly` or `both` |

---

## Security model

| Concern | How it is handled |
|---|---|
| API keys | Stored only in your local `.env` file — never committed (`.gitignore` enforced) |
| Robinhood access | OAuth2 PKCE via Robinhood's official MCP server — no client secret, no proxy |
| Token storage | Access and refresh tokens are encrypted at rest with a Fernet key you generate |
| Account isolation | Robinhood agentic account is separate from your main portfolio by design |
| Trade approval | Human-in-the-loop gates for new positions, full exits, and trades above your threshold |
| Guardrails | Position size cap, daily trade limit, daily loss halt — all enforced before any order reaches Robinhood |
| Dashboard auth | Optional HTTP Basic Auth via `DASHBOARD_SECRET` in `.env` |
| Deployment | Runs on your own machine or your own Railway project — no shared infrastructure |

---

## Prerequisites

- [Anaconda](https://www.anaconda.com/download) or Miniconda (recommended) — or Python 3.11+
- PostgreSQL 14+ (local or hosted, e.g. Railway, Supabase, Neon)
- [Anthropic API key](https://console.anthropic.com)
- [Robinhood account](https://robinhood.com) with the agentic trading feature enabled
- (Optional) [Twilio account](https://twilio.com) for SMS approval alerts
- (Optional) Gmail or any SMTP server for HTML email reports

---

## Running locally

### 1. Clone and set up the environment

```bash
git clone https://github.com/m-np/RobinhoodTrader.git
cd RobinhoodTrader
```

**Option A — Anaconda / Miniconda (recommended)**

```bash
conda create -n robinhoodtrader python=3.11 -y
conda activate robinhoodtrader
pip install -r requirements.txt
```

**Option B — standard venv**

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Generate an encryption key

Robinhood OAuth tokens are encrypted at rest. Generate a key once and put it in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Configure your secrets

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
# ── Required ────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql://localhost/robinhoodtrader
ENCRYPTION_KEY=<paste the key from step 2>

# Robinhood OAuth callback (change port if needed)
ROBINHOOD_REDIRECT_URI=http://localhost:8000/auth/robinhood/callback

# ── Optional — SMS via Twilio ───────────────────────────
# After setting these, go to Settings → Notification delivery
# to enter your phone number and send a test message.
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...

# ── Optional — email via SMTP ───────────────────────────
# After setting these, go to Settings → Notification delivery
# to enter your email address and send a test message.
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=...        # Gmail: use an App Password, not your main password

# ── Optional — defaults for notifications ───────────────
# These can also be set from the dashboard without a restart.
NOTIFY_TO_NUMBER=+1...
NOTIFY_EMAIL=you@example.com

# ── Optional — dashboard auth ───────────────────────────
# Set a password to require Basic Auth when accessing the dashboard.
# Leave empty to disable auth (fine for local use).
DASHBOARD_SECRET=

# ── Optional — tuning ───────────────────────────────────
AGENT_INTERVAL_MINUTES=15
PORT=8000
```

The `.env` file is listed in `.gitignore` and will never be committed.

### 4. Install and start PostgreSQL

**Ubuntu / Debian**

```bash
sudo apt update && sudo apt install -y postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Mac (Homebrew)**

```bash
brew install postgresql@14
brew services start postgresql@14
```

**Create the database**

```bash
createdb robinhoodtrader
```

If you get a permission error:

```bash
sudo -u postgres createuser --superuser $USER
createdb robinhoodtrader
```

Update `DATABASE_URL` in `.env`:

```env
# Most common (createdb worked directly):
DATABASE_URL=postgresql://localhost/robinhoodtrader

# If you needed sudo -u postgres:
DATABASE_URL=postgresql://postgres@localhost/robinhoodtrader
```

The app runs Alembic migrations automatically on startup — no manual `alembic upgrade` needed.

### 5. Start the app

```bash
python main.py
```

On first boot you will see:

```
INFO  Running database migrations...
INFO  Migrations complete
INFO  Seeded 20 missing config knob(s)
INFO  Scheduler started
INFO  Uvicorn running on http://0.0.0.0:8000
```

Open **http://localhost:8000** in your browser.

### 6. Connect Robinhood

Go to **Settings → Robinhood connection** and click **Connect Robinhood**. This starts the OAuth2 PKCE flow — Robinhood will ask you to sign in and grant access to the agentic account. On success you are redirected back to the dashboard.

### 7. What to expect on first run

1. **Empty portfolio and no signals** — expected until the first agent cycle runs (up to 15 minutes after startup).
2. **Yellow wallet banner** — appears if your Robinhood agentic wallet balance is $0. The agent skips trading until the account is funded.
3. **First agent cycle** — Claude reviews your watchlist and portfolio. If it wants to trade, it will create a pending decision card on the dashboard.
4. **Approval gate** — trades above $500 (configurable), new position opens, and full exits appear as pending decisions rather than executing immediately. You have 10 minutes to approve or reject before they auto-cancel.

### 8. Set up notifications

Go to **Settings → Notification delivery**:

- **Email** — if SMTP credentials are in `.env`, the badge shows green. Enter the address you want reports sent to and click **Save**, then **Send test** to verify.
- **SMS** — if Twilio credentials are in `.env`, the badge shows green. Enter your phone number (E.164 format, e.g. `+15551234567`) and click **Save**, then **Send test**.

The email address and phone number are stored in the database — you can update them here at any time without restarting the server. SMTP credentials and Twilio API keys must remain in `.env`.

---

## Troubleshooting

| Error | Fix |
|---|---|
| `No such file or directory` on socket | PostgreSQL not running — `sudo systemctl start postgresql` |
| `FATAL: database "robinhoodtrader" does not exist` | Run `createdb robinhoodtrader` |
| `FATAL: role "..." does not exist` | `sudo -u postgres createuser --superuser $USER` |
| `ANTHROPIC_API_KEY` missing error | `.env` not saved or not in the `RobinhoodTrader/` directory |
| `ENCRYPTION_KEY is not set` | Generate a key with the command in step 2 and add it to `.env` |
| Port 8000 already in use | Add `PORT=8001` to `.env` |
| "Twilio not configured — SMS skipped" in logs | `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` missing from `.env` |
| "SMTP not configured — email skipped" in logs | `SMTP_USER` and `SMTP_PASSWORD` missing from `.env` |
| Watchlist prices not updating | Robinhood not connected — click Connect Robinhood in Settings |
| Today's P&L shows $0 | Robinhood not connected or no portfolio data returned yet |

---

## Deploying to Railway

Railway is the easiest hosted option — it provides managed PostgreSQL and a public URL.

1. [Create a Railway account](https://railway.app) and install the CLI: `npm i -g @railway/cli`
2. From the project root:

```bash
railway login
railway init
railway add           # add a PostgreSQL plugin
railway up
```

3. Set your environment variables in the Railway dashboard (same keys as your `.env`). Make sure `ROBINHOOD_REDIRECT_URI` points to your Railway public URL.
4. Set `DEPLOYMENT_MODE=railway` — this disables hot-reload and uses the `PORT` Railway assigns automatically.
5. Railway uses the `Procfile` to start the app: `web: python main.py`

Set `DASHBOARD_SECRET` to a strong password before going live — Railway deployments are publicly reachable.

---

## Dashboard overview

| Page | What it shows |
|---|---|
| **Dashboard** | Live wallet balance, today's P&L, trades executed today, portfolio holdings with position bars, pending buy/sell decisions (with amounts), last report summary, and a portfolio value chart that always extends to the current moment |
| **Watchlist** | Tickers Claude monitors, with live price, daily change %, and a market open/closed status indicator. Prices refresh every 5 seconds during market hours |
| **Mirrors** | Congressional disclosure feeds (Capitol Trades) and institutional 13F feeds (SEC EDGAR). Toggle each source on/off and set a portfolio allocation percentage per source |
| **Reports** | All generated reports with P&L figures and Claude's commentary |
| **Settings** | All guardrail knobs, approval gates, report preferences, and notification delivery — all changes save to the database immediately |

### Pending decisions

When Claude wants to make a trade that requires your approval, a decision card appears on the dashboard showing:

- **Buy / Sell** label with a green or red background
- **Ticker** and when the decision was made
- **Quantity and price** — e.g. `3.5 shares @ $143.25 · $501.38 total`
- **Reason** — why Claude flagged this trade, or "Via Nancy Pelosi" for mirror trades
- **Approve** and **Reject** buttons

Approving executes the trade immediately; rejecting cancels it. Cards fade away when resolved. Non-decision system alerts (wallet warnings, connection issues) are kept in the database but not shown in this feed.

---

## Settings reference

### Guardrail limits

| Knob | Default | What it controls |
|---|---|---|
| Approval threshold | $500 | Trades above this always require approval before execution |
| Gate: new positions | On | Require approval when buying a stock not currently held |
| Gate: full exits | On | Require approval when selling an entire position |
| Gate: rebalance | Off | Require approval for routine weight adjustments |
| Gate: stop-loss | Off | Require approval for automatic downside protection sells |
| Approval timeout | 10 min | Cancel pending trade if no response within this window |
| Max position size | 20% | Hard cap on what % of the portfolio can be in any single ticker |
| Max trades per day | 5 | Hard stop on executed orders per calendar day |
| Daily loss halt | 3% | Suspend all trading if the portfolio is down more than X% today |

### Asset classes

Stocks are enabled by default. Crypto, options, futures, and event contracts can each be enabled independently from the Settings page.

### Reports

| Knob | Options | What it controls |
|---|---|---|
| Frequency | Daily / Weekly / Both / Off | When reports are generated |
| Weekly day | Mon–Fri | Which day the weekly report fires (4:05 PM ET) |
| Delivery | Email / SMS / Both | Where reports are sent |
| Depth | Brief / Full / Deep analysis | How much detail Claude writes |
| Include trade rationale | On / Off | Whether Claude explains each decision |
| Include P&L breakdown | On / Off | Whether per-position figures are included |

### Notification delivery

Email address and phone number are set here from the dashboard — no restart required.

SMTP credentials (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`) and Twilio credentials (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`) must be configured in `.env`. The Settings page shows a green badge when they are loaded and a "Send test" button to verify each channel.

---

## How Claude makes decisions

Claude sees a snapshot of your portfolio at each cycle:

- Current holdings, market values, and P&L
- Watchlist tickers with live prices and daily % change
- Your guardrail settings (position size limits, allowed asset classes, etc.)
- Market context (indices, broad sentiment)
- Any pending mirror trades from congressional or institutional sources
- Recent trade history to avoid thrashing in and out of positions

Claude uses a set of **skill files** (`brain/skills/*.md`) that define its mandate — how aggressive to be, what to prioritise, how to handle different market conditions. You can edit these files to change the agent's personality without touching any Python code.

Claude does **not** have access to OHLCV bars or historical price data through the Robinhood MCP (only live quotes and daily % change). Its analysis is built around your watchlist, portfolio composition, and the signals you surface to it. If you want Claude to watch a stock, add it to your watchlist.

---

## Project structure

```
RobinhoodTrader/
  main.py              entry point — migrations, seeding, FastAPI + scheduler startup
  config.py            pydantic Settings loaded from .env
  requirements.txt
  Procfile             for Railway / Heroku

  agent/
    loop.py            Claude agent cycle (tool-use loop, trade execution, P&L enrichment)
    guardrails.py      all pre-trade rule checks + approval gate + get_knob/set_knob
    mcp_client.py      Robinhood MCP wrapper (quotes, portfolio, order placement)
    price_cache.py     in-memory watchlist price cache (refreshed every 5 s)
    wallet.py          agentic wallet balance check + low-balance alerts
    token_manager.py   OAuth token refresh logic
    scheduler.py       APScheduler job definitions (9 jobs)

  api/
    routes.py          all FastAPI endpoints (portfolio, trades, alerts, notify, auth, …)
    deps.py            shared DB session dependency

  db/
    models.py          SQLAlchemy ORM — Trade, Watchlist, Blocklist, ConfigKnob,
                       MirrorSource, Alert, Report, PortfolioSnapshot,
                       WatchlistPriceSnapshot, RobinhoodToken
    session.py         engine + SessionLocal
    migrations/        Alembic env + migration scripts

  brain/
    skills/            Markdown skill files assembled into Claude's system prompt

  ui/
    templates/         Jinja2 HTML — base, dashboard, watchlist, mirrors, reports, settings
    static/
      style.css        design system (CSS variables, all component styles)
      app.js           all frontend JS (polling, knobs, charts, alert cards, notify config)

  notifications/
    notifier.py        Twilio SMS + SMTP HTML email — recipient read from DB with .env fallback

  mirrors/
    capitol_trades.py  congressional disclosure polling (Capitol Trades API)
    sec_edgar.py       13F institutional filing polling (SEC EDGAR)

  reports/
    generator.py       Claude-generated daily/weekly summaries with P&L from snapshots

  alerts/
    market_waves.py    price move detection — alerts when a watchlist ticker moves ≥3%
```

---

## API endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/portfolio` | Live portfolio holdings + today's P&L |
| `GET` | `/api/portfolio/history` | Time-series snapshots for the portfolio chart (`?period=7d`) |
| `GET` | `/api/watchlist` | Watchlist tickers with live cached prices |
| `POST` | `/api/watchlist` | Add a ticker |
| `DELETE` | `/api/watchlist/{ticker}` | Remove a ticker |
| `GET` | `/api/alerts` | Unacknowledged alerts (approval requests and mirror trade decisions) |
| `POST` | `/api/alerts/{id}/ack` | Acknowledge (dismiss) an alert |
| `GET` | `/api/trades` | Trade history |
| `POST` | `/api/trades/quick` | Place a quick buy/sell from a signal card |
| `POST` | `/api/trades/{id}/approve` | Approve a pending trade |
| `POST` | `/api/trades/{id}/reject` | Reject a pending trade |
| `GET` | `/api/knobs` | All config knob values |
| `POST` | `/api/knobs` | Update a config knob |
| `GET` | `/api/mirrors` | Mirror sources |
| `PATCH` | `/api/mirrors/{slug}` | Enable/disable a mirror source or change its scale factor |
| `GET` | `/api/reports` | All generated reports |
| `GET` | `/api/notify/status` | SMTP/Twilio configuration status + current recipient addresses |
| `POST` | `/api/notify/config` | Save recipient email and/or phone to DB |
| `POST` | `/api/notify/test` | Send a test email, SMS, or both |
| `GET` | `/auth/robinhood` | Start Robinhood OAuth2 PKCE flow |
| `GET` | `/auth/robinhood/callback` | OAuth callback — exchanges code for tokens |

---

## Contributing

Forks and contributions are welcome. Some ideas for what could be built on top:

- Multi-broker support (Alpaca, Interactive Brokers, etc. via their MCP servers)
- Options strategy execution (the `asset_options` toggle is wired; the order layer needs strategy-specific types)
- Backtesting mode — replay historical data through the agent loop without placing real orders
- Mobile-friendly PWA shell with push notifications
- Richer mirror sources — insider Form 4 filings, ETF holdings, activist positions
- Telegram / Discord bot for approvals instead of SMS
- Auth middleware for public hosting (e.g. Authelia, Cloudflare Access)
- More skill files — earnings plays, macro regime filters, sector rotation

To get started:

```bash
git clone https://github.com/m-np/RobinhoodTrader.git
cd RobinhoodTrader
conda create -n robinhoodtrader python=3.11 -y && conda activate robinhoodtrader
pip install -r requirements.txt
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cp .env.example .env   # fill in ANTHROPIC_API_KEY, DATABASE_URL, ENCRYPTION_KEY at minimum
createdb robinhoodtrader
python main.py
```

Please open an issue before starting large changes so we can discuss the approach first.

---

## Disclaimer

This software is for personal use and educational purposes. It is not financial advice. Automated trading carries significant risk. You are solely responsible for any trades placed through this tool and any resulting gains or losses. Always review your guardrail settings before enabling live trading.

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Mandar Narendra Parab.
