#!/usr/bin/env bash
# Server-side deploy script: pull latest main and rebuild containers.
# Called by GitHub Actions (.github/workflows/deploy.yml) over SSH,
# or run manually on the server: bash deploy/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Pulling latest code from origin/main"
git fetch origin main
git reset --hard origin/main

# bash reads this script incrementally, so a mid-run self-update would
# resume at the old byte offset and silently skip steps. Everything above
# MUST stay byte-identical across versions; the fresh script takes over here.
if [ "${1:-}" != "--reexec" ]; then
    exec bash deploy/update.sh --reexec
fi

echo "==> Rebuilding and restarting containers"
docker compose -f deploy/docker-compose.yml up -d --build

echo "==> Reloading nginx (pick up bind-mounted config, refresh upstream)"
# nginx keeps running with the config it loaded at startup; reload so it
# re-reads nginx.conf (dynamic upstream resolution) without downtime.
docker compose -f deploy/docker-compose.yml exec -T nginx nginx -s reload

echo "==> Pruning old images"
docker image prune -f >/dev/null

echo "==> Waiting for the app to become healthy"
sleep 8
if docker compose -f deploy/docker-compose.yml exec -T app \
    python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" \
    >/dev/null 2>&1; then
    echo "==> Deploy OK"
else
    echo "==> Health check FAILED, recent app logs:"
    docker compose -f deploy/docker-compose.yml logs --tail=50 app
    exit 1
fi
