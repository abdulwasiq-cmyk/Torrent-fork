#!/usr/bin/env python3
"""Add season-pack / complete-series torrents for TV and web series to the per-section files.

The nine ``backend/cache-seed/<section>-torrents.json`` files hold movie torrents (built by
migrate_torrent_cache.py). This script adds ``"tv:<tmdbId>"`` entries to the same files so
the series card can offer "Webtor": the user picks a season or the complete series, the
magnet is copied, and Webtor opens. Nothing here runs in the app; it is an offline build step
(it needs network access, so run it on the VPS):

    cd /path/to/Torrent-Studio
    python3 -I scripts/build_tv_torrent_cache.py --section hollywood --limit 5 --dry-run --debug   # look first
    python3 -I scripts/build_tv_torrent_cache.py                                          # all nine sections

It is resumable: titles that already have a ``tv:`` entry are skipped unless --refresh is given,
and each section file is rewritten atomically after every section. Movie entries are never touched.

Entry shape (same release fields as movies, plus the season scope):

    "tv:108978": {"title": "Reacher", "year": 2022, "releases": [
        {"infoHash": "...", "title": "Reacher S01 1080p ...", "size": ..., "seeders": ..., "leechers": ...,
         "indexer": "...", "infoUrl": "...", "scope": "season",   "season": 1},
        {"infoHash": "...", "title": "Reacher Complete Series ...", ..., "scope": "complete"}]}

Single episodes are dropped; only season packs and complete-series packs are kept, with no size
window (season packs are large - that is why they go to Webtor).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "backend" / "cache-seed"
SECTIONS = ("hollywood", "bollywood", "marvel", "dc", "highest-rated", "korean", "pakistani", "anime", "favourites")
PER_BUCKET = 4        # releases kept per season (or for "complete"): one per resolution first, then the best seeded
MAX_PER_SHOW = 40     # must stay <= torrent_options.MAX_TV_RESULTS
HEX40 = re.compile(r"^[0-9a-f]{40}$")

EPISODE = re.compile(r"(?:\bs\d{1,2}[ ._-]?e\d{1,3}\b|\b\d{1,2}x\d{2,3}\b|\bepisode[ ._-]?\d+\b|\be\d{2,3}\b)", re.IGNORECASE)
SEASON = re.compile(r"(?:\bs(?:eason)?[ ._-]?0*(\d{1,2})\b)", re.IGNORECASE)
MULTI_SEASON = re.compile(
    r"(?:\bs0*\d{1,2}[ ._-]?(?:-|to|&|\+)[ ._-]?s?0*\d{1,2}\b|\bseasons?[ ._-]?0*\d{1,2}[ ._-]?(?:-|to|&|\+)[ ._-]?0*\d{1,2}\b)",
    re.IGNORECASE,
)
SEASON_TOKEN = re.compile(r"\bs0*(\d{1,2})\b", re.IGNORECASE)
RESOLUTION = re.compile(r"\b(2160p|1440p|1080p|720p|576p|480p|4k|8k)\b", re.IGNORECASE)
COMPLETE = re.compile(r"\b(?:complete|full[ ._-]?series|all[ ._-]?seasons|the[ ._-]?complete)\b", re.IGNORECASE)
BAD_QUALITY = re.compile(r"\b(?:cam|hdcam|telesync|telecine|screener|workprint)\b", re.IGNORECASE)


def normalize_title(value: object) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = re.sub(r"[’']", "", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(?:the|a|an)\s+", "", text)


def year_of(value: object) -> str:
    match = re.match(r"^((?:18|19|20)\d{2})", str(value or "").strip())
    return match.group(1) if match else ""


# What may follow the show's name in a pack's release name. Anything else (a word like "and", "the", "vs")
# means the release is a LONGER title, e.g. "Wolverine and the X-Men" is not a pack of "Wolverine".
BOUNDARY = re.compile(
    r"^(?:s\d{1,2}|seasons?|complete|full|series|collection|pack|(?:19|20)\d{2}|\d{3,4}p|4k|8k|uhd|us|uk|web|webrip|dl|rip|"
    r"bluray|bdrip|brrip|hdtv|dvdrip|x264|x265|h264|h265|hevc|amzn|dsnp|nf|hmax|atvp|hdr|dv|multi|dual|hindi|english|eng)$"
)


def names_the_show(release_title: str, show_title: str) -> bool:
    """The show's name appears as a whole phrase and is followed by a season/year/quality marker (or the end)."""
    show, tokens = normalize_title(show_title).split(), normalize_title(release_title).split()
    if not show:
        return False
    for start in range(len(tokens) - len(show) + 1):
        if tokens[start:start + len(show)] == show:
            end = start + len(show)
            if end == len(tokens) or BOUNDARY.match(tokens[end]):
                return True
    return False


