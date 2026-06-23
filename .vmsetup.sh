#!/usr/bin/env bash
set -e

ENV_NAME="robinhoodtrader"
PYTHON_VERSION="3.11"

echo "═════════════════════════════════════════════════════════════════════════════"
echo " RobinhoodTrader — leaf VM setup"
echo "═════════════════════════════════════════════════════════════════════════════"

# ─────────────────────────────────────────────────────────────────────────────
# [1/6] Conda environment
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[1/6] Conda environment ─────────────────────────────────────────────────────"

source "$HOME/anaconda3/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "  Env '$ENV_NAME' exists — skipping creation."
else
    echo "  Creating conda env '$ENV_NAME' (Python $PYTHON_VERSION)..."
    conda create -n "$ENV_NAME" python="$PYTHON_VERSION" -y
fi

# ─────────────────────────────────────────────────────────────────────────────
# [2/6] Python dependencies
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[2/6] Python dependencies ───────────────────────────────────────────────────"
echo "  Installing requirements.txt into '$ENV_NAME'..."
conda run -n "$ENV_NAME" pip install -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# [3/6] PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[3/6] PostgreSQL ────────────────────────────────────────────────────────────"

if command -v psql &>/dev/null; then
    echo "  PostgreSQL already installed — skipping."
else
    echo "  Installing PostgreSQL..."
    sudo apt-get install -y postgresql postgresql-contrib
    sudo systemctl start postgresql
    sudo systemctl enable postgresql
    echo "  PostgreSQL installed and started."
fi

echo "  Creating database '$ENV_NAME'..."
# Try as current user first (works if a PostgreSQL role for $USER already exists).
# If that fails with a missing-role error, create a superuser role for $USER and retry.
if ! createdb "$ENV_NAME" 2>/dev/null; then
    echo "  Current user has no PostgreSQL role — creating one..."
    sudo -u postgres createuser --superuser "$USER" 2>/dev/null || true
    createdb "$ENV_NAME" || true
fi

# ─────────────────────────────────────────────────────────────────────────────
# [4/6] Fernet key generation
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[4/6] Generating Fernet encryption key ──────────────────────────────────────"

FERNET_KEY="$(conda run -n "$ENV_NAME" python -c \
    "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
echo "  Key generated."

# ─────────────────────────────────────────────────────────────────────────────
# [5/6] .env setup
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[5/6] .env setup ────────────────────────────────────────────────────────────"

if [[ ! -f ".env" ]]; then
    cp .env.example .env
    echo "  Created .env from .env.example."
else
    echo "  .env already exists — leaving it in place."
fi

# Inject the generated Fernet key into ENCRYPTION_KEY= line
sed -i "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${FERNET_KEY}|" .env
echo "  ENCRYPTION_KEY injected into .env."

echo ""
echo "  ┌─────────────────────────────────────────────────────────────────────┐"
echo "  │  ACTION REQUIRED — fill in these values in .env before running:    │"
echo "  │                                                                     │"
echo "  │  REQUIRED                                                           │"
echo "  │    ANTHROPIC_API_KEY      — your Anthropic API key                 │"
echo "  │    DATABASE_URL           — default: postgresql:///robinhoodtrader  │"
echo "  │    ROBINHOOD_CLIENT_ID    — from Robinhood developer portal         │"
echo "  │    ROBINHOOD_CLIENT_SECRET                                          │"
echo "  │                                                                     │"
echo "  │  OPTIONAL                                                           │"
echo "  │    TWILIO_*               — SMS trade alerts                        │"
echo "  │    SMTP_*                 — email reports                           │"
echo "  │    POLYGON_API_KEY        — improved market wave alerts             │"
echo "  │    ALPHA_VANTAGE_KEY                                                │"
echo "  └─────────────────────────────────────────────────────────────────────┘"

# ─────────────────────────────────────────────────────────────────────────────
# [6/6] Done
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "[6/6] Complete ──────────────────────────────────────────────────────────────"
echo ""
echo "  ✅ RobinhoodTrader leaf setup complete."
echo "     Next: fill in .env then run:"
echo ""
echo "       conda activate $ENV_NAME && python main.py"
echo ""
echo "═════════════════════════════════════════════════════════════════════════════"
