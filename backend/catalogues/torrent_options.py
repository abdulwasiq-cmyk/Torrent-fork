"""Per-title torrent lookups served from the nine ``<section>-torrents.json`` seed files.

Design rules that keep the app fast (see backend/cache-seed/README.md):

* Torrent data is never part of the section metadata files or of page loads. It is only
  read when a user clicks Prepare on one title.
* Each file is parsed once and kept in memory as a dict, so a lookup is a dictionary hit.
  A file is re-read only when its size/mtime changes (a deploy or cache-bundle overlay).
  There are no locks, checksum passes or per-request validation.
* Magnet links are not stored; they are rebuilt here from info hash + title + the
  tracker list shared by the file.

This module imports nothing from FastAPI so it can be unit-tested on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

SECTIONS = (
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
)
SEED_DIR = Path(__file__).resolve().parents[1] / "cache-seed"
SCHEMA_VERSION = 2
MAX_RESULTS = 12
MAX_TV_RESULTS = 40   # a series has season packs and several qualities per season
MAX_LARGE_RESULTS = 10  # releases ABOVE the size window, offered to Webtor instead of Seedr
MEDIA = ("movie", "tv")


def normalize_title(value: object) -> str:
    """Same normalisation as normalizeGroupTitle() in the frontend."""
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:the|a|an)\s+", "", text)


def _year(value: object) -> str:
    match = re.match(r"^((?:18|19|20)\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


class _Index:
    __slots__ = ("trackers", "by_key", "by_title_year")

    def __init__(self, document: dict[str, Any]) -> None:
        self.trackers: list[str] = [t for t in document.get("trackers", []) if isinstance(t, str)]
        self.by_key: dict[str, dict[str, Any]] = {}
        self.by_title_year: dict[str, str] = {}
        for key, entry in (document.get("titles") or {}).items():
            if not isinstance(entry, dict) or not isinstance(entry.get("releases"), list):
                continue
            self.by_key[key] = entry
            title, year = normalize_title(entry.get("title")), _year(entry.get("year"))
            if title and year:
                # key is "movie:<id>" or "tv:<id>"; movies and series never collide on title+year
                self.by_title_year.setdefault(f"{key.split(':', 1)[0]}|{title}|{year}", key)


# section -> ((mtime_ns, size), index). Plain dict assignment is atomic in CPython; two
# requests racing on a changed file at worst parse it twice.
_INDEXES: dict[str, tuple[tuple[int, int], _Index]] = {}


def _index_for(section: str, seed_dir: Path) -> _Index | None:
    path = seed_dir / f"{section}-torrents.json"
    try:
        stat = path.stat()
    except OSError:
        _INDEXES.pop(section, None)
        return None
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _INDEXES.get(section)
    if cached is not None and cached[0] == signature:
        return cached[1]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != SCHEMA_VERSION
        or document.get("section") != section
        or not isinstance(document.get("titles"), dict)
    ):
        return None
    index = _Index(document)
    _INDEXES[section] = (signature, index)
    return index


def build_magnet(info_hash: str, title: str, trackers: list[str]) -> str:
    parts = [f"magnet:?xt=urn:btih:{info_hash}"]
    if title:
        parts.append("dn=" + quote(title, safe=""))
    parts.extend("tr=" + quote(tracker, safe="") for tracker in trackers)
    return "&".join(parts)


def lookup(
    sections: tuple[str, ...] | list[str] | None,
    *,
    tmdb_id: str | None = None,
    title: str | None = None,
    year: str | int | None = None,
    seed_dir: Path | None = None,
    media: str = "movie",
    min_size: int | None = None,
    max_size: int | None = None,
    only_large: bool = False,
) -> list[dict[str, Any]]:
    """Return ready-to-use release rows for one movie or series, best seeded first.

    ``media="tv"`` reads the ``tv:<tmdbId>`` entries: season packs / complete series, ordered
    complete first, then by season, then by seeders. No size window is applied to them.

    ``min_size`` / ``max_size`` (bytes) are the configured size window for movies
    (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB). The files keep a wider range than any window
    you are likely to set, so the window is applied here, before the result cap, and a larger
    setting simply reveals more of what is already stored.

    ``only_large=True`` (movies) returns the opposite set: only releases ABOVE ``max_size``, at most
    MAX_LARGE_RESULTS. Those are too big for Seedr, so the card offers them through Webtor.

    Matches by TMDB id first, then by normalised title + year. ``sections=None`` searches
    all nine files and merges what they know about the title (a film can sit in several
    sections, e.g. Hollywood "latest" and Marvel).
    """
    if media not in MEDIA:
        return []
    directory = seed_dir or SEED_DIR
    tmdb = str(tmdb_id or "").strip()
    title_key = f"{media}|{normalize_title(title)}|{_year(year)}" if title and _year(year) else ""
    merged: dict[str, dict[str, Any]] = {}
    for section in sections or SECTIONS:
        index = _index_for(section, directory)
        if index is None:
            continue
        key = f"{media}:{tmdb}" if tmdb and f"{media}:{tmdb}" in index.by_key else index.by_title_year.get(title_key)
        entry = index.by_key.get(key) if key else None
        if entry is None:
            continue
        media_title, entry_year = str(entry.get("title") or ""), entry.get("year")
        for release in entry["releases"]:
            digest = str(release.get("infoHash") or "")
            if not digest:
                continue
            if media == "movie":
                size = release.get("size") or 0
                if only_large:
                    if max_size is None or size <= max_size:
                        continue
                elif (min_size is not None and size < min_size) or (max_size is not None and size > max_size):
                    continue
            row = {
                "guid": digest,
                "title": release.get("title") or "",
                "mediaTitle": media_title,
                "size": release.get("size") or 0,
                "seeders": release.get("seeders") or 0,
                "leechers": release.get("leechers") or 0,
                "indexer": release.get("indexer") or "",
                "protocol": "torrent",
                "infoHash": digest,
                "magnetUrl": build_magnet(digest, str(release.get("title") or ""), index.trackers),
                "year": entry_year,
            }
            if media == "tv":
                row["scope"] = "complete" if release.get("scope") == "complete" else "season"
                row["season"] = int(release.get("season") or 0)
            if release.get("infoUrl"):
                row["infoUrl"] = row["sourceUrl"] = release["infoUrl"]
            previous = merged.get(digest)
            if previous is None or row["seeders"] > previous["seeders"]:
                merged[digest] = row
    if media == "tv":
        rows = sorted(merged.values(), key=lambda r: (
            r["scope"] != "complete", r["season"], -r["seeders"], -r["leechers"], r["infoHash"]))
        return rows[:MAX_TV_RESULTS]
    rows = sorted(merged.values(), key=lambda r: (-r["seeders"], -r["leechers"], r["infoHash"]))
    return rows[:(MAX_LARGE_RESULTS if only_large else MAX_RESULTS)]


def clear_memory_cache() -> None:
    """Drop parsed files (tests, or after replacing seed files in place)."""
    _INDEXES.clear()


__all__ = ["MAX_LARGE_RESULTS", "MAX_TV_RESULTS", "SECTIONS", "SEED_DIR", "build_magnet", "clear_memory_cache", "lookup", "normalize_title"]