def classify(release_title: str, show_title: str) -> tuple[str, int] | None:
    """('complete', 0) / ('season', N) for a season or complete-series pack of this show, else None."""
    title = str(release_title or "")
    if not names_the_show(title, show_title):
        return None
    if BAD_QUALITY.search(title) or EPISODE.search(title):
        return None
    if MULTI_SEASON.search(title) or len({int(n) for n in SEASON_TOKEN.findall(title)}) >= 2:
        return ("complete", 0)
    # "Show.S01.COMPLETE" is a complete SEASON 1, not the complete series: a season number wins over the word.
    match = SEASON.search(title)
    if match and 0 < int(match.group(1)) < 100:
        return ("season", int(match.group(1)))
    if COMPLETE.search(title):
        return ("complete", 0)
    return None


def resolution_of(title: str) -> str:
    match = RESOLUTION.search(title or "")
    value = match.group(1).lower() if match else "other"
    return {"4k": "2160p", "8k": "2160p", "1440p": "1080p", "576p": "480p"}.get(value, value)


def select_releases(candidates: list[dict], show_title: str, per_bucket: int = PER_BUCKET, cap: int = MAX_PER_SHOW) -> list[dict]:
    """Per season (and per 'complete'): the best-seeded pack of each resolution, then the next best
    seeded up to ``per_bucket``. Distinct by info hash, capped per show.

    Picking by resolution first matters: the top three by seeders can all be 720p, which would hide the 1080p and 4K
    packs a user picking a quality on the card is looking for.
    """
    buckets: dict[tuple[str, int], list[dict]] = defaultdict(list)
    seen: set[str] = set()
    for item in sorted(candidates, key=lambda c: (-int(c.get("seeders") or 0), -int(c.get("leechers") or 0))):
        digest = str(item.get("infoHash") or "").lower()
        if not HEX40.match(digest) or digest in seen:
            continue
        scope = classify(item.get("title"), show_title)
        if scope is None:
            continue
        seen.add(digest)
        buckets[scope].append({**item, "infoHash": digest, "scope": scope[0], "season": scope[1]})
    ordered = sorted(buckets, key=lambda scope: (scope[0] != "complete", scope[1]))
    out: list[dict] = []
    for scope in ordered:
        rows = buckets[scope]          # already best-seeded first
        first_per_resolution: dict[str, dict] = {}
        for row in rows:
            first_per_resolution.setdefault(resolution_of(row["title"]), row)
        picked = list(first_per_resolution.values())[:per_bucket]
        picked += [row for row in rows if row not in picked][: max(0, per_bucket - len(picked))]
        out.extend(sorted(picked, key=lambda row: (-int(row.get("seeders") or 0), row["infoHash"])))
    return out[:cap]


def entry_for(show: dict, releases: list[dict]) -> dict:
    keep = ("infoHash", "title", "size", "seeders", "leechers", "indexer", "infoUrl", "scope", "season")
    return {
        "title": str(show.get("title") or ""),
        "year": int(year_of(show.get("year") or show.get("releaseDate")) or 0) or None,
        "releases": [{k: r[k] for k in keep if r.get(k) not in ("", None) and not (k == "season" and r.get("scope") == "complete")}
                     for r in releases],
    }


def tv_rows(section_document: dict) -> list[dict]:
    rows: dict[str, dict] = {}
    for subsection in (section_document.get("subsections") or {}).values():
        if not isinstance(subsection, dict) or subsection.get("mediaType") != "tv":
            continue
        for row in subsection.get("results") or []:
            if not isinstance(row, dict):
                continue
            tmdb = str(row.get("tmdbId") or row.get("id") or "").strip()
            if tmdb.isdigit() and row.get("title"):
                rows.setdefault(tmdb, row)
    return list(rows.values())


def merge_section(existing: dict, found: dict[str, dict], section: str, built_at: str) -> dict:
    """Return the section document with ``found`` tv entries merged in; movie entries are untouched."""
    document = dict(existing) if existing else {
        "schemaVersion": 2, "kind": "torrent-options", "section": section, "limits": {}, "trackers": [], "titles": {},
    }
    titles = dict(document.get("titles") or {})
    titles.update(found)
    trackers = list(document.get("trackers") or [])
    document.update({"builtAt": built_at, "titles": dict(sorted(titles.items())), "trackers": trackers})
    return document


def write_atomic(path: Path, document: dict) -> int:
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return len(text.encode())


# --------------------------------------------------------------------------- discovery
MAX_SEASONS = 15
Searcher = "Callable[[str], Awaitable[list[dict]]]"


