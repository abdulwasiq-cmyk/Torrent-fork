"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Query, Request

from core.cache_diagnostics import _record_cache_event
from core.http_cache import (
    _fast_json_response,
    _file_signature,
    _memoized_file_read,
    _page_catalogue_payload,
    _prebuilt_catalogue_page,
)
from metadata.posters import (
    _canonical_catalogue_poster_url,
    _catalogue_row_has_3d_quality,
    _catalogue_row_is_excluded_franchise_title,
    _poster_lookup,
    _poster_url_for_release,
    _sort_cached_catalogue_results,
)
from search.search_providers import (
    _normalize_title,
    _search_tokens,
    parse_size,
    search_1337x,
    search_1337x_direct,
    search_limetorrents,
    search_yts_movies,
)
from seedr.seedr_client import info_hash
from core.settings import (
    BACKFILL_MISSING_METADATA,
    CACHE_FIRST,
    CACHE_ONLY_MODE,
    DATA_DIR,
    DC_TV_CATALOGUE_CACHE_FILE,
    IMDB_RATING_CACHE_FILE,
    MARVEL_TV_CATALOGUE_CACHE_FILE,
    MAX_SEARCH_RESULT_SIZE_BYTES,
    MIN_SEARCH_RESULT_SIZE_BYTES,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS,
    TMDB_API_KEYS,
    TMDB_CATALOGUE_CACHE_FILE,
    TMDB_IMAGE_BASE,
    TMDB_OTT_CACHE_FILE,
    TMDB_READ_ACCESS_TOKENS,
    TMDB_SEARCH_METADATA_CACHE_FILE,
    TMDB_SYNOPSIS_LOOKUP_VERSION,
    WATCHMODE_API_KEYS,
    _CACHE_SEED_DIR,
    data_file,
    logger,
    stored_ttl,
)
from metadata.tmdb import (
    _read_tmdb_persistent_cache,
    _tmdb_get_json,
    _tmdb_movie_catalogue_cache,
    _tmdb_ott_cache,
    _watchmode_get,
    _write_tmdb_persistent_cache,
)

router = APIRouter()


# One-time Marvel catalogue. Results are shared by every visitor to this Home
# instance and never expire; the deployment mounts /app/data on persistent VPS
# storage so a container replacement does not force another provider crawl.
MARVEL_CATALOGUE_VERSION = 11
MARVEL_CATALOGUE_PATH = Path(os.getenv("MARVEL_CATALOGUE_PATH", data_file("marvel_catalogue.json")))
# Curated live-action theatrical Marvel films across studios (Marvel Studios, Fox,
# Sony, Universal, etc.). Excludes TV films, specials, documentaries, and animated
# feature films so the persistent torrent catalogue stays focused on live-action movies.
MARVEL_MOVIE_SEARCHES: tuple[tuple[str, int], ...] = (
    # MCU theatrical films, newest first.
    ("Spider-Man: Brand New Day", 2026),
    # Marvel Television special presentation starring Jon Bernthal as the Punisher.
    ("The Punisher: One Last Kill", 2026),
    ("The Fantastic Four: First Steps", 2025),
    ("Thunderbolts", 2025),
    ("Captain America: Brave New World", 2025),
    ("Deadpool & Wolverine", 2024),
    ("The Marvels", 2023),
    ("Guardians of the Galaxy Vol. 3", 2023),
    ("Ant-Man and the Wasp: Quantumania", 2023),
    ("Black Panther: Wakanda Forever", 2022),
    ("Thor: Love and Thunder", 2022),
    ("Doctor Strange in the Multiverse of Madness", 2022),
    ("Spider-Man: No Way Home", 2021),
    ("Eternals", 2021),
    ("Shang-Chi and the Legend of the Ten Rings", 2021),
    ("Black Widow", 2021),
    ("Spider-Man: Far From Home", 2019),
    ("Avengers: Endgame", 2019),
    ("Captain Marvel", 2019),
    ("Ant-Man and the Wasp", 2018),
    ("Avengers: Infinity War", 2018),
    ("Black Panther", 2018),
    ("Thor: Ragnarok", 2017),
    ("Spider-Man: Homecoming", 2017),
    ("Guardians of the Galaxy Vol. 2", 2017),
    ("Doctor Strange", 2016),
    ("Captain America: Civil War", 2016),
    ("Ant-Man", 2015),
    ("Avengers: Age of Ultron", 2015),
    ("Guardians of the Galaxy", 2014),
    ("Captain America: The Winter Soldier", 2014),
    ("Thor: The Dark World", 2013),
    ("Iron Man 3", 2013),
    ("The Avengers", 2012),
    ("Captain America: The First Avenger", 2011),
    ("Thor", 2011),
    ("Iron Man 2", 2010),
    ("The Incredible Hulk", 2008),
    ("Iron Man", 2008),

    # Non-MCU live-action theatrical films from Sony, Fox, and other studios.
    ("Kraven the Hunter", 2024),
    ("Madame Web", 2024),
    ("Venom: The Last Dance", 2024),
    ("Morbius", 2022),
    ("The New Mutants", 2020),
    ("Deadpool 2", 2018),
    ("Venom", 2018),
    ("Logan", 2017),
    ("Dark Phoenix", 2019),
    ("X-Men: Apocalypse", 2016),
    ("Deadpool", 2016),
    ("The Amazing Spider-Man 2", 2014),
    ("X-Men: Days of Future Past", 2014),
    ("The Wolverine", 2013),
    ("The Amazing Spider-Man", 2012),
    ("Ghost Rider: Spirit of Vengeance", 2011),
    ("X-Men: First Class", 2011),
    ("X-Men Origins: Wolverine", 2009),
    ("Punisher: War Zone", 2008),
    ("Venom: Let There Be Carnage", 2021),
    ("Fantastic Four: Rise of the Silver Surfer", 2007),
    ("Spider-Man 3", 2007),
    ("Ghost Rider", 2007),
    ("X-Men: The Last Stand", 2006),
    ("Elektra", 2005),
    ("Fantastic Four", 2005),
    ("Blade: Trinity", 2004),
    ("The Punisher", 2004),
    ("Spider-Man 2", 2004),
    ("X2: X-Men United", 2003),
    ("Daredevil", 2003),
    ("Hulk", 2003),
    ("Blade II", 2002),
    ("Spider-Man", 2002),
    ("X-Men", 2000),
    ("Blade", 1998),
    ("Howard the Duck", 1986),

    # Animated Spider-Verse films and other Marvel animated features.
    ("Spider-Man: Across the Spider-Verse", 2023),
    ("Spider-Man: Into the Spider-Verse", 2018),
    ("Spider-Man: The Venom Saga", 2005),
    ("Ultimate Avengers: The Movie", 2006),
    ("Ultimate Avengers 2", 2006),
    ("The Invincible Iron Man", 2007),
    ("Doctor Strange: The Sorcerer Supreme", 2007),
    ("Hulk Vs.", 2009),
    ("Planet Hulk", 2010),
    ("Thor: Tales of Asgard", 2011),
    ("Iron Man: Rise of Technovore", 2013),
    ("Avengers Confidential: Black Widow & Punisher", 2014),
    ("Marvel Super Hero Adventures: Frost Fight!", 2015),
    ("Captain America", 1944),
    ("The Amazing Spider-Man", 1977),
    ("Spider-Man Strikes Back", 1978),
    ("Spider-Man: The Dragon's Challenge", 1981),
    ("Dr. Strange", 1978),
    ("Captain America", 1990),
    ("Captain America II: Death Too Soon", 1979),
    ("The Incredible Hulk Returns", 1988),
    ("The Trial of the Incredible Hulk", 1989),
    ("The Death of the Incredible Hulk", 1990),
    ("Man-Thing", 2005),
    ("Generation X", 1996),
    ("Nick Fury: Agent of S.H.I.E.L.D.", 1998),
    ("Blade", 1998),
    ("Howard the Duck", 1986),
    ("The Punisher", 1989),
    ("The Punisher", 2004),
    ("Dr. Strange", 1978),
    ("The Fantastic Four", 1994),
)
_MARVEL_CATALOGUE_CONCURRENCY = 2
_marvel_catalogue_task: asyncio.Task | None = None
_marvel_catalogue_retry_after = 0.0
_marvel_catalogue_state: dict[str, Any] = {
    "status": "idle",
    "completed": 0,
    "total": len(MARVEL_MOVIE_SEARCHES),
    "resultCount": 0,
    "error": "",
}


def _read_marvel_catalogue() -> dict[str, Any] | None:
    return _memoized_file_read("marvel", MARVEL_CATALOGUE_PATH, _read_marvel_catalogue_uncached)


def _read_marvel_catalogue_uncached() -> dict[str, Any] | None:
    try:
        payload = json.loads(MARVEL_CATALOGUE_PATH.read_text(encoding="utf-8"))
        if (
            isinstance(payload, dict)
            # Reuse the previous curated snapshot across catalogue-version
            # changes. A version bump must not discard thousands of usable
            # cached torrent rows and trigger a full provider crawl.
            and isinstance(payload.get("version"), int)
            and payload.get("version") <= MARVEL_CATALOGUE_VERSION
            and isinstance(payload.get("results"), list)
            and payload["results"]
        ):
            changed = False
            retained_results = [
                item for item in payload["results"]
                if isinstance(item, dict)
                and not _catalogue_row_has_3d_quality(item)
                and not _catalogue_row_is_excluded_franchise_title(item)
            ]
            if len(retained_results) != len(payload["results"]):
                changed = True
            sorted_results = _sort_cached_catalogue_results(retained_results)
            if sorted_results != payload["results"]:
                changed = True
            payload["results"] = sorted_results
            payload["resultCount"] = len(sorted_results)
            payload["movieCount"] = len({
                re.sub(r"[^a-z0-9]+", "", str(item.get("catalogueTitle") or item.get("marvelCatalogueTitle") or item.get("mediaTitle") or item.get("title") or "").casefold())
                for item in sorted_results
            })
            for item in payload["results"]:
                canonical_poster = _canonical_catalogue_poster_url(item)
                if canonical_poster and item.get("posterUrl") != canonical_poster:
                    item["posterUrl"] = canonical_poster
                    changed = True
            if changed:
                _write_marvel_catalogue(payload)
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return None


