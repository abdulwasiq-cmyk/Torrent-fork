#!/usr/bin/env python3
"""Split existing seed catalogues into metadata-only JSON files per top section.

Migration only: reads existing metadata seed JSON files, performs no API calls,
no provider searches, and no publishing/deployment. It never reads or writes
torrent payloads. Existing metadata output is sanitized and merged by identity.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or HOME / "seed").resolve()
PAGE_SIZE = 18
# Stream-health fields from older builds; the app no longer reads them (directStreamBroken replaces them).
LEGACY_STREAM_KEYS = {"nexStream", "nexStreamPlayable", "nexStreamVerified", "nexStreamCheckedAt", "directStreamAvailability"}
TORRENT_KEYS = {
    "torrentDetails", "torrentMatch", "torrentMatches", "cachedTorrentDetails",
    "torrentReleases", "torrentResults", "torrent", "torrents", "releases",
    "releaseGroups", "magnetUrl", "magnet", "infoHash", "hash", "downloadUrl",
    "seeders", "leechers", "indexer", "protocol", "publishDate", "infoUrl",
    "sourceUrl", "descriptorUrl", "guid", "size", "category",
    # Marvel TV legacy cards embed episode-level streams and provider results.
    "episodes", "nexStream",
}

REGIONAL_MOVIE = {
    "popular-hollywood": ("hollywood", "popular"),
    "trending-hollywood": ("hollywood", "trending"),
    "latest-hollywood": ("hollywood", "latest"),
    "popular-bollywood": ("bollywood", "popular"),
    "trending-bollywood": ("bollywood", "trending"),
    "latest-bollywood": ("bollywood", "latest"),
    "highest-rated-hollywood": ("highest-rated", "hollywood"),
    "highest-rated-bollywood": ("highest-rated", "bollywood"),
    "popular-korean": ("korean", "movies"),
    "popular-anime": ("anime", "movies"),
}
REGIONAL_TV = {
    "highest-rated-popular": ("highest-rated", "tv"),
    "korean-popular": ("korean", "series"),
    "pakistani-popular": ("pakistani", "series"),
    "anime-popular": ("anime", "series"),
}
LEGACY_FILES = {
    "latest_hollywood_catalogue.json": ("hollywood", "latest"),
    "latest_bollywood_catalogue.json": ("bollywood", "latest"),
    "marvel_catalogue.json": ("marvel", "movies"),
    "marvel_web_series_catalogue.json": ("marvel", "series"),
    "dc_live_action_catalogue.json": ("dc", "live-action"),
    "dc_animated_catalogue.json": ("dc", "animated"),
    "classics_catalogue.json": ("favourites", "movies"),
    "classics_web_series_tv_catalogue.json": ("favourites", "series"),
    "classics_anime_tv_catalogue.json": ("favourites", "anime"),
}
RUNTIME_FILES = {
    "marvel_tv_catalogue_cache.json": ("marvel", "series"),
    "dc_tv_catalogue_cache.json": ("dc", "series"),
}

def log(event: str, **data: Any) -> None:
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def title(row: dict[str, Any]) -> str:
    if isinstance(row.get("movie"), dict):
        row = row["movie"]
    return str(
        row.get("catalogueTitle") or row.get("mediaTitle")
        or row.get("title") or row.get("name") or ""
    ).strip()

def identity(row: dict[str, Any]) -> str:
    if isinstance(row.get("movie"), dict):
        row = row["movie"]
    imdb = str(row.get("imdbId") or "").strip().lower()
    if re.fullmatch(r"tt\d+", imdb):
        return "imdb:" + imdb
    tmdb = row.get("tmdbId") or row.get("id")
    if tmdb not in (None, "") and str(tmdb).isdigit():
        return "tmdb:" + str(tmdb)
    clean = re.sub(r"[^a-z0-9]+", "", title(row).casefold())
    year = row.get("year") or str(row.get("releaseDate") or "")[:4]
    return f"title:{clean}:{year}" if clean else ""

def is_torrent_field(key: str) -> bool:
    low = key.casefold()
    exact = {item.casefold() for item in TORRENT_KEYS}
    return low in exact or any(token in low for token in (
        "magnet", "infohash", "torrentmatch", "torrentrelease",
        "torrentresult", "seeders", "leechers", "downloadurl",
    ))

def clean_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: clean_metadata_value(item)
            for key, item in value.items()
            if not is_torrent_field(str(key)) and key not in LEGACY_STREAM_KEYS
        }
    if isinstance(value, list):
        return [clean_metadata_value(item) for item in value]
    return value

def metadata_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a catalogue card, stripping torrent payloads and release wrappers."""
    source = row.get("movie") if isinstance(row.get("movie"), dict) else row
    clean = clean_metadata_value(source)
    canonical_title = (
        source.get("catalogueTitle") or source.get("mediaTitle")
        or source.get("name") or source.get("title")
    )
    if canonical_title:
        clean["title"] = str(canonical_title).strip()
    if clean.get("year") in (None, "") and source.get("releaseDate"):
        clean["year"] = str(source["releaseDate"])[:4]
    # Catalogue rows built from TMDB lists carry the TMDB id as "id" only; store it as tmdbId too so every
    # section file has one consistent key (in the data, id always equals the id in the row's tmdbUrl).
    if clean.get("tmdbId") in (None, "") and str(clean.get("id") or "").isdigit() and int(clean["id"]) > 0:
        clean["tmdbId"] = int(clean["id"])
    clean.pop("catalogueTitle", None)
    clean.pop("mediaTitle", None)
    return clean

