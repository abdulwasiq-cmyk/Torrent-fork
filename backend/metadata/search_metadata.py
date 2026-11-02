"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Query, Request

from core.cache_diagnostics import _InstrumentedAsyncClient, _record_cache_event
from catalogues.catalogues_extra import (
    MARVEL_CATALOGUE_PATH,
    _EXTRA_CATALOGUE_PATHS,
    _synopsis_cache_paths,
    _write_synopsis_cache,
)
from search.search_providers import _normalize_title, search_1337x
from core.settings import (
    CACHE_ONLY_MODE,
    TMDB_API_KEYS,
    TMDB_CATALOGUE_CACHE_FILE,
    TMDB_IMAGE_BASE,
    TMDB_OTT_CACHE_FILE,
    TMDB_READ_ACCESS_TOKENS,
    TMDB_SEARCH_METADATA_CACHE_FILE,
    TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS,
    TMDB_SYNOPSIS_LOOKUP_VERSION,
    WATCHMODE_API_KEYS,
    _split_env_keys,
    env_values,
    logger,
    log_cache_only_metadata_block,
    stored_ttl,
)
from core.shared import _MANUAL_TORRENT_SEARCH
from metadata.tmdb import (
    _tmdb_get_json,
    _tmdb_movie_catalogue_cache,
    _tmdb_ott_cache,
    _tmdb_ott_disk_key,
    _watchmode_get,
)

router = APIRouter()