def _write_marvel_catalogue(payload: dict[str, Any]) -> None:
    MARVEL_CATALOGUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="marvel-catalogue-",
            suffix=".tmp",
            dir=str(MARVEL_CATALOGUE_PATH.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, MARVEL_CATALOGUE_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def _merge_bundled_marvel_catalogue_cache(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Restore curated, OTT-enriched torrent rows from the bundled snapshot.

    The VPS's persistent cache can be older and narrower than the bundled
    snapshot. Merge only titles in the current curated list, while leaving the
    cache version old so the normal background refresh still runs.
    """
    if payload and (
        int(payload.get("version") or 0) >= MARVEL_CATALOGUE_VERSION
        or int(payload.get("seedMigrationVersion") or 0) >= MARVEL_CATALOGUE_VERSION
    ):
        return payload
    seed_path = _CACHE_SEED_DIR / "marvel_catalogue.json"
    try:
        seed_payload = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return payload

    if not isinstance(seed_payload, dict) or not isinstance(seed_payload.get("results"), list):
        return payload
    if payload and (
        int(payload.get("version") or 0) >= MARVEL_CATALOGUE_VERSION
        or int(payload.get("seedMigrationVersion") or 0) >= MARVEL_CATALOGUE_VERSION
    ):
        return payload

    # With no usable live file, start from the seed's metadata but rebuild its
    # result list from current allowed titles only (no legacy TV films/specials).
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        migrated = dict(payload)
        rows = [dict(item) for item in payload["results"] if isinstance(item, dict)]
    else:
        migrated = dict(seed_payload)
        migrated["results"] = []
        rows = []

    current_titles = {
        (re.sub(r"[^a-z0-9]+", "", title.casefold()), year): title
        for title, year in MARVEL_MOVIE_SEARCHES
    }

    def row_key(item: dict[str, Any]) -> str:
        digest = str(item.get("infoHash") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", digest):
            digest = info_hash(str(item.get("magnetUrl") or item.get("downloadUrl") or ""))
        if re.fullmatch(r"[0-9a-f]{40}", digest, re.I):
            return "hash:" + digest.lower()
        normalized = _normalize_title(str(item.get("title") or ""))
        if not normalized:
            return ""
        try:
            size = int(float(item.get("size") or 0))
        except (TypeError, ValueError, OverflowError):
            size = 0
        return f"title-size:{normalized}|{size}"

    def score(item: dict[str, Any]) -> tuple[int, int]:
        try:
            seeders = int(float(item.get("seeders") or 0))
        except (TypeError, ValueError, OverflowError):
            seeders = 0
        try:
            leechers = int(float(item.get("leechers") or 0))
        except (TypeError, ValueError, OverflowError):
            leechers = 0
        return seeders, leechers

    def missing(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    def ott_score(value: Any) -> int:
        if not isinstance(value, dict):
            return 0
        streaming = value.get("streamingProviders") or []
        rent = value.get("rentProviders") or []
        buy = value.get("buyProviders") or []
        status = str(value.get("status") or "").strip().lower()
        if streaming:
            return 4
        if rent or buy:
            return 3
        if status in {"unavailable", "not_available", "not available"}:
            return 2
        if status and status not in {"unknown", "error", "pending"}:
            return 1
        return 0

    metadata_fields = (
        "tmdbId", "tmdbUrl", "releaseDate", "rating", "posterUrl",
        "backdropUrl", "overview", "genres", "synopsisCheckedAt",
        "synopsisLookupVersion", "synopsisSource", "ottAvailability",
    )
    positions: dict[str, int] = {}
    for index, item in enumerate(rows):
        key = row_key(item)
        if key:
            positions[key] = index

    changed = False
    restored_rows = 0
    restored_titles: set[tuple[str, int]] = set()
    for seed_item in seed_payload["results"]:
        if (
            not isinstance(seed_item, dict)
            or _catalogue_row_has_3d_quality(seed_item)
            or _catalogue_row_is_excluded_franchise_title(seed_item)
        ):
            continue
        old_title = str(
            seed_item.get("marvelCatalogueTitle")
            or seed_item.get("catalogueTitle")
            or seed_item.get("mediaTitle")
            or ""
        ).strip()
        try:
            old_year = int(seed_item.get("year") or 0)
        except (TypeError, ValueError, OverflowError):
            old_year = 0
        canonical = current_titles.get((
            re.sub(r"[^a-z0-9]+", "", old_title.casefold()),
            old_year,
        ))
        if not canonical:
            continue

        candidate = dict(seed_item)
        candidate["mediaTitle"] = canonical
        candidate["marvelCatalogueTitle"] = canonical
        candidate["year"] = old_year
        key = row_key(candidate)
        if not key:
            continue
        restored_titles.add((
            re.sub(r"[^a-z0-9]+", "", canonical.casefold()),
            old_year,
        ))

        position = positions.get(key)
        if position is None:
            positions[key] = len(rows)
            rows.append(candidate)
            restored_rows += 1
            changed = True
            continue

        existing = rows[position]
        merged = dict(existing)
        if score(candidate) > score(existing):
            merged = dict(candidate)
            for field in metadata_fields:
                if missing(merged.get(field)) and not missing(existing.get(field)):
                    merged[field] = existing[field]

        # Preserve the better existing metadata, but restore useful India OTT
        # results when the persistent row has no provider data or only an error.
        for field in metadata_fields:
            value = candidate.get(field)
            if field == "ottAvailability":
                if ott_score(value) > ott_score(merged.get(field)):
                    merged[field] = value
            elif missing(merged.get(field)) and not missing(value):
                merged[field] = value

        if merged != existing:
            rows[position] = merged
            changed = True

    if not changed and int(migrated.get("seedMigrationVersion") or 0) >= MARVEL_CATALOGUE_VERSION:
        return migrated

    migrated["results"] = _sort_cached_catalogue_results(rows)
    migrated["resultCount"] = len(migrated["results"])
    migrated["movieCount"] = len({
        (
            re.sub(
                r"[^a-z0-9]+", "",
                str(item.get("marvelCatalogueTitle") or item.get("mediaTitle") or item.get("title") or "").casefold(),
            ),
            int(item.get("year") or 0),
        )
        for item in migrated["results"]
        if isinstance(item, dict)
    })
    migrated["titlesQueried"] = len(MARVEL_MOVIE_SEARCHES)
    migrated["seedMigrationVersion"] = MARVEL_CATALOGUE_VERSION
    _write_marvel_catalogue(migrated)
    logger.info(
        "Restored %d torrent variants across %d curated Marvel titles from bundled snapshot %s",
        restored_rows,
        len(restored_titles),
        seed_path.name,
    )
    return migrated


def _marvel_result_matches_title(item: dict[str, Any], title: str, year: int) -> bool:
    """Prevent wrong-title and 3D releases from entering shared franchise caches."""
    raw_title = str(item.get("title") or "").strip()
    if not raw_title or _catalogue_row_has_3d_quality(item) or _catalogue_row_is_excluded_franchise_title(item):
        return False

    actual_tokens = set(_search_tokens(raw_title))
    expected_tokens = _search_tokens(title)
    if expected_tokens and expected_tokens[0] in {"the", "a", "an"}:
        expected_tokens = expected_tokens[1:]
    if not expected_tokens or not all(token in actual_tokens for token in expected_tokens):
        return False

    # If a release explicitly carries a year, don't cross-wire remakes/sequels.
    title_years = {
        int(value) for value in re.findall(r"\b((?:19|20)\d{2})\b", raw_title)
    }
    if title_years and year not in title_years:
        return False

    metadata_year = item.get("year")
    if metadata_year not in (None, "") and not title_years:
        try:
            if int(metadata_year) != year:
                return False
        except (TypeError, ValueError):
            pass

    return True


def _extra_result_matches_language(item: dict[str, Any], language: str | None) -> bool:
    """Separate English-original and Hindi/dubbed torrent releases for shared caches."""
    normalized_language = str(language or "").strip().lower()
    if normalized_language not in {"english", "hindi"}:
        return True

    release_text = " ".join(
        str(item.get(field) or "")
        for field in ("title", "quality", "audio", "language", "languages", "audioLanguage", "releaseName")
    )
    hindi_marker = re.compile(
        r"\b(?:hindi|hin|dual[\s._-]*audio|multi[\s._-]*(?:audio|language)|hindi[\s._-]*(?:dubbed|audio))\b",
        re.I,
    )
    other_language_marker = re.compile(
        r"\b(?:hindi|hin|tamil|telugu|malayalam|kannada|bengali|marathi|punjabi|gujarati|urdu|"
        r"dual[\s._-]*audio|multi[\s._-]*audio|multi[\s._-]*language|dubbed)\b",
        re.I,
    )
    if normalized_language == "hindi":
        return bool(hindi_marker.search(release_text))
    return not bool(other_language_marker.search(release_text))


async def _build_marvel_catalogue() -> None:
    if CACHE_ONLY_MODE:
        logger.info("CACHE_ONLY_MODE: skipped Marvel catalogue build; using bundled snapshot.")
        return
    global _marvel_catalogue_retry_after
    semaphore = asyncio.Semaphore(_MARVEL_CATALOGUE_CONCURRENCY)
    poster_semaphore = asyncio.Semaphore(2)
    rows_by_hash: dict[str, dict[str, Any]] = {}
    found_movies: set[str] = set()

    async def resolve_movie_poster(title: str, year: int) -> str:
        async with poster_semaphore:
            try:
                poster = await asyncio.wait_for(
                    _poster_lookup(title, str(year)),
                    timeout=14.0,
                )
                if poster:
                    return poster
            except Exception as exc:
                logger.debug("Marvel poster lookup failed for '%s (%s)': %s", title, year, exc)
        return _poster_url_for_release(f"{title} {year}")

    async def search_movie(title: str, year: int) -> list[dict[str, Any]]:
        async with semaphore:
            try:
                query = f"{title} {year}"
                # Use Home's full provider fan-out first. Some providers return
                # zero rows for older/animated Marvel titles, so fall back to
                # the dedicated YTS catalogue search for those titles.
                try:
                    primary = await asyncio.wait_for(
                        search_1337x(query, limit=50, allow_series_fallback=False),
                        timeout=16.0,
                    )
                except Exception as exc:
                    logger.info("Marvel provider search timed out for '%s': %s", query, exc)
                    primary = []

                def validate_items(items: Any) -> list[dict[str, Any]]:
                    accepted: list[dict[str, Any]] = []
                    if not isinstance(items, list):
                        return accepted
                    for original in items:
                        if (
                            not isinstance(original, dict)
                            or not _marvel_result_matches_title(original, title, year)
                            or not _extra_result_matches_language(original, "english")
                        ):
                            continue
                        item = dict(original)
                        try:
                            size = int(float(item.get("size") or 0))
                            seeders = int(float(item.get("seeders") or 0))
                        except (TypeError, ValueError, OverflowError):
                            continue
                        if size < MIN_SEARCH_RESULT_SIZE_BYTES or size > MAX_SEARCH_RESULT_SIZE_BYTES or seeders <= 0:
                            continue
                        if not any(str(item.get(key) or "").strip() for key in (
                            "magnetUrl", "downloadUrl", "sourceUrl", "infoUrl", "infoHash"
                        )):
                            continue

                        # This field is the stable catalogue identity, not the
                        # raw torrent release name. Quality/magnet stay per variant.
                        item["mediaTitle"] = title
                        item["year"] = year
                        if not item.get("posterUrl"):
                            item["posterUrl"] = _poster_url_for_release(f"{title} {year}")
                        accepted.append(item)
                    return accepted

                accepted = validate_items(primary)
                if len(accepted) < 3:
                    try:
                        yts_items = await asyncio.wait_for(
                            search_yts_movies(query, limit=20),
                            timeout=8.0,
                        )
                        accepted.extend(validate_items(yts_items))
                    except Exception as exc:
                        logger.info("Marvel YTS fallback failed for '%s': %s", query, exc)

                # Deduplicate alternatives per movie before enriching shared poster
                # metadata. Keep the strongest copy of the same info hash.
                per_movie: dict[str, dict[str, Any]] = {}
                for item in accepted:
                    digest = str(item.get("infoHash") or "").strip().lower()
                    if not re.fullmatch(r"[0-9a-f]{40}", digest):
                        digest = info_hash(str(item.get("magnetUrl") or item.get("downloadUrl") or ""))
                    key = "hash:" + digest if re.fullmatch(r"[0-9a-f]{40}", digest, re.I) else (
                        f"title-size:{_normalize_title(str(item.get('title') or ''))}|{int(item.get('size') or 0)}"
                    )
                    previous = per_movie.get(key)
                    if previous is None or (
                        int(item.get("seeders") or 0),
                        int(item.get("leechers") or 0),
                        1 if str(item.get("magnetUrl") or "").startswith("magnet:") else 0,
                    ) > (
                        int(previous.get("seeders") or 0),
                        int(previous.get("leechers") or 0),
                        1 if str(previous.get("magnetUrl") or "").startswith("magnet:") else 0,
                    ):
                        per_movie[key] = item

                accepted = list(per_movie.values())
                if accepted:
                    found_movies.add(f"{_normalize_title(title)}|{year}")
                    poster_url = await resolve_movie_poster(title, year)
                    for item in accepted:
                        item["mediaTitle"] = title
                        item["year"] = year
                        item["posterUrl"] = poster_url
                        item["marvelCatalogueTitle"] = title

                return accepted
            except Exception as exc:
                logger.info("Marvel catalogue search failed for '%s (%s)': %s", title, year, exc)
                return []
            finally:
                _marvel_catalogue_state["completed"] = int(
                    _marvel_catalogue_state.get("completed") or 0
                ) + 1

    try:
        _marvel_catalogue_state.update({
            "status": "building",
            "completed": 0,
            "total": len(MARVEL_MOVIE_SEARCHES),
            "resultCount": 0,
            "movieCount": 0,
            "error": "",
        })
        tasks = [
            asyncio.create_task(search_movie(title, year))
            for title, year in MARVEL_MOVIE_SEARCHES
        ]
        for task in asyncio.as_completed(tasks):
            try:
                items = await task
            except Exception as exc:
                logger.info("Marvel catalogue worker failed: %s", exc)
                items = []

            for item in items:
                digest = str(item.get("infoHash") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", digest):
                    source = str(item.get("magnetUrl") or item.get("downloadUrl") or "")
                    digest = info_hash(source)
                if re.fullmatch(r"[0-9a-f]{40}", digest, re.I):
                    key = "hash:" + digest.lower()
                else:
                    normalized = _normalize_title(str(item.get("title") or ""))
                    if not normalized:
                        continue
                    key = f"title-size:{normalized}|{int(item.get('size') or 0)}"

                previous = rows_by_hash.get(key)
                candidate_score = (
                    1 if str(item.get("magnetUrl") or "").startswith("magnet:") else 0,
                    int(item.get("seeders") or 0),
                    int(item.get("leechers") or 0),
                )
                previous_score = (
                    1 if previous and str(previous.get("magnetUrl") or "").startswith("magnet:") else 0,
                    int(previous.get("seeders") or 0) if previous else 0,
                    int(previous.get("leechers") or 0) if previous else 0,
                )
                if previous is None or candidate_score > previous_score:
                    rows_by_hash[key] = item
            _marvel_catalogue_state["resultCount"] = len(rows_by_hash)
            _marvel_catalogue_state["movieCount"] = len(found_movies)

        # Preserve valid variants for current curated Marvel titles if a provider misses them
        # during this rebuild; new search hits are merged into the existing cache.
        previous_payload = _read_marvel_catalogue()
        current_titles = {
            (re.sub(r"[^a-z0-9]+", "", title.casefold()), year): title
            for title, year in MARVEL_MOVIE_SEARCHES
        }
        if previous_payload:
            for old_item in previous_payload.get("results") or []:
                if not isinstance(old_item, dict):
                    continue
                old_title = str(old_item.get("marvelCatalogueTitle") or old_item.get("mediaTitle") or "").strip()
                try:
                    old_year = int(old_item.get("year") or 0)
                except (TypeError, ValueError):
                    old_year = 0
                # Preserve every previously cached row during additive catalogue
                # updates. Curated titles get canonical naming; legacy entries that
                # are no longer in the current list remain intact rather than vanishing.
                canonical = current_titles.get(
                    (re.sub(r"[^a-z0-9]+", "", old_title.casefold()), old_year),
                    old_title,
                )
                if not canonical:
                    continue
                preserved = dict(old_item)
                preserved["mediaTitle"] = canonical
                preserved["marvelCatalogueTitle"] = canonical
                if old_year:
                    preserved["year"] = old_year
                digest = str(preserved.get("infoHash") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", digest):
                    digest = info_hash(str(preserved.get("magnetUrl") or preserved.get("downloadUrl") or ""))
                dedupe_key = "hash:" + digest if re.fullmatch(r"[0-9a-f]{40}", digest, re.I) else (
                    f"title-size:{_normalize_title(str(preserved.get('title') or ''))}|{int(preserved.get('size') or 0)}"
                )
                existing = rows_by_hash.get(dedupe_key)
                score = (int(preserved.get("seeders") or 0), int(preserved.get("leechers") or 0))
                existing_score = (int(existing.get("seeders") or 0), int(existing.get("leechers") or 0)) if existing else (-1, -1)
                if existing is None or score > existing_score:
                    rows_by_hash[dedupe_key] = preserved

        results = list(rows_by_hash.values())
        movie_count = len({
            f"{_normalize_title(str(item.get('mediaTitle') or item.get('title') or ''))}|{item.get('year') or ''}"
            for item in results
        })
        # Don't permanently cache a partial crawl like a list of just a handful
        # of recent releases. A shared catalogue must contain a useful spread.
        if movie_count < 12:
            raise RuntimeError(
                f"Only {movie_count} Marvel movie titles produced usable results; refusing to cache an incomplete catalogue."
            )

        def catalogue_sort_key(item: dict[str, Any]) -> tuple[int, float, int, str]:
            source = str(item.get("mediaTitle") or item.get("title") or "")
            embedded_year = re.search(r"\b((?:19|20)\d{2})\b", source)
            try:
                year = int(item.get("year") or (embedded_year.group(1) if embedded_year else 0))
            except (TypeError, ValueError):
                year = int(embedded_year.group(1)) if embedded_year else 0
            try:
                rating = float(item.get("rating") or 0)
            except (TypeError, ValueError):
                rating = 0.0
            return (year, rating, int(item.get("seeders") or 0), source.lower())

        results.sort(key=catalogue_sort_key, reverse=True)
        payload = {
            "version": MARVEL_CATALOGUE_VERSION,
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "titlesQueried": len(MARVEL_MOVIE_SEARCHES),
            "movieCount": movie_count,
            "resultCount": len(results),
            "results": results,
        }
        _merge_saved_catalogue_metadata(payload, MARVEL_CATALOGUE_PATH)
        _write_marvel_catalogue(payload)
        _marvel_catalogue_state.update({
            "status": "ready",
            "completed": len(MARVEL_MOVIE_SEARCHES),
            "total": len(MARVEL_MOVIE_SEARCHES),
            "resultCount": len(results),
            "movieCount": movie_count,
            "error": "",
            "builtAt": payload["builtAt"],
        })
        logger.info(
            "Built persistent Marvel catalogue: %d movie titles, %d torrent options from %d title searches",
            movie_count,
            len(results),
            len(MARVEL_MOVIE_SEARCHES),
        )
    except Exception as exc:
        _marvel_catalogue_retry_after = time.time() + 60
        _marvel_catalogue_state.update({
            "status": "failed",
            "error": "The first Marvel catalogue build failed. Please try again in a minute.",
        })
        logger.warning("Marvel catalogue build failed: %s", exc)


# Additional shared catalogues. Curated DC lists are long-lived; latest-release
# catalogues are refreshed monthly and keep serving the previous good cache during refresh.
_EXTRA_CATALOGUES: dict[str, dict[str, Any]] = {
    "dc-live-action": {
        "file": "dc_live_action_catalogue.json", "version": 6, "refresh_days": 36500,
        "minimum_movies": 5, "mode": "fixed", "language": "english",
        "exclude_titles": [
            "The Old Guard", "The Old Guard 2", "RED 2", "The Kitchen", "RED",
            "The Losers", "Stardust", "A History of Violence", "The League of Extraordinary Gentlemen",
            "Road to Perdition", "Steel", "The Spirit", "Batman: Mask of the Phantasm",
            "Superman II: The Richard Donner Cut", "Watchmen: Chapter I", "Watchmen: Chapter II",
        ],
        "titles": [
            ("Superman", 2025), ("Supergirl", 2026), ("The Batman Part II", 2027),
            ("Joker: Folie à Deux", 2024), ("The Batman", 2022), ("The Suicide Squad", 2021),
            ("Batman: The Brave and the Bold", 2028), ("Clayface", 2026),
            ("Superman: Legacy", 2025), ("The Batman - Part II", 2027),
            ("Batman Forever", 1995), ("Batman & Robin", 1997), ("Batman: Mask of the Phantasm", 1993),
            ("Superman III", 1983), ("Superman IV: The Quest for Peace", 1987),
            ("Superman: The Movie", 1978),
            ("The Crow", 1994),
            ("The Crow", 2024), ("Spawn", 1997), ("Jonah Hex", 2010),
            ("Superman II: The Richard Donner Cut", 2006), ("Watchmen: Chapter I", 2024),
            ("Watchmen: Chapter II", 2024), ("Swamp Thing", 1982),
            ("Zack Snyder's Justice League", 2021), ("Wonder Woman 1984", 2020),
            ("Birds of Prey", 2020), ("Joker", 2019), ("Shazam!", 2019),
            ("Aquaman", 2018), ("Aquaman and the Lost Kingdom", 2023),
            ("Wonder Woman", 2017), ("Justice League", 2017), ("Man of Steel", 2013),
            ("Batman v Superman: Dawn of Justice", 2016), ("Suicide Squad", 2016),
            ("Green Lantern", 2011), ("The Dark Knight Rises", 2012),
            ("The Dark Knight", 2008), ("Batman Begins", 2005), ("Batman Returns", 1992),
            ("Batman", 1989), ("Superman Returns", 2006), ("Superman II", 1980),
            ("Superman", 1978), ("Constantine", 2005), ("Watchmen", 2009),
            ("V for Vendetta", 2005),
            ("Catwoman", 2004), ("The Flash", 2023), ("Black Adam", 2022),
            ("Blue Beetle", 2023), ("Shazam! Fury of the Gods", 2023),
        ],
    },
    "dc-animated": {
        "file": "dc_animated_catalogue.json", "version": 3, "refresh_days": 36500,
        "minimum_movies": 5, "mode": "fixed",
        "titles": [
            ("Batman: Knightfall - Part 1: Knightfall", 2026),
            ("Aztec Batman: Clash of Empires", 2025),
            ("Watchmen Chapter II", 2024),
            ("Watchmen Chapter I", 2024),
            ("Justice League: Crisis on Infinite Earths - Part Three", 2024),
            ("Justice League: Crisis on Infinite Earths - Part Two", 2024),
            ("Justice League: Crisis on Infinite Earths - Part One", 2024),
            ("Justice League: Warworld", 2023),
            ("Batman: The Doom That Came to Gotham", 2023),
            ("Legion of Super-Heroes", 2023),
            ("Batman and Superman: Battle of the Super Sons", 2022),
            ("Green Lantern: Beware My Power", 2022),
            ("Catwoman: Hunted", 2022),
            ("Injustice", 2021),
            ("Batman: The Long Halloween, Part Two", 2021),
            ("Batman: The Long Halloween, Part One", 2021),
            ("Justice Society: World War II", 2021),
            ("Batman: Soul of the Dragon", 2021),
            ("Superman: Man of Tomorrow", 2020),
            ("Deathstroke: Knights & Dragons", 2020),
            ("Justice League Dark: Apokolips War", 2020),
            ("Superman: Red Son", 2020),
            ("Wonder Woman: Bloodlines", 2019),
            ("Batman: Hush", 2019),
            ("Justice League vs. the Fatal Five", 2019),
            ("Reign of the Supermen", 2019),
            ("Constantine: City of Demons", 2019),
            ("The Death of Superman", 2018),
            ("Suicide Squad: Hell to Pay", 2018),
            ("Batman: Gotham by Gaslight", 2018),
            ("Batman and Harley Quinn", 2017),
            ("Teen Titans: The Judas Contract", 2017),
            ("Justice League Dark", 2017),
            ("Batman: The Killing Joke", 2016),
            ("Justice League vs. Teen Titans", 2016),
            ("Batman: Bad Blood", 2016),
            ("Justice League: Gods and Monsters", 2015),
            ("Batman vs. Robin", 2015),
            ("Justice League: Throne of Atlantis", 2015),
            ("Justice League: War", 2014),
            ("Batman: Assault on Arkham", 2014),
            ("Son of Batman", 2014),
            ("Justice League: The Flashpoint Paradox", 2013),
            ("Superman: Unbound", 2013),
            ("Batman: The Dark Knight Returns - Part 2", 2013),
            ("Batman: The Dark Knight Returns - Part 1", 2012),
            ("Superman vs. The Elite", 2012),
            ("Justice League: Doom", 2012),
            ("Batman: Year One", 2011),
            ("All-Star Superman", 2011),
            ("Green Lantern: Emerald Knights", 2011),
            ("Superman/Batman: Apocalypse", 2010),
            ("Batman: Under the Red Hood", 2010),
            ("Justice League: Crisis on Two Earths", 2010),
            ("Superman/Batman: Public Enemies", 2009),
            ("Green Lantern: First Flight", 2009),
            ("Wonder Woman", 2009),
            ("Justice League: The New Frontier", 2008),
            ("Batman: Gotham Knight", 2008),
            ("Superman: Doomsday", 2007),
        ],
    },
}
# Separate persistent caches keep English-original and Hindi/dubbed options
# independent so neither language can pollute the other catalogue.
_EXTRA_CATALOGUES["dc-live-action-hindi"] = {
    **_EXTRA_CATALOGUES["dc-live-action"],
    "file": "dc_live_action_hindi_catalogue.json",
    "version": 6,
    "language": "hindi",
    "titles": list(_EXTRA_CATALOGUES["dc-live-action"]["titles"]),
}
_EXTRA_CATALOGUES["classics"] = {
    "file": "classics_catalogue.json",
    "version": 5,
    "refresh_days": 36500,
    "minimum_movies": 5,
    "mode": "fixed",
    "language": "english",
    "titles": [
        ("The Shawshank Redemption", 1994),
        ("Memento", 2000),
        ("Bruce Almighty", 2003),
        ("Good Will Hunting", 1997),
        ("The Truman Show", 1998),
        ("The Sixth Sense", 1999),
        ("The Departed", 2006),
        ("Liar Liar", 1997),
        ("Source Code", 2011),
        ("In Time", 2011),
        ("Bird Box", 2018),
        ("The Interview", 2014),
        ("Focus", 2015),
        ("Nobody", 2021),
        ("Kick-Ass", 2010),
        ("The Raid: Redemption", 2011),
        ("The Raid 2", 2014),
        ("Fight Club", 1999),
        ("Mad Max: Fury Road", 2015),
        ("The Equalizer", 2014),
        ("World War Z", 2013),
        ("Hellboy", 2004),
        ("Hellboy II: The Golden Army", 2008),
        ("Predestination", 2014),
        ("Prometheus", 2012),
        ("National Treasure", 2004),
        ("National Treasure: Book of Secrets", 2007),
        ("Jumanji", 1995),
        ("Jumanji: Welcome to the Jungle", 2017),
        ("Ender's Game", 2013),
        ("Battleship", 2012),
        ("A Quiet Place", 2018),
        ("A Quiet Place Part II", 2020),
        ("John Wick", 2014),
        ("John Wick: Chapter 2", 2017),
        ("John Wick: Chapter 3 - Parabellum", 2019),
        ("The Matrix", 1999),
        ("The Matrix Reloaded", 2003),
        ("The Matrix Revolutions", 2003),
        ("Men in Black", 1997),
        ("Men in Black II", 2002),
        ("Men in Black 3", 2012),
        ("The Mummy", 1999),
        ("The Mummy Returns", 2001),
        ("The Mummy: Tomb of the Dragon Emperor", 2008),
        ("Taken", 2008),
        ("Taken 2", 2012),
        ("Taken 3", 2014),
        ("Van Helsing", 2004),
        ("G.I. Joe: The Rise of Cobra", 2009),
        ("Hancock", 2008),
        ("Wanted", 2008),
        ("Prince of Persia: The Sands of Time", 2010),
        ("AVP: Alien vs. Predator", 2004),
        ("The Rundown", 2003),
        ("Ghost Rider", 2007),
        ("Now You See Me", 2013),
        ("Edge of Tomorrow", 2014),
        ("John Carter", 2012),
        ("Inception", 2010),
        ("Kingsman: The Secret Service", 2014),
        ("Kingsman: The Golden Circle", 2017),
        ("Constantine", 2005),
        ("The Hitman's Bodyguard", 2017),
        ("The Hitman's Wife's Bodyguard", 2021),
        ("Cast Away", 2000),
        ("Dracula Untold", 2014),
        ("Abraham Lincoln: Vampire Hunter", 2012),
        ("300", 2006),
        ("Escape Plan", 2013),
        ("The Maze Runner", 2014),
        ("The A-Team", 2010),
        ("Skyscraper", 2018),
        ("Sherlock Holmes", 2009),
        ("Sherlock Holmes: A Game of Shadows", 2011),
        ("Kill Bill: Vol. 1", 2003),
        ("Kill Bill: Vol. 2", 2004),
    ],
}
_EXTRA_CATALOGUES["marvel-hindi"] = {
    "file": "marvel_hindi_catalogue.json",
    "version": 4,
    "refresh_days": 36500,
    "minimum_movies": 5,
    "mode": "fixed",
    "language": "hindi",
    "titles": list(MARVEL_MOVIE_SEARCHES),
}

_EXTRA_CATALOGUE_PATHS = {
    key: Path(os.getenv("CATALOGUE_" + key.upper().replace("-", "_") + "_PATH", data_file(config["file"])))
    for key, config in _EXTRA_CATALOGUES.items()
}
_CACHE_SEED_FILES = (
    "dc_animated_catalogue.json",
    "dc_live_action_catalogue.json",
    "dc_live_action_hindi_catalogue.json",
    "classics_catalogue.json",
    "regional_tv_prebuilt_cache.json",
    "latest_bollywood_catalogue.json",
    "latest_hollywood_catalogue.json",
    "marvel_catalogue.json",
    "marvel_web_series_catalogue.json",
    "marvel_hindi_catalogue.json",
    "bollywood_torrent_matched_catalogue.json",
)


# Runtime metadata caches are snapshotted to GitHub alongside the curated catalogues.
# This gives fresh/ephemeral deployments a warm starting point without replacing
# any cache data already populated by that deployment.
_RUNTIME_CACHE_SEED_FILES = {
    "tmdb_movie_catalogue_cache.json": TMDB_CATALOGUE_CACHE_FILE,
    "tmdb_search_metadata_cache.json": TMDB_SEARCH_METADATA_CACHE_FILE,
    "imdb_rating_cache.json": IMDB_RATING_CACHE_FILE,
    "tmdb_ott_availability_cache.json": TMDB_OTT_CACHE_FILE,
    "marvel_tv_catalogue_cache.json": MARVEL_TV_CATALOGUE_CACHE_FILE,
    "dc_tv_catalogue_cache.json": DC_TV_CATALOGUE_CACHE_FILE,
    "regional_movie_prebuilt_cache.json": Path(os.getenv(
        "REGIONAL_MOVIE_PREBUILT_CACHE_PATH",
        str(Path(str(DATA_DIR)) / "regional_movie_prebuilt_cache.json"),
    )),
    "regional_movie_trending_archive.json": REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE,
    "nexstream_cache.json": Path(os.getenv(
        "NEXSTREAM_CACHE_PATH", data_file("nexstream_cache.json"),
    )),
    "nexstream_episode_metadata_cache.json": Path(os.getenv(
        "NEXSTREAM_EPISODE_CACHE_PATH", data_file("nexstream_episode_metadata_cache.json"),
    )),
}


def _seed_bundled_runtime_caches() -> None:
    seed_dir = _CACHE_SEED_DIR / "runtime"
    for filename, destination in _RUNTIME_CACHE_SEED_FILES.items():
        source = seed_dir / filename
        if not source.is_file() or source.stat().st_size == 0:
            logger.info("No bundled runtime snapshot for %s at %s", filename, source)
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)

            # OTT is a shared, append-only lookup cache. Merge the bundled VPS
            # snapshot into the runtime file even when the latter already exists;
            # otherwise an old/non-empty Render file can silently hide thousands
            # of useful entries shipped with the deployment.
            if filename == "tmdb_ott_availability_cache.json":
                bundled = json.loads(source.read_text(encoding="utf-8"))
                bundled_items = bundled.get("items") if isinstance(bundled, dict) else None
                if not isinstance(bundled_items, dict):
                    logger.warning("Ignoring invalid bundled OTT cache snapshot: %s", source)
                    continue

                try:
                    runtime = json.loads(destination.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    runtime = {}
                if not isinstance(runtime, dict):
                    runtime = {}
                runtime_items = runtime.get("items")
                if not isinstance(runtime_items, dict):
                    runtime_items = {}

                added = 0
                replaced = 0
                for key, bundled_row in bundled_items.items():
                    if not isinstance(bundled_row, dict) or not isinstance(bundled_row.get("payload"), dict):
                        continue
                    current_row = runtime_items.get(key)
                    try:
                        bundled_saved_at = float(bundled_row.get("savedAt") or 0)
                        current_saved_at = float(current_row.get("savedAt") or 0) if isinstance(current_row, dict) else 0
                    except (TypeError, ValueError):
                        bundled_saved_at = 0
                        current_saved_at = 0
                    if not isinstance(current_row, dict):
                        runtime_items[key] = bundled_row
                        added += 1
                    elif bundled_saved_at > current_saved_at:
                        runtime_items[key] = bundled_row
                        replaced += 1

                runtime["items"] = runtime_items
                if added or replaced or not destination.is_file() or destination.stat().st_size == 0:
                    temp_path = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".tmp")
                    temp_path.write_text(json.dumps(runtime, ensure_ascii=False), encoding="utf-8")
                    os.replace(temp_path, destination)
                    logger.info(
                        "Merged bundled OTT cache snapshot: %s added, %s newer entries applied, %s total entries",
                        added, replaced, len(runtime_items),
                    )
                else:
                    logger.info("OTT cache snapshot already represented in runtime cache (%s entries)", len(runtime_items))
                continue

            if destination.is_file() and destination.stat().st_size > 0:
                continue
            shutil.copy2(source, destination)
            logger.info("Seeded runtime cache %s from GitHub snapshot", filename)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            logger.warning("Could not seed runtime cache %s: %s", filename, exc)


def _seed_bundled_catalogue_caches() -> None:
    destinations = {
        "marvel_catalogue.json": MARVEL_CATALOGUE_PATH,
        "marvel_web_series_catalogue.json": Path(os.getenv("MARVEL_WEB_SERIES_CATALOGUE_PATH", data_file("marvel_web_series_catalogue.json"))),
        **{config["file"]: _EXTRA_CATALOGUE_PATHS[key] for key, config in _EXTRA_CATALOGUES.items()},
        "bollywood_torrent_matched_catalogue.json": Path(os.getenv(
            "BOLLYWOOD_TORRENT_CATALOGUE_PATH",
            str(Path(str(DATA_DIR)) / "bollywood_torrent_matched_catalogue.json"),
        )),
        "regional_tv_prebuilt_cache.json": REGIONAL_TV_PREBUILT_CACHE_FILE,
    }
    for filename in _CACHE_SEED_FILES:
        source = _CACHE_SEED_DIR / filename
        destination = destinations.get(filename)
        if destination is None or not source.is_file() or source.stat().st_size == 0:
            continue
        try:
            if destination.is_file() and destination.stat().st_size > 0:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            logger.info("Seeded catalogue cache %s from bundled snapshot", filename)
        except OSError as exc:
            logger.warning("Could not seed catalogue cache %s: %s", filename, exc)


_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE: dict[str, Any] = {
    "status": "idle", "filesCompleted": 0, "filesTotal": 0,
    "titlesCompleted": 0, "titlesTotal": 0, "updatedRows": 0, "error": "",
}
_catalogue_synopsis_enrichment_task: asyncio.Task | None = None
_CATALOGUE_SYNOPSIS_RECHECK_SECONDS = stored_ttl(30 * 24 * 60 * 60)


def _synopsis_cache_paths() -> list[tuple[str, Path]]:
    paths = [("marvel", MARVEL_CATALOGUE_PATH)]
    paths.extend((key, path) for key, path in _EXTRA_CATALOGUE_PATHS.items())
    # De-duplicate aliases that may intentionally point to the same configured path.
    seen: set[str] = set()
    unique: list[tuple[str, Path]] = []
    for name, path in paths:
        identity = str(path.resolve())
        if identity not in seen:
            seen.add(identity)
            unique.append((name, path))
    return unique


def _synopsis_row_identity(item: dict[str, Any]) -> tuple[str, int]:
    title = str(
        item.get("catalogueTitle") or item.get("marvelCatalogueTitle")
        or item.get("mediaTitle") or item.get("title") or ""
    ).strip()
    year_value = item.get("year")
    try:
        year = int(year_value) if year_value else 0
    except (TypeError, ValueError):
        year = 0
    if not year:
        match = re.search(r"\b(19\d{2}|20\d{2})\b", title)
        if match:
            year = int(match.group(1))
    return _normalize_title(title), year


_CATALOGUE_PERSISTENT_METADATA_FIELDS = (
    "overview",
    "tmdbId",
    "tmdbUrl",
    "releaseDate",
    "rating",
    "posterUrl",
    "backdropUrl",
    "genres",
    "synopsisCheckedAt",
    "synopsisLookupVersion",
    "synopsisSource",
)


def _catalogue_metadata_value_present(field: str, value: Any) -> bool:
    if value in (None, "", []):
        return False
    # Zero-value metadata should not prevent a useful saved value being reused.
    if field in {"tmdbId", "rating", "synopsisCheckedAt", "synopsisLookupVersion"}:
        try:
            return float(value) > 0
        except (TypeError, ValueError):
            return False
    return True


def _catalogue_metadata_tmdb_id(item: dict[str, Any]) -> int:
    try:
        return int(item.get("tmdbId") or item.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _merge_catalogue_metadata_profile(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    for field in _CATALOGUE_PERSISTENT_METADATA_FIELDS:
        value = source.get(field)
        if (
            not _catalogue_metadata_value_present(field, target.get(field))
            and _catalogue_metadata_value_present(field, value)
        ):
            target[field] = value


def _merge_saved_catalogue_metadata(
    payload: dict[str, Any],
    destination_path: Path,
) -> int:
    """Carry saved TMDB metadata forward when rebuilding a torrent catalogue.

    Cache rows are matched by TMDB ID first, then by normalized canonical title
    and release year. Only absent fields are copied, so freshly fetched data wins
    and an empty synopsis from a torrent provider can never erase a saved one.
    Metadata is shared across the English/Hindi Marvel and DC cache variants.
    """
    fresh_rows = payload.get("results")
    if not isinstance(fresh_rows, list):
        return 0

    metadata_by_tmdb_id: dict[int, dict[str, Any]] = {}
    metadata_by_identity: dict[tuple[str, int], dict[str, Any]] = {}

    def collect_profile(
        index: dict[Any, dict[str, Any]],
        key: Any,
        row: dict[str, Any],
    ) -> None:
        if not key:
            return
        profile = index.setdefault(key, {})
        _merge_catalogue_metadata_profile(profile, row)

    seen_paths: set[str] = set()
    for _name, cache_path in _synopsis_cache_paths():
        try:
            canonical_path = str(cache_path.resolve())
        except OSError:
            canonical_path = str(cache_path)
        if canonical_path in seen_paths:
            continue
        seen_paths.add(canonical_path)

        try:
            saved_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        saved_rows = saved_payload.get("results", []) if isinstance(saved_payload, dict) else []
        if not isinstance(saved_rows, list):
            continue

        for saved_row in saved_rows:
            if not isinstance(saved_row, dict):
                continue
            profile = {
                field: saved_row[field]
                for field in _CATALOGUE_PERSISTENT_METADATA_FIELDS
                if _catalogue_metadata_value_present(field, saved_row.get(field))
            }
            if not profile:
                continue

            tmdb_id = _catalogue_metadata_tmdb_id(saved_row)
            if tmdb_id:
                collect_profile(metadata_by_tmdb_id, tmdb_id, profile)

            identity = _synopsis_row_identity(saved_row)
            if identity[0]:
                collect_profile(metadata_by_identity, identity, profile)

    updated_rows = 0
    for row in fresh_rows:
        if not isinstance(row, dict):
            continue

        row_tmdb_id = _catalogue_metadata_tmdb_id(row)
        identity = _synopsis_row_identity(row)
        profile: dict[str, Any] = {}

        if row_tmdb_id and row_tmdb_id in metadata_by_tmdb_id:
            _merge_catalogue_metadata_profile(profile, metadata_by_tmdb_id[row_tmdb_id])

        identity_profile = metadata_by_identity.get(identity) if identity[0] else None
        # If both records already have authoritative but conflicting TMDB IDs,
        # don't transfer the synopsis based on title similarity alone.
        identity_tmdb_id = _catalogue_metadata_tmdb_id(identity_profile or {})
        conflicting_ids = bool(row_tmdb_id and identity_tmdb_id and row_tmdb_id != identity_tmdb_id)
        if identity_profile and not conflicting_ids:
            _merge_catalogue_metadata_profile(profile, identity_profile)

        before = {
            field: row.get(field)
            for field in _CATALOGUE_PERSISTENT_METADATA_FIELDS
        }
        _merge_catalogue_metadata_profile(row, profile)
        if any(row.get(field) != before[field] for field in _CATALOGUE_PERSISTENT_METADATA_FIELDS):
            updated_rows += 1

    if updated_rows:
        logger.info(
            "Preserved previously saved TMDB metadata for %d rows before rebuilding %s",
            updated_rows,
            destination_path.name,
        )
    return updated_rows


def _write_synopsis_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=path.stem + "-synopsis-",
            suffix=".tmp", dir=str(path.parent), delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _normalize_synopsis_match_title(value: Any) -> str:
    """Normalize harmless catalogue/provider title variants before matching metadata."""
    normalized = _normalize_title(str(value or ""))
    # Some sources omit a leading article and spell numerals as words; normalize
    # these common variants without allowing broad fuzzy matches to unrelated films.
    normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized)
    normalized = re.sub(r"\bfour\b", "4", normalized)
    return normalized


async def _lookup_watchmode_catalogue_synopsis(
    title: str,
    year: int,
    tmdb_id: int = 0,
) -> tuple[dict[str, Any] | None, bool]:
    """Fetch Watchmode plot_overview as a fallback; return whether lookup completed."""
    if not WATCHMODE_API_KEYS:
        return None, False

    query = re.sub(r"\s+", " ", title or "").strip()
    completed = False
    timeout = httpx.Timeout(8.0, connect=3.0)

    def make_metadata(details: dict[str, Any], fallback_tmdb_id: int = 0) -> dict[str, Any] | None:
        overview = re.sub(
            r"\s+",
            " ",
            str(details.get("plot_overview") or details.get("overview") or ""),
        ).strip()
        if not overview:
            return None

        try:
            resolved_tmdb_id = int(details.get("tmdb_id") or fallback_tmdb_id or tmdb_id or 0)
        except (TypeError, ValueError):
            resolved_tmdb_id = fallback_tmdb_id or tmdb_id or 0

        release_date = str(details.get("release_date") or "").strip()
        resolved_year = details.get("year") or year or None
        if release_date:
            year_match = re.match(r"^(\d{4})", release_date)
            if year_match:
                resolved_year = int(year_match.group(1))

        metadata: dict[str, Any] = {
            "overview": overview,
            "synopsisSource": "Watchmode",
            "synopsisCheckedAt": int(time.time()),
            "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
        }
        if resolved_tmdb_id > 0:
            metadata["tmdbId"] = resolved_tmdb_id
            metadata["tmdbUrl"] = f"https://www.themoviedb.org/movie/{resolved_tmdb_id}"
        if release_date:
            metadata["releaseDate"] = release_date
        if resolved_year:
            metadata["year"] = resolved_year
        return metadata

    async def get_details(identifier: str, fallback_tmdb_id: int = 0) -> tuple[dict[str, Any] | None, bool]:
        try:
            response = await _watchmode_get(
                f"/title/{quote(identifier, safe='')}/details/",
                params={"language": "en"},
                timeout=timeout,
            )
        except Exception as exc:
            logger.info("Watchmode synopsis lookup failed for %s: %s", identifier, type(exc).__name__)
            return None, False

        if response is None or response.status_code >= 400:
            return None, False
        try:
            details = response.json()
        except (ValueError, TypeError):
            return None, False
        if not isinstance(details, dict):
            return None, False

        metadata = make_metadata(details, fallback_tmdb_id)
        return metadata, True

    # Watchmode supports TMDB-format IDs (movie-123); this avoids a title search
    # for the large group of franchise rows that already have a reliable TMDB ID.
    if tmdb_id > 0:
        metadata, succeeded = await get_details(f"movie-{tmdb_id}", tmdb_id)
        if metadata:
            return metadata, True
        completed = succeeded

    if not query:
        return None, completed

    try:
        response = await _watchmode_get(
            "/search/",
            params={
                "search_field": "name",
                "search_value": query,
                "types": "movie,tv_movie,tv_miniseries,tv_special,short_film",
            },
            timeout=timeout,
        )
    except Exception as exc:
        logger.info("Watchmode synopsis title search failed for %r: %s", query, type(exc).__name__)
        return None, False

    if response is None or response.status_code >= 400:
        return None, False

    try:
        data = response.json()
    except (ValueError, TypeError):
        return None, False

    title_results = data.get("title_results", []) if isinstance(data, dict) else []
    target = _normalize_synopsis_match_title(query)
    candidates: list[tuple[int, dict[str, Any]]] = []
    for candidate in title_results if isinstance(title_results, list) else []:
        if not isinstance(candidate, dict) or not candidate.get("id"):
            continue
        candidate_title = str(candidate.get("name") or candidate.get("title") or "").strip()
        if not candidate_title or _normalize_synopsis_match_title(candidate_title) != target:
            continue
        try:
            candidate_year = int(candidate.get("year") or 0)
        except (TypeError, ValueError):
            candidate_year = 0
        if year and candidate_year and candidate_year != year:
            continue
        year_rank = 0 if year and candidate_year == year else 1
        candidates.append((year_rank, candidate))

    candidates.sort(key=lambda pair: pair[0])
    for _, candidate in candidates[:3]:
        watchmode_id = str(candidate.get("id") or "").strip()
        if not watchmode_id:
            continue
        fallback_id = 0
        try:
            fallback_id = int(candidate.get("tmdb_id") or tmdb_id or 0)
        except (TypeError, ValueError):
            fallback_id = tmdb_id or 0
        metadata, succeeded = await get_details(watchmode_id, fallback_id)
        completed = completed or succeeded
        if metadata:
            return metadata, True

    # A successful search with no exact title/year match is a completed negative
    # result. Failed detail requests stay eligible for retry in the next worker run.
    return None, True if not candidates else completed


async def _lookup_catalogue_synopsis(
    title: str,
    year: int,
    tmdb_id: int = 0,
) -> dict[str, Any] | None:
    """Resolve a synopsis from TMDB first, then use Watchmode's plot overview."""
    query = re.sub(r"\s+", " ", title).strip()
    if not query and not tmdb_id:
        return None

    now = int(time.time())

    def details_to_metadata(
        details: dict[str, Any],
        resolved_id: int,
        fallback_title: str,
        fallback_year: int,
        fallback_row: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = fallback_row or {}
        release_date = str(details.get("release_date") or fallback.get("release_date") or "")
        year_match = re.match(r"^(\d{4})", release_date)
        resolved_year = int(year_match.group(1)) if year_match else (fallback_year or None)
        poster_path = str(details.get("poster_path") or fallback.get("poster_path") or "").strip()
        backdrop_path = str(details.get("backdrop_path") or fallback.get("backdrop_path") or "").strip()
        overview = re.sub(r"\s+", " ", str(details.get("overview") or fallback.get("overview") or "")).strip()
        genres = details.get("genres") or fallback.get("genres") or []
        if genres and isinstance(genres[0], dict):
            genres = [str(genre.get("name") or "").strip() for genre in genres if isinstance(genre, dict)]
            genres = [genre for genre in genres if genre]
        return {
            "id": int(details.get("id") or resolved_id),
            "tmdbId": int(details.get("id") or resolved_id),
            "title": str(details.get("title") or fallback.get("title") or fallback_title).strip(),
            "year": resolved_year,
            "mediaType": "movie",
            "overview": overview,
            "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
            "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
            "tmdbUrl": f"https://www.themoviedb.org/movie/{int(details.get('id') or resolved_id)}",
            "releaseDate": release_date,
            "rating": float(details.get("vote_average") or fallback.get("vote_average") or 0),
            "genres": genres if isinstance(genres, list) else [],
            "synopsisSource": "TMDB" if overview else "",
            "synopsisCheckedAt": now,
            "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
        }

    async def watchmode_fallback() -> tuple[dict[str, Any] | None, bool]:
        return await _lookup_watchmode_catalogue_synopsis(query, year, tmdb_id)

    if tmdb_id > 0:
        successful_details_response = False
        details: dict[str, Any] = {}
        for language in ("en-US", "en"):
            try:
                response = await _tmdb_get_json(
                    f"movie/{tmdb_id}", {"language": language}, request_timeout=6.0
                )
            except Exception as exc:
                logger.info(
                    "Synopsis details lookup failed for %s (%s): %s",
                    tmdb_id, language, type(exc).__name__,
                )
                continue
            successful_details_response = True
            details = response
            if re.sub(r"\s+", " ", str(details.get("overview") or "")).strip():
                break

        if successful_details_response:
            metadata = details_to_metadata(details, tmdb_id, query or str(details.get("title") or ""), year)
            if metadata.get("overview"):
                return metadata
            watchmode_metadata, watchmode_completed = await watchmode_fallback()
            if watchmode_metadata:
                return watchmode_metadata
            if WATCHMODE_API_KEYS and not watchmode_completed:
                # Keep an unresolved record retryable if Watchmode failed transiently.
                metadata["synopsisLookupVersion"] = 0
            return metadata

        watchmode_metadata, _ = await watchmode_fallback()
        return watchmode_metadata

    if not query:
        return None

    params: dict[str, Any] = {
        "query": query, "include_adult": "false", "language": "en-US", "page": 1,
    }
    if 1870 <= year <= 2100:
        params["year"] = year
    try:
        result = await _tmdb_get_json("search/movie", params, request_timeout=6.0)
    except Exception as exc:
        logger.info("Synopsis cache lookup failed for %r (%s): %s", query, year, type(exc).__name__)
        watchmode_metadata, _ = await watchmode_fallback()
        return watchmode_metadata

    rows = [row for row in (result.get("results") or []) if isinstance(row, dict) and row.get("id")]
    target = _normalize_synopsis_match_title(query)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for row in rows:
        candidate_title = str(row.get("title") or row.get("original_title") or "").strip()
        if _normalize_synopsis_match_title(candidate_title) != target:
            continue
        release_date = str(row.get("release_date") or "")
        try:
            candidate_year = int(release_date[:4])
        except (TypeError, ValueError):
            candidate_year = 0
        if year and candidate_year and candidate_year != year:
            continue
        candidates.append((0 if year and candidate_year == year else 1, -int(row.get("vote_count") or 0), row))

    if not candidates:
        watchmode_metadata, watchmode_completed = await watchmode_fallback()
        if watchmode_metadata:
            return watchmode_metadata
        if WATCHMODE_API_KEYS and not watchmode_completed:
            return None
        return {"synopsisCheckedAt": now, "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION}

    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    row = candidates[0][2]
    resolved_id = int(row["id"])
    details: dict[str, Any] = row
    overview = re.sub(r"\s+", " ", str(row.get("overview") or "")).strip()

    if not overview:
        successful_details_response = False
        for language in ("en-US", "en"):
            try:
                response = await _tmdb_get_json(
                    f"movie/{resolved_id}", {"language": language}, request_timeout=6.0
                )
            except Exception as exc:
                logger.info(
                    "Synopsis details lookup failed for %s (%s): %s",
                    resolved_id, language, type(exc).__name__,
                )
                continue
            details = response
            successful_details_response = True
            overview = re.sub(r"\s+", " ", str(details.get("overview") or "")).strip()
            if overview:
                break
        if not successful_details_response:
            watchmode_metadata, _ = await watchmode_fallback()
            return watchmode_metadata

    metadata = details_to_metadata(
        details,
        resolved_id,
        str(row.get("title") or row.get("original_title") or query).strip(),
        year,
        fallback_row=row,
    )
    if metadata.get("overview"):
        return metadata

    watchmode_metadata, watchmode_completed = await watchmode_fallback()
    if watchmode_metadata:
        return watchmode_metadata
    if WATCHMODE_API_KEYS and not watchmode_completed:
        metadata["synopsisLookupVersion"] = 0
    return metadata


async def _enrich_catalogue_synopses() -> None:
    """Fill synopsis metadata into every persistent movie-catalogue JSON without rebuilding torrent rows."""
    if not BACKFILL_MISSING_METADATA:
        return
    state = _CATALOGUE_SYNOPSIS_ENRICHMENT_STATE
    paths = _synopsis_cache_paths()
    state.update({
        "status": "running", "filesCompleted": 0, "filesTotal": len(paths),
        "titlesCompleted": 0, "titlesTotal": 0, "updatedRows": 0, "error": "",
    })
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        state.update({"status": "waiting_for_credentials", "error": "TMDB credentials are not configured"})
        return

    # First collect unique missing-synopsis titles across every cache. Repeated torrent
    # releases for the same film share one TMDB request and one metadata result.
    jobs: dict[tuple[str, int], tuple[str, int, int]] = {}
    file_rows: list[tuple[str, Path, dict[str, Any]]] = []
    now = int(time.time())
    for name, path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            state["filesCompleted"] += 1
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            state["filesCompleted"] += 1
            continue
        file_rows.append((name, path, payload))
        for item in payload["results"]:
            if not isinstance(item, dict) or str(item.get("overview") or "").strip():
                continue
            checked_at = item.get("synopsisCheckedAt")
            try:
                checked_at = int(checked_at or 0)
            except (TypeError, ValueError):
                checked_at = 0
            try:
                lookup_version = int(item.get("synopsisLookupVersion") or 0)
            except (TypeError, ValueError):
                lookup_version = 0
            if (
                (lookup_version >= TMDB_SYNOPSIS_LOOKUP_VERSION or CACHE_FIRST)
                and checked_at
                and now - checked_at < _CATALOGUE_SYNOPSIS_RECHECK_SECONDS
            ):
                continue
            identity = _synopsis_row_identity(item)
            normalized_title = identity[0]
            if not normalized_title:
                continue
            title = str(
                item.get("catalogueTitle") or item.get("marvelCatalogueTitle")
                or item.get("mediaTitle") or item.get("title") or ""
            ).strip()
            tmdb_id = _catalogue_metadata_tmdb_id(item)
            existing_job = jobs.get(identity)
            if existing_job is None or (not existing_job[2] and tmdb_id):
                jobs[identity] = (title, identity[1], tmdb_id)

    state["titlesTotal"] = len(jobs)
    metadata_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    # Conservative pacing avoids a burst against TMDB. Rate-limit responses are
    # respected by _tmdb_get_json and are not bypassed by trying other accounts.
    for identity, (title, year, tmdb_id) in jobs.items():
        metadata = await _lookup_catalogue_synopsis(title, year, tmdb_id)
        if metadata:
            metadata_by_identity[identity] = metadata
        state["titlesCompleted"] += 1
        if state["titlesCompleted"] % 25 == 0:
            logger.info("Catalogue synopsis enrichment: %d/%d titles processed",
                state["titlesCompleted"], state["titlesTotal"])
        await asyncio.sleep(0.25)

    # Re-read each file before writing, so a catalogue rebuilt during enrichment
    # keeps its fresh torrent rows. Only synopsis fields are merged into matching rows.
    for name, path, _initial_payload in file_rows:
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            state["filesCompleted"] += 1
            continue
        if not isinstance(current, dict) or not isinstance(current.get("results"), list):
            state["filesCompleted"] += 1
            continue
        changed = False
        for item in current["results"]:
            if not isinstance(item, dict):
                continue
            identity = _synopsis_row_identity(item)
            metadata = metadata_by_identity.get(identity)
            if not metadata:
                continue
            # Never overwrite a synopsis that another process has already supplied.
            if not str(item.get("overview") or "").strip() and metadata.get("overview"):
                item["overview"] = metadata["overview"]
                changed = True
                state["updatedRows"] += 1
            for field in ("tmdbId", "tmdbUrl", "releaseDate", "rating", "synopsisSource"):
                if field in metadata and metadata[field] not in (None, "", 0) and not item.get(field):
                    item[field] = metadata[field]
                    changed = True
            try:
                old_checked_at = int(item.get("synopsisCheckedAt") or 0)
                new_checked_at = int(metadata.get("synopsisCheckedAt") or 0)
                old_lookup_version = int(item.get("synopsisLookupVersion") or 0)
                new_lookup_version = int(metadata.get("synopsisLookupVersion") or 0)
            except (TypeError, ValueError):
                old_checked_at = new_checked_at = old_lookup_version = new_lookup_version = 0
            if new_checked_at > old_checked_at:
                item["synopsisCheckedAt"] = new_checked_at
                changed = True
            if new_lookup_version > old_lookup_version:
                item["synopsisLookupVersion"] = new_lookup_version
                changed = True
        if changed:
            try:
                _write_synopsis_cache(path, current)
                logger.info("Saved synopsis enrichment for catalogue cache %s", path.name)
            except OSError as exc:
                logger.warning("Could not save synopsis-enriched cache %s: %s", path.name, exc)
        state["filesCompleted"] += 1

    state["status"] = "completed"
    logger.info(
        "Catalogue synopsis enrichment completed: %d unique titles checked, %d rows enriched across %d caches",
        state["titlesCompleted"], state["updatedRows"], state["filesCompleted"],
    )


_synopsis_enrichment_retry_task: asyncio.Task | None = None


async def _start_catalogue_synopsis_enrichment() -> None:
    if not BACKFILL_MISSING_METADATA:
        return
    global _catalogue_synopsis_enrichment_task, _synopsis_enrichment_retry_task
    # Let cache initialization finish first. Enrichment must never delay the API.
    await asyncio.sleep(10)
    if _catalogue_synopsis_enrichment_task is None or _catalogue_synopsis_enrichment_task.done():
        _catalogue_synopsis_enrichment_task = asyncio.create_task(_enrich_catalogue_synopses())
    if _synopsis_enrichment_retry_task is None or _synopsis_enrichment_retry_task.done():
        # Failed transient lookups remain unversioned and will be retried periodically.
        _synopsis_enrichment_retry_task = asyncio.create_task(_synopsis_enrichment_retry_loop())


@router.get("/api/catalogue/synopsis-enrichment")
async def api_catalogue_synopsis_enrichment_status():
    """Expose progress for the background synopsis fill across persistent catalogue JSON files."""
    return dict(_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE)


def _warm_tmdb_ott_memory_cache() -> None:
    """Load persisted OTT entries once so each cache miss does not reparse the entire JSON file."""
    try:
        disk = json.loads(TMDB_OTT_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        logger.warning("Could not warm in-memory OTT cache from %s", TMDB_OTT_CACHE_FILE, exc_info=True)
        return

    items = disk.get("items") if isinstance(disk, dict) else None
    if not isinstance(items, dict) or not items:
        logger.warning("Persistent OTT cache has no readable items at %s", TMDB_OTT_CACHE_FILE)
        return

    now_wall = time.time()
    now_monotonic = time.monotonic()
    warmed = 0
    invalid = 0
    preexisting = set(_tmdb_ott_cache)
    # Disk keys are "v2:<id>:<REGION>" (current) or legacy "<id>:<REGION>". Visit the
    # legacy ones first so a current entry for the same movie wins.
    ordered = sorted(items.items(), key=lambda item: str(item[0]).startswith("v2:"))
    for disk_key, row in ordered:
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            invalid += 1
            continue
        raw_key = str(disk_key)
        if raw_key.startswith("v2:"):
            raw_key = raw_key[3:]
        parts = raw_key.split(":", 1)
        if len(parts) != 2:
            invalid += 1
            continue
        try:
            movie_id = int(parts[0])
            saved_at = float(row.get("savedAt") or 0)
        except (TypeError, ValueError):
            invalid += 1
            continue
        region = parts[1].strip().upper()
        if movie_id < 1 or not re.fullmatch(r"[A-Z]{2}", region) or saved_at <= 0:
            invalid += 1
            continue

        cache_key = (movie_id, region)
        if cache_key in preexisting:
            continue
        # Translate the saved wall-clock age to monotonic time. Expired entries
        # remain available as stale fallbacks instead of being marked fresh again.
        age_seconds = max(0.0, now_wall - saved_at)
        _tmdb_ott_cache[cache_key] = (now_monotonic - age_seconds, row["payload"])
        warmed += 1

    logger.info(
        "Warm-loaded persistent OTT cache into memory: %s entries warmed, %s valid disk entries, %s invalid rows",
        warmed, len(items) - invalid, invalid,
    )


def _initialize_catalogue_caches() -> None:
    logger.info(
        "CACHE_ONLY_MODE=%s BACKFILL_MISSING_METADATA=%s",
        str(CACHE_ONLY_MODE).lower(),
        str(BACKFILL_MISSING_METADATA).lower(),
    )
    # Seed bundled snapshots first; warm OTT entries into memory before serving requests,
    # then normalize the curated catalogue files on disk.
    _seed_bundled_runtime_caches()
    _warm_tmdb_ott_memory_cache()
    _seed_bundled_catalogue_caches()
    _read_marvel_catalogue()
    for key in ("marvel-hindi", "dc-live-action", "dc-live-action-hindi", "dc-animated"):
        _read_extra_catalogue(key)


_extra_catalogue_tasks: dict[str, asyncio.Task | None] = {key: None for key in _EXTRA_CATALOGUES}
_extra_catalogue_retry_after: dict[str, float] = {}
_extra_catalogue_states: dict[str, dict[str, Any]] = {
    key: {"status": "idle", "completed": 0, "total": len(config.get("titles", config.get("queries", []))),
          "resultCount": 0, "movieCount": 0, "error": ""}
    for key, config in _EXTRA_CATALOGUES.items()
}


def _read_extra_catalogue(key: str) -> dict[str, Any] | None:
    return _memoized_file_read("extra:" + key, _EXTRA_CATALOGUE_PATHS[key], lambda: _read_extra_catalogue_uncached(key))


def _read_extra_catalogue_uncached(key: str) -> dict[str, Any] | None:
    path = _EXTRA_CATALOGUE_PATHS[key]
    config = _EXTRA_CATALOGUES[key]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload_version = payload.get("version")
        current_version = int(config["version"])
        # Keep a prior compatible JSON snapshot visible while a behaviour/version
        # refresh runs, so a temporary TMDB outage never blanks a working catalogue.
        is_current_version = payload_version == current_version
        is_older_compatible_version = (
            isinstance(payload_version, int) and payload_version < current_version
        )
        if not ((is_current_version or is_older_compatible_version) and isinstance(payload.get("results"), list) and payload["results"]):
            return None

        changed = False
        excluded_titles = {
            _normalize_title(value)
            for value in (config.get("exclude_titles") or [])
            if str(value or "").strip()
        }
        retained_results = []
        for item in payload["results"]:
            if not isinstance(item, dict):
                changed = True
                continue
            canonical_title = str(
                item.get("catalogueTitle")
                or item.get("marvelCatalogueTitle")
                or item.get("mediaTitle")
                or item.get("title")
                or ""
            ).strip()
            if (
                _normalize_title(canonical_title) in excluded_titles
                or _catalogue_row_has_3d_quality(item)
                or _catalogue_row_is_excluded_franchise_title(item)
            ):
                changed = True
                continue
            retained_results.append(item)

        if not retained_results:
            return None
        if len(retained_results) != len(payload["results"]):
            payload = {
                **payload,
                "results": retained_results,
                "resultCount": len(retained_results),
                "movieCount": len({
                    _normalize_title(str(
                        item.get("catalogueTitle") or item.get("marvelCatalogueTitle") or item.get("mediaTitle") or item.get("title") or ""
                    ))
                    for item in retained_results
                }),
            }
        sorted_results = _sort_cached_catalogue_results(payload["results"])
        if sorted_results != payload["results"]:
            changed = True
        payload["results"] = sorted_results
        payload["resultCount"] = len(sorted_results)
        payload["movieCount"] = len({
            _normalize_title(str(item.get("catalogueTitle") or item.get("marvelCatalogueTitle") or item.get("mediaTitle") or item.get("title") or ""))
            for item in sorted_results
        })
        for item in payload["results"]:
            canonical_poster = _canonical_catalogue_poster_url(item)
            if canonical_poster and item.get("posterUrl") != canonical_poster:
                item["posterUrl"] = canonical_poster
                changed = True
        if changed:
            _write_extra_catalogue(key, payload)
        return payload
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _write_extra_catalogue(key: str, payload: dict[str, Any]) -> None:
    path = _EXTRA_CATALOGUE_PATHS[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=key + "-", suffix=".tmp",
                                         dir=str(path.parent), delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _extra_catalogue_is_stale(key: str, payload: dict[str, Any] | None) -> bool:
    if not payload:
        return True
    if CACHE_FIRST and payload.get("results"):
        # Cache-first: a stored catalogue is used as-is, even if its version or age is
        # behind the code. Rebuilding means hundreds of provider calls.
        return False
    config = _EXTRA_CATALOGUES[key]
    try:
        if int(payload.get("version") or 0) != int(config["version"]):
            return True
    except (TypeError, ValueError):
        return True
    days = int(config["refresh_days"])
    if days >= 36500:
        return False
    try:
        built = datetime.fromisoformat(str(payload.get("builtAt") or "").replace("Z", "+00:00"))
        if built.tzinfo is None:
            built = built.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - built).total_seconds() >= days * 86400
    except (ValueError, TypeError):
        return True


def _extra_item_year(item: dict[str, Any], fallback: int = 0) -> int:
    try:
        if item.get("year"):
            return int(item["year"])
    except (TypeError, ValueError):
        pass
    match = re.search(r"\b((?:19|20)\d{2})\b", str(item.get("title") or ""))
    return int(match.group(1)) if match else fallback


def _extra_item_release_date(item: dict[str, Any]) -> str:
    """Use full release dates where known; fall back to January 1 of the year."""
    for field in ("releaseDate", "release_date", "releaseDateISO", "firstAirDate"):
        value = str(item.get(field) or "").strip()
        if re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", value):
            try:
                datetime.strptime(value, "%Y-%m-%d")
                return value
            except ValueError:
                pass
    year = _extra_item_year(item)
    return f"{year:04d}-01-01" if year else ""


async def _build_extra_catalogue(key: str) -> None:
    if CACHE_ONLY_MODE:
        logger.info("CACHE_ONLY_MODE: skipped build for extra catalogue %s", key)
        return
    config = _EXTRA_CATALOGUES[key]
    state = _extra_catalogue_states[key]
    fixed_mode = config["mode"] == "fixed"
    jobs = list(config.get("titles", [])) if fixed_mode else []
    semaphore = asyncio.Semaphore(2)
    poster_semaphore = asyncio.Semaphore(2)
    state.update({"status": "building", "completed": 0, "total": len(jobs), "resultCount": 0, "error": ""})
    rows: dict[str, dict[str, Any]] = {}
    found_movies: set[str] = set()

    async def search_job(title: str, year: int) -> list[dict[str, Any]]:
        async with semaphore:
            query = f"{title} {year}".strip() if year else title
            query_suffix = str(config.get("query_suffix") or "").strip()
            if query_suffix:
                query = query + " " + query_suffix
            try:
                if fixed_mode:
                    if str(config.get("language") or "").strip().lower() == "hindi":
                        # Search the movie title without appending "Hindi dubbed".
                        # Exact-word constraints previously hid releases labelled only
                        # "Hin", "Dual Audio" or "Multi Audio".
                        try:
                            items = await asyncio.wait_for(
                                search_1337x(query, limit=50, allow_series_fallback=False),
                                timeout=18,
                            )
                        except Exception as exc:
                            logger.info("Catalogue %s primary Hindi search failed for %s: %s", key, query, exc)
                            items = []

                        matched_hindi = [
                            item for item in items
                            if isinstance(item, dict)
                            and _marvel_result_matches_title(item, title, year)
                            and _extra_result_matches_language(item, "hindi")
                        ]
                        if len(matched_hindi) < 3:
                            targeted_queries = ("Hindi", "dual audio", "multi audio")
                            targeted_calls = [
                                asyncio.wait_for(
                                    search_1337x_direct(
                                        f"{title} {language_term}",
                                        limit=50,
                                        pages=2,
                                        category="Movies",
                                        provider_query=f"{title} {language_term}",
                                    ),
                                    timeout=18,
                                )
                                for language_term in targeted_queries
                            ]
                            targeted_results = await asyncio.gather(*targeted_calls, return_exceptions=True)
                            for result in targeted_results:
                                if isinstance(result, list):
                                    items.extend(result)
                                elif isinstance(result, Exception):
                                    logger.info(
                                        "Catalogue %s targeted Hindi search failed for %s: %s",
                                        key, title, str(result) or type(result).__name__,
                                    )
                    else:
                        # The torrent sites are often slow from a server; a title that has no stored
                        # rows yet (a newly added one) would stay missing after a single timeout.
                        items = []
                        for attempt in (1, 2):
                            try:
                                items = await asyncio.wait_for(
                                    search_1337x(query, limit=50, allow_series_fallback=False),
                                    timeout=18 if attempt == 1 else 60,
                                )
                            except Exception as exc:
                                logger.warning("Catalogue %s search failed for %s (attempt %s): %s",
                                               key, query, attempt, str(exc) or type(exc).__name__)
                                items = []
                            if items:
                                break
                        if len(items) < 2:
                            try:
                                fallback = await asyncio.wait_for(search_yts_movies(query, limit=20), timeout=9)
                                items = list(items or []) + list(fallback or [])
                            except Exception as exc:
                                logger.debug("Catalogue %s YTS fallback failed for %s: %s", key, query, exc)
                else:
                    # Search each known title directly in movie listings instead of
                    # passing it through the broad result filter (which requires year
                    # and all title tokens to occur literally in provider filenames).
                    year_match = re.search(r"\b((?:19|20)\d{2})\b", query)
                    expected_year = int(year_match.group(1)) if year_match else datetime.now(timezone.utc).year
                    provider_query = re.sub(r"\b((?:19|20)\d{2})\b", "", query).strip(" .-_")
                    calls = [
                        asyncio.wait_for(
                            search_1337x_direct(
                                query,
                                limit=50,
                                pages=2,
                                category="Movies",
                                provider_query=provider_query,
                            ),
                            timeout=20,
                        ),
                        asyncio.wait_for(
                            search_limetorrents(query, limit=30, pages=1),
                            timeout=14,
                        ),
                    ]
                    searched = await asyncio.gather(*calls, return_exceptions=True)
                    items = []
                    for value in searched:
                        if isinstance(value, list):
                            items.extend(value)
                        elif isinstance(value, Exception):
                            logger.info(
                                "Catalogue %s provider search failed for %s: %s: %s",
                                key, query, type(value).__name__, str(value) or "<no message>",
                            )

                accepted: list[dict[str, Any]] = []
                for original in items or []:
                    if not isinstance(original, dict):
                        continue
                    item = dict(original)
                    if _catalogue_row_has_3d_quality(item) or _catalogue_row_is_excluded_franchise_title(item):
                        continue
                    raw_title = str(item.get("title") or "").strip()
                    if not raw_title:
                        continue
                    if fixed_mode:
                        if (
                            not _marvel_result_matches_title(item, title, year)
                            or not _extra_result_matches_language(item, config.get("language"))
                        ):
                            continue
                        media_title, media_year = title, year
                    else:
                        normalized = _normalize_title(unescape(raw_title))
                        query_year_match = re.search(r"\b((?:19|20)\d{2})\b", query)
                        expected_year = int(query_year_match.group(1)) if query_year_match else datetime.now(timezone.utc).year
                        query_title = re.sub(r"\b((?:19|20)\d{2})\b", "", query).strip(" .-_")
                        query_tokens = [
                            token for token in _normalize_title(query_title).split()
                            if token not in {"the", "a", "an", "of", "and", "for", "to", "movie", "film"}
                        ]
                        result_tokens = set(normalized.split())
                        # Roman-numbered sequels are frequently indexed with Arabic numerals.
                        matched_tokens = sum(
                            1 if token in result_tokens or (
                                token in {"ii", "iii", "iv"} and
                                ({"ii": "2", "iii": "3", "iv": "4"}[token] in result_tokens)
                            ) else 0
                            for token in query_tokens
                        )
                        minimum_matches = max(1, len(query_tokens) - 1) if len(query_tokens) > 2 else len(query_tokens)
                        if query_tokens and matched_tokens < minimum_matches:
                            continue

                        category = str(item.get("category") or "").strip().lower()
                        if (
                            category in {"tv", "television", "series", "tv series", "television series"}
                            or "television series" in category
                            or re.search(r"\b(?:S\d{1,2}E\d{1,2}|season\s+\d+|complete\s+series|episode\s+\d+|web[\s.-]?series)\b", raw_title, re.I)
                        ):
                            continue

                        current_year = datetime.now(timezone.utc).year
                        title_years = [int(value) for value in re.findall(r"\b((?:19|20)\d{2})\b", raw_title)]
                        if title_years:
                            media_year = title_years[-1]
                        else:
                            media_year = _extra_item_year(item, fallback=expected_year)
                        if media_year < current_year - 1 or media_year > current_year:
                            continue

                        # The query title is the canonical display/group title for all of its torrent variants.
                        media_title = unescape(query_title)
                    try:
                        raw_size = item.get("size_bytes") or item.get("sizeBytes") or item.get("size") or 0
                        if isinstance(raw_size, (int, float)):
                            size = int(raw_size)
                        else:
                            size = parse_size(str(raw_size))
                        seeders = int(float(str(item.get("seeders") or 0).replace(",", "")))
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if size < MIN_SEARCH_RESULT_SIZE_BYTES or size > MAX_SEARCH_RESULT_SIZE_BYTES or seeders <= 0:
                        continue
                    if not any(str(item.get(field) or "").strip() for field in ("magnetUrl", "downloadUrl", "sourceUrl", "infoUrl", "infoHash")):
                        continue
                    item["mediaTitle"] = media_title
                    item["year"] = media_year or None
                    if not item.get("posterUrl"):
                        item["posterUrl"] = _poster_url_for_release(f"{media_title} {media_year or ''}")
                    accepted.append(item)

                # Resolve one poster per movie group and reuse it across quality variants.
                grouped: dict[str, list[dict[str, Any]]] = {}
                for item in accepted:
                    group_key = _normalize_title(str(item.get("mediaTitle") or item.get("title") or ""))
                    grouped.setdefault(group_key, []).append(item)
                for group_key, variants in grouped.items():
                    if not variants:
                        continue
                    poster = str(variants[0].get("posterUrl") or "")
                    if not poster:
                        async with poster_semaphore:
                            try:
                                poster = await asyncio.wait_for(_poster_lookup(str(variants[0]["mediaTitle"]), str(variants[0].get("year") or "")), timeout=10)
                            except Exception:
                                poster = ""
                    for item in variants:
                        item["posterUrl"] = poster or _poster_url_for_release(str(item.get("mediaTitle") or item.get("title") or ""))
                        item["catalogueKey"] = key
                        item["catalogueTitle"] = str(item.get("mediaTitle") or item.get("title") or "")
                    found_movies.update(group_key + "|" + str(v.get("year") or "") for v in variants for group_key in [_normalize_title(str(v.get("mediaTitle") or v.get("title") or ""))])
                return accepted
            finally:
                state["completed"] = int(state.get("completed") or 0) + 1

    try:
        if not fixed_mode:
            # Every configured catalogue uses mode "fixed". A "latest" discovery
            # helper was referenced here but never written.
            raise NotImplementedError("Extra catalogue mode 'latest' is not implemented")
        tasks =[asyncio.create_task(search_job(title, year)) for title, year in jobs]
        for task in asyncio.as_completed(tasks):
            try:
                items = await task
            except Exception as exc:
                logger.info("Catalogue %s search task failed: %s", key, exc)
                items = []
            for item in items:
                digest = str(item.get("infoHash") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", digest):
                    digest = info_hash(str(item.get("magnetUrl") or item.get("downloadUrl") or ""))
                dedupe = "hash:" + digest if re.fullmatch(r"[0-9a-f]{40}", digest, re.I) else (
                    "title-size:" + _normalize_title(str(item.get("title") or "")) + "|" + str(item.get("size") or 0)
                )
                previous = rows.get(dedupe)
                if previous is None or (int(item.get("seeders") or 0), int(item.get("leechers") or 0)) > (int(previous.get("seeders") or 0), int(previous.get("leechers") or 0)):
                    rows[dedupe] = item
            state["resultCount"] = len(rows)
            state["movieCount"] = len(found_movies)

        # Keep cached torrent variants for titles still in the refreshed catalogue
        # when providers return a temporary miss; normalize older title aliases.
        previous_payload = _read_extra_catalogue(key)
        canonical_titles = {
            (re.sub(r"[^a-z0-9]+", "", title.casefold()), year): title
            for title, year in jobs
        }
        title_aliases = {
            ("battleofthesupersons", 2022): "Batman and Superman: Battle of the Super Sons",
        }
        if previous_payload:
            for old_item in previous_payload.get("results") or []:
                if not isinstance(old_item, dict):
                    continue
                old_title = str(old_item.get("catalogueTitle") or old_item.get("mediaTitle") or old_item.get("title") or "").strip()
                try:
                    old_year = int(old_item.get("year") or 0)
                except (TypeError, ValueError):
                    old_year = 0
                old_key = (re.sub(r"[^a-z0-9]+", "", old_title.casefold()), old_year)
                canonical = canonical_titles.get(old_key) or title_aliases.get(old_key)
                if not canonical or _catalogue_row_has_3d_quality(old_item) or _catalogue_row_is_excluded_franchise_title(old_item):
                    continue
                preserved = dict(old_item)
                preserved["mediaTitle"] = canonical
                preserved["catalogueTitle"] = canonical
                preserved["catalogueKey"] = key
                preserved["year"] = old_year
                digest = str(preserved.get("infoHash") or "").strip().lower()
                if not re.fullmatch(r"[0-9a-f]{40}", digest):
                    digest = info_hash(str(preserved.get("magnetUrl") or preserved.get("downloadUrl") or ""))
                dedupe_key = "hash:" + digest if re.fullmatch(r"[0-9a-f]{40}", digest, re.I) else (
                    "title-size:" + _normalize_title(str(preserved.get("title") or "")) + "|" + str(preserved.get("size") or 0)
                )
                existing = rows.get(dedupe_key)
                score = (int(preserved.get("seeders") or 0), int(preserved.get("leechers") or 0))
                existing_score = (int(existing.get("seeders") or 0), int(existing.get("leechers") or 0)) if existing else (-1, -1)
                if existing is None or score > existing_score:
                    rows[dedupe_key] = preserved

        results = list(rows.values())
        movie_count = len({ _normalize_title(str(item.get("mediaTitle") or item.get("title") or "")) + "|" + str(item.get("year") or "") for item in results })
        if movie_count < int(config["minimum_movies"]):
            raise RuntimeError(f"Only {movie_count} titles found; keeping the previous catalogue.")
        payload = {"version": config["version"], "builtAt": datetime.now(timezone.utc).isoformat(),
                   "titlesQueried": len(jobs), "movieCount": movie_count, "resultCount": len(results), "results": results}
        # Merge saved metadata before sorting so full release dates are available
        # across Classics, Marvel, DC live-action, DC animated, and language variants.
        _merge_saved_catalogue_metadata(payload, _EXTRA_CATALOGUE_PATHS[key])
        results.sort(
            key=lambda item: (
                _extra_item_release_date(item),
                float(item.get("rating") or 0),
                int(item.get("seeders") or 0),
            ),
            reverse=True,
        )
        _write_extra_catalogue(key, payload)
        _extra_catalogue_retry_after.pop(key, None)
        state.update({"status": "ready", "completed": len(jobs), "total": len(jobs), "movieCount": movie_count,
                      "resultCount": len(results), "builtAt": payload["builtAt"], "error": ""})
        logger.info("Built %s catalogue: %d titles / %d torrent options", key, movie_count, len(results))
    except Exception as exc:
        _extra_catalogue_retry_after[key] = time.monotonic() + 300
        state.update({
            "status": "failed",
            "error": "Catalogue refresh failed; previous cached results were retained.",
            "debugError": f"{type(exc).__name__}: {str(exc)[:240]}",
        })
        logger.exception("Catalogue %s build failed: %s", key, exc)


async def _ensure_extra_catalogue_refresh(key: str) -> None:
    cached = _read_extra_catalogue(key)
    if _extra_catalogue_is_stale(key, cached):
        if time.monotonic() < _extra_catalogue_retry_after.get(key, 0.0):
            return
        task = _extra_catalogue_tasks.get(key)
        if task is None or task.done():
            _extra_catalogue_tasks[key] = asyncio.create_task(_build_extra_catalogue(key))


async def _extra_catalogue_monthly_scheduler() -> None:
    # Do not launch bulk provider traffic during startup. Catalogue endpoints
    # refresh the requested cache on demand; this is only the daily backstop.
    while True:
        await asyncio.sleep(24 * 60 * 60)
        for key, config in _EXTRA_CATALOGUES.items():
            if int(config["refresh_days"]) < 36500:
                await _ensure_extra_catalogue_refresh(key)


# The seven franchise snapshots above are separate from the dynamic Popular/Trending/
# Latest catalogues. Those catalogues are persisted in TMDB_CATALOGUE_CACHE_FILE, so
# backfill their missing overviews there too; otherwise the movie cards never see them.
_TMDB_CATALOGUE_SYNOPSIS_RECHECK_SECONDS = stored_ttl(30 * 24 * 60 * 60)
_TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE: dict[str, Any] = {
    "status": "idle", "entriesCompleted": 0, "entriesTotal": 0,
    "titlesCompleted": 0, "titlesTotal": 0, "updatedRows": 0, "error": "",
}
_tmdb_catalogue_synopsis_enrichment_task: asyncio.Task | None = None
_TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED = False


def _tmdb_payload_needs_synopsis(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return False
    now = int(time.time())
    for item in payload["results"]:
        if not isinstance(item, dict) or str(item.get("overview") or "").strip():
            continue
        try:
            checked_at = int(item.get("synopsisCheckedAt") or 0)
            lookup_version = int(item.get("synopsisLookupVersion") or 0)
        except (TypeError, ValueError):
            checked_at = 0
            lookup_version = 0
        if (
            (lookup_version < TMDB_SYNOPSIS_LOOKUP_VERSION and not CACHE_FIRST)
            or not checked_at
            or now - checked_at >= _TMDB_CATALOGUE_SYNOPSIS_RECHECK_SECONDS
        ):
            return True
    return False


async def _lookup_tmdb_catalogue_synopsis_by_id(item: dict[str, Any]) -> dict[str, Any] | None:
    """Use TMDB movie details by ID; list/discover results may omit an overview."""
    try:
        tmdb_id = int(item.get("tmdbId") or item.get("id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if tmdb_id < 1:
        return None

    successful_response = False
    for language in ("en-US", "en"):
        try:
            details = await _tmdb_get_json(
                f"movie/{tmdb_id}", {"language": language}, request_timeout=6.0
            )
            successful_response = True
        except Exception as exc:
            logger.info("TMDB details synopsis lookup failed for ID %s (%s): %s",
                tmdb_id, language, type(exc).__name__)
            continue

        overview = re.sub(r"\s+", " ", str(details.get("overview") or "")).strip()
        if overview:
            return {
                "overview": overview,
                "tmdbId": tmdb_id,
                "tmdbUrl": f"https://www.themoviedb.org/movie/{tmdb_id}",
                "synopsisCheckedAt": int(time.time()),
                "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
            }

    # Mark only a successfully checked empty response. Transport failures stay
    # unmarked so the scheduled worker retries them.
    if successful_response:
        return {
            "tmdbId": tmdb_id,
            "tmdbUrl": f"https://www.themoviedb.org/movie/{tmdb_id}",
            "synopsisCheckedAt": int(time.time()),
            "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
        }
    return None


async def _enrich_tmdb_persistent_catalogue_synopses() -> None:
    if not BACKFILL_MISSING_METADATA:
        return
    global _tmdb_catalogue_synopsis_enrichment_task, _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED
    state = _TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        state.update({"status": "waiting_for_credentials",
            "error": "TMDB credentials are not configured"})
        return

    state.update({
        "status": "running", "entriesCompleted": 0, "entriesTotal": 0,
        "titlesCompleted": 0, "titlesTotal": 0, "updatedRows": 0, "error": "",
    })
    try:
        try:
            disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            disk = {}
        catalogues = disk.get("catalogues", {}) if isinstance(disk, dict) else {}
        if not isinstance(catalogues, dict):
            catalogues = {}

        cache_entries: list[tuple[tuple[str, int], dict[str, Any]]] = []
        jobs: dict[int, dict[str, Any]] = {}
        now = int(time.time())
        for disk_key, envelope in catalogues.items():
            if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
                continue
            try:
                variant_and_page, page_text = str(disk_key).rsplit(":", 1)
                page = int(page_text)
            except (ValueError, TypeError):
                continue
            cache_key = (variant_and_page, page)
            payload = envelope["payload"]
            if not isinstance(payload.get("results"), list):
                continue
            cache_entries.append((cache_key, payload))
            for item in payload["results"]:
                if not isinstance(item, dict) or str(item.get("overview") or "").strip():
                    continue
                try:
                    checked_at = int(item.get("synopsisCheckedAt") or 0)
                    tmdb_id = int(item.get("tmdbId") or item.get("id") or 0)
                except (TypeError, ValueError):
                    checked_at, tmdb_id = 0, 0
                try:
                    lookup_version = int(item.get("synopsisLookupVersion") or 0)
                except (TypeError, ValueError):
                    lookup_version = 0
                if (
                    (lookup_version >= TMDB_SYNOPSIS_LOOKUP_VERSION or CACHE_FIRST)
                    and checked_at
                    and now - checked_at < _TMDB_CATALOGUE_SYNOPSIS_RECHECK_SECONDS
                ):
                    continue
                if tmdb_id > 0:
                    jobs.setdefault(tmdb_id, item)

        state["entriesTotal"] = len(cache_entries)
        state["titlesTotal"] = len(jobs)
        metadata_by_id: dict[int, dict[str, Any]] = {}
        for tmdb_id, item in jobs.items():
            metadata = await _lookup_tmdb_catalogue_synopsis_by_id(item)
            if metadata:
                metadata_by_id[tmdb_id] = metadata
            state["titlesCompleted"] += 1
            if state["titlesCompleted"] % 25 == 0:
                logger.info("TMDB persistent catalogue synopsis enrichment: %d/%d titles",
                    state["titlesCompleted"], state["titlesTotal"])
            await asyncio.sleep(0.2)

        # Re-read every entry before merging, preserving any newer catalogue rows
        # written while the metadata lookups were running.
        for cache_key, initial_payload in cache_entries:
            current_entry = _read_tmdb_persistent_cache(cache_key)
            payload = current_entry[1] if current_entry else initial_payload
            changed = False
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            for item in rows if isinstance(rows, list) else []:
                if not isinstance(item, dict) or str(item.get("overview") or "").strip():
                    continue
                try:
                    tmdb_id = int(item.get("tmdbId") or item.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                metadata = metadata_by_id.get(tmdb_id)
                if not metadata:
                    continue
                if metadata.get("overview") and not str(item.get("overview") or "").strip():
                    item["overview"] = metadata["overview"]
                    state["updatedRows"] += 1
                    changed = True
                for field in ("tmdbId", "tmdbUrl"):
                    if metadata.get(field) and not item.get(field):
                        item[field] = metadata[field]
                        changed = True
                try:
                    old_lookup_version = int(item.get("synopsisLookupVersion") or 0)
                    new_lookup_version = int(metadata.get("synopsisLookupVersion") or 0)
                except (TypeError, ValueError):
                    old_lookup_version = new_lookup_version = 0
                if new_lookup_version > old_lookup_version:
                    item["synopsisLookupVersion"] = new_lookup_version
                    changed = True
                try:
                    old_checked_at = int(item.get("synopsisCheckedAt") or 0)
                    new_checked_at = int(metadata.get("synopsisCheckedAt") or 0)
                except (TypeError, ValueError):
                    old_checked_at, new_checked_at = 0, 0
                if new_checked_at > old_checked_at:
                    item["synopsisCheckedAt"] = new_checked_at
                    changed = True
            if changed:
                _write_tmdb_persistent_cache(cache_key, payload)
                _tmdb_movie_catalogue_cache[cache_key] = (time.monotonic(), payload)
            state["entriesCompleted"] += 1

        state.update({"status": "completed", "error": ""})
        logger.info("TMDB persistent catalogue synopsis enrichment completed: %d titles, %d rows updated",
            state["titlesCompleted"], state["updatedRows"])
    except Exception as exc:
        logger.exception("TMDB persistent catalogue synopsis enrichment failed")
        state.update({"status": "failed", "error": type(exc).__name__ + ": " + str(exc)[:300]})
    finally:
        # If a new cache page arrived while the startup sweep was running, do one
        # more pass after this task releases its slot so that page is not missed.
        if _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED:
            _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED = False
            _tmdb_catalogue_synopsis_enrichment_task = asyncio.create_task(
                _enrich_tmdb_persistent_catalogue_synopses()
            )


def _schedule_tmdb_catalogue_synopsis_enrichment(payload: dict[str, Any] | None = None) -> None:
    global _tmdb_catalogue_synopsis_enrichment_task, _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED
    if CACHE_ONLY_MODE or not BACKFILL_MISSING_METADATA:
        return
    if payload is not None and not _tmdb_payload_needs_synopsis(payload):
        return
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        _TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE.update({
            "status": "waiting_for_credentials", "error": "TMDB credentials are not configured"})
        return
    if (_tmdb_catalogue_synopsis_enrichment_task is not None
            and not _tmdb_catalogue_synopsis_enrichment_task.done()):
        _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED = True
        return
    _TMDB_CATALOGUE_SYNOPSIS_RESCAN_REQUESTED = False
    _tmdb_catalogue_synopsis_enrichment_task = asyncio.create_task(
        _enrich_tmdb_persistent_catalogue_synopses()
    )


async def _synopsis_enrichment_retry_loop() -> None:
    """Retry only unresolved synopsis rows on a schedule; completed cache hits stay on disk."""
    global _catalogue_synopsis_enrichment_task
    while True:
        await asyncio.sleep(SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS)
        if _catalogue_synopsis_enrichment_task is None or _catalogue_synopsis_enrichment_task.done():
            _catalogue_synopsis_enrichment_task = asyncio.create_task(_enrich_catalogue_synopses())
        _schedule_tmdb_catalogue_synopsis_enrichment()
        tasks = [
            task for task in (
                _catalogue_synopsis_enrichment_task,
                _tmdb_catalogue_synopsis_enrichment_task,
            )
            if task is not None and not task.done()
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def _start_tmdb_catalogue_synopsis_enrichment() -> None:
    if not BACKFILL_MISSING_METADATA:
        return
    # Registered after cache initialization; launch the backfill without holding
    # application startup open while hundreds of TMDB details are fetched.
    _schedule_tmdb_catalogue_synopsis_enrichment()


@router.get("/api/catalogue/marvel")
async def api_marvel_catalogue(request: Request, page: int = Query(0, ge=0), page_size: int = Query(0, ge=0, le=200)):
    global _marvel_catalogue_task
    if CACHE_ONLY_MODE:
        prebuilt = _prebuilt_catalogue_page(request, "marvel", page, page_size)
        if prebuilt is not None:
            return prebuilt
    cached = _merge_bundled_marvel_catalogue_cache(_read_marvel_catalogue())
    _record_cache_event("marvel_catalogue", "hit" if cached else "miss")
    if cached and CACHE_ONLY_MODE:
        return _fast_json_response(request, "marvel-page:%d:%d" % (page, page_size), _file_signature(MARVEL_CATALOGUE_PATH), lambda: _page_catalogue_payload({
            "status": "ready",
            "builtAt": cached.get("builtAt"),
            "completed": int(cached.get("titlesQueried") or len(MARVEL_MOVIE_SEARCHES)),
            "total": int(cached.get("titlesQueried") or len(MARVEL_MOVIE_SEARCHES)),
            "resultCount": int(cached.get("resultCount") or len(cached["results"])),
            "movieCount": int(cached.get("movieCount") or 0),
            "results": cached["results"],
            "refreshing": False,
        }, page, page_size, sort_by_release_date=True))
    if cached:
        # Keep the current cache available immediately while rebuilding it once
        # when its version predates the updated MCU film list.
        if not CACHE_FIRST and int(cached.get("version") or 0) < MARVEL_CATALOGUE_VERSION:
            if _marvel_catalogue_task is None or _marvel_catalogue_task.done():
                if not (_marvel_catalogue_state.get("status") == "failed" and time.time() < _marvel_catalogue_retry_after):
                    _marvel_catalogue_state.update({
                        "status": "building",
                        "completed": 0,
                        "total": len(MARVEL_MOVIE_SEARCHES),
                        "resultCount": int(cached.get("resultCount") or len(cached["results"])),
                        "movieCount": int(cached.get("movieCount") or 0),
                        "error": "",
                    })
                    _marvel_catalogue_task = asyncio.create_task(_build_marvel_catalogue())
        response_payload = {
            "status": "ready",
            "builtAt": cached.get("builtAt"),
            "completed": int(cached.get("titlesQueried") or len(MARVEL_MOVIE_SEARCHES)),
            "total": int(cached.get("titlesQueried") or len(MARVEL_MOVIE_SEARCHES)),
            "resultCount": int(cached.get("resultCount") or len(cached["results"])),
            "movieCount": int(cached.get("movieCount") or 0),
            "results": cached["results"],
            "refreshing": not CACHE_FIRST and int(cached.get("version") or 0) < MARVEL_CATALOGUE_VERSION,
        }
        if page > 0 and page_size > 0:
            return _fast_json_response(
                request,
                "marvel-page:%d:%d" % (page, page_size),
                _file_signature(MARVEL_CATALOGUE_PATH),
                lambda: _page_catalogue_payload(response_payload, page, page_size, sort_by_release_date=True),
            )
        return response_payload

    if _marvel_catalogue_task is None or _marvel_catalogue_task.done():
        if _marvel_catalogue_state.get("status") == "failed" and time.time() < _marvel_catalogue_retry_after:
            return {**_marvel_catalogue_state, "results": []}
        _marvel_catalogue_state.update({
            "status": "building",
            "completed": 0,
            "total": len(MARVEL_MOVIE_SEARCHES),
            "resultCount": 0,
            "error": "",
        })
        _marvel_catalogue_task = asyncio.create_task(_build_marvel_catalogue())

    return {
        **_marvel_catalogue_state,
        "total": len(MARVEL_MOVIE_SEARCHES),
        "results": [],
    }


async def _warm_marvel_catalogue_on_startup() -> None:
    """Keep startup quiet; the Marvel catalogue builds when first requested."""
    if _read_marvel_catalogue():
        logger.info("Persistent Marvel catalogue is available; startup warm-up skipped.")
    else:
        logger.info("Marvel catalogue build deferred until the catalogue is requested.")
