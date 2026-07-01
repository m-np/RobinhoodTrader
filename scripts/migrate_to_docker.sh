#!/usr/bin/env bash
# Migrate your local Postgres data into the Docker postgres volume.
# Run this once before switching to Docker. Your local data is never modified.
#
# Usage: ./scripts/migrate_to_docker.sh

set -euo pipefail

# Use sudo for docker if the current user can't reach the socket directly
if docker info &>/dev/null; then
    DC="docker compose"
else
    echo "    (docker requires sudo on this machine — using sudo docker compose)"
    DC="sudo docker compose"
fi

DUMP_FILE="$(mktemp /tmp/robinhoodtrader_dump.XXXXXX.sql)"
trap 'rm -f "$DUMP_FILE"' EXIT

echo "==> Stopping any running containers and wiping Docker postgres volume..."
$DC down -v

echo "==> Starting Docker postgres..."
$DC up -d db

echo "==> Waiting for postgres to be ready..."
until $DC exec -T db pg_isready -U postgres -q; do
    sleep 1
done

echo "==> Dumping local postgres..."
pg_dump --no-owner --no-acl robinhoodtrader > "$DUMP_FILE"
echo "    Dump size: $(wc -c < "$DUMP_FILE") bytes"

echo "==> Importing into Docker postgres..."
$DC exec -T db psql \
    --set ON_ERROR_STOP=on \
    --single-transaction \
    -U postgres robinhoodtrader < "$DUMP_FILE"

echo "==> Verifying import..."
$DC exec -T db psql -U postgres robinhoodtrader -t -c "
SELECT relname || ': ' || n_live_tup || ' rows'
FROM pg_stat_user_tables
ORDER BY relname;
" 2>/dev/null || \
$DC exec -T db psql -U postgres robinhoodtrader -c "
SELECT table_name, (SELECT COUNT(*) FROM information_schema.columns WHERE table_name=t.table_name) AS cols
FROM information_schema.tables t
WHERE table_schema='public' AND table_type='BASE TABLE'
ORDER BY table_name;
"

echo ""
echo "==> Done. Start the app with:"
echo "    $DC up"
