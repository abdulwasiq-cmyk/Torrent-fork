#!/usr/bin/env python3
"""Pick up titles newly added to the Classics lists, keeping everything already stored.

Movies: every listed title is searched again; torrent rows found earlier are kept when a search misses.
Web series / anime: the curated lists are resolved through TMDB and only titles missing from the stored
catalogue are added, so existing cards (and their saved details) are untouched.
Run from backend/ with APP_DATA_DIR set (scripts/refresh_seed.py does this).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogues import catalogues_extra, catalogues_tv  # noqa: E402


def title_key(row: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold())


async def rebuild_tv() -> None:
    keys = ("classics-web-series", "classics-anime")
    stored = {key: catalogues_tv._load_bundled_classics_tv_cache(key) for key in keys}
    catalogues_tv._load_bundled_classics_tv_cache = lambda key: None  # force a fresh resolve of the lists
    for key in keys:
        catalogues_tv._CLASSICS_TV_CATALOGUE_CACHE.pop(key, None)
        built = await catalogues_tv._get_classics_tv_catalogue(key)
        old = stored.get(key)
        if not old:
            continue
        have = {title_key(row) for row in old["results"]}
        added = [row for row in built["results"] if title_key(row) not in have and row.get("posterUrl")]
        # Resolved with no TMDB match at all (no poster, no overview): not worth a blank card.
        merged = {**old, "results": sorted(
            old["results"] + added,
            key=lambda row: (str(row.get("releaseDate") or row.get("year") or ""), str(row.get("title") or "")),
            reverse=True)}
        merged["totalResults"] = len(merged["results"])
        path = Path(str(catalogues_tv.DATA_DIR)) / catalogues_tv._CLASSICS_TV_CACHE_FILES[key]
        path.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{key}: {len(old['results'])} stored + {len(added)} new = {len(merged['results'])}", flush=True)


async def main() -> None:
    await catalogues_extra._build_extra_catalogue("classics")
    state = dict(catalogues_extra._extra_catalogue_states.get("classics") or {})
    print(f"classics build state: status={state.get('status')} titles={state.get('movieCount')} "
          f"rows={state.get('resultCount')} error={state.get('debugError') or state.get('error') or '-'} "
          f"cache_only={catalogues_extra.CACHE_ONLY_MODE}", flush=True)
    stored = catalogues_extra._read_extra_catalogue("classics") or {}
    kill = sorted({str(r.get("mediaTitle") or r.get("title")) for r in stored.get("results") or []
                   if "kill bill" in str(r.get("mediaTitle") or r.get("title") or "").casefold()})
    print(f"classics movies stored: {len(stored.get('results') or [])} rows; Kill Bill: {kill or 'NONE'}", flush=True)
    await diagnose_missing_titles(stored)
    await rebuild_tv()


async def diagnose_missing_titles(stored: dict) -> None:
    """For each listed title with no stored rows, run the same search and show why nothing matched."""
    config = catalogues_extra._EXTRA_CATALOGUES["classics"]
    have = {(re.sub(r"[^a-z0-9]+", "", str(r.get("catalogueTitle") or r.get("mediaTitle") or "").casefold()))
            for r in stored.get("results") or []}
    for title, year in config.get("titles", []):
        if re.sub(r"[^a-z0-9]+", "", title.casefold()) in have:
            continue
        query = f"{title} {year}".strip()
        try:
            items = await asyncio.wait_for(catalogues_extra.search_1337x(query, limit=50, allow_series_fallback=False), timeout=90)
        except Exception as exc:  # noqa: BLE001
            print(f"MISSING {title} ({year}): search failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        matched = [i for i in items if isinstance(i, dict) and catalogues_extra._marvel_result_matches_title(i, title, year)]
        print(f"MISSING {title} ({year}): search returned {len(items)}, {len(matched)} matched the title", flush=True)
        for item in items[:6]:
            print(f"    {str(item.get('title'))[:100]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
