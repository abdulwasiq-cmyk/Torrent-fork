"""Moved out of main.py (see docs/main-split-plan.md)."""

import json
import logging
import os
import re
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}


def env_values(*names: str) -> list[str]:
    """All credentials for the given variable names, so several keys/tokens can be supplied.

    For each NAME this reads NAME itself plus numbered variants (NAME_2, NAME2, NAME_3 ...), and
    every value may hold several entries separated by commas, semicolons, spaces or new lines.
    """
    found: list[str] = []
    for name in names:
        variants = sorted(
            (key for key in os.environ if re.fullmatch(re.escape(name) + r"_?\d+", key)),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        for key in [name, *variants]:
            for item in re.split(r"[,;\s]+", os.getenv(key, "").replace("\\n", " ")):
                item = item.strip().strip("\"'")
                if item and item not in found:
                    found.append(item)
    return found
# Cache-only deployments (e.g. Render free without provider keys) must never
# call TMDB/Watchmode/OMDb/poster providers; prefilled sections read the bundled cache.
_PROVIDER_KEY_ENV_NAMES = (
    "TMDB_API_KEY", "TMDB_API_KEYS", "TMDB_READ_ACCESS_TOKEN", "TMDB_READ_ACCESS_TOKENS",
    "WATCHMODE_API_KEY", "WATCHMODE_API_KEYS", "OMDB_API_KEY", "OMDB_API_KEYS",
)
_CACHE_ONLY_ENV = os.getenv("CACHE_ONLY_MODE", "").strip().casefold()
if _CACHE_ONLY_ENV in _TRUTHY or os.getenv("OTT_CACHE_ONLY", "false").strip().casefold() in _TRUTHY:
    CACHE_ONLY_MODE = True
elif _CACHE_ONLY_ENV in {"0", "false", "no", "off"}:
    CACHE_ONLY_MODE = False
else:
    # No explicit setting: a deployment without any provider key can only serve
    # from the bundled cache, so behave as cache-only instead of failing live calls.
    CACHE_ONLY_MODE = not any(env_values(name) for name in _PROVIDER_KEY_ENV_NAMES)


# Cache-first (default on): an entry that is already stored -- in the bundled seed or in the
# runtime cache -- is served as-is, however old, and providers are only asked for entries that
# do not exist yet. No TTL expiry, no background refresh of existing entries. Set
# CACHE_FIRST=false to get the older "expire and refresh" behaviour back. A user-triggered
# refresh (force=true, "clear TMDB cache") still bypasses the cache on purpose.
CACHE_FIRST = os.getenv("CACHE_FIRST", "true").strip().casefold() not in {"0", "false", "no", "off"}
_CACHE_FOREVER_SECONDS = 20 * 365 * 24 * 60 * 60


def stored_ttl(seconds: float) -> float:
    """TTL to use for stored provider data: effectively unlimited when CACHE_FIRST is on."""
    return float(_CACHE_FOREVER_SECONDS) if CACHE_FIRST else seconds


# Filling GAPS (titles that have no synopsis / OTT / rating stored yet) is separate from
# refreshing what is stored. Leave it on to let the app complete its cache over time; turn it
# off (BACKFILL_MISSING_METADATA=false) for a deployment that must not contact providers at all.
BACKFILL_MISSING_METADATA = (
    False if CACHE_ONLY_MODE else
    os.getenv("BACKFILL_MISSING_METADATA", "true").strip().casefold() not in {"0", "false", "no", "off"}
)


# One place for the runtime data directory (Render: mount a disk and set APP_DATA_DIR).
# Individual files can still be overridden with their own environment variable.
DATA_DIR = Path(os.getenv("APP_DATA_DIR", "/app/data"))


def data_file(name: str) -> str:
    return str(DATA_DIR / name)


APP_NAME = "Torrent Studio API"
logger = logging.getLogger("torrent-studio")


def log_cache_only_metadata_block(provider: str, *, enabled: bool | None = None) -> bool:
    """Log and report metadata-provider requests blocked by strict cache-only mode."""
    if not (CACHE_ONLY_MODE if enabled is None else enabled):
        return False
    normalized = str(provider or "").strip().casefold()
    if normalized in {"imdb", "omdb"}:
        logger.info("[CACHE-ONLY] IMDb lookup blocked")
    elif normalized in {"ott", "watchmode", "streaming availability"}:
        logger.info("[CACHE-ONLY] OTT lookup blocked")
    else:
        name = "TMDB" if normalized == "tmdb" else str(provider or "unknown").strip()
        logger.info("[CACHE-ONLY] Metadata lookup blocked: provider=%s", name)
    return True


# TMDB provides dynamic, paginated movie discovery. Credentials stay server-side;
# use a free developer key for non-commercial use or the API Read Access Token.
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
def _split_env_keys(*values: str) -> list[str]:
    return list(dict.fromkeys(item.strip() for value in values
        for item in str(value or "").replace("\\n", "\n").replace(",", "\n").splitlines()
        if item.strip()))

TMDB_API_KEYS = env_values("TMDB_API_KEYS", "TMDB_API_KEY")
TMDB_READ_ACCESS_TOKENS = env_values("TMDB_READ_ACCESS_TOKENS", "TMDB_READ_ACCESS_TOKEN", "TMDB_BEARER_TOKEN")
TMDB_READ_ACCESS_TOKEN = TMDB_READ_ACCESS_TOKENS[0] if TMDB_READ_ACCESS_TOKENS else ""
TMDB_API_BASE = "https://api.themoviedb.org/3"
WATCHMODE_API_KEYS = env_values("WATCHMODE_API_KEYS", "WATCHMODE_API_KEY")
WATCHMODE_API_KEY = WATCHMODE_API_KEYS[0] if WATCHMODE_API_KEYS else ""
WATCHMODE_API_BASE = "https://api.watchmode.com/v1"
STREAMING_AVAILABILITY_API_KEY = os.getenv("STREAMING_AVAILABILITY_API_KEY", "").strip()
STREAMING_AVAILABILITY_API_BASE = "https://api.movieofthenight.com/v4"


TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


# If TMDB API connections are reset before TLS completes# If TMDB API connections are reset before TLS completes, pause new API attempts
# briefly so catalogue requests fail fast and can fall back to persistent caches.
TMDB_API_CONNECT_FAILURE_COOLDOWN_SECONDS = max(15, int(os.getenv("TMDB_API_CONNECT_FAILURE_COOLDOWN_SECONDS", "60")))


TMDB_CATALOGUE_CACHE_SECONDS = stored_ttl(max(300, int(os.getenv("TMDB_CATALOGUE_CACHE_SECONDS", str(6 * 60 * 60)))))
REGIONAL_MOVIE_CACHE_TTL_SECONDS = stored_ttl(7 * 24 * 60 * 60)
REGIONAL_MOVIE_CACHE_PAGE_SIZE = 18
REGIONAL_MOVIE_PREWARM_PAGES = 3
# Cached Hollywood/Bollywood titles must have at least one torrent or be playable on NexStream.
REGIONAL_CACHE_REQUIRE_SOURCE = os.getenv("REGIONAL_CACHE_REQUIRE_SOURCE", "true").strip().casefold() not in {"0", "false", "no", "off"}
REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE = Path(os.getenv(
    "REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE",
    data_file("regional_movie_trending_archive.json"),
))
REGIONAL_MOVIE_TRENDING_ARCHIVE_WEEKS = 52
REGIONAL_MOVIE_CATALOGUE_KEYS = (
    "highest-rated-hollywood",
    "highest-rated-bollywood",
    "popular-hollywood",
    "trending-hollywood",
    "latest-hollywood",
    "popular-bollywood",
    "trending-bollywood",
    "latest-bollywood",
    "popular-korean",
    "popular-anime", "trending-anime", "latest-anime",
)
TMDB_COMPANY_CACHE_SECONDS = stored_ttl(max(3600, int(os.getenv("TMDB_COMPANY_CACHE_SECONDS", str(24 * 60 * 60)))))
TMDB_CATALOGUE_CACHE_FILE = Path(os.getenv("TMDB_CATALOGUE_CACHE_FILE", data_file("tmdb_movie_catalogue_cache.json")))
TMDB_SEARCH_METADATA_CACHE_FILE = Path(os.getenv("TMDB_SEARCH_METADATA_CACHE_FILE", data_file("tmdb_search_metadata_cache.json")))
TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS = stored_ttl(max(3600, int(os.getenv("TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS", str(30 * 24 * 60 * 60)))))
IMDB_RATING_CACHE_FILE = Path(os.getenv("IMDB_RATING_CACHE_FILE", data_file("imdb_rating_cache.json")))
IMDB_RATING_CACHE_TTL_SECONDS = stored_ttl(max(86400, int(os.getenv("IMDB_RATING_CACHE_TTL_SECONDS", str(30 * 24 * 60 * 60)))))
IMDB_RATING_LOOKUP_VERSION = 7  # 7: resolve IMDb ratings by the exact TMDB-linked IMDb ID before title search
# Misses are re-checked sooner than hits: OMDb data and title matching improve over time.
IMDB_RATING_NOT_FOUND_TTL_SECONDS = stored_ttl(max(3600, int(os.getenv("IMDB_RATING_NOT_FOUND_TTL_SECONDS", str(24 * 60 * 60)))))


TMDB_SYNOPSIS_LOOKUP_VERSION = 5
SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS = max(300, int(os.getenv("SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS", "900")))
TMDB_OTT_CACHE_SECONDS = stored_ttl(max(3600, int(os.getenv("TMDB_OTT_CACHE_SECONDS", str(24 * 60 * 60)))))
# Results with no provider names (not_confirmed, release dates only) may just mean the
# upstream lookup missed or failed, so they are re-checked much sooner than hits.
# Partial lookups (a provider errored) are kept too under cache-first: set CACHE_FIRST=false or
# call /api/movies/ott/<id>?force=true to re-check one.
TMDB_OTT_INCOMPLETE_CACHE_SECONDS = stored_ttl(max(300, int(os.getenv("TMDB_OTT_INCOMPLETE_CACHE_SECONDS", "1800"))))
TMDB_OTT_MISSING_CACHE_SECONDS = stored_ttl(max(900, int(os.getenv("TMDB_OTT_MISSING_CACHE_SECONDS", str(6 * 60 * 60)))))
TMDB_OTT_CACHE_FILE = Path(os.getenv("TMDB_OTT_CACHE_FILE", data_file("tmdb_ott_availability_cache.json")))
MARVEL_TV_CATALOGUE_CACHE_FILE = Path(os.getenv("MARVEL_TV_CATALOGUE_CACHE_FILE", data_file("marvel_tv_catalogue_cache.json")))
DC_TV_CATALOGUE_CACHE_FILE = Path(os.getenv("DC_TV_CATALOGUE_CACHE_FILE", data_file("dc_tv_catalogue_cache.json")))


GITHUB_FEEDBACK_TOKEN = os.getenv("GITHUB_FEEDBACK_TOKEN", "").strip()
GITHUB_FEEDBACK_REPO = os.getenv("GITHUB_FEEDBACK_REPO", "wroxtaaar/new-test").strip()
SEEDR_BASE = "https://www.seedr.cc/api/v0.1/p"
SEEDR_MEDIA_BASE = "https://www.seedr.cc/api"
SEEDR_V2_BASE = "https://v2.seedr.cc/api/v0.1/p"
SEEDR_PAT_BASE = "https://www.seedr.cc/api/v0.1/p"
# Legacy developer-level Seedr credentials remain supported only when explicitly enabled.
# Normal requests use a per-browser Seedr connection established through device auth.
SEEDR_TOKEN = os.getenv("SEEDR_API_TOKEN", "").strip()
ALLOW_LEGACY_SEEDR_TOKEN = os.getenv("ALLOW_LEGACY_SEEDR_TOKEN", "false").strip().lower() in {"1", "true", "yes", "on"}
# A shared folder ID cannot be used safely across different users. Personal
# connections always start at each Seedr account's own root folder.
SEEDR_LIBRARY_FOLDER_ID = "0"
SEEDR_DEVICE_CLIENT_ID = os.getenv("SEEDR_DEVICE_CLIENT_ID", "seedr_xbmc").strip() or "seedr_xbmc"
SEEDR_DEVICE_CODE_URL = "https://www.seedr.cc/api/device/code"
SEEDR_DEVICE_AUTHORIZE_URL = "https://www.seedr.cc/api/device/authorize"
SEEDR_SESSION_COOKIE = os.getenv("SEEDR_SESSION_COOKIE", "torrent_studio_seedr_session").strip() or "torrent_studio_seedr_session"
SEEDR_SESSION_TTL_SECONDS = int(float(os.getenv("SEEDR_SESSION_TTL_SECONDS", str(30 * 24 * 60 * 60))))
# The bundled frontend is served from the same origin, so Lax is enough and gives
# better CSRF protection. Set SEEDR_SESSION_SAMESITE=none only if the frontend is
# hosted on a different origin (and list that origin in CORS_ORIGINS).
SEEDR_SESSION_SAMESITE = os.getenv("SEEDR_SESSION_SAMESITE", "lax").strip().lower()
if SEEDR_SESSION_SAMESITE not in {"lax", "strict", "none"}:
    SEEDR_SESSION_SAMESITE = "lax"
# Diagnostic endpoints that reveal server internals are off unless explicitly enabled.
DEBUG_ENDPOINTS_ENABLED = os.getenv("DEBUG_ENDPOINTS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

# Simple in-memory sliding-window limiter for the public feedback endpoint.
FEEDBACK_RATE_LIMIT = int(os.getenv("FEEDBACK_RATE_LIMIT", "5"))
FEEDBACK_RATE_WINDOW_SECONDS = int(os.getenv("FEEDBACK_RATE_WINDOW_SECONDS", "3600"))
FEEDBACK_GLOBAL_RATE_LIMIT = int(os.getenv("FEEDBACK_GLOBAL_RATE_LIMIT", "100"))


SEEDR_SESSION_SECRET = os.getenv("SEEDR_SESSION_SECRET", "").strip()


SEARCH_STOPWORDS = {"the", "a", "an", "movie", "film", "series", "season", "episode", "web", "show", "tv"}
TORRENT_SEARCH_API_URL = os.getenv("TORRENT_SEARCH_API_URL", "https://torrent-search-api-ujfa.onrender.com").rstrip("/")
KNABEN_API_URL = os.getenv("KNABEN_API_URL", "https://api.knaben.org/v2/search").rstrip("/")
TORRENT_METADATA_API_URL = os.getenv("TORRENT_METADATA_API_URL", "https://torrentmeta.fly.dev").rstrip("/")
FAST_SEARCH_TEST_URL = os.getenv("FAST_SEARCH_TEST_URL", "https://torrent-search-test.onrender.com").rstrip("/")
SEARCH_SOURCE_TIMEOUT_SECONDS = float(os.getenv("SEARCH_SOURCE_TIMEOUT_SECONDS", "2.25"))
SEARCH_TOTAL_TIMEOUT_SECONDS = float(os.getenv("SEARCH_TOTAL_TIMEOUT_SECONDS", "3.5"))
SEARCH_GRACE_SECONDS = float(os.getenv("SEARCH_GRACE_SECONDS", "0.2"))
SEARCH_CACHE_SECONDS = float(os.getenv("SEARCH_CACHE_SECONDS", "60"))
SEARCH_CACHE_STALE_SECONDS = float(os.getenv("SEARCH_CACHE_STALE_SECONDS", "600"))
SEARCH_CACHE_MAX_ENTRIES = int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "75"))
SEARCH_CACHE_MIN_RESULTS = int(os.getenv("SEARCH_CACHE_MIN_RESULTS", "8"))


