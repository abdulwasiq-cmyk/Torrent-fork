#!/usr/bin/env bash
# Safe targeted cache scan. Does not search torrents, publish a bundle, deploy Render, or restart services.
# Usage: scripts/vps/cache_scan.sh missing|deep
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "missing" && "$MODE" != "deep" ]]; then
  echo "Usage: $0 missing|deep" >&2
  exit 2
fi

HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
REPO_DIR="$HOME_DIR/repo"
SEED_DIR="${REFRESH_SEED_DIR:-$HOME_DIR/seed}"
PYTHON="$HOME_DIR/venv/bin/python"
API_BASE="${HOME_API_BASE:-http://127.0.0.1:10000}"
LOCK_DIR="${XDG_RUNTIME_DIR:-/tmp}"
LOCK_FILE="$LOCK_DIR/torrent-studio-targeted-cache-scan.lock"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Repository checkout not found: $REPO_DIR" >&2
  exit 2
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Python environment not found: $PYTHON" >&2
  exit 2
fi
if [[ ! -d "$SEED_DIR" ]]; then
  echo "Cache seed directory not found: $SEED_DIR" >&2
  exit 2
fi

# Prevent two invocations of this new scanner from modifying the seed at once.
# This lock does not stop legacy refresh scripts that do not use the same lock.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another targeted cache scan is already running; refusing to overlap." >&2
  exit 3
fi

export REFRESH_SEED_DIR="$SEED_DIR"
export HOME_API_BASE="$API_BASE"

echo "Checking the existing API at $API_BASE ..."
curl --fail --silent --show-error --max-time 8 "$API_BASE/api/health" >/dev/null

echo "Starting '$MODE' cache scan."
"$PYTHON" "$REPO_DIR/scripts/cache_scan.py" "$MODE"

echo "Scan finished. No bundle was published and no deployment/restart was triggered."
echo "Updated seed: $SEED_DIR"
