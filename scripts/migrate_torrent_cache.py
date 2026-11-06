#!/usr/bin/env python3
"""Build the nine slim per-section torrent files from the old torrent data.

Why: the nine self-contained section files (hollywood.json, marvel.json, ...) hold
metadata only and are fast because they are small. Torrent data must stay out of them
and out of the page-load path. The old "Phase 5" torrent files were 15-66 MB each (about
247 MB in total) because every record repeated poster/overview/OTT blocks and a magnet
with ~18 trackers. This script rebuilds them as small per-title lookup files:

    backend/cache-seed/<section>-torrents.json

    {
      "schemaVersion": 2, "kind": "torrent-options", "section": "marvel",
      "builtAt": "...", "limits": {"minSizeBytes": ..., "maxSizeBytes": ...},
      "trackers": ["udp://...", ...],             # shared by every release in the file
      "titles": {
        "movie:617126": {"title": "...", "year": 2025,
                         "releases": [{"infoHash", "title", "size", "seeders", "leechers",
                                       "indexer", "infoUrl"}, ...]}
      }
    }

Magnet links are rebuilt from infoHash + title + the shared trackers when a title is
served, so they are not stored per release.

Sources (all merged, de-duplicated by infoHash):
  * the old Phase 5 files, read from git history (default revision 39b31c0), or --old-dir
  * backend/cache-seed/bollywood_torrent_matched_catalogue.json
  * backend/cache-seed/runtime/regional_movie_prebuilt_cache.json

Only movie rows are migrated (the Prepare card is movie-only; TV uses NexStream).
Every release is filtered the way the Prepare card filters it (stored size range
at least TORRENT_CACHE_MIN_SIZE_MB (default 100 MB), no upper limit unless TORRENT_CACHE_MAX_SIZE_GB is set, no cam/telesync/screener, release title must contain the movie
title), so nothing is stored that the UI would hide.

Standard library only. Run:  python3 -I scripts/migrate_torrent_cache.py
"""
from __future__ import annotations

import argparse
import os
import base64
import binascii
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = (
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
)
DEFAULT_GIT_REV = "39b31c0"
SCHEMA_VERSION = 2
MAX_RELEASES_PER_TITLE = 60       # sanity cap over all bands
MAX_RELEASES_PER_BAND = 10        # the old per-title cap, now per size band so one band cannot crowd out another
MAX_RELEASES_PER_RESOLUTION = 4   # per resolution AND size band (see SIZE_BAND_EDGES_GB)
# The files must hold more than the window anyone is likely to set (TORRENT_MAX_SIZE_GB), because the
# window is applied when a title is served. Selection is therefore done per size band: if only the
# best-seeded releases overall were kept, the top few 1080p might all be 4 GB and a 2 GB window would
# find nothing left to show.
SIZE_BAND_EDGES_GB = (1, 2, 3, 5, 8)
MAX_TRACKERS = 10
# Trackers that no longer answer; keeping them only slows peer discovery.
DEAD_TRACKER_MARKERS = (
    "rarbg", "coppersurfer", "leechers-paradise", "openbittorrent",
    "cyberia.is", "internetwarriors",
)
LOW_QUALITY = re.compile(
    r"(?:^|[\s._()\[\]-])(?:cam(?:rip)?|hdcam|hd[ ._-]?cam|telesync|tele[ ._-]?sync|"
    r"ts[ ._-]?(?:md|ac3|hd)?|telecine|dvdscr|dvd[ ._-]?scr|screener|workprint)"
    r"(?:$|[\s._()\[\]-])",
    re.IGNORECASE,
)
RESOLUTION = re.compile(r"\b(2160p|1440p|1080p|720p|576p|480p|4k|8k)\b", re.IGNORECASE)
HEX40 = re.compile(r"^[0-9a-f]{40}$")


# --------------------------------------------------------------------------- helpers
def normalize_title(value: object) -> str:
    """Same normalisation as normalizeGroupTitle() in the frontend."""
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:the|a|an)\s+", "", text)