@router.get("/api/catalogue/ott/search")
async def api_search_saved_ott(titles: list[str] = Query(..., min_length=1, max_length=80)):
    """Look up saved OTT enrichment by title from persistent franchise catalogue caches only."""
    _record_cache_event("saved_ott_title_search", "lookup")
    # Read the persistent OTT JSON once for the entire title search. The cache
    # file may contain over a thousand rows; parsing the complete file once per
    # catalogue row turns a cache-only lookup into unnecessary repeated I/O.
    try:
        ott_disk = json.loads(TMDB_OTT_CACHE_FILE.read_text(encoding="utf-8"))
        ott_items = ott_disk.get("items", {}) if isinstance(ott_disk, dict) else {}
        if not isinstance(ott_items, dict):
            ott_items = {}
    except (OSError, ValueError, TypeError):
        ott_items = {}

    source_paths = [MARVEL_CATALOGUE_PATH, *_EXTRA_CATALOGUE_PATHS.values()]
    saved_rows: list[dict[str, Any]] = []
    seen_rows: set[tuple[str, str]] = set()
    for source_path in source_paths:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("catalogueTitle") or row.get("marvelCatalogueTitle") or row.get("mediaTitle") or row.get("title") or "").strip()
            if not title:
                continue
            year = str(row.get("year") or "")
            identity = (_normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title)), year)
            if identity in seen_rows:
                continue
            availability = row.get("ottAvailability")
            tmdb_id = row.get("tmdbId")
            try:
                tmdb_id = int(tmdb_id or 0)
            except (TypeError, ValueError):
                tmdb_id = 0
            # Catalogue rows are not the only source of saved OTT data. The shared
            # runtime cache is bundled into the image and may already contain a
            # result for this TMDB ID even when the catalogue row predates enrichment.
            if not isinstance(availability, dict) and tmdb_id > 0:
                cached = _tmdb_ott_cache.get((tmdb_id, "IN"))
                if cached and isinstance(cached[1], dict):
                    availability = cached[1]
                if not isinstance(availability, dict):
                    envelope = ott_items.get(_tmdb_ott_disk_key((tmdb_id, "IN")))
                    persistent_payload = envelope.get("payload") if isinstance(envelope, dict) else None
                    if isinstance(persistent_payload, dict):
                        availability = persistent_payload
                        _tmdb_ott_cache[(tmdb_id, "IN")] = (time.monotonic(), availability)
            if not isinstance(availability, dict):
                continue
            seen_rows.add(identity)
            saved_rows.append({
                "title": title,
                "year": year or None,
                "tmdbId": tmdb_id or row.get("tmdbId"),
                "ottAvailability": availability,
            })

    # Also use title-to-TMDB-ID mappings in the general saved metadata/catalogue
    # cache. This makes OTT entries reusable even when their title is not in a
    # Marvel/DC/Classics catalogue snapshot.
    for row in _read_search_metadata_catalogue_rows():
        if not isinstance(row, dict):
            continue
        raw_title = str(
            row.get("catalogueTitle") or row.get("marvelCatalogueTitle")
            or row.get("mediaTitle") or row.get("title") or row.get("name") or ""
        ).strip()
        if not raw_title:
            continue
        try:
            tmdb_id = int(row.get("tmdbId") or row.get("id") or 0)
        except (TypeError, ValueError):
            tmdb_id = 0
        if tmdb_id <= 0:
            continue
        availability = row.get("ottAvailability")
        if not isinstance(availability, dict):
            envelope = ott_items.get(_tmdb_ott_disk_key((tmdb_id, "IN")))
            availability = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(availability, dict):
            continue
        year_value = row.get("year")
        title_identity = (
            _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", raw_title)),
            str(year_value or ""),
        )
        if title_identity in seen_rows:
            continue
        seen_rows.add(title_identity)
        saved_rows.append({
            "title": raw_title,
            "year": str(year_value or "") or None,
            "tmdbId": tmdb_id,
            "ottAvailability": availability,
        })

    requested = []
    for raw in titles:
        title = re.sub(r"\s+", " ", str(raw or "")).strip()
        if title:
            requested.append({"title": title, "normalized": _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title))})

    matches = []
    for request in requested:
        candidates = [row for row in saved_rows
            if _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", row["title"])) == request["normalized"]]
        if candidates:
            matches.append({"query": request["title"], "found": True, "entries": candidates[:3]})
        else:
            matches.append({"query": request["title"], "found": False, "entries": []})
    matched_count = sum(1 for item in matches if item.get("found"))
    _record_cache_event("saved_ott_title_search", "title_hit" if matched_count else "title_miss")
    _record_cache_event("saved_ott_title_search", "matched_rows", sum(len(item.get("entries") or []) for item in matches))
    return {"status": "ready", "results": matches}


_watchmode_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_WATCHMODE_SEARCH_CACHE_TTL = stored_ttl(6 * 60 * 60)
_TVMAZE_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _availability_normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _availability_title_is_relevant(query: str, title: Any) -> bool:
    """Reject distant partial-title matches while allowing modest subtitle/region suffixes."""
    target = _availability_normalize_title(query)
    candidate = _availability_normalize_title(title)
    if not target or not candidate:
        return False
    if target == candidate:
        return True
    # Containment is useful for regional editions and subtitles, but not arbitrary
    # longer titles that happen to begin with the requested words.
    max_extra = max(4, int(len(target) * 0.5))
    if target in candidate:
        return len(candidate) - len(target) <= max_extra
    if candidate in target:
        return len(target) - len(candidate) <= max_extra
    return False


def _availability_canonical_type(value: Any) -> str:
    kind = str(value or "").casefold().replace("-", "_").replace(" ", "_")
    if any(token in kind for token in ("tv", "series", "show", "episode")):
        return "tv"
    if any(token in kind for token in ("movie", "film", "feature")):
        return "movie"
    return kind or "unknown"


async def _fallback_tvmaze_search(query: str, timeout: httpx.Timeout) -> list[dict[str, Any]]:
    """Metadata-only fallback used only when Watchmode and TMDB find no title."""
    cache_key = query.casefold()
    cached = _TVMAZE_SEARCH_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _WATCHMODE_SEARCH_CACHE_TTL:
        return cached[1]
    if CACHE_ONLY_MODE:
        log_cache_only_metadata_block("TVmaze", enabled=True)
        return []
    try:
        async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get("https://api.tvmaze.com/search/shows", params={"q": query})
        if response.status_code != 200:
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    target = _availability_normalize_title(query)
    matches = []
    for row in payload if isinstance(payload, list) else []:
        show = row.get("show") if isinstance(row, dict) else None
        if not isinstance(show, dict) or not show.get("id"):
            continue
        title = str(show.get("name") or "").strip()
        if not title:
            continue
        normalized = _availability_normalize_title(title)
        if not _availability_title_is_relevant(query, title):
            continue
        premiered = str(show.get("premiered") or "")
        network = show.get("network") or show.get("webChannel") or {}
        matches.append({
            "id": str(show["id"]), "title": title, "year": premiered[:4] or None,
            "type": "tv", "providers": [], "status": "not_confirmed", "source": "TVmaze",
            "tvmazeId": show["id"], "imdbId": (show.get("externals") or {}).get("imdb"),
            "overview": re.sub(r"<[^>]+>", " ", str(show.get("summary") or "")).strip(),
            "network": network.get("name") if isinstance(network, dict) else None,
            "url": show.get("url"),
        })
    matches.sort(key=lambda item: (
        _availability_normalize_title(item.get("title")) == target,
        bool(item.get("year")),
    ), reverse=True)
    matches = matches[:5]
    _TVMAZE_SEARCH_CACHE[cache_key] = (time.time(), matches)
    return matches


async def _fallback_omdb_search(query: str, timeout: httpx.Timeout) -> list[dict[str, Any]]:
    """OMDb metadata fallback; OMDb does not provide streaming availability."""
    keys = env_values("OMDB_API_KEYS", "OMDB_API_KEY")
    if CACHE_ONLY_MODE:
        log_cache_only_metadata_block("IMDb", enabled=True)
        return []
    if not keys:
        return []
    target = _availability_normalize_title(query)
    for key in keys:
        try:
            async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get("https://www.omdbapi.com/", params={"apikey": key, "s": query})
            if response.status_code != 200:
                continue
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            continue
        matches = []
        for row in payload.get("Search") or []:
            title = str(row.get("Title") or "").strip()
            imdb_id = str(row.get("imdbID") or "").strip()
            if not title or not imdb_id:
                continue
            normalized = _availability_normalize_title(title)
            if not _availability_title_is_relevant(query, title):
                continue
            kind = "tv" if str(row.get("Type") or "").casefold() == "series" else "movie"
            matches.append({
                "id": imdb_id, "title": title, "year": row.get("Year"), "type": kind,
                "providers": [], "status": "not_confirmed", "source": "OMDb",
                "imdbId": imdb_id, "poster": row.get("Poster"),
            })
        if matches:
            matches.sort(key=lambda item: _availability_normalize_title(item["title"]) == target, reverse=True)
            return matches[:5]
        # Search returned no titles; try the next configured key only on auth errors
        # is intentionally avoided here so rate limits cannot be bypassed.
        if payload.get("Response") == "False":
            return []
    return []


@router.get("/api/search/availability")
async def api_search_availability(q: str = Query(..., min_length=2, max_length=160)):
    """Bound streaming lookups so slow provider APIs cannot leave the UI scanning forever."""
    query = re.sub(r"\s+", " ", q).strip()
    try:
        # Upstream providers have their own timeouts and retries; apply one total
        # budget to the whole lookup so nested retries cannot accumulate indefinitely.
        return await asyncio.wait_for(_api_search_availability_impl(query), timeout=12.0)
    except asyncio.TimeoutError:
        logger.info("Streaming availability lookup timed out for query %r", query)
        return {
            "status": "unavailable",
            "query": query,
            "title": query,
            "year": None,
            "matches": [],
            "providers": [],
            "message": "Streaming availability timed out. Torrent results are still available.",
        }


async def _api_search_availability_impl(q: str) -> dict[str, Any]:
    """Search Watchmode and TMDB first; use TVmaze/OMDb for metadata only if neither finds a title."""
    query = re.sub(r"\s+", " ", q).strip()
    cache_key = query.casefold()
    now = time.time()
    cached = _watchmode_search_cache.get(cache_key)
    if cached and now - cached[0] < _WATCHMODE_SEARCH_CACHE_TTL:
        _record_cache_event("availability_search", "hit")
        return cached[1]

    _record_cache_event("availability_search", "miss")
    if CACHE_ONLY_MODE:
        # This endpoint previously searched Watchmode/TMDB directly, bypassing the
        # movie-ID OTT cache-only guard. Reuse saved, title-matched OTT enrichment.
        try:
            saved_payload = await api_search_saved_ott(titles=[query])
        except Exception:
            saved_payload = {"results": []}
        saved_results = saved_payload.get("results") if isinstance(saved_payload, dict) else []
        saved_match = next((
            item for item in saved_results
            if isinstance(item, dict) and _availability_normalize_title(item.get("query")) == _availability_normalize_title(query)
        ), {})
        saved_entries = saved_match.get("entries") if isinstance(saved_match, dict) else []
        matches: list[dict[str, Any]] = []
        merged_providers: list[dict[str, Any]] = []
        seen_providers: set[tuple[str, str]] = set()
        for entry in saved_entries if isinstance(saved_entries, list) else []:
            if not isinstance(entry, dict):
                continue
            availability = entry.get("ottAvailability")
            if not isinstance(availability, dict):
                continue
            providers: list[dict[str, Any]] = []
            for source_field, kind in (
                ("streamingProviders", "subscription"),
                ("rentProviders", "rent"),
                ("buyProviders", "buy"),
            ):
                for provider in availability.get(source_field) or []:
                    if not isinstance(provider, dict):
                        continue
                    name = str(provider.get("name") or "").strip()
                    if not name:
                        continue
                    normalized_provider = {
                        "providerId": provider.get("providerId"),
                        "name": name,
                        "region": str(availability.get("region") or "IN").upper(),
                        "type": kind,
                        "webUrl": str(provider.get("webUrl") or availability.get("providerLink") or ""),
                        "logoUrl": str(provider.get("logoUrl") or ""),
                    }
                    providers.append(normalized_provider)
                    identity = (name.casefold(), kind)
                    if identity not in seen_providers:
                        seen_providers.add(identity)
                        merged_providers.append(normalized_provider)
            matches.append({
                "id": str(entry.get("tmdbId") or ""),
                "tmdbId": entry.get("tmdbId"),
                "title": str(entry.get("title") or query),
                "year": entry.get("year"),
                "type": "movie",
                "providers": providers[:24],
                "status": "ready" if providers else "not_confirmed",
                "source": str(availability.get("source") or "Saved OTT cache"),
            })
        result = {
            "status": "ready" if merged_providers else ("not_confirmed" if matches else "not_cached"),
            "query": query,
            "title": matches[0].get("title", query) if matches else query,
            "year": matches[0].get("year") if matches else None,
            "matches": matches[:10],
            "providers": merged_providers[:24],
            "source": "Saved OTT cache",
            "cacheOnly": True,
            "message": "" if matches else "No saved OTT entry matched this title; live provider lookups are disabled on this service.",
        }
        _watchmode_search_cache[cache_key] = (time.time(), result)
        _record_cache_event("availability_search", "cache_only_saved_hit" if matches else "cache_only_miss_blocked")
        return result

    timeout = httpx.Timeout(8.0, connect=3.0)
    target = _availability_normalize_title(query)
    primary_matches: list[dict[str, Any]] = []
    primary_errors = []

    # Primary source 1: Watchmode. Search both films and TV series automatically.
    if WATCHMODE_API_KEYS:
        try:
            response = await _watchmode_get("/search/", params={
                "search_field": "name", "search_value": query, "types": "movie,tv_series,tv_miniseries,tv_movie"
            }, timeout=timeout)
            if response is not None and response.status_code < 400:
                data = response.json()
                titles = data.get("title_results", []) if isinstance(data, dict) else []
                titles = [item for item in titles if isinstance(item, dict) and item.get("id")
                    and _availability_title_is_relevant(query, item.get("name"))]
                titles.sort(key=lambda item: (
                    _availability_normalize_title(item.get("name")) == target,
                    bool(item.get("year")),
                ), reverse=True)
                selected, seen_ids = [], set()
                for item in titles:
                    wid = str(item.get("id") or "")
                    if not wid or wid in seen_ids:
                        continue
                    kind = str(item.get("type") or "").casefold()
                    if kind and not any(token in kind for token in ("movie", "film", "feature", "tv", "show", "series")):
                        continue
                    seen_ids.add(wid)
                    selected.append(item)
                    if len(selected) >= 6:
                        break

                async def resolve_watchmode(item: dict[str, Any]) -> dict[str, Any]:
                    wid = str(item.get("id") or "")
                    kind = str(item.get("type") or "").lower()
                    try:
                        resp = await _watchmode_get(
                            f"/title/{quote(wid, safe='')}/sources/",
                            params={"regions": "IN"}, timeout=timeout)
                        raw = resp.json() if resp is not None and resp.status_code < 400 else []
                    except (httpx.HTTPError, ValueError, TypeError):
                        raw = []
                    providers, seen_sources = [], set()
                    for source in raw if isinstance(raw, list) else []:
                        if not isinstance(source, dict):
                            continue
                        name = str(source.get("name") or source.get("source_name") or "").strip()
                        if not name:
                            continue
                        region = str(source.get("region") or "IN").upper()
                        provider_type = str(source.get("type") or "").lower()
                        identity = (name.casefold(), region, provider_type)
                        if identity in seen_sources:
                            continue
                        seen_sources.add(identity)
                        logo_url = str(
                            source.get("logo_url") or source.get("logoUrl") or source.get("logo")
                            or source.get("image_url") or source.get("image") or ""
                        ).strip()
                        logo_path = str(source.get("logo_path") or "").strip()
                        if not logo_url and logo_path:
                            logo_url = (
                                "https://image.tmdb.org/t/p/w92" + logo_path
                                if logo_path.startswith("/") else logo_path
                            )
                        providers.append({
                            "providerId": source.get("source_id", source.get("id")),
                            "name": name,
                            "region": region,
                            "type": provider_type,
                            "webUrl": source.get("web_url") or source.get("ios_url") or source.get("android_url") or "",
                            "logoUrl": logo_url,
                        })
                    return {"id": wid, "title": str(item.get("name") or query), "year": item.get("year"),
                        "type": kind or "unknown", "tmdbId": item.get("tmdb_id"), "providers": providers[:24],
                        "status": "ready" if providers else "not_confirmed", "source": "Watchmode"}

                primary_matches.extend(await asyncio.gather(*(resolve_watchmode(item) for item in selected)))
            else:
                primary_errors.append("Watchmode unavailable")
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            primary_errors.append("Watchmode " + type(exc).__name__)

    # Primary source 2: search movies and TV concurrently. A movie miss or a
    # movie with no providers must not delay or suppress the TV-series lookup.
    if TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS:
        media_specs = (
            ("movie", "search/movie", "title", "release_date"),
            ("tv", "search/tv", "name", "first_air_date"),
        )

        async def search_tmdb_media(spec: tuple[str, str, str, str]) -> tuple[str, str, str, list[dict[str, Any]]]:
            media_type, search_path, title_key, date_key = spec
            try:
                payload = await _tmdb_get_json(search_path, {
                    "query": query, "include_adult": "false", "language": "en-US", "page": 1
                })
            except Exception as exc:
                primary_errors.append("TMDB " + type(exc).__name__)
                return media_type, title_key, date_key, []
            rows = []
            for row in payload.get("results") or []:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                title = str(row.get(title_key) or "").strip()
                if not title or not _availability_title_is_relevant(query, title):
                    continue
                rows.append(row)
            rows.sort(key=lambda row: (
                _availability_normalize_title(row.get(title_key)) == target,
                bool(row.get(date_key)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            return media_type, title_key, date_key, rows[:3]

        searched_media = await asyncio.gather(*(search_tmdb_media(spec) for spec in media_specs))

        async def resolve_tmdb_match(
            media_type: str, title_key: str, date_key: str, row: dict[str, Any]
        ) -> dict[str, Any]:
            tmdb_id = int(row["id"])
            try:
                provider_data = await _tmdb_get_json(f"{media_type}/{tmdb_id}/watch/providers", {})
            except Exception as exc:
                primary_errors.append("TMDB providers " + type(exc).__name__)
                provider_data = {}
            region_data = (provider_data.get("results") or {}).get("IN") or {}
            providers = []
            for category, kind in (("flatrate", "subscription"), ("free", "free"),
                                   ("ads", "ads"), ("rent", "rent"), ("buy", "buy")):
                for provider in region_data.get(category) or []:
                    name = str(provider.get("provider_name") or "").strip()
                    if name:
                        logo_path = str(provider.get("logo_path") or "").strip()
                        providers.append({
                            "providerId": provider.get("provider_id"),
                            "name": name,
                            "region": "IN",
                            "type": kind,
                            "webUrl": region_data.get("link") or "",
                            "logoUrl": "https://image.tmdb.org/t/p/w92" + logo_path if logo_path else "",
                        })
            return {
                "id": str(tmdb_id), "title": str(row.get(title_key) or query),
                "year": str(row.get(date_key) or "")[:4] or None,
                "type": media_type, "tmdbId": tmdb_id, "providers": providers[:24],
                "status": "ready" if providers else "not_confirmed", "source": "TMDB",
            }

        # Resolve providers concurrently too. This makes the fallback quick when
        # the exact movie has no listing: the TV-series provider result can win
        # without waiting for every unrelated movie candidate.
        tmdb_candidates = [
            (media_type, title_key, date_key, row)
            for media_type, title_key, date_key, rows in searched_media
            for row in rows
        ]
        if tmdb_candidates:
            primary_matches.extend(await asyncio.gather(*(
                resolve_tmdb_match(media_type, title_key, date_key, row)
                for media_type, title_key, date_key, row in tmdb_candidates
            )))

    # De-duplicate same title/media/ID across sources; merge their provider entries.
    deduped: list[dict[str, Any]] = []
    index_by_identity: dict[tuple[str, str], int] = {}
    for match in primary_matches:
        identity = (_availability_canonical_type(match.get("type")),
                    _availability_normalize_title(match.get("title")))
        if identity in index_by_identity:
            existing = deduped[index_by_identity[identity]]
            existing_providers = existing.get("providers") or []
            provider_indexes = {
                (str(provider.get("name") or "").casefold(), str(provider.get("type") or "").casefold()): provider
                for provider in existing_providers
            }
            for provider in match.get("providers") or []:
                key = (str(provider.get("name") or "").casefold(), str(provider.get("type") or "").casefold())
                previous_provider = provider_indexes.get(key)
                if previous_provider is None:
                    existing_providers.append(provider)
                    provider_indexes[key] = provider
                    continue
                for field in ("webUrl", "providerId"):
                    if not previous_provider.get(field) and provider.get(field):
                        previous_provider[field] = provider[field]
            existing["providers"] = existing_providers
            if match.get("source") not in str(existing.get("source") or ""):
                existing["source"] = str(existing.get("source") or "") + " + " + str(match.get("source") or "")
            existing["status"] = "ready" if existing.get("providers") else "not_confirmed"
        else:
            index_by_identity[identity] = len(deduped)
            deduped.append(match)

    # Only use TVmaze/OMDb when both primary catalogues returned no title match.
    if not deduped:
        fallback_matches = await _fallback_tvmaze_search(query, timeout)
        if not fallback_matches:
            fallback_matches = await _fallback_omdb_search(query, timeout)
        if fallback_matches:
            result = {"status": "not_confirmed", "query": query, "title": fallback_matches[0]["title"],
                "year": fallback_matches[0].get("year"), "matches": fallback_matches, "providers": [],
                "source": fallback_matches[0].get("source"),
                "message": "Metadata match found, but no streaming provider could be confirmed by Watchmode or TMDB."}
        else:
            result = {"status": "not_found" if not primary_errors else "unavailable", "query": query,
                "title": query, "year": None, "matches": [], "providers": [],
                "message": "No title match found in Watchmode, TMDB, TVmaze, or OMDb."}
        _watchmode_search_cache[cache_key] = (time.time(), result)
        return result

    deduped.sort(key=lambda item: (
        _availability_normalize_title(item.get("title")) == target,
        bool(item.get("providers")),
        bool(item.get("year")),
    ), reverse=True)

    merged_providers, merged_provider_index = [], {}
    for match in deduped:
        for provider in match.get("providers") or []:
            identity = (str(provider.get("name") or "").casefold(),
                        str(provider.get("region") or "IN").upper(),
                        str(provider.get("type") or "").casefold())
            existing_provider = merged_provider_index.get(identity)
            if existing_provider is None:
                merged_provider_index[identity] = provider
                merged_providers.append(provider)
                continue
            for field in ("webUrl", "providerId"):
                if not existing_provider.get(field) and provider.get(field):
                    existing_provider[field] = provider[field]
    result = {
        "status": "ready" if merged_providers else "not_confirmed",
        "query": query, "title": deduped[0].get("title") or query, "year": deduped[0].get("year"),
        "matches": deduped[:10], "providers": merged_providers[:24],
        "source": "Watchmode + TMDB",
    }
    _watchmode_search_cache[cache_key] = (time.time(), result)
    return result


# Small, independent TMDB lookup for the quick search cards. This intentionally
# does not wait for torrent metadata or Watchmode source resolution.
_TMDB_SEARCH_METADATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TMDB_SEARCH_METADATA_CACHE_TTL = stored_ttl(1800.0)


@router.get("/api/search/metadata")
async def api_search_metadata(q: str = Query(..., min_length=2, max_length=160)):
    """Return poster, synopsis, release year and TMDB link for fast search cards."""
    query = re.sub(r"\s+", " ", q).strip()
    cache_key = query.casefold()
    now = time.time()
    cached = _TMDB_SEARCH_METADATA_CACHE.get(cache_key)
    if cached and now - cached[0] < _TMDB_SEARCH_METADATA_CACHE_TTL:
        _record_cache_event("search_metadata", "memory_hit")
        return cached[1]
    _record_cache_event("search_metadata", "miss")

    # Disk-backed query envelopes survive process/container restarts. The per-title
    # cache below remains durable indefinitely and is refreshed whenever a new
    # successful lookup supplies better data.
    persistent_cache = _read_persistent_search_metadata_cache()
    query_entry = (persistent_cache.get("queries") or {}).get(cache_key)
    try:
        query_saved_at = int((query_entry or {}).get("savedAt") or 0)
    except (TypeError, ValueError):
        query_saved_at = 0
    if (
        isinstance(query_entry, dict)
        and now - query_saved_at < TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS
    ):
        # Read newer reference-only envelopes; continue to support any legacy
        # envelope from a previous deployment.
        cached_response = query_entry.get("response")
        if isinstance(cached_response, dict) and cached_response.get("status") == "ready":
            _record_cache_event("search_metadata", "persistent_query_hit")
            _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, cached_response)
            return cached_response
        key_rows = query_entry.get("keys", [])
        requested_keys = {
            (
                str(key.get("title") or ""),
                int(key.get("year") or 0),
                str(key.get("mediaType") or "movie"),
                str(key.get("tmdbId") or ""),
            )
            for key in key_rows if isinstance(key, dict)
        } if isinstance(key_rows, list) else set()
        cached_results: list[dict[str, Any]] = []
        for raw in persistent_cache.get("results", []):
            if not isinstance(raw, dict):
                continue
            candidate = _search_metadata_cache_candidate(raw)
            if not candidate:
                continue
            row_key = (
                _normalize_title(candidate["title"]),
                int(candidate.get("year") or 0),
                str(candidate.get("mediaType") or "movie"),
                str(candidate.get("tmdbId") or ""),
            )
            if row_key in requested_keys:
                cached_results.append(candidate)
        if cached_results:
            _record_cache_event("search_metadata", "persistent_title_hit")
            _record_cache_event("search_metadata", "persistent_rows_served", len(cached_results))
            cached_response = {
                "status": "ready",
                "query": query,
                "source": "Persistent synopsis cache",
                "results": cached_results[:30],
            }
            _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, cached_response)
            return cached_response

    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        return {"status": "unavailable", "query": query, "source": "TMDB", "results": []}

    try:
        # Give the helper time to try each configured token on key-specific
        # failures. Use a shorter per-token timeout for this non-blocking UI lookup.
        payload = await asyncio.wait_for(
            _tmdb_get_json("search/multi", {
                "query": query,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            }, request_timeout=3.5),
            timeout=14.0,
        )
    except Exception as exc:
        logger.info("TMDB quick metadata search failed for %r: %s", query, type(exc).__name__)
        return {"status": "unavailable", "query": query, "source": "TMDB", "results": []}

    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("media_type") or "").lower()
        if media_type not in {"movie", "tv"} or not item.get("id"):
            continue
        title = str((item.get("title") if media_type == "movie" else item.get("name")) or "").strip()
        # TMDB has already ranked these results for the submitted query. Do not
        # apply the stricter Watchmode availability matcher here: franchise titles
        # such as "The Amazing Spider-Man 2" are valid hits for "Spider-Man".
        if not title:
            continue
        release_date = str(
            (item.get("release_date") if media_type == "movie" else item.get("first_air_date")) or ""
        ).strip()
        year_match = re.match(r"^(\d{4})", release_date)
        poster_path = str(item.get("poster_path") or "").strip()
        backdrop_path = str(item.get("backdrop_path") or "").strip()
        tmdb_id = int(item["id"])
        results.append({
            "id": tmdb_id,
            "tmdbId": tmdb_id,
            "title": title,
            "year": int(year_match.group(1)) if year_match else None,
            "mediaType": media_type,
            "overview": str(item.get("overview") or "").strip(),
            "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
            "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
            "rating": float(item.get("vote_average") or 0),
            "tmdbUrl": f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
            "source": "TMDB",
        })

    target = _availability_normalize_title(query)
    results.sort(key=lambda item: (
        _availability_normalize_title(item["title"]) == target,
        bool(item.get("year")),
        float(item.get("rating") or 0),
    ), reverse=True)
    response = {
        "status": "ready" if results else "not_found",
        "query": query,
        "source": "TMDB",
        "results": results[:30],
    }
    if response["status"] == "ready":
        _persist_search_metadata_cache_rows(results[:30], query=query, query_response=response)
        if len(_TMDB_SEARCH_METADATA_CACHE) > 300:
            expired_keys = [
                key for key, value in _TMDB_SEARCH_METADATA_CACHE.items()
                if now - value[0] >= _TMDB_SEARCH_METADATA_CACHE_TTL
            ]
            for key in expired_keys:
                _TMDB_SEARCH_METADATA_CACHE.pop(key, None)
            if len(_TMDB_SEARCH_METADATA_CACHE) > 300:
                _TMDB_SEARCH_METADATA_CACHE.pop(next(iter(_TMDB_SEARCH_METADATA_CACHE)), None)
        _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, response)
    return response


