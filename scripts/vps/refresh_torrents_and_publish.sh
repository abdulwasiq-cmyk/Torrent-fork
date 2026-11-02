#!/usr/bin/env bash
# Explicit torrent-only refresh. This is intentionally not installed by install_schedule.sh.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
SEED_DIR="${REFRESH_SEED_DIR:-$HOME_DIR/seed}"
PY="$HOME_DIR/venv/bin/python"
REPO="wroxtaaar/Torrent-Studio"
OUT_DIR="$HOME_DIR/out-torrent-cache"

[ -x "$PY" ] || { echo "Python environment not found: $PY" >&2; exit 2; }
[ -d "$SEED_DIR" ] || { echo "Torrent cache seed not found: $SEED_DIR" >&2; exit 2; }

mkdir -p "$HOME_DIR" "$OUT_DIR"
exec 9>"$HOME_DIR/.torrent-refresh.lock"
if ! flock -n 9; then
  echo "Another torrent refresh or publication is already running." >&2
  exit 3
fi

if [ -f "$HOME/.config/torrent-studio/env" ]; then
  eval "$(python3 "$REPO_DIR/scripts/vps/load_env.py" "$HOME/.config/torrent-studio/env")"
fi
API_BASE="${TORRENT_CACHE_API_BASE:-${HOME_API_BASE:-http://127.0.0.1:3000}}"
export REFRESH_SEED_DIR="$SEED_DIR"
export TORRENT_REFRESH_LOCK_HELD=1

echo "Checking torrent search API at $API_BASE ..."
curl --fail --silent --show-error --max-time 8 "$API_BASE/api/health" >/dev/null

"$PY" "$REPO_DIR/scripts/refresh_torrent_cache.py" \
  --seed-dir "$SEED_DIR" \
  --api-base "$API_BASE"

GENERATION="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["generation"])' \
  "$SEED_DIR/torrent-cache-manifest.json")"
"$PY" "$REPO_DIR/scripts/make_torrent_cache_bundle.py" \
  "$SEED_DIR" "$OUT_DIR" --generation "$GENERATION"

if ! gh release view cache-data -R "$REPO" >/dev/null 2>&1; then
  gh release create cache-data -R "$REPO" --title "Cache data (rolling)" \
    --notes "Independent metadata and torrent manifests with immutable, versioned bundles." || \
    gh release view cache-data -R "$REPO" >/dev/null
fi
"$PY" "$REPO_DIR/scripts/publish_torrent_cache_bundle.py" \
  --manifest "$OUT_DIR/torrent-cache-bundle.json" \
  --repository "$REPO"

echo "Torrent-only cache refresh and publication finished. No metadata files or deployment were changed."
