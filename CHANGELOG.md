# Changelog

All notable changes to this project will be documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- Docker support (`Dockerfile` + `docker-compose.yml`) — single-command setup
- `CONTRIBUTING.md`, `SECURITY.md`, issue templates, PR template
- GitHub Actions CI — pytest runs on every push and PR
- `requirements-dev.txt` — test dependencies split from production requirements

### Fixed
- `httpx2` typo in `requirements.txt` corrected to `httpx`
- CI fixture ordering — migrations now run before DB snapshot in `_isolate_live_db`
- `TestClient` Basic Auth — tests now authenticate correctly against the dashboard middleware

---

## [0.1.0] — 2026-06-12

Initial public release.

### Added
- Agent loop — Claude runs every 15 minutes, reads portfolio + journal, decides to buy/sell/hold
- Thesis journal — conviction-based position gating; no hypothesis = no buy
- Tier classifier — core / growth / moonshot tiers with per-tier position size caps
- Guardrails — daily loss halt, max position %, max trades per day, earnings blackout window
- Watchlist — live price monitoring with 5-second refresh and 24h sparklines
- Dashboard — wallet balance, P&L, holdings, pending approval cards, portfolio chart
- Mirrors — Capitol Trades (congressional disclosures) and SEC EDGAR (13F filings) tracking
- Stock discovery — fundamentals scan with optional Serper.dev web search
- Reports — plain-English daily/weekly summaries delivered via email or SMS
- Notifications — Twilio SMS and SMTP email with test buttons in the UI
- Robinhood OAuth2 PKCE flow — tokens encrypted at rest with Fernet
- Settings UI — all guardrails and config knobs editable without restarting
- Alembic migrations — run automatically on startup
- REST API — full programmatic access to journal, trades, watchlist, and settings
- CLI journal script — `scripts/journal_cli.py` for fast bulk updates
