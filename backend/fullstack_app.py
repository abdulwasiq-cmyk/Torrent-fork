"""Serve the built Vite frontend from the same FastAPI process.

This module imports the existing API application, then adds a final SPA
fallback route. API routes remain unchanged and continue to take precedence.
"""

import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from core.settings import SEARCH_SIZE_LIMITS_PUBLIC
from main import app

# main.py already exposes "/" as the API health endpoint. In the full-stack
# container that route would win before the SPA route below, so replace only
# that root route while leaving every other API route untouched.
app.routes[:] = [
    route
    for route in app.routes
    if not (getattr(route, "path", None) == "/" and getattr(route, "name", None) == "root")
]

FRONTEND_DIR = Path("/app/frontend-dist").resolve()
INDEX_FILE = FRONTEND_DIR / "index.html"

# The HTML entrypoint references fingerprinted Vite assets. Never let a browser
# or intermediary keep an old index.html after a deployment, or it can keep
# loading an old JavaScript bundle even when the container has been updated.
HTML_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


# The size window (TORRENT_MIN_SIZE_MB / TORRENT_MAX_SIZE_GB) reaches the browser inside index.html, so
# the frontend filter always matches the backend one and changing the setting needs only a restart.
# No extra request: the page is read and patched once per file version, then served from memory.
_index_cache: tuple[tuple[int, int], str] | None = None


def _index_html() -> str:
    global _index_cache
    stat = INDEX_FILE.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    if _index_cache is None or _index_cache[0] != signature:
        text = INDEX_FILE.read_text(encoding="utf-8")
        tag = "<script>window.__SEARCH_LIMITS__=" + json.dumps(SEARCH_SIZE_LIMITS_PUBLIC) + ";</script>"
        text = text.replace("</head>", tag + "</head>", 1) if "</head>" in text else tag + text
        _index_cache = (signature, text)
    return _index_cache[1]


def _index_response() -> HTMLResponse:
    return HTMLResponse(_index_html(), headers=HTML_NO_CACHE_HEADERS)


def _frontend_file(path: str) -> Path | None:
    candidate = (FRONTEND_DIR / path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIR)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


@app.get("/", include_in_schema=False)
async def frontend_index():
    if not INDEX_FILE.is_file():
        raise HTTPException(503, "Frontend build is not available")
    return _index_response()


@app.get("/{path:path}", include_in_schema=False)
async def frontend_spa_fallback(path: str):
    # Never turn an unknown API endpoint into an HTML response.
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")

    file_path = _frontend_file(path)
    if file_path is not None:
        return FileResponse(file_path)

    if not INDEX_FILE.is_file():
        raise HTTPException(503, "Frontend build is not available")

    # React Router/client-side routes are served by the Vite index.
    return _index_response()
