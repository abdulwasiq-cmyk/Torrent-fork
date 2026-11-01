"""Backend-only TorrServer adapter used by the torrent playback card."""

import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

TORRSERVER_ENABLED = os.getenv("TORRSERVER_ENABLED", "").strip().casefold() in {
    "1", "true", "yes", "on",
}
TORRSERVER_URL = os.getenv("TORRSERVER_URL", "").strip().rstrip("/")
TORRSERVER_USERNAME = os.getenv("TORRSERVER_USERNAME", "").strip()
TORRSERVER_PASSWORD = os.getenv("TORRSERVER_PASSWORD", "")
_HASH_PATTERN = re.compile(r"^[a-fA-F0-9]{40,64}$")
_STREAM_HEADERS = (
    "accept-ranges",
    "cache-control",
    "content-disposition",
    "content-length",
    "content-range",
    "content-type",
    "etag",
    "last-modified",
)


class AddTorrentRequest(BaseModel):
    magnet: str


def _ensure_enabled() -> None:
    if not TORRSERVER_ENABLED:
        raise HTTPException(status_code=404, detail="TorrServer playback is disabled.")
    if not TORRSERVER_URL:
        raise HTTPException(
            status_code=503,
            detail="Set TORRSERVER_URL to enable TorrServer playback.",
        )
    if bool(TORRSERVER_USERNAME) != bool(TORRSERVER_PASSWORD):
        raise HTTPException(
            status_code=503,
            detail="Set both TORRSERVER_USERNAME and TORRSERVER_PASSWORD, or leave both empty.",
        )


def _torrserver_auth() -> httpx.BasicAuth | None:
    if not TORRSERVER_USERNAME:
        return None
    return httpx.BasicAuth(TORRSERVER_USERNAME, TORRSERVER_PASSWORD)


def _validated_hash(value: str) -> str:
    if not _HASH_PATTERN.fullmatch(value):
        raise HTTPException(status_code=422, detail="Invalid TorrServer torrent hash.")
    return value.lower()


def _normalise_files(torrent_hash: str, file_stats: object) -> list[dict]:
    if not isinstance(file_stats, list):
        return []

    files = []
    for item in file_stats:
        if not isinstance(item, dict):
            continue
        try:
            file_id = int(item.get("id"))
            length = max(0, int(item.get("length") or 0))
        except (TypeError, ValueError):
            continue
        path = str(item.get("path") or "").strip()
        if file_id < 0 or not path:
            continue
        files.append({
            "id": file_id,
            "path": path,
            "length": length,
            "streamUrl": f"/api/torrserver/stream/{torrent_hash}/{file_id}",
        })
    return files


async def _request_torrserver(payload: dict) -> dict:
    _ensure_enabled()
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.post(
                f"{TORRSERVER_URL}/torrents",
                json=payload,
                auth=_torrserver_auth(),
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="TorrServer request timed out.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to TorrServer.") from exc

    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail=f"TorrServer returned HTTP {response.status_code}.",
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="TorrServer returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="TorrServer returned an invalid response.")
    return data


def _torrent_response(data: dict) -> dict:
    torrent_hash = _validated_hash(str(data.get("hash") or ""))
    return {
        "hash": torrent_hash,
        "title": str(data.get("title") or ""),
        "files": _normalise_files(torrent_hash, data.get("file_stats")),
        "status": str(data.get("stat_string") or ""),
    }


@router.get("/api/torrserver/status")
async def torrserver_status():
    if not TORRSERVER_ENABLED:
        return {"enabled": False}
    if not TORRSERVER_URL:
        return {
            "enabled": False,
            "error": "TorrServer is enabled but TORRSERVER_URL is missing.",
        }
    if bool(TORRSERVER_USERNAME) != bool(TORRSERVER_PASSWORD):
        return {
            "enabled": False,
            "error": "Set both TORRSERVER_USERNAME and TORRSERVER_PASSWORD, or leave both empty.",
        }
    return {"enabled": True}


@router.post("/api/torrserver/add")
async def add_torrserver_torrent(payload: AddTorrentRequest):
    _ensure_enabled()
    magnet = payload.magnet.strip()
    if len(magnet) > 8192 or not magnet.lower().startswith("magnet:?"):
        raise HTTPException(status_code=422, detail="A valid magnet URL is required.")
    data = await _request_torrserver({
        "action": "add",
        "link": magnet,
        "save_to_db": False,
    })
    return _torrent_response(data)


@router.get("/api/torrserver/torrents/{torrent_hash}")
async def get_torrserver_torrent(torrent_hash: str):
    _ensure_enabled()
    torrent_hash = _validated_hash(torrent_hash)
    data = await _request_torrserver({"action": "get", "hash": torrent_hash})
    return _torrent_response(data)


@router.delete("/api/torrserver/torrents/{torrent_hash}")
async def remove_torrserver_torrent(torrent_hash: str):
    _ensure_enabled()
    torrent_hash = _validated_hash(torrent_hash)
    await _request_torrserver({"action": "rem", "hash": torrent_hash})
    return {"removed": True}


@router.get("/api/torrserver/stream/{torrent_hash}/{file_id}")
async def stream_torrserver_file(
    torrent_hash: str,
    file_id: int,
    request: Request,
):
    _ensure_enabled()
    torrent_hash = _validated_hash(torrent_hash)
    if file_id < 0:
        raise HTTPException(status_code=422, detail="Invalid TorrServer file selection.")

    params = {"link": torrent_hash, "index": str(file_id), "play": ""}
    headers = {
        name: request.headers[name]
        for name in ("range", "if-range")
        if name in request.headers
    }
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10, read=None, write=10, pool=10),
        follow_redirects=False,
    )
    try:
        upstream_request = client.build_request(
            "GET",
            f"{TORRSERVER_URL}/stream",
            params=params,
            headers=headers,
        )
        upstream = await client.send(
            upstream_request,
            stream=True,
            auth=_torrserver_auth(),
        )
    except httpx.TimeoutException as exc:
        await client.aclose()
        raise HTTPException(status_code=504, detail="TorrServer stream request timed out.") from exc
    except httpx.HTTPError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Could not open the TorrServer stream.") from exc

    response_headers = {
        name: upstream.headers[name]
        for name in _STREAM_HEADERS
        if name in upstream.headers
    }

    async def stream_body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream.status_code,
        headers=response_headers,
    )
