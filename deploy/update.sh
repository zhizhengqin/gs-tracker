#!/usr/bin/env bash
# Server-side deploy script: pull latest main and rebuild containers.
# Called by GitHub Actions (.github/workflows/deploy.yml) over SSH,
# or run manually on the server: bash deploy/update.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Pulling latest code from origin/main"
git fetch origin main
git reset --hard origin/main

echo "==> Rebuilding and restarting containers"
docker compose -f deploy/docker-compose.yml up -d --build

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
