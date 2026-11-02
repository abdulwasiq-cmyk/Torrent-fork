import asyncio
from html import unescape
import base64
import contextvars
import secrets
from datetime import date, datetime, timedelta, timezone
from collections import deque
import gzip
import json
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit

import httpx
import libtorrent as lt
from cryptography.fernet import Fernet, InvalidToken
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel


from core.cache_diagnostics import (
    _CACHE_DIAGNOSTICS,
    _CACHE_DIAGNOSTICS_STARTED_AT,
    _UPSTREAM_FEATURE,
    _InstrumentedAsyncClient,
    _record_cache_event,
    _record_upstream_request,
    _upstream_provider_name,
    _upstream_endpoint_group,
)

from core.settings import (
    REGIONAL_MOVIE_PREBUILT_CACHE_PATH,
    ALLOW_LEGACY_SEEDR_TOKEN,
    APP_NAME,
    CACHE_ONLY_MODE,
    CORS_ORIGINS,
    CORS_ORIGIN_REGEX,
    DC_TV_CATALOGUE_CACHE_FILE,
    DEBUG_ENDPOINTS_ENABLED,
    FAST_SEARCH_TEST_URL,
    FAST_SEARCH_TRACKERS,
    FEEDBACK_GLOBAL_RATE_LIMIT,
    FEEDBACK_RATE_LIMIT,
    FEEDBACK_RATE_WINDOW_SECONDS,
    GITHUB_FEEDBACK_REPO,
    GITHUB_FEEDBACK_TOKEN,
    IMDB_RATING_CACHE_FILE,
    IMDB_RATING_CACHE_TTL_SECONDS,
    IMDB_RATING_LOOKUP_VERSION,
    IMDB_RATING_NOT_FOUND_TTL_SECONDS,
    KNABEN_API_URL,
    MARVEL_TV_CATALOGUE_CACHE_FILE,
    MAX_SEARCH_RESULT_SIZE_BYTES,
    MIN_SEARCH_RESULT_SIZE_BYTES,
    REGIONAL_MOVIE_CACHE_PAGE_SIZE,
    REGIONAL_MOVIE_CACHE_TTL_SECONDS,
    REGIONAL_MOVIE_CATALOGUE_KEYS,
    REGIONAL_MOVIE_PREWARM_PAGES,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_WEEKS,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    SEARCH_CACHE_MAX_ENTRIES,
    SEARCH_CACHE_MIN_RESULTS,
    SEARCH_CACHE_SECONDS,
    SEARCH_CACHE_STALE_SECONDS,
    SEARCH_COMPOUND_ALIASES,
    SEARCH_SOURCE_TIMEOUT_SECONDS,
    SEARCH_TOTAL_TIMEOUT_SECONDS,
    SEEDR_BASE,
    SEEDR_DEVICE_AUTHORIZE_URL,
    SEEDR_DEVICE_CLIENT_ID,
    SEEDR_DEVICE_CODE_URL,
    SEEDR_MEDIA_BASE,
    SEEDR_PAT_BASE,
    SEEDR_SESSION_COOKIE,
    SEEDR_SESSION_SAMESITE,
    SEEDR_SESSION_SECRET,
    SEEDR_SESSION_TTL_SECONDS,
    SEEDR_TOKEN,
    SEEDR_V2_BASE,
    STREAMING_AVAILABILITY_API_BASE,
    STREAMING_AVAILABILITY_API_KEY,
    SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS,
    TMDB_API_BASE,
    TMDB_API_KEYS,
    TMDB_CATALOGUE_CACHE_FILE,
    TMDB_CATALOGUE_CACHE_SECONDS,
    TMDB_COMPANY_CACHE_SECONDS,
    TMDB_IMAGE_BASE,
    TMDB_OTT_CACHE_FILE,
    TMDB_OTT_CACHE_SECONDS,
    TMDB_OTT_INCOMPLETE_CACHE_SECONDS,
    TMDB_OTT_MISSING_CACHE_SECONDS,
    TMDB_READ_ACCESS_TOKENS,
    TMDB_SEARCH_METADATA_CACHE_FILE,
    TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS,
    TMDB_SYNOPSIS_LOOKUP_VERSION,
    TORRENT_METADATA_API_URL,
    TORRENT_METADATA_BACKGROUND_RETRY_SECONDS,
    TORRENT_METADATA_BACKGROUND_TTL_SECONDS,
    TORRENT_METADATA_CACHE_FILE,
    TORRENT_METADATA_ITORRENTS_BASE_URL,
    TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS,
    TORRENT_METADATA_JOB_RETENTION_SECONDS,
    TORRENT_METADATA_JOB_TIMEOUT_SECONDS,
    TORRENT_SEARCH_API_URL,
    WATCHMODE_API_BASE,
    WATCHMODE_API_KEYS,
    YTS_API_HOSTS,
    _CACHE_SEED_DIR,
    _split_env_keys,
    logger,
)

from core.shared import (
    SeedrError,
    _MANUAL_TORRENT_SEARCH,
    _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS,
    _seedr_request_session_id,
    _seedr_request_token,
)