def _search_metadata_cache_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = str(
        raw.get("catalogueTitle") or raw.get("marvelCatalogueTitle")
        or raw.get("mediaTitle") or raw.get("title") or raw.get("name") or ""
    ).strip()
    if not title:
        return None

    year_value = raw.get("year")
    release_date = str(raw.get("releaseDate") or raw.get("release_date") or raw.get("first_air_date") or "")
    try:
        year = int(year_value) if year_value else 0
    except (TypeError, ValueError):
        year = 0
    if not year and re.match(r"^\d{4}", release_date):
        year = int(release_date[:4])
    if not year:
        year_match = re.search(r"\b((?:19|20)\d{2})\b\s*\)?\s*$", title)
        if year_match:
            year = int(year_match.group(1))

    canonical_title = re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title).strip()
    normalized = _normalize_title(canonical_title)
    if not normalized:
        return None

    media_type = str(raw.get("mediaType") or raw.get("media_type") or "movie").lower()
    if media_type not in {"movie", "tv"}:
        media_type = "movie"
    tmdb_id = raw.get("tmdbId") or raw.get("id")
    try:
        numeric_id = int(tmdb_id) if tmdb_id else 0
    except (TypeError, ValueError):
        numeric_id = 0
    overview = re.sub(r"\s+", " ", str(raw.get("overview") or "")).strip()
    # Keep rows with a known TMDB ID even when overview is empty. The batch
    # endpoint can hydrate those rows from TMDB's movie-details endpoint.

    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    poster_url = str(raw.get("posterUrl") or raw.get("poster_url") or "")
    if not poster_url and str(raw.get("poster_path") or "").strip():
        poster_url = TMDB_IMAGE_BASE + str(raw["poster_path"]).strip()
    backdrop_url = str(raw.get("backdropUrl") or raw.get("backdrop_url") or "")
    if not backdrop_url and str(raw.get("backdrop_path") or "").strip():
        backdrop_url = "https://image.tmdb.org/t/p/w780" + str(raw["backdrop_path"]).strip()
    tmdb_url = str(raw.get("tmdbUrl") or raw.get("tmdb_url") or "")
    if not tmdb_url and numeric_id:
        tmdb_url = f"https://www.themoviedb.org/{media_type}/{numeric_id}"

    return {
        "id": numeric_id or ("cached:" + normalized + (":" + str(year) if year else "")),
        "tmdbId": numeric_id or None,
        "title": canonical_title,
        "year": year or None,
        "mediaType": media_type,
        "overview": overview,
        "posterUrl": poster_url,
        "backdropUrl": backdrop_url,
        "rating": _number(raw.get("rating") or raw.get("vote_average")),
        "tmdbUrl": tmdb_url,
        "source": str(raw.get("source") or "VPS catalogue cache"),
        "synopsisCheckedAt": raw.get("synopsisCheckedAt"),
        "synopsisLookupVersion": raw.get("synopsisLookupVersion"),
    }