def collect_top_level_results(value: Any) -> list[dict[str, Any]]:
    """Read only top-level results from a catalogue wrapper, never nested episodes."""
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        return []
    rows = [
        metadata_row(row)
        for row in value["results"]
        if isinstance(row, dict) and title(row)
    ]
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = identity(row)
        if key:
            dedup.setdefault(key, row)
    return list(dedup.values())


def collect_rows(value: Any) -> list[dict[str, Any]]:
    """Collect catalogue metadata records without descending into torrent payloads."""
    found: list[dict[str, Any]] = []
    seen_objects: set[int] = set()
    metadata_markers = {
        "tmdbId", "imdbId", "posterUrl", "backdropUrl", "overview",
        "synopsis", "releaseDate", "firstAirDate", "catalogueTitle",
        "mediaTitle", "imdbRating",
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if id(node) in seen_objects:
                return
            seen_objects.add(id(node))
            if title(node) and metadata_markers.intersection(node):
                found.append(metadata_row(node))
            for key, child in node.items():
                if not is_torrent_field(str(key)):
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    dedup: dict[str, dict[str, Any]] = {}
    for row in found:
        key = identity(row)
        if key:
            dedup.setdefault(key, row)
    return list(dedup.values())

def media_type(section: str, subsection: str) -> str:
    if section == "highest-rated" and subsection == "tv":
        return "tv"
    if subsection in {"series", "anime", "tv", "web-series", "webseries", "television"}:
        return "tv"
    return "movie"

def has_catalogue_metadata(row: dict[str, Any]) -> bool:
    source = row.get("movie") if isinstance(row.get("movie"), dict) else row
    markers = {
        "tmdbId", "imdbId", "posterUrl", "backdropUrl", "overview",
        "synopsis", "releaseDate", "firstAirDate", "imdbRating",
        "ottAvailability", "tmdbUrl", "imdbUrl",
    }
    return bool(markers.intersection(source))

def merge_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], *, metadata: bool) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in existing + incoming:
        key = identity(row)
        if not key:
            continue
        clean = metadata_row(row) if metadata else row
        if metadata and not has_catalogue_metadata(clean):
            continue
        if key not in merged:
            merged[key] = dict(clean)
            order.append(key)
        else:
            current = merged[key]
            for field, value in clean.items():
                if current.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                    current[field] = value
    return [merged[k] for k in order]

def subsection_doc(section: str, previous: Any) -> dict[str, Any]:
    if isinstance(previous, dict) and previous.get("section") == section:
        return previous
    return {"schemaVersion": 1, "section": section, "subsections": {}}

def get_existing_rows(doc: dict[str, Any], sub: str) -> list[dict[str, Any]]:
    node = (doc.get("subsections") or {}).get(sub) or {}
    rows = node.get("results") if isinstance(node, dict) else []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