from metadata.tmdb import (
    _OMDB_REQUEST_SEMAPHORE,
    _PROVIDER_KEY_CURSORS,
    _close_tmdb_http_client,
    _omdb_client,
    _omdb_rate_limit_for,
    _omdb_rate_limited_until,
    _provider_key_available,
    _provider_key_failure,
    _provider_key_success,
    _read_tmdb_ott_persistent_cache,
    _read_tmdb_persistent_cache,
    _retry_after_seconds,
    _tmdb_company_id_cache,
    _tmdb_company_inflight,
    _tmdb_fetch_movie_ott_availability,
    _tmdb_get_json,
    _tmdb_movie_catalogue_cache,
    _tmdb_movie_catalogue_inflight,
    _tmdb_ott_cache,
    _tmdb_ott_disk_key,
    _tmdb_ott_inflight,
    _tmdb_ott_ttl,
    _watchmode_get,
    _watchmode_provider_rows,
    _write_tmdb_ott_persistent_cache,
    _write_tmdb_persistent_cache,
)

from metadata.imdb import _get_imdb_rating_record, router as imdb_router

from routes.feedback import router as feedback_router
from integrations.nexstream import router as nexstream_router
from integrations.nexstream_reports import router as nexstream_reports_router
from integrations.vidrift import router as vidrift_router
from integrations.yenime import router as yenime_router

from seedr.seedr_session import (
    _clear_seedr_session_token,
    _seedr_get_session,
    _seedr_new_session,
    _seedr_restore_session,
    _seedr_session_auth_mode,
    _seedr_session_cookie_value,
    _seedr_session_csrf_ok,
    _seedr_session_fingerprint,
    _seedr_session_token,
    _seedr_sessions,
    current_seedr_token,
    normalize_seedr_token,
)

from search.search_providers import (
    LIMETORRENTS_HOSTS,
    X1337_HOSTS,
    _normalize_title,
    _search_1337x_uncached,
    _search_tokens,
    parse_size,
    search_1337x,
    search_1337x_direct,
    search_limetorrents,
    search_yts_movies,
)

from seedr.seedr_api import (
    get_seedr_metadata_tree,
    seedr_add,
    seedr_file_delete,
    seedr_folder_payload,
    seedr_quota,
    start_seedr_cleanup_worker,
    router as seedr_api_router,
)

from search.torrent_metadata import MagnetRequest, router as torrent_metadata_router


app = FastAPI(title=APP_NAME)


def _diagnostic_feature_for_path(path: str) -> str:
    cleaned = re.sub(r"/movie-\d+(?=/|$)", "/movie-{id}", path or "/")
    cleaned = re.sub(r"(?<=/)\d+(?=/|$)", "{id}", cleaned)
    return "request:" + cleaned[:120]


@app.middleware("http")
async def _set_upstream_diagnostic_feature(request: Request, call_next):
    token = _UPSTREAM_FEATURE.set(_diagnostic_feature_for_path(request.url.path))
    try:
        return await call_next(request)
    finally:
        _UPSTREAM_FEATURE.reset(token)