def _read_persistent_search_metadata_cache() -> dict[str, Any]:
    try:
        payload = json.loads(TMDB_SEARCH_METADATA_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("results", [])
            payload.setdefault("queries", {})
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "results": [], "queries": {}}


def _write_persistent_search_metadata_cache(payload: dict[str, Any]) -> None:
    # The same atomic/fsync writer used by the catalogue snapshots keeps this
    # cache safe across container restarts and interrupted writes.
    _write_synopsis_cache(TMDB_SEARCH_METADATA_CACHE_FILE, payload)


def _persist_search_metadata_cache_rows(
    raw_rows: list[dict[str, Any]],
    *,
    query: str | None = None,
    query_response: dict[str, Any] | None = None,
) -> int:
    """Persist per-title metadata permanently without duplicating synopsis text in query envelopes."""
    disk = _read_persistent_search_metadata_cache()
    rows = disk.get("results", [])
    if not isinstance(rows, list):
        rows = []
    index: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        candidate = _search_metadata_cache_candidate(raw)
        if not candidate:
            continue
        key = (
            _normalize_title(candidate["title"]),
            int(candidate.get("year") or 0),
            str(candidate.get("mediaType") or "movie"),
            str(candidate.get("tmdbId") or ""),
        )
        index[key] = {**raw, **candidate}

    now = int(time.time())
    added = 0
    query_keys: list[dict[str, Any]] = []
    seen_query_keys: set[tuple[str, int, str, str]] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        candidate = _search_metadata_cache_candidate(raw)
        if not candidate:
            continue
        key = (
            _normalize_title(candidate["title"]),
            int(candidate.get("year") or 0),
            str(candidate.get("mediaType") or "movie"),
            str(candidate.get("tmdbId") or ""),
        )
        previous = index.get(key, {})
        # Do not replace a previously stored synopsis or useful artwork with blanks.
        merged = {**previous, **candidate}
        for field in ("overview", "posterUrl", "backdropUrl", "tmdbUrl", "tmdbId", "year", "rating"):
            if candidate.get(field) in (None, "", 0):
                if previous.get(field) not in (None, "", 0):
                    merged[field] = previous[field]
        merged["cacheUpdatedAt"] = now
        if not previous or merged != previous:
            added += 1
        index[key] = merged
        if query and query_response and query_response.get("status") == "ready" and key not in seen_query_keys:
            seen_query_keys.add(key)
            query_keys.append({
                "title": key[0],
                "year": key[1],
                "mediaType": key[2],
                "tmdbId": key[3],
            })

    if query and query_response and query_response.get("status") == "ready":
        queries = disk.get("queries", {})
        if not isinstance(queries, dict):
            queries = {}
        queries[re.sub(r"\s+", " ", query).strip().casefold()] = {
            "savedAt": now,
            "keys": query_keys,
        }
        # Query envelopes only store references; actual synopsis text exists once
        # per title in results and is retained permanently.
        if len(queries) > 1000:
            queries = dict(sorted(
                queries.items(),
                key=lambda pair: int((pair[1] or {}).get("savedAt") or 0),
                reverse=True,
            )[:1000])
        disk["queries"] = queries

    max_rows = 8000
    merged_rows = list(index.values())
    merged_rows.sort(key=lambda item: int(item.get("cacheUpdatedAt") or 0), reverse=True)
    disk["version"] = 1
    disk["updatedAt"] = now
    disk["results"] = merged_rows[:max_rows]
    try:
        _write_persistent_search_metadata_cache(disk)
    except OSError as exc:
        logger.warning("Could not persist search-card synopsis cache: %s", exc)
    return added


