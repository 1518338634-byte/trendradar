#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

echo "[$(date '+%F %T')] Starting TrendRadar stack..."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI is not available."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    echo "Docker engine is not running. Starting Colima..."
    colima start --cpu 2 --memory 4 --disk 20
  else
    echo "Docker engine is not running and Colima is not available."
    exit 1
  fi
fi

echo "Starting TrendRadar container..."
docker compose --env-file docker/.env -f docker/docker-compose.yml up -d trendradar

echo "Starting control panel..."
exec node control-panel/server.mjs
