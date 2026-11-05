# Bundled cache seed

Everything the app needs to show catalogues and title details **without calling any
provider** (TMDB, Watchmode, OMDb, IMDb, iTunes, NexStream). It ships inside the Docker
image so a fresh Render instance is fast from the first request.

## Layout

| Path | Contents |
|---|---|
| `*_catalogue.json` | Franchise / classics / latest catalogues (Marvel, DC, Bollywood, Hollywood, classics, TV). Rows already embed tmdbId, poster and overview. |
| `poster_map.json` | Title → poster URL lookups. |
| `regional_tv_prebuilt_cache.json` | Prebuilt regional TV pages. |
| `tmdb_ott_availability_cache.json` | OTT availability per title/region (`v2:<id>:<REGION>`). |
| `runtime/` | Files the app also *writes* at run time: TMDB catalogue pages, search metadata, regional movie pages, IMDb ratings, NexStream caches, TV caches. |

Run `python scripts/cache_report.py` for a per-file coverage table (rows, tmdbId, poster, overview).

## How it is used

1. On startup each seed file is copied into `APP_DATA_DIR` (default `/app/data`) **only if the
   destination does not already exist**; the OTT cache is merged. Anything the app learned at
   run time is therefore never overwritten by a redeploy.
2. With `CACHE_FIRST=true` (default) any stored entry — seed or runtime, any age — is served
   as-is. Providers are only asked for entries that do not exist. A user-triggered refresh
   (`force=true`, "clear TMDB cache") still bypasses this.
3. `CACHE_ONLY_MODE=true` (current Render setting) goes further: no provider calls at all.
4. `BACKFILL_MISSING_METADATA=false` additionally stops background gap-filling (synopsis / OTT).

| Env var | Default | Meaning |
|---|---|---|
| `CACHE_FIRST` | `true` | Serve stored data regardless of age. |
| `CACHE_ONLY_MODE` | `false` (`true` on Render) | Never call providers. |
| `BACKFILL_MISSING_METADATA` | `true` | Background enrichment of missing synopsis/OTT. |
| `APP_DATA_DIR` | `/app/data` | Runtime cache directory (point at a Render disk to keep it across deploys). |
| `CACHE_SEED_DIR` | `/app/cache-seed` | Where the seed is read from. |

## Torrent files (separate from the nine section files)

`<section>-torrents.json` (hollywood, bollywood, marvel, dc, highest-rated, korean, pakistani, anime,
favourites) hold the releases the **Prepare** button uses. They are per-title lookups, not catalogues:

```
{"schemaVersion": 2, "kind": "torrent-options", "section": "marvel", "trackers": [...shared...],
 "titles": {"movie:617126": {"title": "...", "year": 2025, "releases": [{"infoHash", "title", "size", "seeders", "leechers", "indexer", "infoUrl"}]}}}
```

How they are used, and the rules that keep the app fast:

1. The nine section files (`hollywood.json`, ...) stay metadata-only. `validate_section_caches.py` and
   `test_migrate_torrent_cache.py` fail if a torrent field ever appears in them.
2. Page loads and pagination only call `/api/sections/{section}` (one file per section, paged in the browser).
   Nothing in that path reads torrent data. `frontend/tests/torrentLookupGuard.test.mjs` enforces this.
3. Torrent data is requested only when a user clicks Prepare: `GET /api/sections/all/torrent-options?tmdb_id=&title=&year=`
   (`backend/catalogues/torrent_options.py`). Each file is parsed once and kept as a dict (about 2 MiB
   in memory, ~0.2 ms per lookup); it is re-read only when the file changes. No locks, no checksum
   pass, no per-request validation. Magnets are rebuilt from info hash + title + the shared trackers.
4. Prepare tries, in order: matches embedded in the card, `torrent-options`, then the older
   `/api/regional-movies/prebuilt` cache. A miss at any step simply falls through.
5. Keep them small: at most 10 releases per title (4 per resolution), only releases the Prepare card
   would show (size window from `search_limits.json`, no cam/telesync/screener, title in the release name).