async def discover(title: str, searcher, max_seasons: int = MAX_SEASONS, log=None) -> list[dict]:
    """Find packs for one show with targeted queries, so a long-running show's early seasons are
    not buried under thousands of episode torrents.

    ``searcher(query)`` returns raw release rows for a query string. Queries, in order:
      "<title> complete"                       the complete-series pack(s)
      "<title> S01", "<title> S02", ...        one query per season (a token match, so S01E05 episodes
                                               are not returned), falling back to "<title> Season N"
    It stops after two seasons in a row with no pack, so it adapts to the show's length.
    """
    seen: list[dict] = []
    log = log or (lambda *_: None)

    async def ask(query: str, wanted) -> int:
        rows = await searcher(query)
        hits = [r for r in rows if classify(r.get("title"), title) == wanted]
        log(query, len(rows), len(hits), [r.get("title") for r in rows if r not in hits][:3])
        # Keep only what this query was asking for. A "<title> complete" search also returns single
        # seasons of unrelated shows and stray seasons ("S07"), which must not become entries.
        seen.extend(r for r in rows if classify(r.get("title"), title) in {wanted, ("complete", 0)})
        return len(hits)

    await ask(f"{title} complete", ("complete", 0))
    misses = 0
    for number in range(1, max_seasons + 1):
        wanted = ("season", number)
        found = await ask(f"{title} S{number:02d}", wanted) or await ask(f"{title} Season {number}", wanted)
        misses = 0 if found else misses + 1
        if misses >= 2:
            break
    return seen


# --------------------------------------------------------------------------- live search (VPS only)
def make_searcher(delay: float):
    """A searcher backed by the app's own providers (needs the backend's dependencies and network)."""
    sys.path.insert(0, str(ROOT / "backend"))
    from core.shared import _MANUAL_TORRENT_SEARCH            # noqa: PLC0415 (backend only)
    from search import search_providers as providers          # noqa: PLC0415

    _MANUAL_TORRENT_SEARCH.set(True)
    providers._SIZE_WINDOW_DISABLED.set(True)                  # season packs are far above the movie size window

    async def searcher(query: str) -> list[dict]:
        rows: list[dict] = []
        try:
            # provider_query = the exact text sent to Knaben, so "Reacher S02" is a token match for season packs
            rows.extend(await providers.search_knaben(query, 150, provider_query=query))
        except Exception as exc:                               # a provider hiccup must not stop the run
            print(f"    knaben failed for {query!r}: {exc}", file=sys.stderr)
        if query.endswith(" complete"):
            try:
                rows.extend((await providers.search_apibay(query, 100)).get("results", []))
            except Exception as exc:
                print(f"    apibay failed for {query!r}: {exc}", file=sys.stderr)
        await asyncio.sleep(delay)
        return rows

    return searcher


async def run(args: argparse.Namespace) -> int:
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    totals: Counter = Counter()
    searcher = make_searcher(args.delay)
    gate = asyncio.Semaphore(max(1, args.workers))
    for section in args.section or SECTIONS:
        metadata_path = args.seed_dir / f"{section}.json"
        target = args.seed_dir / f"{section}-torrents.json"
        if not metadata_path.is_file() or not target.is_file():
            print(f"  {section}: missing metadata or torrent file", file=sys.stderr)
            return 1
        existing = json.loads(target.read_text(encoding="utf-8"))
        rows = tv_rows(json.loads(metadata_path.read_text(encoding="utf-8")))
        todo = [r for r in rows if args.refresh or f"tv:{str(r.get('tmdbId') or r.get('id'))}" not in existing.get("titles", {})]
        if args.limit:
            todo = todo[: args.limit]
        found: dict[str, dict] = {}

        async def one(index: int, show: dict) -> None:
            async with gate:
                lines: list[str] = []
                log = (lambda query, raw, hits, others: lines.append(
                    f"      {query!r}: {raw} results, {hits} packs" + (f"; e.g. {others}" if args.debug and others else ""))) \
                    if args.debug else None
                candidates = await discover(str(show["title"]), searcher, log=log)
                chosen = select_releases(candidates, str(show["title"]))
                seasons = sorted({r["season"] for r in chosen if r["scope"] == "season"})
                print(f"  {section} {index}/{len(todo)} {show['title']!r}: {len(chosen)} packs"
                      + (f" (complete: {any(r['scope'] == 'complete' for r in chosen)}, seasons: {seasons})" if chosen else ""))
                for line in lines:
                    print(line)
                if chosen:
                    found[f"tv:{show.get('tmdbId') or show.get('id')}"] = entry_for(show, chosen)

        await asyncio.gather(*(one(i, show) for i, show in enumerate(todo, 1)))
        totals.update(shows=len(rows), searched=len(todo), withPacks=len(found))
        if not args.dry_run and found:
            size = write_atomic(target, merge_section(existing, found, section, built_at))
            print(f"  {section}: wrote {len(found)} series, file now {size / 1024:.1f} KiB")
    print(f"total: {totals['withPacks']}/{totals['searched']} searched series have packs"
          f"{' (dry run, nothing written)' if args.dry_run else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed-dir", type=Path, default=SEED_DIR)
    parser.add_argument("--section", action="append", choices=SECTIONS, help="repeatable; default all nine")
    parser.add_argument("--limit", type=int, default=0, help="only the first N series per section (for a trial run)")
    parser.add_argument("--refresh", action="store_true", help="re-search series that already have an entry")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds after every provider call")
    parser.add_argument("--workers", type=int, default=3, help="series searched at the same time")
    parser.add_argument("--debug", action="store_true", help="print every query with its result and pack counts")
    parser.add_argument("--dry-run", action="store_true")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
