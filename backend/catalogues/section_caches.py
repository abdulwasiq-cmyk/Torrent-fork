import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from catalogues import torrent_options

router = APIRouter()
SECTION_CACHE_NAMES = frozenset({
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
})
SECTION_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache-seed"


@router.get("/api/sections/{section}")
async def api_get_section_cache(section: str) -> dict[str, Any]:
    if section not in SECTION_CACHE_NAMES:
        raise HTTPException(status_code=404, detail="Section cache not found")
    path = SECTION_CACHE_DIR / f"{section}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Section cache is not installed") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Section cache could not be read") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("section") != section
        or payload.get("metadataSelfContained") is not True
        or not isinstance(payload.get("subsections"), dict)
    ):
        raise HTTPException(status_code=500, detail="Section cache has an invalid document shape")
    return payload


@router.get("/api/sections/{section}/torrent-options")
async def api_get_torrent_options(
    section: str,
    tmdb_id: str | None = Query(None, pattern=r"^\d{1,12}$"),
    title: str | None = Query(None, min_length=1, max_length=200),
    year: str = Query("", max_length=4),
) -> dict[str, Any]:
    """Releases for ONE movie from the ``<section>-torrents.json`` files (Prepare click only).

    ``section`` is one of the nine section names, or ``all`` to search every file. The
    response mirrors /api/regional-movies/prebuilt so the Prepare card reads either one.
    Never reached by page loads or pagination: those only use /api/sections/{section}.
    """
    if section != "all" and section not in SECTION_CACHE_NAMES:
        raise HTTPException(status_code=404, detail="Section cache not found")
    if not tmdb_id and not (title and year):
        raise HTTPException(status_code=422, detail="Provide tmdb_id, or both title and year")
    rows = torrent_options.lookup(
        None if section == "all" else (section,),
        tmdb_id=tmdb_id,
        title=title,
        year=year,
    )
    if not rows:
        return {"status": "not_cached", "section": section, "torrentDetails": None}
    return {"status": "ready", "section": section, "torrentDetails": {"results": rows}}