def year_of(value: object) -> str:
    match = re.match(r"^((?:18|19|20)\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


def info_hash_of(hash_value: object, magnet: object = "") -> str:
    """Return a lowercase 40-hex info hash, or '' when none can be determined."""
    candidates = [str(hash_value or "").strip()]
    query = urlsplit(str(magnet or "")).query
    for key, val in parse_qsl(query, keep_blank_values=True):
        if key == "xt" and val.lower().startswith("urn:btih:"):
            candidates.append(val[9:])
    for raw in candidates:
        raw = raw.strip()
        if HEX40.match(raw.lower()):
            return raw.lower()
        if len(raw) == 32:  # base32 form of the hash
            try:
                return base64.b32decode(raw.upper()).hex()
            except (binascii.Error, ValueError):
                continue
    return ""


def trackers_of(magnet: object) -> list[str]:
    query = urlsplit(str(magnet or "")).query
    return [val for key, val in parse_qsl(query, keep_blank_values=True) if key == "tr" and val]


def resolution_bucket(title: str) -> str:
    match = RESOLUTION.search(title or "")
    if not match:
        return "other"
    value = match.group(1).lower()
    return {"4k": "2160p", "8k": "2160p", "1440p": "1080p", "576p": "480p"}.get(value, value)


def title_phrase_match(release_title: str, expected: list[str]) -> bool:
    haystack = f" {normalize_title(release_title)} "
    return any(f" {needle} " in haystack for needle in expected if needle)


def expected_titles(title: str) -> list[str]:
    """The movie title, plus the title without a bracketed alias or subtitle."""
    full = normalize_title(title)
    base = normalize_title(re.split(r"\s+[-–—:]\s+|\s*\(", str(title or ""))[0])
    return [full] + ([base] if len(base) >= 3 and base != full else [])


# ---------------------------------------------------------------- load candidate pool
class Pool:
    """Every known release, indexed by TMDB id and by normalised title + year."""

    def __init__(self) -> None:
        self.releases: dict[str, dict] = {}   # infoHash -> best release record
        self.by_tmdb: dict[str, set[str]] = {}
        self.by_title_year: dict[str, set[str]] = {}
        self.stats: Counter = Counter()

    def add(self, release: dict, identities: list[dict]) -> None:
        digest = info_hash_of(release.get("infoHash"), release.get("magnetUrl") or release.get("downloadUrl"))
        if not digest:
            self.stats["skipped_no_hash"] += 1
            return
        size = release.get("size")
        record = {
            "infoHash": digest,
            "title": str(release.get("title") or "").strip(),
            "size": int(size) if isinstance(size, (int, float)) and not isinstance(size, bool) else 0,
            "seeders": int(release.get("seeders") or 0),
            "leechers": int(release.get("leechers") or 0),
            "indexer": str(release.get("indexer") or "").strip(),
            "infoUrl": str(release.get("infoUrl") or release.get("sourceUrl") or "").strip(),
            "_trackers": trackers_of(release.get("magnetUrl")) or trackers_of(release.get("downloadUrl")),
        }
        if not record["title"]:
            self.stats["skipped_no_title"] += 1
            return
        existing = self.releases.get(digest)
        if existing is None:
            self.releases[digest] = record
        else:  # same torrent seen again: keep the freshest-looking numbers, merge trackers
            if record["seeders"] > existing["seeders"]:
                record["_trackers"] = record["_trackers"] or existing["_trackers"]
                self.releases[digest] = existing = record
            elif not existing["_trackers"]:
                existing["_trackers"] = record["_trackers"]
            self.stats["duplicates_merged"] += 1
        for identity in identities:
            if identity.get("mediaType") not in (None, "movie"):
                continue
            tmdb = str(identity.get("tmdbId") or "").strip()
            if tmdb.isdigit():
                self.by_tmdb.setdefault(tmdb, set()).add(digest)
            title, year = normalize_title(identity.get("title")), year_of(identity.get("year"))
            if title and year:
                self.by_title_year.setdefault(f"{title}|{year}", set()).add(digest)

    def candidates(self, tmdb_id: str, title: str, year: str) -> list[dict]:
        hashes: set[str] = set()
        if tmdb_id:
            hashes |= self.by_tmdb.get(tmdb_id, set())
        for name in expected_titles(title):
            if year:
                hashes |= self.by_title_year.get(f"{name}|{year}", set())
        return [self.releases[h] for h in hashes]


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_old_phase5(pool: Pool, old_dir: Path | None, git_rev: str) -> int:
    loaded = 0
    for section in SECTIONS:
        name = f"backend/cache-seed/{section}-torrents.json"
        if old_dir is not None:
            path = old_dir / f"{section}-torrents.json"
            if not path.is_file():
                continue
            document = read_json(path)
        else:
            proc = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{git_rev}:{name}"],
                capture_output=True, check=False,
            )
            if proc.returncode != 0:
                print(f"  note: {name} not found in {git_rev}", file=sys.stderr)
                continue
            document = json.loads(proc.stdout.decode("utf-8"))
        for record in document.get("records", []) if isinstance(document, dict) else []:
            pool.add(record, record.get("mediaIdentities") or [])
            loaded += 1
    return loaded


