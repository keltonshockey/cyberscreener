#!/bin/bash
# ── QUAEST.TECH Deploy Script ──
# Deploys to DigitalOcean droplet via Docker
# Usage: ./deploy.sh [user@host]
#
# Prerequisites on the droplet:
#   - Docker & Docker Compose installed
#   - Nginx installed (reverse proxy to :8000)
#   - SSL via certbot/Let's Encrypt for cyber.keltonshockey.com

set -euo pipefail

# ── Config ──
REMOTE="${1:-root@cyber.keltonshockey.com}"
APP_DIR="/opt/cyberscreener"
IMAGE_NAME="cyberscreener"

echo "🚀 Deploying QUAEST.TECH to $REMOTE"

# ── 1. Push latest code to GitHub ──
echo "📦 Pushing to GitHub..."
git push origin main

# ── 2. Pull on server & rebuild ──
echo "🔨 Building on server..."
ssh "$REMOTE" bash -s "$APP_DIR" "$IMAGE_NAME" << 'DEPLOY_SCRIPT'
APP_DIR="$1"
IMAGE_NAME="$2"

cd "$APP_DIR"
git pull origin main

# Build the Docker image (multi-stage: builds frontend + API)
docker build -t "$IMAGE_NAME" .

# Stop old container, start new one
docker stop "$IMAGE_NAME" 2>/dev/null || true
docker rm "$IMAGE_NAME" 2>/dev/null || true

docker run -d \
  --name "$IMAGE_NAME" \
  --restart unless-stopped \
  -p 8000:8000 \
  -v cyberscreener-data:/data/db \
  --env-file .env \
  "$IMAGE_NAME"

# Prune old images
docker image prune -f

echo "✅ Container running:"
docker ps --filter name="$IMAGE_NAME" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
DEPLOY_SCRIPT

echo "✅ Deployed to https://cyber.keltonshockey.com"
