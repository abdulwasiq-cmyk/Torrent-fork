#!/usr/bin/env bash
# Run on the VPS (cron). Refreshes cache data, publishes ONE bundle to a rolling GitHub
# release (old asset replaced, so GitHub never accumulates history), then asks Render to restart.
#
#   refresh_and_publish.sh hollywood-bollywood     # weekly
#   refresh_and_publish.sh franchise               # when you want Marvel/DC/classics updated
#   refresh_and_publish.sh classics                # only the Classics lists (much quicker)
#   refresh_and_publish.sh episode-metadata         # explicitly build/publish the TV episode cache
#   refresh_and_publish.sh publish-only            # just re-publish the current working copy
#
# Config in ~/.config/torrent-studio/env (chmod 600):
#   TMDB_API_KEY=... TMDB_READ_ACCESS_TOKEN=... WATCHMODE_API_KEY=... OMDB_API_KEY=...
#   GH_TOKEN=<fine-grained token: Contents read/write on this repo>
#   RENDER_DEPLOY_HOOK=https://api.render.com/deploy/srv-...?key=...
set -euo pipefail
# Everything runs inside a function so that `git pull` replacing this file mid-run is harmless.
main() {
GROUP="${1:?usage: $0 hollywood-bollywood|franchise|classics|tv-imdb|imdb-dataset|episode-metadata|publish-only}"
REPO="wroxtaaar/Torrent-Studio"
HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
mkdir -p "$HOME_DIR"; cd "$HOME_DIR"
if [ ! -d repo/.git ]; then git clone --depth 1 "https://github.com/$REPO.git" repo; fi
# fetch + reset (not pull): a plain pull fails on a shallow clone with "Cannot fast-forward to multiple branches"
git -C repo fetch -q --depth 1 origin main
git -C repo reset -q --hard FETCH_HEAD
# Load keys (repeated TMDB_READ_ACCESS_TOKEN lines are all kept, not just the last one).
eval "$(python3 repo/scripts/vps/load_env.py "$HOME/.config/torrent-studio/env")"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q -r repo/backend/requirements.txt

# The working copy persists between runs so the weekly and manual refreshes both keep their results.
export REFRESH_SEED_DIR="$HOME_DIR/seed"
[ -d "$REFRESH_SEED_DIR" ] || cp -r repo/backend/cache-seed "$REFRESH_SEED_DIR"

if [ "$GROUP" != "publish-only" ]; then
  if [ "$GROUP" = "episode-metadata" ]; then
    ./venv/bin/python repo/scripts/build_episode_metadata_cache.py \
      --seed-dir "$REFRESH_SEED_DIR" \
      --cache-path "$REFRESH_SEED_DIR/runtime/nexstream_episode_metadata_cache.json" \
      --allow-live-tmdb \
      --allow-live-anilist
  else
    ./venv/bin/python repo/scripts/refresh_seed.py "$GROUP"
  fi
fi

# Build self-contained section documents from the persistent seed and its runtime metadata caches.
# The builder writes only the nine section JSON files; episode and MAL caches remain untouched.
./venv/bin/python repo/scripts/build_self_contained_section_cache.py \
  --source-dir "$REFRESH_SEED_DIR" \
  --cache-dir "$REFRESH_SEED_DIR/runtime" \
  --regional-tv-cache "$REFRESH_SEED_DIR/regional_tv_prebuilt_cache.json" \
  --output-dir "$REFRESH_SEED_DIR"
./venv/bin/python repo/scripts/validate_section_caches.py \
  --seed "$REFRESH_SEED_DIR" \
  --require-all \
  --require-self-contained

rm -rf out; ./venv/bin/python repo/scripts/make_cache_bundle.py "$REFRESH_SEED_DIR" out

gh release view cache-data -R "$REPO" >/dev/null 2>&1 || \
  gh release create cache-data -R "$REPO" --title "Cache data (rolling)" \
    --notes "Rolling cache manifest with immutable, versioned cache bundle assets."
# The publisher reads the exact bundle filename from the manifest, verifies its checksum and
# release presence, then updates the legacy asset and manifest in that order.
./venv/bin/python repo/scripts/publish_cache_bundle.py \
  --manifest out/cache-bundle.json \
  --legacy-bundle out/cache-bundle.tar.gz \
  --repository "$REPO"

curl -fsS -X POST "$RENDER_DEPLOY_HOOK" >/dev/null && echo "Render deploy triggered"
}
main "$@"
exit $?
