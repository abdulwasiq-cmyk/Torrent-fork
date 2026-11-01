#!/usr/bin/env bash
# Build only the new catalogue metadata caches and a selective bundle.
# This does NOT search torrents, publish a release, or trigger a Render deploy.
set -euo pipefail

HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
REPO_DIR="$HOME_DIR/repo"
SEED_DIR="${REFRESH_SEED_DIR:-$HOME_DIR/seed}"
API_BASE="${HOME_API_BASE:-http://127.0.0.1:10000}"

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

echo "Checking the existing API at $API_BASE ..."
curl --fail --silent --show-error "$API_BASE/api/health" >/dev/null

echo "Building selected catalogue metadata only (torrent scans are not called)..."
"$HOME_DIR/venv/bin/python" "$REPO_DIR/scripts/build_new_sections_cache.py"

echo "Packing only the two merged regional cache documents..."
OUT_DIR="$HOME_DIR/out-new-sections"
rm -rf "$OUT_DIR"
"$HOME_DIR/venv/bin/python" "$REPO_DIR/scripts/make_new_sections_cache_bundle.py" "$SEED_DIR" "$OUT_DIR"

echo
echo "Build complete. Nothing has been published or deployed."
echo "Seed updated: $SEED_DIR"
echo "Selective bundle: $OUT_DIR/cache-bundle.tar.gz"
echo "Bundle manifest: $OUT_DIR/cache-bundle.json"