def load_bollywood_matches(pool: Pool, seed_dir: Path) -> int:
    path = seed_dir / "bollywood_torrent_matched_catalogue.json"
    if not path.is_file():
        return 0
    loaded = 0
    for record in (read_json(path) or {}).get("records", []):
        identity = {"mediaType": "movie", "tmdbId": record.get("tmdbId"),
                    "title": record.get("title"), "year": record.get("year")}
        for match in record.get("torrentMatches") or []:
            pool.add(match, [identity])
            loaded += 1
    return loaded


def load_regional_prebuilt(pool: Pool, seed_dir: Path) -> int:
    path = seed_dir / "runtime" / "regional_movie_prebuilt_cache.json"
    if not path.is_file():
        return 0
    loaded = 0
    for entry in ((read_json(path) or {}).get("movies") or {}).values():
        movie = entry.get("movie") or {}
        details = entry.get("torrentDetails")
        rows = details.get("results") if isinstance(details, dict) else details
        identity = {"mediaType": "movie", "tmdbId": movie.get("id"),
                    "title": movie.get("title"), "year": movie.get("year")}
        for row in rows or []:
            pool.add(row, [identity])
            loaded += 1
    return loaded


# --------------------------------------------------------------------------- selection
def select_releases(candidates: list[dict], title: str, limits: dict) -> list[dict]:
    """Apply the Prepare card's own filters, then keep a few per resolution."""
    needles = expected_titles(title)
    usable = []
    for release in candidates:
        size = release["size"]
        if size < limits["minSizeBytes"] or (limits["maxSizeBytes"] is not None and size > limits["maxSizeBytes"]):
            continue
        if LOW_QUALITY.search(release["title"]):
            continue
        if needles and not title_phrase_match(release["title"], needles):
            continue
        usable.append(release)
    seeded = [r for r in usable if r["seeders"] > 0]
    usable = seeded or usable  # prefer active swarms, but do not hide every release
    usable.sort(key=lambda r: (-r["seeders"], -r["leechers"], r["size"], r["infoHash"]))
    per_resolution: Counter = Counter()
    per_band: Counter = Counter()
    chosen = []
    for release in usable:
        band = size_band(release["size"])
        bucket = (resolution_bucket(release["title"]), band)
        if per_resolution[bucket] >= MAX_RELEASES_PER_RESOLUTION or per_band[band] >= MAX_RELEASES_PER_BAND:
            continue
        per_resolution[bucket] += 1
        per_band[band] += 1
        chosen.append(release)
        if len(chosen) >= MAX_RELEASES_PER_TITLE:
            break
    return chosen


def size_band(size: int) -> int:
    return sum(1 for edge in SIZE_BAND_EDGES_GB if size > edge * 1024 ** 3)


def pick_trackers(releases: list[dict]) -> list[str]:
    counts: Counter = Counter()
    for release in releases:
        for tracker in set(release.get("_trackers") or []):
            lowered = tracker.lower()
            if not lowered.startswith(("udp://", "http://", "https://", "wss://")):
                continue
            if any(marker in lowered for marker in DEAD_TRACKER_MARKERS):
                continue
            counts[tracker] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [tracker for tracker, _ in ranked[:MAX_TRACKERS]]


def movie_rows(section_document: dict) -> list[dict]:
    rows = []
    for subsection in (section_document.get("subsections") or {}).values():
        if isinstance(subsection, dict) and subsection.get("mediaType") == "movie":
            rows.extend(row for row in subsection.get("results") or [] if isinstance(row, dict))
    return rows


def row_tmdb_id(row: dict) -> str:
    for key in ("tmdbId", "id"):
        value = str(row.get(key) or "").strip()
        if value.isdigit():
            return value
    return ""


