#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/docker"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed or not available in PATH."
  echo
  echo "Option 1: Install and open Docker Desktop, then run this script again."
  echo "Option 2: Install Colima with Homebrew:"
  echo "  brew install colima docker docker-compose"
  echo "  mkdir -p ~/.docker/cli-plugins"
  echo "  ln -sf \$(brew --prefix)/opt/docker-compose/bin/docker-compose ~/.docker/cli-plugins/docker-compose"
  echo "  colima start --cpu 2 --memory 4 --disk 20"
  echo
  echo "Then run: ./start-local-docker.sh"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker is installed, but the Docker engine is not running."
  echo "Start Docker Desktop or run: colima start"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  compose=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  compose=(docker-compose)
else
  echo "Docker Compose is not installed."
  echo "Install it with: brew install --formula docker-compose"
  exit 1
fi

"${compose[@]}" pull trendradar
"${compose[@]}" up -d trendradar
docker ps --filter "name=trendradar"

echo
echo "TrendRadar is starting."
echo "Open http://localhost:${WEBSERVER_PORT:-8080} after the first run finishes."