def _persist_search_metadata_overview(tmdb_id: int, overview: str) -> int:
    """Persist a newly fetched overview into any matching runtime catalogue row."""
    overview = re.sub(r"\s+", " ", str(overview or "")).strip()
    if tmdb_id < 1 or not overview:
        return 0

    updated_rows = 0
    now = int(time.time())
    for _name, path in _synopsis_cache_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        changed = False
        for row in rows:
            if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                continue
            try:
                row_id = int(row.get("tmdbId") or row.get("id") or 0)
            except (TypeError, ValueError):
                row_id = 0
            if row_id != tmdb_id:
                continue
            row["overview"] = overview
            row["synopsisCheckedAt"] = now
            row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
            changed = True
            updated_rows += 1
        if changed:
            try:
                _write_synopsis_cache(path, payload)
                logger.info("Saved fetched TMDB synopsis for ID %s into %s", tmdb_id, path.name)
            except OSError as exc:
                logger.warning("Could not persist synopsis for TMDB ID %s in %s: %s", tmdb_id, path.name, exc)

    # Popular/Trending/Latest responses are stored in a separate persistent file.
    try:
        disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(disk, dict):
            disk = {}
    except (OSError, ValueError, TypeError):
        disk = {}
    catalogues = disk.get("catalogues", {})
    disk_changed = False
    if isinstance(catalogues, dict):
        for envelope in catalogues.values():
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                    continue
                try:
                    row_id = int(row.get("tmdbId") or row.get("id") or 0)
                except (TypeError, ValueError):
                    row_id = 0
                if row_id == tmdb_id:
                    row["overview"] = overview
                    row["synopsisCheckedAt"] = now
                    row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
                    updated_rows += 1
                    disk_changed = True

    if disk_changed:
        temporary: Path | None = None
        try:
            TMDB_CATALOGUE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                prefix=TMDB_CATALOGUE_CACHE_FILE.stem + "-synopsis-",
                suffix=".tmp", dir=str(TMDB_CATALOGUE_CACHE_FILE.parent), delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(disk, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, TMDB_CATALOGUE_CACHE_FILE)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not persist dynamic catalogue synopsis for TMDB ID %s: %s", tmdb_id, exc)
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    # Keep in-memory catalogue responses consistent with the disk cache.
    for cache_key, entry in list(_tmdb_movie_catalogue_cache.items()):
        payload = entry[1]
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                continue
            try:
                row_id = int(row.get("tmdbId") or row.get("id") or 0)
            except (TypeError, ValueError):
                row_id = 0
            if row_id == tmdb_id:
                row["overview"] = overview
                row["synopsisCheckedAt"] = now
                row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
    return updated_rows