@app.exception_handler(SeedrError)
async def handle_seedr_error(request: Request, exc: SeedrError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "detail": exc.detail,
            "code": exc.code,
            "provider": "seedr",
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from core.http_cache import (
    _DATE_SORTED_EXTRA_CATALOGUES,
    _fast_json_response,
    _file_signature,
    _memoized_file_read,
    _page_catalogue_payload,
    _prebuilt_catalogue_page,
)

@app.middleware("http")
async def attach_seedr_session(request: Request, call_next):
    raw_cookie = str(request.cookies.get(SEEDR_SESSION_COOKIE) or "").strip()
    restored = _seedr_restore_session(raw_cookie)
    is_new = False

    if restored:
        session_id, restored_session = restored
        _seedr_sessions[session_id] = restored_session
    elif raw_cookie in _seedr_sessions:
        session_id = raw_cookie
    else:
        session_id, _ = _seedr_new_session()
        is_new = True

    session = _seedr_get_session(session_id)
    session["last_seen"] = time.time()

    token_ctx = _seedr_request_token.set(_seedr_session_token(session_id))
    session_ctx = _seedr_request_session_id.set(session_id)
    try:
        path = request.url.path or ""
        method = request.method.upper()
        # Every state-changing API call needs the session CSRF token, not only
        # /api/seedr/*: compatibility routes such as /api/files/delete and
        # /api/v2/torrents/* also act on the connected Seedr account.
        # NexStream failure reports act on no account (they only add a rate-limited comment to a GitHub issue),
        # and the browser may report before a Seedr session exists, so they skip the CSRF check.
        csrf_exempt = path == "/api/nexstream/report"
        if path.startswith("/api/") and method not in {"GET", "HEAD", "OPTIONS"} and not csrf_exempt:
            if not _seedr_session_csrf_ok(request):
                response = JSONResponse(
                    status_code=403,
                    content={"error": "Seedr session security check failed.", "code": "SEEDR_CSRF_INVALID"},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
    finally:
        _seedr_request_token.reset(token_ctx)
        _seedr_request_session_id.reset(session_ctx)

    is_https = (
        request.url.scheme.lower() == "https"
        or str(request.headers.get("x-forwarded-proto") or "").lower() == "https"
    )
    response.set_cookie(
        SEEDR_SESSION_COOKIE,
        _seedr_session_cookie_value(session_id, session),
        max_age=SEEDR_SESSION_TTL_SECONDS,
        httponly=True,
        secure=is_https,
        samesite=SEEDR_SESSION_SAMESITE if is_https else "lax",
        path="/",
    )

    now = time.time()
    if len(_seedr_sessions) > 2000:
        stale = [
            sid for sid, item in _seedr_sessions.items()
            if now - float(item.get("last_seen") or now) > SEEDR_SESSION_TTL_SECONDS
        ]
        for sid in stale:
            _seedr_sessions.pop(sid, None)

    return response


@app.middleware("http")
async def add_timing_allow_origin(request: Request, call_next):
    # Allows the frontend to read Resource Timing transfer sizes for the
    # cross-origin Render media stream when the frontend is hosted on Vercel.
    response = await call_next(request)
    response.headers["Timing-Allow-Origin"] = "*"
    return response

from seedr.seedr_client import (
    add_task,
    arr,
    folder_name,
    info_hash,
    legacy_seedr_list_contents,
    normalize_file,
    normalize_magnet,
    rename_seedr_folder,
    seedr_data,
    seedr_error_message,
    seedr_request,
    seedr_root_request,
    seedr_task_folder_id,
    seedr_task_name,
    task_complete,
    task_contents,
    task_id,
    unwrap_seedr_task,
)
app.include_router(seedr_api_router)

from metadata.posters import (
    _canonical_catalogue_poster_url,
    _catalogue_row_has_3d_quality,
    _catalogue_row_is_excluded_franchise_title,
    _poster_lookup,
    _poster_url_for_release,
    _sort_cached_catalogue_results,
    router as posters_router,
)
app.include_router(posters_router)

from routes.misc_routes import router as misc_routes_router
app.include_router(misc_routes_router)


# Registered directly on `app` (not via a router): fullstack_app.py removes this
# route by path/name so the SPA can serve "/" instead.
@app.get("/")
async def root():
    return {"name": APP_NAME, "status": "ok"}


app.router.add_event_handler("startup", start_seedr_cleanup_worker)

from catalogues.catalogues_extra import (
    MARVEL_CATALOGUE_PATH,
    MARVEL_MOVIE_SEARCHES,
    _CACHE_SEED_FILES,
    _EXTRA_CATALOGUES,
    _EXTRA_CATALOGUE_PATHS,
    _RUNTIME_CACHE_SEED_FILES,
    _TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE,
    _ensure_extra_catalogue_refresh,
    _extra_catalogue_monthly_scheduler,
    _extra_catalogue_states,
    _extra_catalogue_tasks,
    _extra_item_year,
    _initialize_catalogue_caches,
    _lookup_catalogue_synopsis,
    _normalize_synopsis_match_title,
    _read_extra_catalogue,
    _schedule_tmdb_catalogue_synopsis_enrichment,
    _start_catalogue_synopsis_enrichment,
    _start_tmdb_catalogue_synopsis_enrichment,
    _synopsis_cache_paths,
    _warm_marvel_catalogue_on_startup,
    _write_extra_catalogue,
    _write_synopsis_cache,
    router as catalogues_extra_router,
)
app.include_router(catalogues_extra_router)


app.router.add_event_handler("startup", _initialize_catalogue_caches)
app.router.add_event_handler("startup", _start_catalogue_synopsis_enrichment)

# Register only after the callback above exists; earlier startup hooks are defined
# further up the module and must not reference this function prematurely.
app.router.add_event_handler("startup", _start_tmdb_catalogue_synopsis_enrichment)
app.router.add_event_handler("shutdown", _close_tmdb_http_client)

from catalogues.catalogues_movies import (
    _resolve_marvel_tmdb_movie_id,
    _start_regional_movie_catalogue_scheduler,
    _warm_extra_catalogues_on_startup,
    router as catalogues_movies_router,
)

from catalogues.catalogues_tv import router as catalogues_tv_router
app.include_router(catalogues_tv_router)
app.include_router(catalogues_movies_router)

from catalogues.section_caches import router as section_caches_router
app.include_router(section_caches_router)

app.router.add_event_handler("startup", _warm_extra_catalogues_on_startup)


app.router.add_event_handler("startup", _start_regional_movie_catalogue_scheduler)

from metadata.search_metadata import router as search_metadata_router
app.include_router(search_metadata_router)


app.router.add_event_handler("startup", _warm_marvel_catalogue_on_startup)
app.include_router(imdb_router)
app.include_router(torrent_metadata_router)

from routes.compat_routes import router as compat_routes_router
app.include_router(compat_routes_router)
app.include_router(feedback_router)
app.include_router(nexstream_router)
app.include_router(nexstream_reports_router)
app.include_router(vidrift_router)
app.include_router(yenime_router)
