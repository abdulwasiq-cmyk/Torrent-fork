#!/usr/bin/env python3
"""Metadata-only enrichment for the nine top-level section seed JSON files.

Preserves section membership/order. Reads shared IMDb/OTT caches, calls only
TMDB metadata and IMDb metadata endpoints, and writes only <section>.json files.
Never reads/writes paired *-torrents.json files or calls torrent search routes.
Usage:
  python scripts/enrich_top_section_metadata.py [--mode missing|deep]
  python scripts/enrich_top_section_metadata.py --section anime --mode missing

The default API is http://127.0.0.1:3000; set HOME_API_BASE to override it.
"""
from __future__ import annotations

import argparse
import email.utils
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for import_path in (ROOT, BACKEND):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from backend.metadata.imdb import _imdb_rating_cache_key  # noqa: E402

HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or HOME / "seed").resolve()
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:3000").rstrip("/")
REGION = os.getenv("OTT_REGION", "IN").upper()
SECTIONS = (
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
)
TV_SUBSECTIONS = {
    ("marvel", "series"), ("dc", "series"), ("highest-rated", "tv"),
    ("korean", "series"), ("pakistani", "series"), ("anime", "series"),
    ("favourites", "series"), ("favourites", "anime"),
}
TORRENT_KEYS = {
    "torrent", "torrents", "torrentdetails", "torrentmatch", "torrentmatches",
    "cachedtorrentdetails", "torrentreleases", "torrentresults", "magnet",
    "magneturl", "infohash", "hash", "downloadurl", "seeders", "leechers",
    "nexstream", "episodes",
}
VALID_IMDB = re.compile(r"^tt\d+$")
RETRYABLE_STATUS_CODES = {408, 425, 429}
UNSUPPORTED_ENDPOINTS: set[str] = set()
UNSUPPORTED_ENDPOINTS_REPORTED: set[str] = set()


class UnsupportedEndpoint(RuntimeError):
    pass