async def _lookup_search_metadata_by_tmdb_id(item: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch a missing synopsis using the cached row's authoritative TMDB ID."""
    try:
        tmdb_id = int(item.get("tmdbId") or item.get("id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if tmdb_id < 1:
        return None

    details: dict[str, Any] | None = None
    for language in ("en-US", "en"):
        try:
            details = await asyncio.wait_for(
                _tmdb_get_json(
                    f"movie/{tmdb_id}",
                    {"language": language},
                    request_timeout=3.0,
                ),
                timeout=4.5,
            )
        except Exception as exc:
            logger.info("On-demand synopsis lookup failed for TMDB ID %s (%s): %s",
                tmdb_id, language, type(exc).__name__)
            continue
        overview = re.sub(r"\s+", " ", str(details.get("overview") or "")).strip()
        if overview:
            return {
                "overview": overview,
                "tmdbId": tmdb_id,
                "tmdbUrl": f"https://www.themoviedb.org/movie/{tmdb_id}",
                "rating": float(details.get("vote_average") or item.get("rating") or 0),
                "posterUrl": (
                    TMDB_IMAGE_BASE + str(details.get("poster_path")).strip()
                    if str(details.get("poster_path") or "").strip()
                    else str(item.get("posterUrl") or "")
                ),
                "backdropUrl": (
                    "https://image.tmdb.org/t/p/w780" + str(details.get("backdrop_path")).strip()
                    if str(details.get("backdrop_path") or "").strip()
                    else str(item.get("backdropUrl") or "")
                ),
                "synopsisCheckedAt": int(time.time()),
                "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
            }
        # Only issue the alternate-language request if TMDB answered but had no overview.
    return None


def _read_search_metadata_catalogue_rows() -> list[dict[str, Any]]:
    """Read metadata from the persistent VPS JSON snapshots used by the catalogues."""
    candidates: list[dict[str, Any]] = []
    for _name, path in _synopsis_cache_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if isinstance(rows, list):
            candidates.extend(row for row in rows if isinstance(row, dict))

    # Query search results and successful synopses are kept separately so arbitrary
    # searches survive restarts even when they are not in a prebuilt catalogue.
    persistent_metadata = _read_persistent_search_metadata_cache()
    persistent_rows = persistent_metadata.get("results", [])
    if isinstance(persistent_rows, list):
        candidates.extend(row for row in persistent_rows if isinstance(row, dict))

    # Popular, Trending and Latest are stored separately from franchise snapshots.
    try:
        disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        catalogues = disk.get("catalogues", {}) if isinstance(disk, dict) else {}
        for envelope in catalogues.values() if isinstance(catalogues, dict) else []:
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if isinstance(rows, list):
                candidates.extend(row for row in rows if isinstance(row, dict))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return candidates


@router.get("/api/search/metadata/batch")
async def api_search_metadata_batch(
    titles: list[str] = Query(..., min_length=2, max_length=180),
):
    """Resolve search-card metadata from persistent VPS catalogue JSON by exact title/year."""
    requested = list(dict.fromkeys(
        re.sub(r"\s+", " ", str(value or "")).strip()
        for value in titles[:80] if str(value or "").strip()
    ))
    if not requested:
        return {"status": "ready", "source": "VPS catalogue cache", "results": []}

    candidates = []
    seen_rows: set[tuple[str, int, str, str]] = set()
    for raw in _read_search_metadata_catalogue_rows():
        item = _search_metadata_cache_candidate(raw)
        if not item:
            continue
        identity = (
            _normalize_title(item["title"]),
            int(item.get("year") or 0),
            str(item.get("mediaType") or "movie"),
            str(item.get("tmdbId") or ""),
        )
        if identity not in seen_rows:
            seen_rows.add(identity)
            candidates.append(item)

    matched: list[dict[str, Any]] = []
    missing_synopsis_candidates: dict[int, dict[str, Any]] = {}
    seen_matches: set[tuple[str, int, str]] = set()
    for requested_title in requested:
        year_match = re.search(r"\s*\(?((?:19|20)\d{2})\)?\s*$", requested_title)
        requested_year = int(year_match.group(1)) if year_match else 0
        clean_title = re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", requested_title).strip()
        target = _normalize_title(clean_title)
        if not target:
            continue
        options = [item for item in candidates if _normalize_title(item["title"]) == target]
        same_year = [item for item in options if int(item.get("year") or 0) == requested_year] if requested_year else []
        unknown_year = [item for item in options if not int(item.get("year") or 0)]
        if same_year:
            selected = same_year
        elif unknown_year:
            selected = unknown_year if len(unknown_year) == 1 else []
        elif not requested_year and options:
            selected = options
        elif len(options) == 1:
            selected = options
        else:
            selected = []
        if not selected:
            continue
        selected.sort(key=lambda item: (
            bool(item.get("overview")),
            bool(item.get("tmdbId")),
            float(item.get("rating") or 0),
        ), reverse=True)
        best = selected[0]
        match_key = (
            _normalize_title(best["title"]),
            int(best.get("year") or 0),
            str(best.get("mediaType") or "movie"),
        )
        if match_key not in seen_matches:
            seen_matches.add(match_key)
            matched.append(best)
        if not str(best.get("overview") or "").strip():
            try:
                missing_id = int(best.get("tmdbId") or best.get("id") or 0)
            except (TypeError, ValueError):
                missing_id = 0
            if missing_id > 0:
                missing_synopsis_candidates.setdefault(missing_id, best)

    # The saved catalogues can know a movie's TMDB ID even when the discover/search
    # list originally supplied no overview. Hydrate a small batch of those misses by
    # ID, then write the successful synopsis back into the persistent JSON caches.
    # Bound concurrency/work so a large catalogue search does not turn into a slow scan.
    semaphore = asyncio.Semaphore(4)
    async def hydrate_missing(item_id: int, item: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        async with semaphore:
            metadata = await _lookup_search_metadata_by_tmdb_id(item)
            return item_id, metadata

    selected_missing = list(missing_synopsis_candidates.items())[:12]
    if selected_missing:
        hydrated = await asyncio.gather(
            *(hydrate_missing(item_id, item) for item_id, item in selected_missing),
            return_exceptions=True,
        )
        for value in hydrated:
            if isinstance(value, Exception) or not isinstance(value, tuple):
                continue
            item_id, metadata = value
            if not metadata or not str(metadata.get("overview") or "").strip():
                continue
            for item in matched:
                try:
                    existing_id = int(item.get("tmdbId") or item.get("id") or 0)
                except (TypeError, ValueError):
                    existing_id = 0
                if existing_id != item_id:
                    continue
                item.update(metadata)
                item["source"] = "TMDB movie details"
            persisted_item = {**item, **metadata}
            _persist_search_metadata_cache_rows([persisted_item])
            saved_rows = _persist_search_metadata_overview(item_id, metadata["overview"])
            logger.info("Hydrated missing search-card synopsis for TMDB ID %s; persisted rows=%s",
                item_id, saved_rows)

    # Permanently save successful overview hits from any of the catalogue sources.
    matched = [item for item in matched if str(item.get("overview") or "").strip()]
    if matched:
        _persist_search_metadata_cache_rows(matched)

    # Never send blank synopsis entries if no details lookup could recover them;
    # this keeps the response list focused on usable saved metadata.
    return {
        "status": "ready",
        "source": "VPS catalogue cache",
        "requested": len(requested),
        "matched": len(matched),
        "results": matched,
    }


@router.get("/api/search")
async def api_search(request: Request, q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=50)):
    prepare_intent = request.headers.get("x-prepare-intent", "missing")
    prepare_trace = request.headers.get("x-prepare-trace", "missing")
    if prepare_intent != "missing" or prepare_trace != "missing":
        logger.info(
            "PREPARE_TRACE event=live-search-request intent=%s trace=%s query=%r",
            prepare_intent, prepare_trace, q,
        )
    # Live torrent-provider access is explicitly scoped to this user-triggered endpoint.
    token = _MANUAL_TORRENT_SEARCH.set(True)
    try:
        return await search_1337x(q, limit)
    finally:
        _MANUAL_TORRENT_SEARCH.reset(token)