Rebuild with `python3 -I scripts/migrate_torrent_cache.py` (reads the old data from git history and the
Bollywood/regional caches). For fresh data, feed new scan results into the same script rather than
adding torrent fields to the section files. Titles without releases (mostly 2026 releases, Korean,
Anime, Pakistani) need a new scan on the VPS.

## Known gaps

Three titles (43 rows) have no synopsis: *Doctor Strange: The Sorcerer Supreme*,
*Deathstroke: Knights & Dragons*, *The Raid: Redemption*. The Marvel movie catalogue only has
page 1 of an older variant. Both need a one-off refresh with real API keys
(`CACHE_ONLY_MODE=false`, `BACKFILL_MISSING_METADATA=true`), then commit the refreshed files.

## Tests

`backend/tests/test_cache_first.py` hits ~100 cached endpoints with all outbound HTTP blocked
and fails if any provider request is attempted.

## Hollywood and Bollywood paging

Each of the six regional catalogues (popular / trending / latest × Hollywood / Bollywood) has
**3 cached pages of 18 titles** (`REGIONAL_MOVIE_PREWARM_PAGES`). Pages 1–3 are served from the cache
and the UI is told a page 4 exists. From page 4 on the backend uses the API keys, continues
right after the cached titles (no repeats) and stores each fetched page so it is only fetched once.
The refresh (`scripts/build_regional_movie_cache.py`) builds each catalogue's finished list: it walks
candidates and keeps only titles with a torrent or a NexStream stream until 54 are found, then stores
them under `catalogues.<name>.final`; the app serves that list as-is. Trending is this week's list,
then earlier weeks from the weekly archive (each title shows the week it trended), then popular
titles to fill what is still missing. This week is added to the archive, so after some weeks the
fill is no longer needed.
This needs `CACHE_ONLY_MODE=false` and TMDB keys on Render (set in `render.yaml`).

## Keeping the data fresh (VPS → rolling GitHub release → Render)

GitHub never stores refreshed data in `main`'s history. Instead:

1. A cron job on the VPS runs `scripts/vps/refresh_and_publish.sh <group>`. It refreshes data with
   live API keys (`scripts/refresh_seed.py`), rebuilds the nine self-contained section documents
   from the persistent seed's `runtime/` metadata caches and `regional_tv_prebuilt_cache.json`,
   validates their API-required shape, then packs one `cache-bundle.tar.gz` + `cache-bundle.json`
   (checksum, version) with `scripts/make_cache_bundle.py`. The publisher uploads the versioned
   immutable archive before replacing the rolling manifest, so concurrent Render startups never
   pair a newly replaced archive with a stale manifest. The section migration writes only the
   nine section files, preserving the persistent episode and MAL mapping caches. It uploads the
   bundle to the rolling release `cache-data` using `scripts/publish_cache_bundle.py`. That
   publisher takes the immutable asset name directly from the manifest, verifies its checksum and
   GitHub release presence before replacing the legacy archive and rolling manifest, then confirms
   all three release assets exist. It calls the Render deploy hook only after those checks pass.
   `scripts/make_cache_bundle.py` repeats the self-contained shape check and repairs legacy
   section documents from those same local caches before packaging, protecting runs launched by
   an older copy of the VPS publisher script.
2. When the Render container starts, `maintenance/fetch_cache_bundle.py` downloads the bundle,
   verifies the checksum, refuses anything unsafe or not valid JSON, and overlays it on the seed
   baked into the image. If anything fails it prints why and the baked seed is used.
3. The app then seeds `APP_DATA_DIR` from it as before and serves everything from local files.

| Group | Suggested schedule | Refreshes |
|---|---|---|
| `hollywood-bollywood` | weekly cron | Regional movie/TV pages, trending archive, shared metadata/OTT/IMDb entries (set `REGIONAL_CACHE_TORRENT_SCAN=false` to skip the slow torrent re-scan) |
| `franchise` | run by hand when wanted | Missing OTT data and synopses for Marvel, DC and classics |
| `imdb-dataset` | by hand (also part of both groups above) | IMDb ratings for every movie, web series and anime from IMDb's free dataset (personal, non-commercial use only), then Cinemeta for what the dataset lacks; no OMDb key needed |
| `tv-imdb` | by hand | Only the OMDb lookups for web series/anime |
| `publish-only` | by hand | Re-publish the VPS working copy |