def log(event: str, **data: Any) -> None:
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Could not read JSON from {path}: {exc}") from exc


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def endpoint_template(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    path = re.sub(r"/api/tv/tmdb-metadata/\d+$", "/api/tv/tmdb-metadata/{tmdb_id}", path)
    path = re.sub(r"/api/movies/tmdb-metadata/\d+$", "/api/movies/tmdb-metadata/{tmdb_id}", path)
    path = re.sub(r"/api/catalogue/tmdb-find/tt\d+$", "/api/catalogue/tmdb-find/{imdb_id}", path)
    path = re.sub(r"/api/movies/ott/\d+$", "/api/movies/ott/{movie_id}", path)
    return path


def retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
    headers = getattr(exc, "headers", None) or getattr(exc, "hdrs", None) or {}
    retry_after = str(headers.get("Retry-After") or "").strip()
    try:
        return min(21600.0, max(0.0, float(retry_after)))
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(retry_after)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return min(21600.0, max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            pass
        return min(30.0, 0.5 * (2 ** attempt))


def request_json(url: str, timeout: int = 60) -> dict[str, Any]:
    template = endpoint_template(url)
    if template in UNSUPPORTED_ENDPOINTS:
        raise UnsupportedEndpoint(f"API endpoint is unavailable: {template}")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "TorrentStudio-SectionMetadataRefresh/1.0",
    })
    retries = max(0, int(os.getenv("SECTION_METADATA_RETRIES", "3")))
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
            if not isinstance(value, dict):
                raise RuntimeError("API returned a non-object JSON response")
            return value
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                UNSUPPORTED_ENDPOINTS.add(template)
                raise UnsupportedEndpoint(f"API endpoint is unavailable: {template}") from exc
            retryable = exc.code in RETRYABLE_STATUS_CODES or exc.code >= 500
            if not retryable or attempt >= retries:
                raise
            delay = retry_delay(exc, attempt)
            log("api_retry", endpoint=template, attempt=attempt + 1, status=exc.code, delaySeconds=delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise
            delay = min(30.0, 0.5 * (2 ** attempt))
            log("api_retry", endpoint=template, attempt=attempt + 1, error=str(exc), delaySeconds=delay)
        time.sleep(delay)
    raise RuntimeError(f"API request exhausted retries: {template}")


def valid_id(value: Any) -> int:
    try:
        n = int(value)
        return n if n > 0 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def empty(value: Any) -> bool:
    return value is None or value is False or value == "" or value == 0 or value == [] or value == {}


def has_torrent_payload(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
            if normalized in TORRENT_KEYS or any(
                marker in normalized for marker in (
                    "magnet", "infohash", "torrentmatch", "torrentrelease",
                    "torrentresult", "seeders", "leechers", "downloadurl",
                )
            ):
                return True
            if has_torrent_payload(child):
                return True
    elif isinstance(value, list):
        return any(has_torrent_payload(item) for item in value)
    return False


def image_url(value: Any, size: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Strip repeated TMDB size prefixes, including malformed /w500/w780/... paths.
    if "image.tmdb.org/t/p/" in raw:
        tail = urllib.parse.urlsplit(raw).path.split("/t/p/", 1)[1]
        parts = tail.split("/")
        while parts and re.fullmatch(r"w\d+|original", parts[0]):
            parts.pop(0)
        filename = "/".join(parts).lstrip("/")
        return f"https://image.tmdb.org/t/p/{size}/{filename}" if filename else ""
    if raw.startswith("/") or re.match(r"^(?:w\d+|original)/", raw):
        raw = raw.lstrip("/")
        while re.match(r"^(?:w\d+|original)/", raw):
            raw = raw.split("/", 1)[1]
        return f"https://image.tmdb.org/t/p/{size}/{raw}" if raw else ""
    return raw


def media_type(section: str, subsection: str, node: dict[str, Any]) -> str:
    if node.get("mediaType") in {"tv", "series"} or (section, subsection) in TV_SUBSECTIONS:
        return "tv"
    return "movie"


def cache_key_for(row: dict[str, Any], kind: str) -> str:
    title = str(row.get("title") or row.get("name") or "").strip()
    raw_year = row.get("year") or row.get("releaseDate") or row.get("firstAirDate") or ""
    match = re.match(r"^(\d{4})", str(raw_year))
    year = int(match.group(1)) if match else 0
    return _imdb_rating_cache_key(title, year, kind) if title else ""


def valid_rating(value: Any) -> bool:
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return False
    return 0 < rating <= 10


def apply_imdb(row: dict[str, Any], record: dict[str, Any], *, overwrite: bool = False) -> int:
    changed = 0
    imdb_id = str(record.get("imdbId") or "").strip()
    existing_id = str(row.get("imdbId") or "").strip()
    if VALID_IMDB.fullmatch(imdb_id) and (overwrite or not VALID_IMDB.fullmatch(existing_id)):
        row["imdbId"] = imdb_id
        changed += 1
    rating = record.get("imdbRating")
    try:
        rating = float(rating)
    except (TypeError, ValueError):
        rating = None
    if rating is not None and 0 < rating <= 10 and (overwrite or not valid_rating(row.get("imdbRating"))):
        row["imdbRating"] = rating
        changed += 1
    for source, target in (("imdbVotes", "imdbVotes"), ("imdbUrl", "imdbUrl")):
        if (overwrite or empty(row.get(target))) and not empty(record.get(source)):
            row[target] = record[source]
            changed += 1
    if record.get("checkedAt") and (overwrite or not row.get("imdbCheckedAt")):
        row["imdbCheckedAt"] = record["checkedAt"]
        changed += 1
    if record.get("status") and (
        record["status"] == "found"
        or (not valid_rating(row.get("imdbRating")) and not VALID_IMDB.fullmatch(str(row.get("imdbId") or "")))
    ):
        row["imdbRatingStatus"] = record["status"]
    return changed


def movie_ott(ott_items: dict[str, Any], tmdb_id: int) -> dict[str, Any] | None:
    for key in (f"v2:{tmdb_id}:{REGION}", f"{tmdb_id}:{REGION}"):
        envelope = ott_items.get(key)
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if isinstance(payload, dict):
            return payload
    return None


def metadata_url(kind: str, tmdb_id: int) -> str:
    prefix = "/api/tv/tmdb-metadata/" if kind == "tv" else "/api/movies/tmdb-metadata/"
    return API + prefix + str(tmdb_id)


def metadata_value_is_valid(field: str, value: Any) -> bool:
    if empty(value):
        return False
    if field == "year":
        match = re.match(r"^(\d{4})", str(value))
        return bool(match and 1870 <= int(match.group(1)) <= 2100)
    if field == "rating":
        try:
            return 0 < float(value) <= 10
        except (TypeError, ValueError):
            return False
    if field == "imdbId":
        return VALID_IMDB.fullmatch(str(value).strip()) is not None
    if field == "ottAvailability":
        return isinstance(value, dict) and str(value.get("region") or REGION).upper() == REGION
    if field == "streamingProviders":
        return isinstance(value, list)
    return True


def year_from_dates(row: dict[str, Any]) -> int:
    for field in ("releaseDate", "firstAirDate", "release_date", "first_air_date"):
        match = re.match(r"^(\d{4})", str(row.get(field) or ""))
        if match:
            year = int(match.group(1))
            if 1870 <= year <= 2100:
                return year
    return 0


DETAIL_FIELDS = (
    "year", "releaseDate", "overview", "posterUrl", "backdropUrl", "rating",
    "tmdbUrl", "imdbId", "streamingProviders", "ottAvailability", "providerLink",
)


def merge_metadata(row: dict[str, Any], details: dict[str, Any], *, mode: str) -> int:
    changed = 0
    for field in DETAIL_FIELDS:
        value = details.get(field)
        if not metadata_value_is_valid(field, value):
            continue
        if field in {"posterUrl", "backdropUrl"}:
            value = image_url(value, "w500" if field == "posterUrl" else "w780")
            if not value:
                continue
        current_is_valid = metadata_value_is_valid(field, row.get(field))
        if mode == "deep" or not current_is_valid:
            if row.get(field) != value:
                row[field] = value
                changed += 1
    derived_year = year_from_dates(row)
    if derived_year and not metadata_value_is_valid("year", row.get("year")):
        if row.get("year") != derived_year:
            row["year"] = derived_year
            changed += 1
    return changed


def missing_metadata(row: dict[str, Any], kind: str) -> list[str]:
    missing: list[str] = []
    if not str(row.get("title") or row.get("name") or "").strip():
        missing.append("title")
    if empty(row.get("year")):
        missing.append("year")
    if not valid_id(row.get("tmdbId")):
        missing.append("tmdbId")
    if not VALID_IMDB.fullmatch(str(row.get("imdbId") or "")):
        missing.append("imdbId")
    if not valid_rating(row.get("imdbRating")):
        missing.append("imdbRating")
    if empty(row.get("imdbVotes")):
        missing.append("imdbVotes")
    if empty(row.get("imdbUrl")):
        missing.append("imdbUrl")
    if row.get("mediaType") not in {"movie", "tv", "series"}:
        missing.append("mediaType")
    for field in ("posterUrl", "backdropUrl", "overview"):
        if empty(row.get(field)):
            missing.append(field)
    if not valid_rating(row.get("rating")):
        missing.append("rating")
    if empty(row.get("releaseDate")) and (kind != "tv" or empty(row.get("firstAirDate"))):
        missing.append("releaseDate")
    if not metadata_value_is_valid("ottAvailability", row.get("ottAvailability")):
        missing.append("ottAvailability")
    return missing


def enrich_imdb_batches(
    rows: list[tuple[dict[str, Any], str, int]],
    cache: dict[str, dict[str, Any]],
    *,
    mode: str,
) -> int:
    pending_by_key: dict[str, tuple[str, int, str, list[dict[str, Any]]]] = {}
    for row, kind, tmdb_id in rows:
        key = cache_key_for(row, kind)
        cached = cache.get(key)
        if cached and cached.get("status") == "found":
            apply_imdb(row, cached, overwrite=mode == "deep")
        complete = (
            VALID_IMDB.fullmatch(str(row.get("imdbId") or "")) is not None
            and valid_rating(row.get("imdbRating"))
            and not empty(row.get("imdbVotes"))
            and not empty(row.get("imdbUrl"))
        )
        if mode == "deep" or not complete:
            title = str(row.get("title") or row.get("name") or "").strip()
            raw_year = row.get("year") or row.get("releaseDate") or row.get("firstAirDate") or ""
            match = re.match(r"^(\d{4})", str(raw_year))
            year = match.group(1) if match else ""
            query = f"{title} ({year})" if year else title
            if title and key:
                pending = pending_by_key.get(key)
                if pending:
                    pending[3].append(row)
                else:
                    pending_by_key[key] = (kind, tmdb_id, query, [row])
    fetched = 0
    pending = list(pending_by_key.values())
    for start in range(0, len(pending), 80):
        batch = pending[start:start + 80]
        params = [("persist", "false"), ("refresh_incomplete", "true")]
        for kind, tmdb_id, query, _ in batch:
            params.extend([
                ("titles", query), ("media_types", kind), ("tmdb_ids", str(tmdb_id)),
            ])
        url = API + "/api/catalogue/imdb-ratings?" + urllib.parse.urlencode(params)
        try:
            payload = request_json(url, timeout=180)
        except UnsupportedEndpoint as exc:
            log("imdb_endpoint_unavailable", endpoint=endpoint_template(url), error=str(exc))
            break
        except Exception as exc:
            log("imdb_batch_failed", batch=start // 80 + 1, count=len(batch), error=str(exc))
            continue
        by_query = {str(item.get("query") or "").casefold(): item
                    for item in payload.get("results", []) if isinstance(item, dict)}
        for kind, tmdb_id, query, target_rows in batch:
            result = by_query.get(query.casefold())
            if not result:
                continue
            # A TMDB identity mismatch must never overwrite the curated row.
            returned = valid_id(result.get("tmdbIdTried"))
            if returned and tmdb_id and returned != tmdb_id:
                continue
            for target in target_rows:
                target_tmdb_id = valid_id(target.get("tmdbId")) or valid_id(target.get("id"))
                if returned and target_tmdb_id and returned != target_tmdb_id:
                    continue
                fetched += apply_imdb(target, result, overwrite=mode == "deep")
            cache_key = cache_key_for(target_rows[0], kind)
            if cache_key:
                cache[cache_key] = result
        log("imdb_batch_complete", batch=start // 80 + 1, requested=len(batch),
            matched=int(payload.get("matched") or 0))
        time.sleep(0.2)
    return fetched


def load_cache(path: Path, label: str) -> dict[str, Any]:
    try:
        value = read_json(path, {})
    except RuntimeError as exc:
        log("cache_read_failed", cache=label, error=str(exc))
        return {}
    if not isinstance(value, dict):
        log("cache_read_failed", cache=label, error="cache root is not an object")
        return {}
    return value


def backup_section(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / path.name
    shutil.copy2(path, destination)
    return destination


def refresh_section(
    section: str,
    *,
    mode: str,
    imdb_cache: dict[str, dict[str, Any]],
    ott_items: dict[str, Any],
    detail_cache: dict[tuple[str, int], dict[str, Any]],
    ott_lookup_cache: dict[int, dict[str, Any]],
    backup_dir: Path,
) -> dict[str, Any]:
    path = SEED / f"{section}.json"
    doc = read_json(path)
    if not isinstance(doc, dict) or not isinstance(doc.get("subsections"), dict):
        raise RuntimeError(f"{path} is missing a valid subsections object")

    pending_imdb: list[tuple[dict[str, Any], str, int]] = []
    counts: dict[str, Any] = {
        "records": 0, "tmdbLookups": 0, "imdbFieldsFilled": 0,
        "metadataFieldsFilled": 0, "ottCacheHits": 0, "ottLookups": 0,
        "unresolved": 0,
    }

    for subsection, node in doc["subsections"].items():
        if not isinstance(node, dict) or not isinstance(node.get("results"), list):
            log("subsection_skipped", section=section, subsection=subsection, reason="invalid_results")
            continue
        if has_torrent_payload(node["results"]):
            raise RuntimeError(
                f"{section}/{subsection} contains torrent-specific data; refusing to write it"
            )
        kind = media_type(section, subsection, node)
        for row in node["results"]:
            if not isinstance(row, dict):
                continue
            counts["records"] += 1
            title = str(row.get("title") or row.get("name") or "").strip()
            tmdb_id = valid_id(row.get("tmdbId")) or valid_id(row.get("id"))
            imdb_id = str(row.get("imdbId") or "").strip()
            if tmdb_id and not valid_id(row.get("tmdbId")):
                row["tmdbId"] = tmdb_id
                counts["metadataFieldsFilled"] += 1
                log("metadata_field_filled", section=section, subsection=subsection,
                    title=title, field="tmdbId", source="id")

            if not tmdb_id and VALID_IMDB.fullmatch(imdb_id):
                find_url = (
                    API + "/api/catalogue/tmdb-find/" + imdb_id
                    + "?" + urllib.parse.urlencode({"media_type": kind})
                )
                try:
                    resolved = request_json(find_url)
                    result_kind = str(resolved.get("mediaType") or "").casefold()
                    expected_kind = "tv" if kind == "tv" else "movie"
                    if (
                        resolved.get("found")
                        and result_kind == expected_kind
                        and valid_id(resolved.get("tmdbId"))
                    ):
                        tmdb_id = valid_id(resolved["tmdbId"])
                        row["tmdbId"] = tmdb_id
                        counts["metadataFieldsFilled"] += 1
                        log("tmdb_id_resolved", section=section, subsection=subsection,
                            title=title, imdbId=imdb_id, tmdbId=tmdb_id, mediaType=kind)
                    else:
                        log("tmdb_id_unresolved", section=section, subsection=subsection,
                            title=title, imdbId=imdb_id, mediaType=kind, reason="no_valid_exact_match")
                except UnsupportedEndpoint as exc:
                    template = endpoint_template(find_url)
                    if template not in UNSUPPORTED_ENDPOINTS_REPORTED:
                        log("tmdb_find_unavailable", endpoint=template, reason=str(exc))
                        UNSUPPORTED_ENDPOINTS_REPORTED.add(template)
                except Exception as exc:
                    log("tmdb_id_resolution_failed", section=section, subsection=subsection,
                        title=title, imdbId=imdb_id, error=str(exc))
                if endpoint_template(find_url) not in UNSUPPORTED_ENDPOINTS:
                    time.sleep(float(os.getenv("SECTION_METADATA_DELAY_SECONDS", "0.15")))

            if row.get("mediaType") not in {"movie", "tv", "series"}:
                row["mediaType"] = kind
                counts["metadataFieldsFilled"] += 1
            if empty(row.get("overview")) and not empty(row.get("synopsis")):
                row["overview"] = row["synopsis"]
                counts["metadataFieldsFilled"] += 1
            for field, legacy in (("posterUrl", "posterPath"), ("backdropUrl", "backdropPath")):
                if empty(row.get(field)) and not empty(row.get(legacy)):
                    size = "w500" if field == "posterUrl" else "w780"
                    row[field] = image_url(row[legacy], size)
                    if row[field]:
                        counts["metadataFieldsFilled"] += 1
            if empty(row.get("releaseDate")) and not empty(row.get("firstAirDate")):
                row["releaseDate"] = row["firstAirDate"]
                counts["metadataFieldsFilled"] += 1
            if empty(row.get("year")):
                derived_year = year_from_dates(row)
                if derived_year:
                    row["year"] = derived_year
                    counts["metadataFieldsFilled"] += 1

            for field, size in (("posterUrl", "w500"), ("backdropUrl", "w780")):
                repaired = image_url(row.get(field), size)
                if repaired and repaired != row.get(field):
                    row[field] = repaired
                    counts["metadataFieldsFilled"] += 1
                    log("metadata_field_filled", section=section, subsection=subsection,
                        title=title, field=field, source="url_normalization")

            if tmdb_id:
                if kind == "movie":
                    cached_ott = movie_ott(ott_items, tmdb_id)
                    has_valid_ott = metadata_value_is_valid("ottAvailability", row.get("ottAvailability"))
                    if cached_ott and mode != "deep" and not has_valid_ott:
                        row["ottAvailability"] = cached_ott
                        if empty(row.get("streamingProviders")):
                            row["streamingProviders"] = cached_ott.get("streamingProviders") or []
                        counts["ottCacheHits"] += 1
                        counts["metadataFieldsFilled"] += 1
                    elif mode == "deep" or not has_valid_ott:
                        if tmdb_id not in ott_lookup_cache:
                            ott_url = API + f"/api/movies/ott/{tmdb_id}?" + urllib.parse.urlencode({"region": REGION})
                            try:
                                ott_lookup_cache[tmdb_id] = request_json(ott_url, timeout=30)
                            except UnsupportedEndpoint as exc:
                                template = endpoint_template(ott_url)
                                if template not in UNSUPPORTED_ENDPOINTS_REPORTED:
                                    log("ott_endpoint_unavailable", endpoint=template, reason=str(exc))
                                    UNSUPPORTED_ENDPOINTS_REPORTED.add(template)
                                ott_lookup_cache[tmdb_id] = {}
                            except Exception as exc:
                                log("ott_lookup_failed", section=section, subsection=subsection,
                                    title=title, tmdbId=tmdb_id, region=REGION, error=str(exc))
                                ott_lookup_cache[tmdb_id] = {}
                            counts["ottLookups"] += 1
                            if endpoint_template(ott_url) not in UNSUPPORTED_ENDPOINTS:
                                time.sleep(float(os.getenv("SECTION_METADATA_DELAY_SECONDS", "0.15")))
                        availability = ott_lookup_cache[tmdb_id]
                        if metadata_value_is_valid("ottAvailability", availability):
                            row["ottAvailability"] = availability
                            row["streamingProviders"] = availability.get("streamingProviders") or []
                            counts["metadataFieldsFilled"] += 1

                current_detail = detail_cache.get((kind, tmdb_id))
                fields_missing = (
                    empty(row.get("year"))
                    or empty(row.get("overview"))
                    or empty(row.get("posterUrl"))
                    or empty(row.get("backdropUrl"))
                    or not valid_rating(row.get("rating"))
                    or (empty(row.get("releaseDate")) and empty(row.get("firstAirDate")))
                    or (kind == "tv" and not metadata_value_is_valid("ottAvailability", row.get("ottAvailability")))
                )
                if mode == "deep" or fields_missing:
                    if current_detail is None:
                        url = metadata_url(kind, tmdb_id)
                        try:
                            current_detail = request_json(url)
                            detail_cache[(kind, tmdb_id)] = current_detail
                            counts["tmdbLookups"] += 1
                        except UnsupportedEndpoint as exc:
                            template = endpoint_template(url)
                            if template not in UNSUPPORTED_ENDPOINTS_REPORTED:
                                log("tmdb_metadata_endpoint_unavailable",
                                    endpoint=template, reason=str(exc))
                                UNSUPPORTED_ENDPOINTS_REPORTED.add(template)
                            detail_cache[(kind, tmdb_id)] = {}
                            current_detail = {}
                        except Exception as exc:
                            log("tmdb_lookup_failed", section=section, subsection=subsection,
                                title=title, tmdbId=tmdb_id, mediaType=kind, error=str(exc))
                            detail_cache[(kind, tmdb_id)] = {}
                            current_detail = {}
                        if endpoint_template(url) not in UNSUPPORTED_ENDPOINTS:
                            time.sleep(float(os.getenv("SECTION_METADATA_DELAY_SECONDS", "0.15")))
                    counts["metadataFieldsFilled"] += merge_metadata(row, current_detail, mode=mode)

            pending_imdb.append((row, kind, tmdb_id))

    counts["imdbFieldsFilled"] = enrich_imdb_batches(pending_imdb, imdb_cache, mode=mode)
    missing_counts: dict[str, int] = {}
    for subsection, node in doc["subsections"].items():
        if not isinstance(node, dict) or not isinstance(node.get("results"), list):
            continue
        kind = media_type(section, subsection, node)
        for row in node["results"]:
            if not isinstance(row, dict):
                continue
            missing = missing_metadata(row, kind)
            for field in missing:
                missing_counts[field] = missing_counts.get(field, 0) + 1
            if missing:
                counts["unresolved"] += 1
                log("record_incomplete", section=section, subsection=subsection,
                    title=row.get("title") or row.get("name"),
                    tmdbId=valid_id(row.get("tmdbId")) or None,
                    imdbId=str(row.get("imdbId") or "") or None, missing=missing)
    counts["missingFields"] = missing_counts
    doc["builtAt"] = datetime.now(timezone.utc).isoformat()
    doc["metadataRefresh"] = {
        "mode": mode,
        "region": REGION,
        "torrentSearches": 0,
        "torrentFilesRead": 0,
        "torrentFilesWritten": 0,
        "curatedOrderPreserved": True,
    }
    backup = backup_section(path, backup_dir)
    atomic_write(path, doc)
    counts["backup"] = str(backup)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("missing", "deep"), default="missing")
    parser.add_argument("--section", action="append", choices=SECTIONS, dest="sections",
                        help="refresh only this section; may be supplied more than once")
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")
    health = request_json(API + "/api/health", timeout=10)
    if not health:
        raise SystemExit("Application API health check failed")

    imdb_doc = load_cache(SEED / "runtime" / "imdb_rating_cache.json", "imdb_rating_cache")
    imdb_rows = imdb_doc.get("results", []) if isinstance(imdb_doc, dict) else []
    imdb_cache = {
        str(item.get("cacheKey")): item for item in imdb_rows
        if isinstance(item, dict) and item.get("cacheKey")
    }
    ott_doc = load_cache(SEED / "runtime" / "tmdb_ott_availability_cache.json", "tmdb_ott_availability_cache")
    ott_items = ott_doc.get("items", {}) if isinstance(ott_doc, dict) else {}
    if not isinstance(ott_items, dict):
        ott_items = {}

    selected_sections = args.sections or list(SECTIONS)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = SEED.parent / "backups" / f"metadata-refresh-{run_stamp}"
    detail_cache: dict[tuple[str, int], dict[str, Any]] = {}
    ott_lookup_cache: dict[int, dict[str, Any]] = {}
    totals: dict[str, Any] = {"sections": 0, "records": 0, "tmdbLookups": 0,
                              "metadataFieldsFilled": 0, "imdbFieldsFilled": 0,
                              "ottCacheHits": 0, "ottLookups": 0, "unresolved": 0}
    failures = 0
    for section in selected_sections:
        try:
            section_counts = refresh_section(
                section,
                mode=args.mode,
                imdb_cache=imdb_cache,
                ott_items=ott_items,
                detail_cache=detail_cache,
                ott_lookup_cache=ott_lookup_cache,
                backup_dir=backup_dir,
            )
        except Exception as exc:
            failures += 1
            log("section_failed", section=section, error=str(exc))
            continue
        totals["sections"] += 1
        for key in ("records", "tmdbLookups", "metadataFieldsFilled", "imdbFieldsFilled",
                    "ottCacheHits", "ottLookups", "unresolved"):
            totals[key] += section_counts[key]
        for field, count in section_counts["missingFields"].items():
            totals.setdefault("missingFields", {})
            totals["missingFields"][field] = totals["missingFields"].get(field, 0) + count
        log("section_written", section=section, **section_counts)

    log("metadata_refresh_complete", **totals,
        imdbCacheRecords=len(imdb_rows), ottCacheEntries=len(ott_items),
        failedSections=failures, torrentSearches=0, torrentFilesRead=0, torrentFilesWritten=0)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
