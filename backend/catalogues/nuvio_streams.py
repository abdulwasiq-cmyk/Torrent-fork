"""HD download links from a self-hosted Nuvio Streams add-on (https://github.com/tapframe/NuvioStreamsAddon).

The add-on is a separate Node service that runs next to this app (default http://localhost:7777). For one movie
it returns direct HTTP file links with the quality and size written in each stream's name/title. This module
asks it, turns the answer into a short list of quality options, and keeps the answer for a while because a
lookup takes 5-20 s (the add-on queries several sites).

Rules:
* Only called when a user opens a movie card (never by page loads or pagination).
* With NUVIO_URL unset, or the add-on down/slow/empty, the result is "unavailable" and the card simply
  shows no HD button.
* Links are returned percent-encoded and https-only; the browser downloads straight from the file host.

No FastAPI import here so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

MAX_OPTIONS = 12
SUCCESS_TTL_S = 20 * 60      # links may expire, so do not keep them long
EMPTY_TTL_S = 10 * 60        # remember "nothing" briefly so repeated clicks do not rescrape
MAX_CACHE_ENTRIES = 500

_QUALITY = (("2160p", re.compile(r"\b(?:2160p|4k|uhd)\b", re.I)),
            ("1080p", re.compile(r"\b1080p\b", re.I)),
            ("720p", re.compile(r"\b720p\b", re.I)),
            ("480p", re.compile(r"\b(?:480p|576p)\b", re.I)))
_RANK = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "other": 0}
_LABEL = {"2160p": "4K", "1080p": "1080p", "720p": "720p", "480p": "480p", "other": "HD"}
_SIZE = re.compile(r"([\d.]+)\s*(TB|GB|MB|KB)\b", re.I)
_UNITS = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
_TAGS = (("REMUX", re.compile(r"\bremux\b", re.I)), ("HDR", re.compile(r"\bhdr(?:10)?\+?\b", re.I)),
         ("DV", re.compile(r"\b(?:dv|dolby[ ._-]?vision)\b", re.I)), ("IMAX", re.compile(r"\bimax\b", re.I)))

Fetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_INFLIGHT: dict[str, "asyncio.Future[list[dict[str, Any]]]"] = {}


def _quality_of(text: str) -> str:
    for name, pattern in _QUALITY:
        if pattern.search(text):
            return name
    return "other"


def _size_of(text: str) -> int:
    matches = _SIZE.findall(text or "")
    if not matches:
        return 0
    number, unit = matches[-1]
    try:
        return int(float(number) * _UNITS[unit.upper()])
    except (ValueError, OverflowError):
        return 0


def safe_url(raw: str) -> str:
    """https only, spaces/brackets in the file name percent-encoded (they break plain links)."""
    try:
        parts = urlsplit(str(raw or "").strip())
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/:@%+,;=~!$&'()*-._"), parts.query, ""))


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB".replace(".0 GB", " GB")
    return f"{max(1, round(size / 1024 ** 2))} MB" if size else ""


def parse_streams(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Quality options from the add-on's ``{"streams": [...]}`` answer, best quality first, smaller files first."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stream in (payload or {}).get("streams") or []:
        if not isinstance(stream, dict):
            continue
        url = safe_url(stream.get("url"))
        if not url or url in seen:
            continue
        name, title = str(stream.get("name") or ""), str(stream.get("title") or "")
        lines = [line.strip() for line in title.splitlines() if line.strip()]
        filename = lines[0] if lines else ""
        size = _size_of(lines[-1] if len(lines) > 1 else "") or _size_of(name)
        quality = _quality_of(f"{name} {filename}")
        tags = [tag for tag, pattern in _TAGS if pattern.search(f"{name} {filename}")]
        seen.add(url)
        options.append({
            "key": str(len(options)),
            "quality": quality,
            "label": " · ".join(part for part in (_LABEL[quality], format_size(size), " ".join(tags)) if part),
            "size": size,
            "filename": filename,
            "url": url,
        })
    options.sort(key=lambda o: (-_RANK[o["quality"]], o["size"] or 1 << 60, o["filename"]))
    options = options[:MAX_OPTIONS]
    for index, option in enumerate(options):
        option["key"] = str(index)
    return options


async def http_fetcher(url: str, timeout_s: float = 45.0) -> dict[str, Any] | None:
    import httpx  # noqa: PLC0415 (only the live path needs it)

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
        return response.json() if response.status_code == 200 else None
    except Exception:  # an add-on hiccup must never break the movie card
        return None


async def lookup(
    base_url: str,
    tmdb_id: str | int,
    *,
    fetcher: Fetcher | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Quality options for one movie; ``[]`` when not configured, not found, or the add-on is unavailable."""
    base = str(base_url or "").strip().rstrip("/")
    tmdb = str(tmdb_id or "").strip()
    if not base or not tmdb.isdigit():
        return []
    cached = _CACHE.get(tmdb)
    if cached is not None and cached[0] > now():
        return cached[1]
    pending = _INFLIGHT.get(tmdb)
    if pending is not None:            # two clicks on the same title share one scrape
        return await asyncio.shield(pending)
    future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
    _INFLIGHT[tmdb] = future
    options: list[dict[str, Any]] = []
    try:
        payload = await (fetcher or http_fetcher)(f"{base}/stream/movie/tmdb:{tmdb}.json")
        options = parse_streams(payload)
        if len(_CACHE) >= MAX_CACHE_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[tmdb] = (now() + (SUCCESS_TTL_S if options else EMPTY_TTL_S), options)
        return options
    finally:
        _INFLIGHT.pop(tmdb, None)
        if not future.done():
            future.set_result(options)


def clear_cache() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


__all__ = ["clear_cache", "format_size", "lookup", "parse_streams", "safe_url"]
