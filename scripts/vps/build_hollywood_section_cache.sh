#!/usr/bin/env bash
# Build the self-contained Hollywood section cache only.
# This does not search torrents, publish a release, or restart/deploy the app.
set -euo pipefail

HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
REPO_DIR="$HOME_DIR/repo"
SEED_DIR="${REFRESH_SEED_DIR:-$HOME_DIR/seed}"
API_BASE="${HOME_API_BASE:-http://127.0.0.1:10000}"
MODE="${1:-missing}"

case "$MODE" in
  missing|deep) ;;
  *) echo "Usage: $0 [missing|deep]" >&2; exit 2 ;;
esac

if [ ! -d "$REPO_DIR/.git" ]; then
  echo "Repository checkout not found: $REPO_DIR" >&2
  exit 2
fi
if [ ! -x "$HOME_DIR/venv/bin/python" ]; then
  echo "Python environment not found: $HOME_DIR/venv/bin/python" >&2
  exit 2
fi
if [ ! -d "$SEED_DIR" ]; then
  echo "Seed directory not found: $SEED_DIR" >&2
  exit 2
fi

export HOME_API_BASE="$API_BASE"
export REFRESH_SEED_DIR="$SEED_DIR"
export PYTHONUNBUFFERED=1

echo "Checking existing API at $API_BASE ..."
curl --fail --silent --show-error "$API_BASE/api/health" >/dev/null

echo "Migrating existing Hollywood torrent records first (no provider searches)..."
"$HOME_DIR/venv/bin/python" "$REPO_DIR/scripts/build_hollywood_torrent_cache.py" "$MODE"
echo
echo "Building Hollywood metadata cache separately..."
"$HOME_DIR/venv/bin/python" "$REPO_DIR/scripts/build_hollywood_section_cache.py" "$MODE"

echo
echo "Hollywood cache build finished. No torrent searches, publishing, deployment, or restart was performed."
echo "Metadata: $SEED_DIR/hollywood.json"
echo "Torrents: $SEED_DIR/hollywood-torrents.json"
