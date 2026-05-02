#!/bin/bash
# ── QUAEST.TECH Deploy Script ──
# Builds frontend locally, rsyncs dist/ to droplet, restarts backend.
# Avoids building on the 1GB droplet (28-min OOM risk with Vite).
#
# Usage:
#   ./deploy.sh            # full deploy (build + rsync + restart)
#   ./deploy.sh --api-only # skip frontend build, just pull + restart backend
#   ./deploy.sh --fe-only  # build + rsync frontend only, no backend restart

set -euo pipefail

REMOTE="root@64.23.150.209"
APP_DIR="/opt/cyberscreener"
FE_DIR="$APP_DIR/frontend/dist"

MODE="${1:-}"

echo "🚀 Deploying QUAEST.TECH → $REMOTE"

# ── Push code to GitHub ──
echo "📦 Pushing to GitHub..."
cd "$(dirname "$0")"
git push github main

if [[ "$MODE" != "--api-only" ]]; then
  # ── Build frontend locally ──
  echo "🔨 Building frontend locally..."
  cd frontend
  npm run build
  cd ..

  # ── Rsync dist/ to droplet ──
  echo "📡 Syncing dist/ to droplet..."
  rsync -az --delete frontend/dist/ "$REMOTE:$FE_DIR/"
  echo "✅ Frontend synced"
fi

if [[ "$MODE" != "--fe-only" ]]; then
  # ── Pull latest code + restart backend ──
  echo "🔄 Restarting backend..."
  ssh "$REMOTE" "cd $APP_DIR && git pull origin main && systemctl restart cyberscreener.service cyberscreener-scheduler.service"
  echo "✅ Backend restarted"
fi

echo ""
echo "✅ Deployed → https://quaest.tech"
