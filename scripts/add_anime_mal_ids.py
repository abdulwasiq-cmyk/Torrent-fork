#!/usr/bin/env python3
"""Store MyAnimeList ids on the anime rows of the section caches, so the deployed (cache-only)
app never needs a live AniList lookup to start an anime episode.

Targets: every subsection of anime.json, and the "anime" subsection of favourites.json.
Each row without a `malId` is looked up through the running app (`/api/yenime/resolve-mal`, which
uses AniList and remembers answers); the result is written back as `malId`, and `malIdCheckedAt`
records the attempt so unresolved titles are not retried every run (default: retry after 30 days).

  HOME_API_BASE=http://127.0.0.1:3000 REFRESH_SEED_DIR=~/torrent-studio-refresh/seed \\
      python3 scripts/add_anime_mal_ids.py [--dry-run] [--limit N]

Needs the app running with provider access (CACHE_ONLY_MODE=false). Metadata only.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or HOME / "seed").expanduser().resolve()
API_BASE = os.getenv("HOME_API_BASE", "http://127.0.0.1:3000").rstrip("/")
DELAY_SECONDS = float(os.getenv("MAL_LOOKUP_DELAY_SECONDS", "0.8"))  # AniList allows ~90 requests/minute
RETRY_AFTER_SECONDS = int(os.getenv("MAL_RETRY_DAYS", "30")) * 86400
TARGETS = (("anime.json", None), ("favourites.json", "anime"))  # (file, only this subsection or all)


def row_title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("name") or row.get("catalogueTitle") or "").strip()


def row_year(row: dict[str, Any]) -> int | None:
    for value in (row.get("year"), str(row.get("releaseDate") or row.get("firstAirDate") or "")[:4]):
        try:
            year = int(value)
        except (TypeError, ValueError):
            continue
        if 1900 <= year <= 2100:
            return year
    return None


def row_tmdb_id(row: dict[str, Any]) -> int | None:
    value = row.get("tmdbId") or row.get("id")
    return int(value) if str(value or "").isdigit() and int(value) > 0 else None


def needs_lookup(row: dict[str, Any], now: float) -> bool:
    if not row_title(row):
        return False
    if str(row.get("malId") or "").isdigit() and int(row["malId"]) > 0:
        return False
    checked = row.get("malIdCheckedAt")
    return not (isinstance(checked, (int, float)) and now - checked < RETRY_AFTER_SECONDS)


def http_resolve(title: str, year: int | None, tmdb_id: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"title": title}
    if year:
        params["year"] = year
    if tmdb_id:
        params["tmdbId"] = tmdb_id
    url = f"{API_BASE}/api/yenime/resolve-mal?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fill_document(
    doc: dict[str, Any],
    only_subsection: str | None,
    resolve: Callable[[str, int | None, int | None], dict[str, Any]],
    *,
    now: float | None = None,
    limit: int | None = None,
    delay: float = 0.0,
) -> dict[str, int]:
    """Add malId to the rows of one section document. Returns counts."""
    now = time.time() if now is None else now
    counts = {"checked": 0, "resolved": 0, "unresolved": 0, "alreadyHad": 0, "errors": 0}
    for name, node in (doc.get("subsections") or {}).items():
        if only_subsection is not None and name != only_subsection:
            continue
        for row in node.get("results") or [] if isinstance(node, dict) else []:
            if not isinstance(row, dict):
                continue
            if str(row.get("malId") or "").isdigit() and int(row["malId"]) > 0:
                counts["alreadyHad"] += 1
                continue
            if not needs_lookup(row, now):
                continue
            if limit is not None and counts["checked"] >= limit:
                return counts
            counts["checked"] += 1
            try:
                result = resolve(row_title(row), row_year(row), row_tmdb_id(row))
            except (urllib.error.URLError, OSError, ValueError, TimeoutError):
                counts["errors"] += 1  # transient: leave unmarked so the next run retries
                continue
            mal = result.get("malId") if isinstance(result, dict) else None
            if result.get("status") == "resolved" and str(mal or "").isdigit():
                row["malId"] = int(mal)
                row.pop("malIdCheckedAt", None)
                counts["resolved"] += 1
            elif result.get("status") == "unavailable":
                counts["errors"] += 1  # AniList cool-down / cache-only: not a real "not found"
                continue
            else:
                row["malIdCheckedAt"] = int(now)
                counts["unresolved"] += 1
            if delay:
                time.sleep(delay)
    return counts


def atomic_write(path: Path, value: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="look up and report, but do not write files")
    parser.add_argument("--limit", type=int, default=None, help="look up at most N rows per file")
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")
    for filename, only in TARGETS:
        path = SEED / filename
        if not path.is_file():
            print(json.dumps({"event": "skip_missing", "file": filename}))
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        counts = fill_document(doc, only, http_resolve, limit=args.limit, delay=DELAY_SECONDS)
        print(json.dumps({"event": "mal_ids", "file": filename, **counts}))
        if counts["resolved"] or counts["unresolved"]:
            if not args.dry_run:
                atomic_write(path, doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
