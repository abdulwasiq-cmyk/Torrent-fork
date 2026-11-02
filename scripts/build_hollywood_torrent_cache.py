#!/usr/bin/env python3
"""Migrate existing Hollywood torrent records into a dedicated cache file.

This is a migration/preservation task only: it never searches torrent providers.
Run after build_hollywood_section_cache.py; it reads the legacy latest cache and
any torrent fields still embedded in an older hollywood.json.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REFRESH_HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or REFRESH_HOME / "seed").resolve()
METADATA_PATH = SEED / "hollywood.json"
LEGACY_PATH = SEED / "latest_hollywood_catalogue.json"
OUTPUT = SEED / "hollywood-torrents.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except OSError:
            pass
        raise


def movie_id(row: dict[str, Any]) -> str:
    value = row.get("tmdbId") or row.get("id")
    return str(value).strip() if value not in (None, "") else ""


def torrent_release(row: dict[str, Any]) -> dict[str, Any] | None:
    fields = ("guid", "title", "mediaTitle", "quality", "size", "seeders", "leechers",
              "indexer", "protocol", "publishDate", "infoHash", "magnetUrl",
              "downloadUrl", "infoUrl", "sourceUrl", "matchScore")
    release = {key: row[key] for key in fields if key in row and row[key] not in (None, "")}
    if not (release.get("infoHash") or release.get("magnetUrl") or release.get("guid")):
        return None
    return release


def add_release(target: dict[str, Any], release: dict[str, Any]) -> None:
    releases = target.setdefault("matches", [])
    identity = str(release.get("infoHash") or release.get("magnetUrl") or release.get("guid") or "")
    if identity and all(str(item.get("infoHash") or item.get("magnetUrl") or item.get("guid") or "") != identity
                        for item in releases):
        releases.append(release)


def collect_embedded(document: dict[str, Any], movies: dict[str, Any]) -> None:
    subsections = document.get("subsections") or {}
    if not isinstance(subsections, dict):
        return
    for subsection, section in subsections.items():
        if not isinstance(section, dict):
            continue
        for row in section.get("results") or []:
            if not isinstance(row, dict):
                continue
            ident = movie_id(row)
            if not ident:
                continue
            record = movies.setdefault(ident, {"tmdbId": ident, "title": row.get("title") or row.get("name") or "", "subsections": []})
            if subsection not in record["subsections"]:
                record["subsections"].append(subsection)
            for field in ("torrentMatch", "torrentMatches", "torrentDetails", "cachedTorrentDetails"):
                value = row.get(field)
                candidates = value if isinstance(value, list) else ([value] if isinstance(value, dict) else [])
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    release = torrent_release(candidate)
                    if release:
                        add_release(record, release)
            checked = row.get("torrentCheckedAt") or row.get("torrentCheckedAtEpoch")
            if checked:
                record["checkedAt"] = checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("missing", "deep"))
    args = parser.parse_args()
    previous = read_json(OUTPUT)
    movies: dict[str, Any] = {}
    old_movies = previous.get("movies") if isinstance(previous.get("movies"), dict) else {}
    for ident, old in old_movies.items():
        if isinstance(old, dict):
            movies[str(ident)] = dict(old)
            movies[str(ident)]["matches"] = list(old.get("matches") or [])

    collect_embedded(read_json(METADATA_PATH), movies)
    legacy = read_json(LEGACY_PATH)
    legacy_count = 0
    for row in legacy.get("results") or []:
        if not isinstance(row, dict):
            continue
        ident = movie_id(row)
        if not ident:
            continue
        release = torrent_release(row)
        if not release:
            continue
        record = movies.setdefault(ident, {"tmdbId": ident, "title": row.get("catalogueTitle") or row.get("mediaTitle") or row.get("title") or "", "subsections": []})
        if "latest" not in record.setdefault("subsections", []):
            record["subsections"].append("latest")
        add_release(record, release)
        checked = row.get("torrentCheckedAt") or row.get("torrentCheckedAtEpoch") or legacy.get("builtAt")
        if checked:
            record.setdefault("checkedAt", checked)
        legacy_count += 1

    # Do not publish an empty migration over a previously useful torrent cache.
    if not movies and not old_movies:
        raise RuntimeError("No existing Hollywood torrent data found; refusing to write an empty cache")
    generated = datetime.now(timezone.utc).isoformat()
    document = dict(previous)
    document.update({
        "schemaVersion": 1,
        "section": "hollywood",
        "builtAt": generated,
        "mode": args.mode,
        "movies": movies,
        "safety": {"torrentSearches": 0, "migrationOnly": True},
    })
    atomic_write(OUTPUT, document)
    print(json.dumps({"event": "hollywood_torrent_cache_written", "path": str(OUTPUT),
                      "movies": len(movies), "legacyReleasesSeen": legacy_count,
                      "torrent_searches": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