def build_section(section: str, document: dict, pool: Pool, limits: dict, built_at: str) -> tuple[dict, dict]:
    titles: dict[str, dict] = {}
    all_chosen: list[dict] = []
    rows = movie_rows(document)
    seen_keys: set[str] = set()
    for row in rows:
        title = str(row.get("title") or "").strip()
        tmdb_id, year = row_tmdb_id(row), year_of(row.get("year") or row.get("releaseDate"))
        if not title:
            continue
        key = f"movie:{tmdb_id}" if tmdb_id else f"ty:{normalize_title(title)}|{year}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        chosen = select_releases(pool.candidates(tmdb_id, title, year), title, limits)
        if not chosen:
            continue
        all_chosen.extend(chosen)
        titles[key] = {
            "title": title,
            "year": int(year) if year else None,
            "releases": [
                {k: v for k, v in {
                    "infoHash": r["infoHash"], "title": r["title"], "size": r["size"],
                    "seeders": r["seeders"], "leechers": r["leechers"],
                    "indexer": r["indexer"], "infoUrl": r["infoUrl"],
                }.items() if v not in ("", None)}
                for r in chosen
            ],
        }
    output = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "torrent-options",
        "section": section,
        "builtAt": built_at,
        "limits": dict(limits),
        "trackers": pick_trackers(all_chosen),
        "titles": dict(sorted(titles.items())),
    }
    report = {
        "movieRows": len(seen_keys),
        "titlesWithReleases": len(titles),
        "releases": len(all_chosen),
    }
    return output, report


def load_limits() -> dict:
    """The CACHE range (what is stored), not the display window. The display window is applied when a
    title is served (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB), so store a generous superset."""
    return {
        "minSizeBytes": int(float(os.getenv("TORRENT_CACHE_MIN_SIZE_MB", "100")) * 1024 * 1024),
        # No upper ceiling by default: any size is stored (per size band, so huge releases cannot crowd out small
        # ones) and TORRENT_MAX_SIZE_GB decides what is shown. Set TORRENT_CACHE_MAX_SIZE_GB only to cap file growth.
        "maxSizeBytes": int(float(os.getenv("TORRENT_CACHE_MAX_SIZE_GB") or 0) * 1024 ** 3) or None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "backend" / "cache-seed")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: the seed dir")
    parser.add_argument("--old-dir", type=Path, default=None, help="folder holding the old <section>-torrents.json files")
    parser.add_argument("--git-rev", default=DEFAULT_GIT_REV, help="git revision to read the old files from")
    parser.add_argument("--built-at", default=None, help="ISO timestamp to embed (default: now)")
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    out_dir = args.out_dir or args.seed_dir
    built_at = args.built_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    limits = load_limits()

    pool = Pool()
    old = load_old_phase5(pool, args.old_dir, args.git_rev)
    bolly = load_bollywood_matches(pool, args.seed_dir)
    prebuilt = load_regional_prebuilt(pool, args.seed_dir)
    print(f"pool: {old} old records + {bolly} bollywood matches + {prebuilt} prebuilt rows "
          f"-> {len(pool.releases)} unique torrents ({dict(pool.stats)})")
    top = "no upper limit" if limits["maxSizeBytes"] is None else f"{limits['maxSizeBytes'] / 1024**3:.0f} GiB"
    print(f"cache range: {limits['minSizeBytes'] / 1024**2:.0f} MiB .. {top} (display window is applied when serving)")

    failures = 0
    totals: Counter = Counter()
    for section in SECTIONS:
        path = args.seed_dir / f"{section}.json"
        if not path.is_file():
            print(f"  {section}: metadata file missing", file=sys.stderr)
            failures += 1
            continue
        document = read_json(path)
        output, report = build_section(section, document, pool, limits, built_at)
        target_existing = (out_dir / f"{section}-torrents.json")
        if target_existing.is_file():   # series packs (build_tv_torrent_cache.py) live in the same file: keep them
            previous = read_json(target_existing)
            tv = {k: v for k, v in (previous.get("titles") or {}).items() if k.startswith("tv:")} if isinstance(previous, dict) else {}
            if tv:
                output["titles"] = dict(sorted({**output["titles"], **tv}.items()))
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":"), sort_keys=False) + "\n"
        target = out_dir / f"{section}-torrents.json"
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)
        totals.update(report)
        print(f"  {section:14s} movie rows {report['movieRows']:4d}  with releases {report['titlesWithReleases']:4d}  "
              f"releases {report['releases']:5d}  file {len(text.encode()) / 1024:7.1f} KiB")
    print(f"total: {totals['titlesWithReleases']}/{totals['movieRows']} movie rows have releases, "
          f"{totals['releases']} releases kept{' (dry run, nothing written)' if args.dry_run else ''}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