# Shared root config is used by both the backend and frontend.
_SEARCH_LIMITS_CANDIDATES = (
    Path(__file__).resolve().parent / "search_limits.json",
    Path(__file__).resolve().parent.parent / "search_limits.json",
    Path(__file__).resolve().parent.parent.parent / "search_limits.json",
)
_SEARCH_LIMITS = {}
for _limits_path in _SEARCH_LIMITS_CANDIDATES:
    try:
        with _limits_path.open("r", encoding="utf-8") as _limits_file:
            _SEARCH_LIMITS = json.load(_limits_file)
        break
    except (OSError, json.JSONDecodeError):
        continue
MIN_SEARCH_RESULT_SIZE_BYTES = max(0, int(_SEARCH_LIMITS.get("minSizeMb", 100))) * 1024 * 1024
MAX_SEARCH_RESULT_SIZE_BYTES = max(MIN_SEARCH_RESULT_SIZE_BYTES, int(_SEARCH_LIMITS.get("maxSizeGb", 5))) * 1024 * 1024 * 1024
SEARCH_COMPOUND_ALIASES = {
    "antman": "ant man",
    "spiderman": "spider man",
    "ironman": "iron man",
    "blackpanther": "black panther",
    "doctorstrange": "doctor strange",
    "captainamerica": "captain america",
    "guardiansofthegalaxy": "guardians of the galaxy",
}
# Match the movie app's mirror strategy. YTS availability varies by ISP/domain,
# so keep multiple API mirrors and allow an environment override for ordering.
# YTS domains are inconsistent across networks. The accelerator API is a
# keyless YTS-compatible mirror, followed by the public YTS domains.
YTS_API_HOSTS = tuple(
    host.strip()
    for host in os.getenv(
        "YTS_API_HOSTS",
        "movies-api.accel.li,yts.bz,yts.mx,yts.am,yts.lt,yts.rs",
    ).split(",")
    if host.strip()
)
FAST_SEARCH_TRACKERS = (
    "http://tracker.dler.org:6969/announce",
    "http://tracker2.dler.org:80/announce",
    "http://1337.abcvg.info:80/announce",
)
TORRENT_METADATA_CACHE_FILE = Path(os.getenv("TORRENT_METADATA_CACHE_FILE", "/app/.torrent_metadata_cache.json"))
TORRENT_METADATA_JOB_TIMEOUT_SECONDS = float(os.getenv("TORRENT_METADATA_JOB_TIMEOUT_SECONDS", "60"))
TORRENT_METADATA_ITORRENTS_BASE_URL = os.getenv("TORRENT_METADATA_ITORRENTS_BASE_URL", "https://itorrents.net/torrent").rstrip("/")
TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS = float(os.getenv("TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS", "5"))
TORRENT_METADATA_BACKGROUND_TTL_SECONDS = float(os.getenv("TORRENT_METADATA_BACKGROUND_TTL_SECONDS", str(6 * 60 * 60)))
TORRENT_METADATA_BACKGROUND_RETRY_SECONDS = float(os.getenv("TORRENT_METADATA_BACKGROUND_RETRY_SECONDS", "30"))
TORRENT_METADATA_JOB_RETENTION_SECONDS = float(os.getenv("TORRENT_METADATA_JOB_RETENTION_SECONDS", str(60 * 60)))


CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
# Credentials are allowed below, so the default must NOT trust shared hosting
# domains such as *.vercel.app or *.onrender.com: anyone can deploy a page there
# and make credentialed requests to this API. Deployed frontends must be listed
# explicitly in CORS_ORIGINS (or matched by a deliberate CORS_ORIGIN_REGEX).
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
)


# Bundled snapshots let ephemeral hosts (such as Render) start with the same
# catalogues as the VPS. Seed only missing/empty data files; never replace a
# populated persistent cache with an older image snapshot.
_CACHE_SEED_DIR = Path(os.getenv("CACHE_SEED_DIR", "/app/cache-seed"))


REGIONAL_TV_PREBUILT_CACHE_FILE = Path(os.getenv("REGIONAL_TV_PREBUILT_CACHE_FILE", data_file("regional_tv_prebuilt_cache.json")))


REGIONAL_MOVIE_PREBUILT_CACHE_PATH = Path(os.getenv("REGIONAL_MOVIE_PREBUILT_CACHE_PATH", data_file("regional_movie_prebuilt_cache.json")))