def source_for_file(name: str) -> Path | None:
    candidates = [SEED / name, SEED / "runtime" / name]
    return next((p for p in candidates if p.is_file()), None)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report planned records without writing")
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")

    incoming: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    source_report: list[dict[str, Any]] = []
    regional = read_json(SEED / "runtime" / "regional_movie_prebuilt_cache.json")
    if isinstance(regional, dict):
        catalogues = regional.get("catalogues") or {}
        for key, target in REGIONAL_MOVIE.items():
            node = catalogues.get(key) if isinstance(catalogues, dict) else None
            rows = node.get("final") if isinstance(node, dict) else []
            if not isinstance(rows, list) or not rows:
                continue
            incoming[target].extend(r for r in rows if isinstance(r, dict) and title(r))
            source_report.append({"source": "regional_movie_prebuilt_cache.json", "catalogue": key, "records": len(rows)})
    regional_tv = read_json(SEED / "regional_tv_prebuilt_cache.json")
    if isinstance(regional_tv, dict):
        catalogues = regional_tv.get("catalogues") or {}
        for key, target in REGIONAL_TV.items():
            node = catalogues.get(key) if isinstance(catalogues, dict) else None
            rows: list[dict[str, Any]] = []
            if isinstance(node, dict):
                for page in node.get("pages") or []:
                    if isinstance(page, dict) and isinstance(page.get("results"), list):
                        rows.extend(r for r in page["results"] if isinstance(r, dict) and title(r))
                if not rows and isinstance(node.get("results"), list):
                    rows = [r for r in node["results"] if isinstance(r, dict) and title(r)]
            if rows:
                incoming[target].extend(metadata_row(row) for row in rows)
                source_report.append({"source": "regional_tv_prebuilt_cache.json", "catalogue": key, "records": len(rows)})
    for filename, target in {**LEGACY_FILES, **RUNTIME_FILES}.items():
        path = source_for_file(filename)
        if not path:
            continue
        payload = read_json(path)
        rows = (
            collect_top_level_results(payload)
            if filename == "marvel_web_series_catalogue.json" or filename in RUNTIME_FILES
            else collect_rows(payload)
        )
        if not rows:
            log("source_empty_or_unrecognized", source=str(path))
            continue
        incoming[target].extend(metadata_row(row) for row in rows)
        source_report.append({"source": str(path.relative_to(SEED)), "records": len(rows)})
    section_names = sorted({section for section, _ in incoming} | {
        p.stem for p in SEED.glob("*.json") if p.stem in {
            "hollywood", "bollywood", "marvel", "dc", "highest-rated",
            "korean", "pakistani", "anime", "favourites"
        }
    })
    totals: dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    for section in section_names:
        out_path = SEED / f"{section}.json"
        old_doc = subsection_doc(section, read_json(out_path))
        old_subs = old_doc.get("subsections") if isinstance(old_doc.get("subsections"), dict) else {}
        new_subs = dict(old_subs)
        removed_subsections: list[str] = []
        if section == "pakistani" and "movies" in new_subs:
            new_subs.pop("movies", None)
            removed_subsections.append("movies")
        obsolete = {
            "marvel": ("hindi-movies",),
            "dc": ("hindi-live-action",),
        }.get(section, ())
        for subsection in obsolete:
            if subsection in new_subs:
                new_subs.pop(subsection, None)
                removed_subsections.append(subsection)
        section_counts: dict[str, int] = {}
        subs = {sub for sec, sub in incoming if sec == section}
        for sub in sorted(subs):
            # The old Marvel series subsection contains torrent release cards.
            # Rebuild it from clean catalogue sources instead of merging those rows.
            previous_rows = [] if section == "marvel" and sub == "series" else get_existing_rows(old_doc, sub)
            rows = merge_rows(previous_rows, incoming[(section, sub)], metadata=True)
            new_subs[sub] = {
                "catalogueKey": sub,
                "mediaType": media_type(section, sub),
                "pageSize": PAGE_SIZE,
                "pageCount": (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE,
                "totalResults": len(rows),
                "builtAt": now,
                "results": rows,
            }
            section_counts[sub] = len(rows)
        old_doc.update({
            "schemaVersion": 1, "section": section, "builtAt": now,
            "mode": "legacy-migration", "subsections": new_subs,
            "safety": {"torrentSearches": 0, "torrentDataStoredSeparately": True,
                       "torrentFilesTouched": False, "activeApplicationCacheWrites": 0,
                       "source": "existing seed JSON files only"},
        })
        totals[section] = {"metadata": section_counts, "removedSubsections": removed_subsections, "torrentWrites": 0}
        if not args.dry_run and section_counts:
            atomic_write(out_path, old_doc)
    log("section_split_complete", seed=str(SEED), dryRun=args.dry_run, sections=totals, sources=source_report,
        filesWritten=0 if args.dry_run else sum(1 for v in totals.values() if v.get("metadata")),
        torrentFilesRead=0, torrentFilesWritten=0, torrentSearches=0)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())