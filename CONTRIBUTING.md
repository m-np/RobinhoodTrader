# Contributing to RobinhoodTrader

Thanks for your interest. This is a personal finance tool that touches real brokerage accounts — contributions are welcome, but correctness and safety matter more than speed.

## Before you start

- Open an issue first for anything non-trivial so we can align before you invest time writing code.
- For small fixes (typos, docs, obvious bugs) a PR without a prior issue is fine.

## Setup

```bash
git clone https://github.com/m-np/RobinhoodTrader.git
cd RobinhoodTrader

conda create -n robinhoodtrader python=3.11 -y
conda activate robinhoodtrader
pip install -r requirements.txt

cp .env.example .env
# fill in DATABASE_URL, ANTHROPIC_API_KEY, ENCRYPTION_KEY, DASHBOARD_SECRET
createdb robinhoodtrader
```

Migrations run automatically on first startup (`python main.py`).

## Running tests

```bash
conda activate robinhoodtrader
pytest
```

Tests require a running Postgres database. They snapshot and restore live data — safe to run against your dev database. CI runs the same suite against a clean Postgres container.

## Branch and PR conventions

- Branch from `main`, target `main` in your PR.
- One logical change per PR.
- Keep commits focused — squash noise before opening the PR.
- Run `pytest` and confirm all tests pass before submitting.

## What's in scope

- Bug fixes with a clear reproduction case
- Docs improvements
- New guardrail types or journal entry types
- Performance improvements to the agent cycle
- Docker / deployment improvements

## What's out of scope

- Features that bypass the thesis-journal gate (the discipline mechanic is intentional)
- Crypto or futures support (not planned)
- Shared backend / multi-user support (this is intentionally a personal tool)
- Changes that store credentials outside the local machine

## Code style

- Python 3.11+, no type: ignore without a comment explaining why
- No new dependencies without discussion — each one is a fresh attack surface for a tool that holds OAuth tokens
- Keep the guardrails file (`agent/guardrails.py`) conservative — when in doubt, block rather than allow

## Reporting security issues

See [SECURITY.md](SECURITY.md). Do not open a public issue for vulnerabilities.
