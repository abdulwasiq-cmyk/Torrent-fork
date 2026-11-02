#!/usr/bin/env bash
# Build the per-section metadata caches (<section>.json for the nine top sections) on the VPS.
# Metadata only: no torrent search, nothing is published, no Render deploy.
#
#   scripts/vps/build_section_caches.sh                 # new-section sources -> split -> enrich -> validate
#   SKIP_NEW_SOURCES=1 scripts/vps/build_section_caches.sh   # reuse the sources already in the seed
#   SKIP_ENRICH=1      scripts/vps/build_section_caches.sh   # offline only (split + validate)
#   SECTION_METADATA_MODE=deep scripts/vps/build_section_caches.sh  # recheck available metadata
#
# Needs the app running with provider access (CACHE_ONLY_MODE=false) for the new-sources and enrich steps.
# HOME_API_BASE is used when set; otherwise the app is looked for on port 3000.
set -euo pipefail

HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
REPO_DIR="$HOME_DIR/repo"
SEED_DIR="${REFRESH_SEED_DIR:-$HOME_DIR/seed}"
PY="$HOME_DIR/venv/bin/python"
SECTIONS="marvel dc hollywood bollywood korean pakistani anime favourites highest-rated"

[ -d "$REPO_DIR/.git" ] || { echo "Repository checkout not found: $REPO_DIR" >&2; exit 2; }
[ -x "$PY" ] || { echo "Python environment not found: $PY" >&2; exit 2; }
[ -d "$SEED_DIR" ] || { echo "Seed directory not found: $SEED_DIR" >&2; exit 2; }

step() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }

if [ "${SKIP_ENRICH:-0}" != "1" ] || [ "${SKIP_NEW_SOURCES:-0}" != "1" ]; then
  if [ -z "${HOME_API_BASE:-}" ]; then
    if curl -fsS --max-time 5 "http://127.0.0.1:3000/api/health" >/dev/null 2>&1; then
      HOME_API_BASE="http://127.0.0.1:3000"
    fi
  fi
  [ -n "${HOME_API_BASE:-}" ] || { echo "The app is not answering on port 3000. Start it or set HOME_API_BASE." >&2; exit 2; }
  curl -fsS --max-time 10 "$HOME_API_BASE/api/health" >/dev/null || { echo "Health check failed at $HOME_API_BASE" >&2; exit 2; }
  export HOME_API_BASE
  step "Using the app at $HOME_API_BASE"
fi
export REFRESH_SEED_DIR="$SEED_DIR"

BACKUP="$HOME_DIR/backups/sections-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
for s in $SECTIONS; do [ -f "$SEED_DIR/$s.json" ] && cp "$SEED_DIR/$s.json" "$BACKUP/"; done
step "Existing section files backed up to $BACKUP"

if [ "${SKIP_NEW_SOURCES:-0}" != "1" ]; then
  step "1/4 Korean, Pakistani, Anime and Highest Rated source catalogues (metadata only)"
  "$PY" "$REPO_DIR/scripts/build_new_sections_cache.py"
fi

step "2/4 Splitting the sources into one metadata file per top section (offline)"
"$PY" "$REPO_DIR/scripts/split_top_section_caches.py"

if [ "${SKIP_ENRICH:-0}" != "1" ]; then
  step "3/4 Filling missing IDs, ratings and streaming info (TMDB / IMDb metadata only)"
  "$PY" "$REPO_DIR/scripts/enrich_top_section_metadata.py" \
    --mode "${SECTION_METADATA_MODE:-missing}"
fi

step "4/4 Validating the section files"
REQUIRE=""; [ "${SKIP_NEW_SOURCES:-0}" = "1" ] || REQUIRE="--require-all"  # with fresh sources every section must exist
if "$PY" "$REPO_DIR/scripts/validate_section_caches.py" --seed "$SEED_DIR" $REQUIRE; then
  step "Done. Files are in $SEED_DIR (previous versions in $BACKUP). Nothing was published."
else
  step "Validation FAILED (see above). Previous versions are in $BACKUP; nothing was published."
  exit 1
fi
