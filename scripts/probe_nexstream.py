#!/usr/bin/env python3
"""Find out which titles NexStream can actually play, before a user clicks them.

Every title in the nine top section files is asked of the running app's NexStream endpoint
(`/api/nexstream/resolve?provider=nexstream`), exactly as the player would. A title that comes
back with at least one usable source is `ok`; one with none is `none`. Series are checked on
season 1 episode 1 (a good proxy for "NexStream knows this show", not a guarantee for every episode).

Results go to `<seed>/nexstream_availability.json`, keyed "movie:<tmdbId>" / "tv:<tmdbId>", so they
survive section rebuilds. Titles checked recently are skipped. Transient problems (network, rate
limit, server error) are never recorded as "none".

  HOME_API_BASE=http://127.0.0.1:3000 REFRESH_SEED_DIR=~/torrent-studio-refresh/seed \\
      python3 scripts/probe_nexstream.py [--limit N] [--max-age-days 7] [--force] [--dry-run]

Needs the app running with NEXSTREAM_API_KEY set and CACHE_ONLY_MODE=false (the VPS app).
Set RATE_LIMIT_DISABLED=1 on the app, or keep the default delay, to stay under its 60/minute limit.
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
DELAY_SECONDS = float(os.getenv("NEXSTREAM_PROBE_DELAY_SECONDS", "1.2"))
OUTPUT_NAME = "nexstream_availability.json"
SECTION_FILES = (
    "marvel", "dc", "hollywood", "bollywood", "korean", "pakistani", "anime", "favourites", "highest-rated",
)
# The app words an empty answer like this; anything else non-200 is treated as a transient failure.
NONE_MARKERS = ("no supported player source", "could not resolve this title", "not found")


class Fatal(Exception):
    """The probe cannot continue (not configured, app down)."""


def collect_titles(seed: Path) -> dict[str, dict[str, Any]]:
    """Unique titles across all section files: {"movie:1": {"type", "tmdbId", "title"}, ...}."""
    found: dict[str, dict[str, Any]] = {}
    for section in SECTION_FILES:
        path = seed / f"{section}.json"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for node in (doc.get("subsections") or {}).values():
            for row in (node.get("results") or []) if isinstance(node, dict) else []:
                if not isinstance(row, dict):
                    continue
                raw_id = row.get("tmdbId") or row.get("id")
                media = "tv" if str(row.get("mediaType") or "").lower() in ("tv", "series") else "movie"
                if not str(raw_id or "").isdigit() or int(raw_id) <= 0:
                    continue
                key = f"{media}:{int(raw_id)}"
                found.setdefault(key, {
                    "type": media,
                    "tmdbId": int(raw_id),
                    "title": str(row.get("title") or row.get("name") or ""),
                })
    return found


def http_resolve(media: str, tmdb_id: int) -> tuple[int, str]:
    """Return (status, body text) from the app; network failures raise OSError."""
    params: dict[str, Any] = {"type": media, "tmdb_id": tmdb_id, "provider": "nexstream"}
    if media == "tv":
        params.update(season=1, episode=1)
    url = f"{API_BASE}/api/nexstream/resolve?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def classify(status: int, body: str) -> str:
    """'ok', 'none' (NexStream has nothing), or 'retry' (do not record)."""
    if status == 200:
        try:
            sources = json.loads(body).get("sources")
        except (ValueError, AttributeError):
            return "retry"
        return "ok" if isinstance(sources, list) and sources else "none"
    if status in (503, 401, 403):
        raise Fatal(f"HTTP {status}: NexStream is not configured or the key was refused. {body[:200]}")
    if status == 502:
        lowered = body.lower()
        return "none" if any(marker in lowered for marker in NONE_MARKERS) else "retry"
    return "retry"  # 429 and anything unexpected


def probe(
    titles: dict[str, dict[str, Any]],
    existing: dict[str, Any],
    resolve: Callable[[str, int], tuple[int, str]],
    *,
    now: float,
    max_age: float,
    force: bool = False,
    limit: int | None = None,
    delay: float = 0.0,
) -> dict[str, int]:
    counts = {"checked": 0, "ok": 0, "none": 0, "retry": 0, "skipped": 0}
    for key, info in titles.items():
        previous = existing.get(key)
        if not force and isinstance(previous, dict) and now - float(previous.get("checkedAt") or 0) < max_age:
            counts["skipped"] += 1
            continue
        if limit is not None and counts["checked"] >= limit:
            break
        counts["checked"] += 1
        try:
            verdict = classify(*resolve(info["type"], info["tmdbId"]))
        except (OSError, TimeoutError):
            verdict = "retry"
        counts[verdict] += 1
        if verdict != "retry":
            existing[key] = {
                "ok": verdict == "ok",
                "title": info["title"],
                "checkedAt": int(now),
            }
        if delay:
            time.sleep(delay)
    return counts


def atomic_write(path: Path, value: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="probe at most N titles this run")
    parser.add_argument("--max-age-days", type=float, default=7.0, help="skip titles checked more recently than this")
    parser.add_argument("--force", action="store_true", help="re-check everything")
    parser.add_argument("--dry-run", action="store_true", help="probe and report, do not write the file")
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")

    out_path = SEED / OUTPUT_NAME
    document: dict[str, Any] = {"schemaVersion": 1, "titles": {}}
    if out_path.is_file():
        try:
            loaded = json.loads(out_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("titles"), dict):
                document = loaded
        except ValueError:
            pass
    titles = collect_titles(SEED)
    print(json.dumps({"event": "start", "titles": len(titles), "alreadyKnown": len(document["titles"])}), flush=True)
    try:
        counts = probe(
            titles, document["titles"], http_resolve,
            now=time.time(), max_age=args.max_age_days * 86400,
            force=args.force, limit=args.limit, delay=DELAY_SECONDS,
        )
    except Fatal as exc:
        print(json.dumps({"event": "fatal", "reason": str(exc)}))
        return 2
    except KeyboardInterrupt:
        counts = {"interrupted": 1}
    known = {k: v for k, v in document["titles"].items() if k in titles}
    summary = {
        "event": "done", **counts,
        "playableTotal": sum(1 for v in known.values() if v.get("ok")),
        "unavailableTotal": sum(1 for v in known.values() if not v.get("ok")),
    }
    print(json.dumps(summary))
    if not args.dry_run:
        atomic_write(out_path, document)
        missing = sorted(v["title"] for v in known.values() if not v.get("ok"))
        print(f"Unavailable on NexStream ({len(missing)}): " + "; ".join(missing[:40]) + (" ..." if len(missing) > 40 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