The VPS keeps its own working copy of the seed (`~/torrent-studio-refresh/seed`), so each group's
results survive the other group's runs. Set `CACHE_BUNDLE_BASE_URL=off` on Render to disable the
download.

### VPS setup (Oracle, Ubuntu)

```sh
sudo apt-get update && sudo apt-get install -y git python3-venv curl gh
mkdir -p ~/.config/torrent-studio && chmod 700 ~/.config/torrent-studio
cat > ~/.config/torrent-studio/env <<'EOF'
TMDB_READ_ACCESS_TOKENS=token1,token2,token3   # one kind is enough; TMDB_API_KEYS works too
WATCHMODE_API_KEY=...
OMDB_API_KEY=...
GH_TOKEN=...            # fine-grained token, this repo only, Contents: read and write
RENDER_DEPLOY_HOOK=...  # Render service -> Settings -> Deploy Hook
REGIONAL_CACHE_TORRENT_SCAN=true
EOF
chmod 600 ~/.config/torrent-studio/env
git clone https://github.com/wroxtaaar/Torrent-Studio.git ~/ts && cd ~/ts
crontab -l 2>/dev/null; (crontab -l 2>/dev/null; echo '0 3 * * 1 /home/ubuntu/ts/scripts/vps/refresh_and_publish.sh hollywood-bollywood >> /home/ubuntu/refresh.log 2>&1') | crontab -
```

Run `scripts/vps/refresh_and_publish.sh publish-only` once to publish the first bundle, and
`scripts/vps/refresh_and_publish.sh franchise` whenever Marvel/DC/classics need an update.
The VPS makes only outbound connections, so no domain, certificate or open port is needed.

### TV / web series: season packs (same nine torrent files)

The `<section>-torrents.json` files also hold `"tv:<tmdbId>"` entries (season packs and
complete-series packs; each release has `scope` = `season` | `complete` and `season` = N, no size window).

* Served by `GET /api/sections/{section}/torrent-options?media=tv&tmdb_id=...` (`section` may be `all`).
* UI: tapping a series card looks the series up once (`tvTorrentStore.ts`, cached per session).
  Packs found: a second card opens with **Play** (the existing NexStream / VidRift / Yenime flow) and
  **Webtor** (copies the selected pack's magnet, opens webtor.io, the user pastes it to stream or download).
  No packs: the tap plays immediately, exactly as before. Page loads and pagination never touch these files.
* Fill the data on the VPS (needs network): `python3 -I scripts/build_tv_torrent_cache.py --section hollywood --limit 5 --dry-run`
  to look first, then without `--dry-run` / `--limit`. It is resumable and never touches movie entries.

### Size window (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB)

Which releases the Prepare card shows by size is one setting, read once in `backend/core/settings.py`
(env vars win, then `search_limits.json`; default 250 MB .. 2 GB). Change it with an env var and restart:
`TORRENT_MAX_SIZE_GB=5` (decimals allowed). It is applied in layers, each as early as it can be without
dropping anything relevant:

1. **Search providers** (`search_providers.py`, `_in_size_window`): each provider drops out-of-window rows
   *before* sorting and truncating to its `limit`, so a 4 GB release cannot take a slot an in-window one could use.
2. **Merge gate** (`_search_quality_filter`) and the catalogue/prebuilt readers (`misc_routes`, `catalogues_extra`): same constants.
3. **Cached torrent files** (`torrent_options.lookup`): the window is applied while a title is served, *before*
   the 12-result cap. The files store a wider range (100 MB .. 10 GB, kept per size band so big releases cannot
   crowd out smaller ones), so raising the limit reveals data that is already stored.
4. **Browser**: `index.html` is served with `window.__SEARCH_LIMITS__` (no extra request); the Prepare filters and the
   Prepare-card cache key use it, so a changed window never reuses results cached under another one.

TV season packs (Webtor) are not size-filtered. To store a different range, rebuild with
`TORRENT_CACHE_MAX_SIZE_GB=12 python3 -I scripts/migrate_torrent_cache.py` (this keeps the `tv:` entries).
