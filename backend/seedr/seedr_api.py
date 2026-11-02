"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from core.cache_diagnostics import _InstrumentedAsyncClient
from seedr.seedr_client import (
    add_task,
    arr,
    folder_name,
    info_hash,
    legacy_seedr_list_contents,
    normalize_file,
    rename_seedr_folder,
    seedr_data,
    seedr_error_message,
    seedr_request,
    seedr_root_request,
    seedr_task_folder_id,
    seedr_task_name,
    task_complete,
    task_contents,
    task_id,
    unwrap_seedr_task,
)
from seedr.seedr_session import (
    _clear_seedr_session_token,
    _seedr_get_session,
    _seedr_session_auth_mode,
    _seedr_session_fingerprint,
    _seedr_session_token,
    current_seedr_token,
    normalize_seedr_token,
)
from core.settings import (
    DEBUG_ENDPOINTS_ENABLED,
    SEEDR_DEVICE_AUTHORIZE_URL,
    SEEDR_DEVICE_CLIENT_ID,
    SEEDR_DEVICE_CODE_URL,
    SEEDR_MEDIA_BASE,
    SEEDR_PAT_BASE,
    SEEDR_SESSION_COOKIE,
    SEEDR_V2_BASE,
    logger,
)
from core.shared import SeedrError, _seedr_request_session_id, _seedr_request_token

router = APIRouter()


# Rolling server-side byte counters for browser media streams. This is more
# reliable than Resource Timing for long-lived media responses, which browsers
# may report with transferSize=0 until the response completes.
_media_download_stats: dict[str, deque[tuple[float, int]]] = {}
_media_stats_lock = asyncio.Lock()
_MEDIA_STATS_WINDOW_SECONDS = 5.0

def _record_media_bytes(file_id: str, amount: int) -> None:
    if amount <= 0:
        return
    now = time.monotonic()
    bucket = _media_download_stats.setdefault(file_id, deque())
    bucket.append((now, amount))
    cutoff = now - _MEDIA_STATS_WINDOW_SECONDS
    while bucket and bucket[0][0] < cutoff:
        bucket.popleft()

def _media_download_speed(file_id: str) -> float:
    now = time.monotonic()
    bucket = _media_download_stats.get(file_id)
    if not bucket:
        return 0.0
    cutoff = now - _MEDIA_STATS_WINDOW_SECONDS
    while bucket and bucket[0][0] < cutoff:
        bucket.popleft()
    if not bucket:
        return 0.0
    total = sum(amount for _, amount in bucket)
    span = max(0.5, now - bucket[0][0])
    return total / span


SEEDR_FOLDER_CONCURRENCY = 8
_seedr_folder_semaphore = asyncio.Semaphore(SEEDR_FOLDER_CONCURRENCY)

# Library metadata is shared between the Files explorer and the Seedr Library
# so opening the Files tab does not trigger the same Seedr tree walk twice.
SEEDR_METADATA_CACHE_SECONDS = 5
SEEDR_FOLDER_CACHE_SECONDS = 15
_seedr_metadata_cache: tuple[float, dict[str, Any]] | None = None
_seedr_metadata_task: asyncio.Task | None = None
_seedr_folder_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_seedr_torrent_names: dict[str, str] = {}
_seedr_torrent_names_by_task: dict[str, str] = {}

SEEDR_AUTO_DELETE_SECONDS = 2 * 60 * 60
SEEDR_CLEANUP_FILE = Path("/app/.seedr_cleanup.json")
_seedr_cleanup_jobs: dict[str, dict[str, Any]] = {}
_seedr_cleanup_worker_task: asyncio.Task | None = None


def _load_seedr_cleanup_jobs() -> None:
    global _seedr_cleanup_jobs
    try:
        raw = SEEDR_CLEANUP_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            _seedr_cleanup_jobs = {
                str(k): v for k, v in data.items()
                if isinstance(v, dict) and float(v.get("deleteAt") or 0) > 0
            }
    except Exception:
        _seedr_cleanup_jobs = {}


def _save_seedr_cleanup_jobs() -> None:
    try:
        SEEDR_CLEANUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEDR_CLEANUP_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_seedr_cleanup_jobs, separators=(",", ":")), encoding="utf-8")
        tmp.replace(SEEDR_CLEANUP_FILE)
    except Exception as exc:
        logger.info("Could not persist Seedr cleanup schedule: %s", exc)


def schedule_seedr_cleanup(
    task_id_value: str,
    torrent_name: str,
    folder_id: str = "",
    added_at: float | None = None,
) -> None:
    tid = str(task_id_value or "").strip()
    if not tid:
        return

    now = time.time()
    started = float(added_at or now)
    _seedr_cleanup_jobs[tid] = {
        "taskId": tid,
        "torrentName": str(torrent_name or "").strip() or f"Torrent {tid}",
        "folderId": str(folder_id or "").strip(),
        "addedAt": started,
        "deleteAt": started + SEEDR_AUTO_DELETE_SECONDS,
    }
    _save_seedr_cleanup_jobs()


async def _cleanup_seedr_job(tid: str, job: dict[str, Any]) -> bool:
    folder_id = str(job.get("folderId") or "").strip()
    torrent_name = str(job.get("torrentName") or f"Torrent {tid}").strip()

    # Seedr may expose the folder only after the task starts.
    if not folder_id:
        try:
            raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
            task = unwrap_seedr_task(raw)
            folder_id = seedr_task_folder_id(task)
            if folder_id:
                job["folderId"] = folder_id
                _save_seedr_cleanup_jobs()
        except HTTPException as exc:
            if exc.status_code == 404:
                _seedr_cleanup_jobs.pop(tid, None)
                _save_seedr_cleanup_jobs()
                return True
            return False
        except Exception:
            return False

    if not folder_id or not folder_id.isdigit() or folder_id == "0":
        return False

    # Stop the Seedr task first so an active transfer cannot keep rebuilding
    # files while the folder is being removed.
    try:
        await seedr_request(f"/tasks/{quote(tid)}", "DELETE")
    except HTTPException as exc:
        if exc.status_code != 404:
            logger.info("Seedr task cleanup failed for %s: HTTP %s", tid, exc.status_code)
            return False
    except Exception as exc:
        logger.info("Seedr task cleanup failed for %s: %s", tid, exc)
        return False

    try:
        await seedr_folder_delete(folder_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            logger.info("Seedr folder cleanup failed for %s (%s): HTTP %s", torrent_name, folder_id, exc.status_code)
            return False
    except Exception as exc:
        logger.info("Seedr folder cleanup failed for %s (%s): %s", torrent_name, folder_id, exc)
        return False

    _seedr_cleanup_jobs.pop(tid, None)
    _save_seedr_cleanup_jobs()
    logger.info("Auto-deleted Seedr torrent after 2 hours: %s (task=%s folder=%s)", torrent_name, tid, folder_id)
    return True


async def _seedr_cleanup_worker() -> None:
    while True:
        try:
            now = time.time()
            due = [
                (tid, job)
                for tid, job in list(_seedr_cleanup_jobs.items())
                if float(job.get("deleteAt") or 0) <= now
            ]
            for tid, job in due:
                await _cleanup_seedr_job(tid, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Seedr cleanup worker error: %s", exc)
        await asyncio.sleep(30)


async def collect_folder(folder_id: str, path: str = "/", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 8:
        return []

    async with _seedr_folder_semaphore:
        try:
            payload = seedr_data(await seedr_request(f"/fs/folder/{quote(folder_id)}/contents"))
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise

    if not isinstance(payload, dict):
        return []

    files: list[dict[str, Any]] = []
    for raw in arr(payload, ("files", "items")):
        item = normalize_file(raw, folder_id)
        item["folderPath"] = path
        item["url"] = None
        files.append(item)

    child_jobs: list[asyncio.Future] = []
    for raw in arr(payload, ("folders", "directories")):
        child_id = str(raw.get("id") or raw.get("folder_id") or "") if isinstance(raw, dict) else ""
        if not child_id:
            continue

        child_name = (
            str(raw.get("name") or raw.get("title") or child_id)
            if isinstance(raw, dict)
            else child_id
        )
        child_path = path.rstrip("/") + "/" + child_name
        child_jobs.append(collect_folder(child_id, child_path, depth + 1))

    if child_jobs:
        children = await asyncio.gather(*child_jobs, return_exceptions=True)
        for child in children:
            if isinstance(child, list):
                files.extend(child)

    return files

def _safe_download_filename(filename: str, fallback: str) -> str:
    value = str(filename or "").strip().replace("\r", "").replace("\n", "")
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:240] or fallback


async def _stream_seedr_download(url: str):
    client = _InstrumentedAsyncClient(timeout=None, follow_redirects=True)
    request = client.build_request("GET", url, headers={"Accept": "*/*"})
    response = await client.send(request, stream=True)

    if response.status_code >= 400:
        try:
            detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
        finally:
            await response.aclose()
            await client.aclose()
        raise HTTPException(response.status_code, detail or "Seedr download request failed")

    content_type = response.headers.get("content-type") or "application/octet-stream"
    content_length = response.headers.get("content-length")
    content_range = response.headers.get("content-range")

    async def body():
        try:
            async for chunk in response.aiter_bytes(1024 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    headers = {
        "Content-Disposition": "",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
        "Cache-Control": "no-store",
    }
    if content_length:
        headers["Content-Length"] = content_length
    if content_range:
        headers["Content-Range"] = content_range

    return body, content_type, headers


async def download_url(file_id: str) -> dict[str, str]:
    payload = seedr_data(await seedr_request(f"/download/file/{quote(file_id)}/url"))
    if isinstance(payload, dict):
        url = str(payload.get("url") or payload.get("download_url") or payload.get("downloadUrl") or payload.get("direct_url") or "")
        name = str(payload.get("name") or payload.get("filename") or "")
    else:
        url, name = str(payload or ""), ""
    if not url:
        raise HTTPException(502, "Seedr did not return a download URL")
    return {"url": url, "name": name}

def _srt_to_webvtt(text: str) -> str:
    """Convert a UTF-8/legacy SRT subtitle into browser-compatible WebVTT."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = normalized.split("\n")
    output = ["WEBVTT", ""]
    for line in lines:
        if "-->" in line:
            line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
        output.append(line)
    result = "\n".join(output)
    return result if result.endswith("\n") else result + "\n"


async def _seedr_subtitle_text(file_id: str, filename: str) -> tuple[str, str]:
    result = await download_url(file_id)
    url = result["url"]
    lower = (filename or result.get("name") or "").lower()
    async with _InstrumentedAsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        raw = response.content

    if lower.endswith(".vtt"):
        text = raw.decode("utf-8-sig", errors="replace")
        if not text.lstrip().startswith("WEBVTT"):
            text = _srt_to_webvtt(text)
    elif lower.endswith(".srt"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        text = _srt_to_webvtt(text)
    else:
        raise HTTPException(415, "Only SRT and WebVTT subtitle files are supported")
    return text, "text/vtt; charset=utf-8"


@router.get("/api/seedr/files/{file_id}/subtitle")
async def seedr_file_subtitle(
    file_id: str,
    filename: str = Query(""),
):
    """Proxy a Seedr SRT/VTT file as WebVTT for the browser <track> element."""
    text, content_type = await _seedr_subtitle_text(file_id, filename)
    return Response(
        content=text,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


async def start_seedr_cleanup_worker():
    global _seedr_cleanup_worker_task
    _load_seedr_cleanup_jobs()
    if _seedr_cleanup_worker_task is None or _seedr_cleanup_worker_task.done():
        _seedr_cleanup_worker_task = asyncio.create_task(_seedr_cleanup_worker())


@router.get("/api/seedr/session")
async def seedr_session(request: Request):
    """Initialize the browser session quickly; provider health checks happen on demand."""
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)
    # Session bootstrap must not wait on Seedr. The CSRF token is needed before
    # the browser can submit a PAT, and a slow provider must not cause POST 403s.
    # Actual token/API failures are reported by the operation the user requests.
    return {
        "connected": bool(current_seedr_token()),
        "csrfToken": str(session.get("csrf_token") or ""),
    }


async def _validate_seedr_pat(token: str) -> None:
    """Validate a Seedr PAT sequentially; avoid bursts of concurrent auth requests."""
    token = normalize_seedr_token(token)
    if not token:
        raise SeedrError("SEEDR_PAT_MISSING", 400, "A Seedr Personal Access Token is required.")

    endpoints = (
        f"{SEEDR_PAT_BASE}/user",
        f"{SEEDR_PAT_BASE}/tasks",
        f"{SEEDR_PAT_BASE}/fs/root/contents",
        f"{SEEDR_V2_BASE}/tasks",
        f"{SEEDR_V2_BASE}/fs/root/contents",
    )
    outcomes: list[str] = []
    saw_unauthorized = False
    timeout = httpx.Timeout(8.0, connect=3.0)

    # The endpoints have been verified to accept the current PAT when called
    # individually. Do not fan out concurrently: concurrent probes previously
    # all failed at the transport layer despite these same endpoints succeeding
    # when tested one at a time. Stop on the first 2xx response.
    async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in endpoints:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                logger.info(
                    "Seedr PAT validation transport error: endpoint=%s error=%s",
                    url,
                    type(exc).__name__,
                )
                outcomes.append(f"{url}=transport:{type(exc).__name__}")
                continue

            if 200 <= response.status_code < 300:
                logger.info(
                    "Seedr PAT validation succeeded: endpoint=%s status=%s",
                    url,
                    response.status_code,
                )
                return

            if response.status_code == 401:
                saw_unauthorized = True
                outcomes.append(f"{url}=401")
                continue

            if response.status_code in {403, 404, 405}:
                outcomes.append(f"{url}={response.status_code}")
                continue

            try:
                payload = response.json() if response.content else {}
                reason = str(
                    payload.get("error_description")
                    or payload.get("reason_phrase")
                    or payload.get("message")
                    or payload.get("error")
                    or ""
                ).strip() if isinstance(payload, dict) else ""
            except (ValueError, TypeError):
                reason = ""

            # Retry the next known API variant for transient/provider-specific
            # errors rather than concluding the token is invalid prematurely.
            outcomes.append(f"{url}=HTTP{response.status_code}")
            logger.info(
                "Seedr PAT validation endpoint returned HTTP %s: endpoint=%s reason=%s",
                response.status_code,
                url,
                reason[:160],
            )

    logger.warning(
        "Seedr PAT validation found no successful endpoint: %s",
        ", ".join(outcomes),
    )
    if saw_unauthorized and not any("transport:" in row for row in outcomes):
        raise SeedrError(
            "SEEDR_PAT_REJECTED",
            401,
            "Seedr rejected the Personal Access Token. Copy a fresh PAT from Seedr and try again.",
        )

    raise SeedrError(
        "SEEDR_PAT_VALIDATION_FAILED",
        502,
        "Could not validate the Seedr token using the account API. Please retry shortly.",
    )


@router.post("/api/seedr/connect/pat")
async def seedr_connect_pat(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)

    try:
        payload = await request.json()
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        raise HTTPException(400, "Request body must be JSON.")

    raw_pat = payload.get("pat") or payload.get("token")
    if not isinstance(raw_pat, str):
        raise HTTPException(400, "A Seedr Personal Access Token is required.")

    pat = normalize_seedr_token(raw_pat)
    if not pat:
        raise HTTPException(400, "A Seedr Personal Access Token is required.")

    await _validate_seedr_pat(pat)

    session["access_token"] = pat
    session["refresh_token"] = ""
    session["token_type"] = "Bearer"
    session["auth_mode"] = "pat"
    session["device"] = None
    session["last_seen"] = time.time()

    logger.info(
        "Seedr PAT connected: session=%s token_length=%s",
        _seedr_session_fingerprint(session_id),
        len(pat),
    )
    return {"status": "connected", "connected": True}


@router.post("/api/seedr/connect/start")
async def seedr_connect_start(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)

    logger.info(
        "Seedr connect start: session=%s cookie_present=%s has_device=%s has_token=%s",
        _seedr_session_fingerprint(session_id),
        bool(request.cookies.get(SEEDR_SESSION_COOKIE)),
        bool(isinstance(session.get("device"), dict)),
        bool(_seedr_session_token(session_id)),
    )

    token = current_seedr_token()
    if token:
        return {"status": "connected", "connected": True}

    try:
        async with _InstrumentedAsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(
                SEEDR_DEVICE_CODE_URL,
                params={"client_id": SEEDR_DEVICE_CLIENT_ID},
                headers={"Accept": "application/json"},
            )
        raw = response.text
        try:
            data = response.json() if raw else {}
        except Exception:
            data = {}

        if response.status_code >= 400 or not isinstance(data, dict):
            detail = seedr_error_message(response.status_code, data, raw)
            raise SeedrError("SEEDR_DEVICE_CODE_FAILED", 502, detail)

        device_code = str(data.get("device_code") or data.get("deviceCode") or "").strip()
        user_code = str(data.get("user_code") or data.get("userCode") or "").strip()
        verification_url = str(
            data.get("verification_url")
            or data.get("verificationUrl")
            or "https://www.seedr.cc/devices"
        ).strip()
        expires_in = int(float(data.get("expires_in") or data.get("expiresIn") or 900))

        if not device_code or not user_code:
            raise SeedrError(
                "SEEDR_DEVICE_CODE_INVALID",
                502,
                "Seedr returned an incomplete device authorization response.",
            )

        session["device"] = {
            "device_code": device_code,
            "user_code": user_code,
            "verification_url": verification_url,
            "expires_at": time.time() + max(60, expires_in),
            "created_at": time.time(),
        }
        session["last_seen"] = time.time()

        poll_interval = int(float(data.get("interval") or 5))
        poll_interval = max(2, min(30, poll_interval))
        session["device"]["interval"] = poll_interval
        logger.info(
            "Seedr connect start stored device: session=%s expires_in=%s interval=%s",
            _seedr_session_fingerprint(session_id),
            expires_in,
            poll_interval,
        )
        return {
            "status": "pending",
            "connected": False,
            "userCode": user_code,
            "verificationUrl": verification_url,
            "expiresIn": expires_in,
            "interval": poll_interval,
        }
    except SeedrError:
        raise
    except Exception as exc:
        logger.warning("Seedr device-code request failed: %s", exc)
        raise SeedrError(
            "SEEDR_DEVICE_CODE_FAILED",
            502,
            "Could not start Seedr account authorization right now.",
        ) from exc


def _extract_seedr_access_token(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("access_token", "accessToken", "token"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                normalized = normalize_seedr_token(candidate)
                if normalized:
                    return normalized

        for key in ("data", "result", "response"):
            nested = payload.get(key)
            token = _extract_seedr_access_token(nested)
            if token:
                return token
    return ""


@router.get("/api/seedr/connect/status")
async def seedr_connect_status(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)
    token = _seedr_session_token(session_id)
    device = session.get("device")

    logger.info(
        "Seedr connect status: session=%s cookie_present=%s has_device=%s has_token=%s",
        _seedr_session_fingerprint(session_id),
        bool(request.cookies.get(SEEDR_SESSION_COOKIE)),
        bool(isinstance(device, dict)),
        bool(token),
    )

    if token:
        try:
            token_ctx = _seedr_request_token.set(token)
            try:
                await seedr_request("/user")
            finally:
                _seedr_request_token.reset(token_ctx)
            session["device"] = None
            return {"status": "connected", "connected": True}
        except SeedrError as exc:
            if exc.status_code == 401:
                _clear_seedr_session_token(session_id)
            else:
                return {"status": "pending", "connected": False}

    device = session.get("device")
    if not isinstance(device, dict):
        return {
            "status": "error",
            "connected": False,
            "code": "SEEDR_SESSION_LOST",
            "message": "The Seedr connection session was lost. Start the connection again.",
        }

    expires_at = float(device.get("expires_at") or 0)
    if expires_at and time.time() >= expires_at:
        session["device"] = None
        return {
            "status": "expired",
            "connected": False,
            "message": "The Seedr authorization code expired. Start a new connection.",
        }

    device_code = str(device.get("device_code") or "").strip()
    if not device_code:
        session["device"] = None
        return {
            "status": "error",
            "connected": False,
            "message": "Seedr did not provide a usable device code.",
        }

    try:
        async with _InstrumentedAsyncClient(timeout=10, follow_redirects=True) as client:
            # Seedr's device authorization endpoint expects the original
            # device_code. The current Seedr client implementations pass only
            # device_code here; do not add client_id to this request.
            response = await client.get(
                SEEDR_DEVICE_AUTHORIZE_URL,
                params={"device_code": device_code},
                headers={"Accept": "application/json"},
            )

        raw = response.text
        try:
            data = response.json() if raw else {}
        except Exception:
            data = {}

        access_token = _extract_seedr_access_token(data)
        logger.info(
            "Seedr device authorization poll: http=%s token_present=%s error=%s message=%s",
            response.status_code,
            bool(access_token),
            str(data.get("error") or data.get("code") or "")[:120] if isinstance(data, dict) else "",
            str(
                (data.get("error_description") or data.get("message") or data.get("error") or "")
                if isinstance(data, dict) else ""
            )[:200],
        )
        if access_token:
            refresh_token = ""
            token_type = "Bearer"
            if isinstance(data, dict):
                refresh_token = str(data.get("refresh_token") or data.get("refreshToken") or "").strip()
                token_type = str(data.get("token_type") or "Bearer").strip() or "Bearer"
                for key in ("data", "result", "response"):
                    nested = data.get(key)
                    if isinstance(nested, dict):
                        refresh_token = refresh_token or str(
                            nested.get("refresh_token") or nested.get("refreshToken") or ""
                        ).strip()
                        token_type = str(nested.get("token_type") or token_type).strip() or token_type

            session["access_token"] = access_token
            session["refresh_token"] = refresh_token
            session["token_type"] = token_type
            session["device"] = None
            session["last_seen"] = time.time()

            token_ctx = _seedr_request_token.set(access_token)
            try:
                await seedr_request("/user")
            except SeedrError:
                _clear_seedr_session_token(session_id)
                raise
            finally:
                _seedr_request_token.reset(token_ctx)

            return {"status": "connected", "connected": True}

        error_code = ""
        error_message = ""
        if isinstance(data, dict):
            error_code = str(data.get("error") or data.get("code") or "").strip().lower()
            error_message = str(
                data.get("error_description")
                or data.get("message")
                or data.get("error")
                or ""
            ).strip()

        pending = (
            response.status_code in {400, 409, 428}
            and (
                not error_code
                or "pending" in error_code
                or "authorize" in error_code
                or "not_authorized" in error_code
                or "not approved" in error_message.lower()
            )
        )
        if pending:
            return {
                "status": "pending",
                "connected": False,
                "expiresIn": max(0, int(expires_at - time.time())),
                "interval": max(2, min(30, int(float(device.get("interval") or 5)))),
            }

        if response.status_code >= 400:
            if response.status_code == 401:
                session["device"] = None
                return {
                    "status": "error",
                    "connected": False,
                    "message": "Seedr rejected this authorization request.",
                }
            return {
                "status": "error",
                "connected": False,
                "message": error_message or seedr_error_message(response.status_code, data, raw),
            }

        return {
            "status": "pending",
            "connected": False,
            "expiresIn": max(0, int(expires_at - time.time())),
        }
    except SeedrError:
        raise
    except Exception as exc:
        logger.info("Seedr device authorization poll failed: %s", exc)
        return {
            "status": "pending",
            "connected": False,
            "expiresIn": max(0, int(expires_at - time.time())),
        }


@router.post("/api/seedr/connect/disconnect")
async def seedr_connect_disconnect(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    _clear_seedr_session_token(session_id)
    return {"status": "disconnected", "connected": False}


@router.get("/api/seedr/token-diagnostic")
async def seedr_token_diagnostic():
    if not current_seedr_token():
        return {
            "configured": False,
            "code": "SEEDR_TOKEN_MISSING",
            "tokenLength": 0,
            "tokenFingerprint": None,
            "checks": {},
        }

    token = normalize_seedr_token(current_seedr_token())
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else None

    async def check(path: str) -> dict[str, Any]:
        try:
            await seedr_request(path)
            return {"ok": True, "status": 200}
        except SeedrError as exc:
            return {"ok": False, "status": exc.status_code, "code": exc.code, "message": exc.detail}
        except Exception as exc:
            return {"ok": False, "status": 0, "code": "LOCAL_ERROR", "message": str(exc)[:200]}

    result: dict[str, Any] = {
        "configured": True,
        "code": "SEEDR_TOKEN_PRESENT",
        "checks": {
            "user": await check("/tasks" if _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat" else "/user"),
        },
    }
    if DEBUG_ENDPOINTS_ENABLED:
        # Token metadata is only returned when debugging is explicitly enabled.
        result["tokenLength"] = len(token)
        result["tokenFingerprint"] = fingerprint
    return result


@router.get("/api/seedr/auth-status")
async def seedr_auth_status():
    if not current_seedr_token():
        return {
            "configured": False,
            "authenticated": False,
            "code": "SEEDR_TOKEN_MISSING",
            "message": "Seedr API token is not configured in Render.",
        }

    try:
        # The old working integration treats a successful /user call as the
        # authentication test. Do the same here; /user is explicitly documented
        # by Seedr for Bearer-authenticated requests.
        await seedr_request(
            "/tasks" if _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat" else "/user"
        )
        return {
            "configured": True,
            "authenticated": True,
            "code": "SEEDR_AUTH_OK",
        }
    except SeedrError as exc:
        return {
            "configured": True,
            "authenticated": False,
            "code": exc.code,
            "message": exc.detail,
        }


@router.get("/api/seedr/quota")
async def seedr_quota():
    if not current_seedr_token():
        return {"configured": False, "maxSpace": 0, "usedSpace": 0, "remainingSpace": 0}

    try:
        is_pat = _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat"
        result = seedr_data(await seedr_request("/fs/root/contents" if is_pat else "/user"))
        storage = result.get("account", {}).get("storage", {}) if isinstance(result, dict) else {}
        if not isinstance(storage, dict):
            storage = result.get("storage", {}) if isinstance(result, dict) else {}
        result_dict = result if isinstance(result, dict) else {}
        if is_pat:
            max_space = int(float(
                result_dict.get("space_max", 0)
                or result_dict.get("max_space", 0)
                or result_dict.get("maxSpace", 0)
                or storage.get("limit", 0)
            ))
            used = int(float(
                result_dict.get("space_used", 0)
                or result_dict.get("used_space", 0)
                or result_dict.get("usedSpace", 0)
                or storage.get("used", 0)
            ))
        else:
            max_space = int(float(
                storage.get("limit")
                or storage.get("max_space")
                or storage.get("maxSpace")
                or result_dict.get("max_space", 0)
                or result_dict.get("space_max", 0)
                or 0
            ))
            used = int(float(
                storage.get("used")
                or storage.get("used_space")
                or storage.get("usedSpace")
                or result_dict.get("used_space", 0)
                or result_dict.get("space_used", 0)
                or 0
            ))
    except SeedrError:
        raise
    except Exception as exc:
        logger.warning("Seedr quota parsing failed: %s", exc)
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            503,
            "Seedr account storage information is temporarily unavailable.",
        ) from exc

    if not (max_space > 0) or used < 0 or used > max_space:
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            503,
            "Seedr account storage information is temporarily unavailable.",
        )

    return {
        "configured": True,
        "maxSpace": max_space,
        "usedSpace": used,
        "remainingSpace": max(0, max_space - used),
    }

async def _prepare_seedr_space(
    required_bytes: int,
    *,
    force_one: bool = False,
) -> list[dict[str, Any]]:
    """Free old completed Seedr folders; optionally force at least one deletion after a quota rejection."""
    required = max(0, int(required_bytes or 0))
    if required <= 0:
        return []

    quota = await seedr_quota()
    remaining = int(quota.get("remainingSpace") or 0)
    if remaining >= required and not force_one:
        return []

    library = await get_seedr_metadata_tree(force_refresh=True)
    folders = [
        folder for folder in (library.get("folders") or [])
        if isinstance(folder, dict)
        and str(folder.get("folderId") or folder.get("id") or "").strip()
        and str(folder.get("folderId") or folder.get("id") or "").strip() != "0"
    ]

    # Prefer actual Seedr task timestamps so the oldest completed torrent is
    # removed first. Fall back to the library order when a provider response
    # does not expose a timestamp.
    task_meta: dict[str, dict[str, Any]] = {}
    active_folder_ids: set[str] = set()
    try:
        tasks_payload = seedr_data(await seedr_request("/tasks"))
        for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
            task = unwrap_seedr_task(seedr_data(raw_task))
            if not task:
                continue
            folder_id = seedr_task_folder_id(task)
            if not folder_id:
                continue
            if not task_complete(task):
                active_folder_ids.add(str(folder_id))
            task_meta[str(folder_id)] = task
    except (HTTPException, SeedrError):
        pass

    def task_timestamp(task: dict[str, Any]) -> float:
        for key in (
            "created_at", "createdAt", "created", "added_at", "addedAt",
            "time_added", "timeAdded", "timestamp", "date_added", "dateAdded",
        ):
            value = task.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value if value < 10_000_000_000 else value / 1000)
            if isinstance(value, str) and value.strip():
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return parsed.timestamp()
                except Exception:
                    continue
        return 0.0

    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for index, folder in enumerate(folders):
        folder_id = str(folder.get("folderId") or folder.get("id") or "").strip()
        if not folder_id or folder_id in active_folder_ids:
            continue
        task = task_meta.get(folder_id, {})
        candidates.append((index, task_timestamp(task), folder))

    candidates.sort(key=lambda item: (item[1] if item[1] > 0 else float("inf"), item[0]))

    deleted: list[dict[str, Any]] = []
    for _, _, folder in candidates:
        if remaining >= required and (not force_one or deleted):
            break

        folder_id = str(folder.get("folderId") or folder.get("id") or "").strip()
        folder_name = str(folder.get("torrentName") or folder.get("name") or folder_id).strip()
        folder_size = max(0, int(float(folder.get("totalSize") or 0)))

        try:
            await seedr_request(f"/fs/folder/{quote(folder_id)}", "DELETE")
            deleted.append({
                "folderId": folder_id,
                "name": folder_name,
                "size": folder_size,
            })
            remaining += folder_size
            _seedr_folder_cache.pop(folder_id, None)
        except (HTTPException, SeedrError) as exc:
            logger.warning(
                "Seedr automatic cleanup skipped folder=%s status=%s detail=%s",
                folder_id,
                getattr(exc, "status_code", 0),
                getattr(exc, "detail", str(exc)),
            )

    global _seedr_metadata_cache
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()

    if remaining < required:
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            413,
            "Seedr does not have enough space for this torrent, even after removing older completed files.",
        )

    logger.info(
        "Seedr automatic cleanup freed=%s required=%s deleted=%s",
        sum(int(item.get("size") or 0) for item in deleted),
        required,
        len(deleted),
    )
    return deleted


@router.post("/api/seedr/add")
async def seedr_add(request: Request):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    # Direct Seedr mode:
    # validate without changing the input, then forward that exact string.
    try:
        payload = await request.json()
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        raise HTTPException(400, "Request body must be JSON.")

    raw_magnet = payload.get("magnet")
    if not isinstance(raw_magnet, str) or not raw_magnet:
        raise HTTPException(400, "A magnet link is required.")

    if not info_hash(raw_magnet):
        raise HTTPException(400, "A valid BTIH magnet link is required")

    requested_folder = str(payload.get("folder_id") or "").strip()
    folder = int(requested_folder) if requested_folder.isdigit() else 0
    auto_cleanup = bool(payload.get("auto_cleanup"))
    required_bytes = max(0, int(float(payload.get("required_bytes") or 0)))

    session_id = _seedr_request_session_id.get().strip()
    logger.info(
        "Seedr add start: session=%s mode=%s magnet_length=%s magnet_info_hash=%s "
        "requested_folder=%s resolved_folder=%s",
        _seedr_session_fingerprint(session_id),
        _seedr_session_auth_mode(session_id),
        len(raw_magnet),
        info_hash(raw_magnet),
        requested_folder or "<none>",
        folder,
    )

    # Treat every new Seedr add as replacing the prior unfinished transfer.
    # Do not depend on frontend localStorage/current-notice state: an old task
    # may still exist after a page refresh or backend/container restart.
    replace_task_id = str(payload.get("replace_task_id") or "").strip()
    cancelled_tasks = await _cancel_active_seedr_tasks_for_replacement(replace_task_id)

    deleted_folders: list[dict[str, Any]] = [
        {
            "folderId": str(item.get("folderId") or ""),
            "name": str(item.get("name") or "Cancelled Seedr task"),
            "size": max(0, int(item.get("size") or 0)),
        }
        for item in cancelled_tasks
        if item.get("folderDeleted") and str(item.get("folderId") or "").strip()
    ]
    if auto_cleanup and required_bytes > 0:
        deleted_folders.extend(await _prepare_seedr_space(required_bytes))

    try:
        task = unwrap_seedr_task(await add_task(raw_magnet, folder))
    except SeedrError as exc:
        reason = str(exc.detail or "").lower()
        is_storage_shortage = (
            exc.status_code == 413
            or "not enough space" in reason
            or "insufficient storage" in reason
            or "insufficient space" in reason
        )
        if not (is_storage_shortage and auto_cleanup and required_bytes > 0):
            logger.exception(
                "Seedr add failed: session=%s mode=%s code=%s status=%s detail=%s",
                _seedr_session_fingerprint(session_id),
                _seedr_session_auth_mode(session_id),
                exc.code,
                exc.status_code,
                exc.detail,
            )
            raise

        # Seedr can reject a new magnet even when its quota endpoint appears to
        # have enough free bytes (for example, while an old transfer is stuck
        # reserving space). Cancelled tasks are already removed; now delete at
        # least one oldest completed folder and retry the same requested magnet
        # exactly once.
        logger.warning(
            "Seedr reported insufficient space after preflight; reclaiming one more completed folder before retry: required=%s",
            required_bytes,
        )
        deleted_folders.extend(await _prepare_seedr_space(required_bytes, force_one=True))
        try:
            task = unwrap_seedr_task(await add_task(raw_magnet, folder))
        except SeedrError as retry_exc:
            logger.exception(
                "Seedr retry after storage cleanup failed: session=%s code=%s status=%s detail=%s",
                _seedr_session_fingerprint(session_id),
                retry_exc.code,
                retry_exc.status_code,
                retry_exc.detail,
            )
            raise
    except Exception as exc:
        logger.exception(
            "Seedr add unexpected failure: session=%s mode=%s exception_type=%s exception=%s",
            _seedr_session_fingerprint(session_id),
            _seedr_session_auth_mode(session_id),
            type(exc).__name__,
            str(exc)[:2000],
        )
        raise
    tid = task_id(task)
    if not tid:
        raise HTTPException(502, "Seedr did not return a task id")

    task_folder_id = seedr_task_folder_id(task)
    task_name = seedr_task_name(task) or f"Torrent {tid}"
    schedule_seedr_cleanup(str(tid), task_name, task_folder_id)

    logger.info(
        "Seedr add success: session=%s mode=%s task_id=%s folder_id=%s task_name=%s",
        _seedr_session_fingerprint(session_id),
        _seedr_session_auth_mode(session_id),
        tid,
        task_folder_id or "<none>",
        task_name[:300],
    )

    return {
        "backend": "seedr",
        "task_id": int(tid) if tid.isdigit() else tid,
        "id": int(tid) if tid.isdigit() else tid,
        "torrent_name": task_name,
        "folder_id": task_folder_id,
        "deleted_folders": deleted_folders,
        "cancelled_tasks": cancelled_tasks,
    }

def _seedr_file_folder_id(files: list[dict[str, Any]]) -> str:
    """Return the actual torrent folder id exposed by completed file rows."""
    for file in files:
        folder_id = str(file.get("folderId") or "").strip()
        if folder_id:
            return folder_id
    return ""


def _seedr_effective_task_folder_id(
    task: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
) -> str:
    """Prefer the created torrent folder over the destination parent folder."""
    task_folder_id = seedr_task_folder_id(task)
    file_folder_id = _seedr_file_folder_id(files or [])

    if file_folder_id and (
        not task_folder_id
        or file_folder_id != task_folder_id
        or task_folder_id == "0"
    ):
        return file_folder_id
    return task_folder_id


def _remember_seedr_cleanup_folder(tid: str, folder_id: str) -> None:
    folder_id = str(folder_id or "").strip()
    if not folder_id:
        return
    job = _seedr_cleanup_jobs.get(str(tid).strip())
    if not job:
        return
    if str(job.get("folderId") or "").strip() == folder_id:
        return
    job["folderId"] = folder_id
    _save_seedr_cleanup_jobs()


@router.get("/api/seedr/tasks/{tid}/progress")
async def seedr_task_progress(tid: str):
    """Fast polling endpoint: only fetch task state/progress from Seedr."""
    try:
        raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
    except HTTPException as exc:
        if exc.status_code == 404:
            return {
                "taskId": tid,
                "status": "not_found",
                "progress": 0,
                "name": "",
                "folderId": "",
            }
        raise

    task = (
        raw.get("task")
        if isinstance(raw, dict) and isinstance(raw.get("task"), dict)
        else (raw if isinstance(raw, dict) else {})
    )
    progress = float(task.get("progress") or 0)
    complete = task_complete(task)
    if complete:
        progress = 100

    state = str(task.get("state") or task.get("status") or "").lower()
    status = "completed" if complete else (
        "waiting" if state in {"queued", "pending", "waiting", "paused", "stopped"} else "downloading"
    )

    task_folder_id = seedr_task_folder_id(task)
    completed_files: list[dict[str, Any]] = []
    if complete:
        try:
            completed_files = await task_contents(tid)
        except (HTTPException, SeedrError):
            completed_files = []

    effective_folder_id = _seedr_effective_task_folder_id(task, completed_files)
    task_id_value = str(tid).strip()

    canonical_name = str(
        _seedr_torrent_names_by_task.get(task_id_value)
        or _seedr_torrent_names.get(effective_folder_id)
        or seedr_task_name(task)
        or ""
    ).strip()

    if effective_folder_id and canonical_name:
        _seedr_torrent_names[effective_folder_id] = canonical_name
        if complete:
            _remember_seedr_cleanup_folder(task_id_value, effective_folder_id)
        # Seedr can expose the folder only after the task starts. Rename at
        # that point, rather than only immediately after /tasks POST.
        # Do not call Seedr folder-management endpoints from the free-account
        # progress path. The task state itself is sufficient for polling.

    seedr_task_display_name = canonical_name
    return {
        "taskId": tid,
        "status": status,
        "progress": progress,
        "name": seedr_task_display_name,
        "folderId": effective_folder_id,
    }

@router.get("/api/seedr/tasks/{tid}")
async def seedr_task(tid: str):
    try:
        raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"taskId": tid, "status": "not_found", "progress": 0, "files": [], "downloadUrl": None}
        raise
    task = raw.get("task") if isinstance(raw, dict) and isinstance(raw.get("task"), dict) else (raw if isinstance(raw, dict) else {})
    progress = float(task.get("progress") or 0)
    complete = task_complete(task)
    if complete:
        progress = 100
    files = await task_contents(tid)
    folder_id = _seedr_effective_task_folder_id(task, files)
    _remember_seedr_cleanup_folder(str(tid).strip(), folder_id)
    task_id_value = str(tid).strip()
    canonical_name = str(
        _seedr_torrent_names_by_task.get(task_id_value)
        or _seedr_torrent_names.get(folder_id)
        or seedr_task_name(task)
        or ""
    ).strip()
    if folder_id and canonical_name:
        previous_name = _seedr_torrent_names.get(folder_id)
        _seedr_torrent_names[folder_id] = canonical_name
        if previous_name != canonical_name:
            try:
                await rename_seedr_folder(folder_id, canonical_name)
            except Exception:
                pass
            global _seedr_metadata_cache
            _seedr_metadata_cache = None
    folderNameValue = canonical_name or (await folder_name(folder_id) if folder_id else "")
    for f in files:
        f["folderPath"] = "/Torrent Studio" + ("/" + folderNameValue if folderNameValue else "")
        # Do not resolve direct Seedr URLs while polling/finalizing a task.
        # A fresh URL is generated only by an explicit download/copy/stream action.
        f["url"] = None
    return {"taskId": tid, "name": str(task.get("title") or task.get("name") or ""), "folderName": folderNameValue, "folderId": folder_id, "status": "completed" if complete else "downloading", "progress": progress, "task": task, "files": files, "downloadUrl": None}

async def seedr_folder_payload(folder_id: str) -> dict[str, Any]:
    """Fetch one Seedr folder level, with a short-lived in-process cache."""
    folder_id = str(folder_id).strip()
    if not folder_id:
        return {}

    now = asyncio.get_running_loop().time()
    cached = _seedr_folder_cache.get(folder_id)
    if cached and now - cached[0] < SEEDR_FOLDER_CACHE_SECONDS:
        return cached[1]

    async with _seedr_folder_semaphore:
        # Re-check after waiting for the semaphore so concurrent callers do
        # not issue duplicate Seedr requests for the same folder.
        now = asyncio.get_running_loop().time()
        cached = _seedr_folder_cache.get(folder_id)
        if cached and now - cached[0] < SEEDR_FOLDER_CACHE_SECONDS:
            return cached[1]

        try:
            # Root access is inconsistent across Seedr API variants/accounts.
            # Prefer the normal bearer-authenticated filesystem endpoint, then
            # fall back to the dedicated root endpoint and finally the legacy
            # list_contents endpoint. A failure in one variant must not be
            # presented as a token failure when another variant works.
            if folder_id == "0":
                root_errors: list[str] = []

                try:
                    payload = seedr_data(await seedr_request("/fs/folder/0/contents"))
                    logger.info("Seedr library root resolved via bearer fs endpoint")
                except (HTTPException, SeedrError) as exc:
                    root_errors.append(f"fs:{getattr(exc, 'status_code', 0)}")
                    try:
                        payload = seedr_data(await seedr_root_request())
                        logger.info("Seedr library root resolved via dedicated root endpoint")
                    except (HTTPException, SeedrError) as root_exc:
                        root_errors.append(f"root:{getattr(root_exc, 'status_code', 0)}")
                        try:
                            payload = seedr_data(await legacy_seedr_list_contents("0"))
                            logger.info("Seedr library root resolved via legacy list_contents endpoint")
                        except (HTTPException, SeedrError) as legacy_exc:
                            root_errors.append(f"legacy:{getattr(legacy_exc, 'status_code', 0)}")
                            logger.warning(
                                "Seedr library root resolution failed across all API variants: %s",
                                ",".join(root_errors),
                            )
                            raise legacy_exc
            else:
                payload = seedr_data(await seedr_request(f"/fs/folder/{quote(folder_id)}/contents"))
        except HTTPException as exc:
            if exc.status_code == 404:
                return {}
            raise

    result = payload if isinstance(payload, dict) else {}
    _seedr_folder_cache[folder_id] = (asyncio.get_running_loop().time(), result)
    return result


def direct_folder_summary(folder_id: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    files = arr(payload, ("files", "items"))
    folders = arr(payload, ("folders", "directories"))
    total_size = 0
    valid_files = 0
    for raw in files:
        if not isinstance(raw, dict):
            continue
        try:
            size = int(float(raw.get("size") or 0))
        except Exception:
            size = 0
        total_size += max(0, size)
        if str(raw.get("id") or raw.get("file_id") or "").strip():
            valid_files += 1

    return {
        "id": str(folder_id),
        "folderId": str(folder_id),
        "name": Path(path.rstrip("/")).name or "Root Files",
        "path": path,
        "filesCount": valid_files,
        "totalSize": total_size,
        "folderCount": len([x for x in folders if isinstance(x, dict)]),
    }


async def build_seedr_metadata_tree(
    folder_id: str,
    path: str,
    folder_name_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Build the first library response from the root and its immediate child
    folders. Child contents are fetched concurrently so folder cards already
    have exact file counts/sizes when the browser receives this response.
    """
    folder_name_overrides = folder_name_overrides or {}
    payload = await seedr_folder_payload(folder_id)
    summary = direct_folder_summary(folder_id, path, payload)

    child_entries: list[tuple[str, str, dict[str, Any]]] = []
    for raw in arr(payload, ("folders", "directories")):
        if not isinstance(raw, dict):
            continue
        child_id = str(raw.get("id") or raw.get("folder_id") or "").strip()
        if not child_id:
            continue
        folder_override = str(folder_name_overrides.get(child_id) or "").strip()
        child_name = (
            folder_override
            or str(raw.get("name") or raw.get("title") or child_id).strip()
            or child_id
        )
        child_path = path.rstrip("/") + "/" + child_name
        child_entries.append((child_id, child_name, raw))

    async def load_child(entry: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
        child_id, child_name, raw = entry
        child_payload = await seedr_folder_payload(child_id)

        # Older Seedr folders can be exposed with their raw 40-character
        # identifier as the visible name. For a single-file torrent we can
        # recover the human title from the actual file name and normalize the
        # folder once, so existing downloads also get fixed on refresh.
        effective_child_name = child_name
        child_files = arr(child_payload, ("files", "items"))
        if (
            re.fullmatch(r"[0-9a-fA-F]{40}", effective_child_name)
            and len(child_files) == 1
            and isinstance(child_files[0], dict)
        ):
            raw_file_name = str(
                child_files[0].get("name")
                or child_files[0].get("title")
                or ""
            ).strip()
            inferred_name = Path(raw_file_name.replace("\\", "/")).name
            inferred_name = Path(inferred_name).stem.strip()
            if inferred_name:
                try:
                    renamed = await rename_seedr_folder(child_id, inferred_name)
                except Exception:
                    renamed = False
                _seedr_torrent_names[child_id] = inferred_name
                effective_child_name = inferred_name
                if renamed:
                    logger.info(
                        "Renamed legacy hash-named Seedr folder %s to %s",
                        child_id,
                        inferred_name,
                    )

        child_summary = direct_folder_summary(
            child_id,
            path.rstrip("/") + "/" + effective_child_name,
            child_payload,
        )

        # Some Seedr responses expose size/count directly on the folder item;
        # use those only when the contents endpoint did not provide a value.
        if child_summary["filesCount"] == 0:
            for key in ("files_count", "file_count", "filesCount", "fileCount", "count"):
                value = raw.get(key)
                if value is not None:
                    try:
                        child_summary["filesCount"] = max(0, int(value))
                        break
                    except (TypeError, ValueError):
                        pass

        if child_summary["totalSize"] == 0:
            for key in ("size", "total_size", "totalSize"):
                value = raw.get(key)
                if value is not None:
                    try:
                        child_summary["totalSize"] = max(0, int(float(value)))
                        break
                    except (TypeError, ValueError):
                        pass

        child_summary["torrentName"] = (
            _seedr_torrent_names.get(child_id)
            or folder_name_overrides.get(child_id)
            or (effective_child_name if re.fullmatch(r"[0-9a-fA-F]{40}", child_name) is None else "")
            or ""
        )
        child_summary["folderCount"] = len(
            [x for x in arr(child_payload, ("folders", "directories")) if isinstance(x, dict)]
        )
        return child_summary

    children: list[dict[str, Any]] = []
    if child_entries:
        results = await asyncio.gather(
            *(load_child(entry) for entry in child_entries),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, dict):
                children.append(result)

    # The top-level library badge represents all files in its visible torrent
    # folders, not just files placed directly in the root.
    summary["filesCount"] += sum(int(item.get("filesCount") or 0) for item in children)
    summary["totalSize"] += sum(int(item.get("totalSize") or 0) for item in children)
    summary["folderCount"] = len(children)

    return summary, children


async def get_seedr_metadata_tree(force_refresh: bool = False) -> dict[str, Any]:
    global _seedr_metadata_cache, _seedr_metadata_task

    if not current_seedr_token():
        return {"configured": False, "root": None, "folders": []}

    now = asyncio.get_running_loop().time()

    if force_refresh:
        # A completed Seedr task can become visible in the filesystem a few
        # seconds after the metadata cache was populated. Clear both caches so
        # the completion flow can see the new folder immediately.
        _seedr_metadata_cache = None
        _seedr_folder_cache.clear()

    if _seedr_metadata_cache and now - _seedr_metadata_cache[0] < SEEDR_METADATA_CACHE_SECONDS:
        return _seedr_metadata_cache[1]

    if _seedr_metadata_task is not None and not _seedr_metadata_task.done():
        return await _seedr_metadata_task

    async def build() -> dict[str, Any]:
        # Seedr's account root is exposed through a dedicated endpoint.
        # Keep SEEDR_LIBRARY_FOLDER_ID as an optional override for deployments
        # that want to start from a specific existing folder.
        root = "0"

        # Resolve human-readable torrent names from Seedr task metadata in one
        # call. The folder contents/counts and task list are independent, so
        # fetch them concurrently without adding a serial round trip.
        folder_name_overrides: dict[str, str] = dict(_seedr_torrent_names)
        task_folders: list[tuple[str, str]] = []
        try:
            tasks_payload = seedr_data(await seedr_request("/tasks"))
            for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
                task = unwrap_seedr_task(seedr_data(raw_task))
                if not task:
                    continue

                task_folder_id = seedr_task_folder_id(task)
                task_name = seedr_task_name(task)

                if task_folder_id:
                    task_folders.append((task_folder_id, task_name))

                if task_folder_id and task_name:
                    # The title supplied by our search/add flow is canonical.
                    # Seedr's task title can contain provider/site prefixes
                    # (for example "www.UIndex.org - ..."), so never let task
                    # metadata overwrite an existing canonical title.
                    if task_folder_id not in _seedr_torrent_names:
                        _seedr_torrent_names[task_folder_id] = task_name
                    folder_name_overrides[task_folder_id] = (
                        _seedr_torrent_names.get(task_folder_id) or task_name
                    )
        except (HTTPException, SeedrError):
            # Folder metadata remains usable even when task-name lookup fails.
            pass

        try:
            root_summary, children = await build_seedr_metadata_tree(
                root,
                "/Torrent Studio",
                folder_name_overrides,
            )
        except (HTTPException, SeedrError) as exc:
            # Some Seedr tokens can authenticate and manage transfers while
            # denying the account-root filesystem listing. Do not turn that
            # provider limitation into a library-wide error. Reconstruct the
            # visible library from the task list and each task's own contents.
            if getattr(exc, "status_code", 0) not in {401, 403}:
                raise

            # First collect folder IDs from the task list. Seedr may expose
            # the created folder only after a task has started/completed, so
            # also resolve task contents below when the task object has no
            # folder_created_id.
            task_candidates: list[dict[str, Any]] = []
            try:
                tasks_payload = seedr_data(await seedr_request("/tasks"))
                for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
                    task = unwrap_seedr_task(seedr_data(raw_task))
                    if task:
                        task_candidates.append(task)
            except (HTTPException, SeedrError):
                task_candidates = []

            unique_folders: dict[str, str] = {}

            for task in task_candidates:
                tid = task_id(task)
                task_name = (
                    seedr_task_name(task)
                    or (folder_name_overrides.get(seedr_task_folder_id(task)) if seedr_task_folder_id(task) else "")
                    or f"Torrent {tid}"
                ).strip()
                folder_id = seedr_task_folder_id(task)

                # If the task itself does not expose its created folder, the
                # task contents endpoint often does. This is the same endpoint
                # already used by the completion/progress flow.
                if tid and (not folder_id or folder_id == "0"):
                    try:
                        task_files = await task_contents(tid)
                        folder_id = _seedr_file_folder_id(task_files)
                    except (HTTPException, SeedrError):
                        folder_id = ""

                if folder_id and folder_id != root:
                    unique_folders.setdefault(
                        folder_id,
                        folder_name_overrides.get(folder_id)
                        or _seedr_torrent_names.get(folder_id)
                        or task_name
                        or folder_id,
                    )

            # Preserve any folder IDs already learned from task metadata.
            for folder_id, task_name in task_folders:
                if folder_id and folder_id != root:
                    unique_folders.setdefault(
                        folder_id,
                        folder_name_overrides.get(folder_id)
                        or _seedr_torrent_names.get(folder_id)
                        or task_name
                        or folder_id,
                    )

            async def load_task_folder(folder_id: str, name: str) -> dict[str, Any] | None:
                try:
                    payload = await seedr_folder_payload(folder_id)
                except (HTTPException, SeedrError):
                    return None
                if not payload:
                    return None
                summary = direct_folder_summary(
                    folder_id,
                    "/Torrent Studio/" + name,
                    payload,
                )
                summary["torrentName"] = name
                summary["folderCount"] = len(
                    [x for x in arr(payload, ("folders", "directories")) if isinstance(x, dict)]
                )
                return summary

            if unique_folders:
                results = await asyncio.gather(
                    *(load_task_folder(folder_id, name) for folder_id, name in unique_folders.items()),
                    return_exceptions=True,
                )
                children = [result for result in results if isinstance(result, dict)]
            else:
                children = []

            # A denied root listing is a capability limitation, not an
            # authentication failure. Returning an empty but valid library
            # keeps Search/Prepare/Stream usable even for an account with no
            # folders exposed through the token.
            root_summary = {
                "id": root,
                "folderId": root,
                "name": "Torrent Studio",
                "path": "/Torrent Studio",
                "filesCount": sum(int(item.get("filesCount") or 0) for item in children),
                "totalSize": sum(int(item.get("totalSize") or 0) for item in children),
                "folderCount": len(children),
            }

        return {
            "configured": True,
            "root": root_summary,
            "folders": children,
        }

    _seedr_metadata_task = asyncio.create_task(build())
    try:
        result = await _seedr_metadata_task
        _seedr_metadata_cache = (asyncio.get_running_loop().time(), result)
        return result
    finally:
        _seedr_metadata_task = None


@router.get("/api/seedr/library")
async def seedr_library_metadata(fresh: bool = Query(False)):
    return await get_seedr_metadata_tree(force_refresh=fresh)


@router.get("/api/seedr/folders/{folder_id}/contents")
async def seedr_folder_contents(folder_id: str):
    if not current_seedr_token():
        return {"configured": False, "folderId": folder_id, "files": [], "folders": []}

    payload = await seedr_folder_payload(folder_id)
    files: list[dict[str, Any]] = []
    for raw in arr(payload, ("files", "items")):
        file = normalize_file(raw, folder_id)
        file["url"] = None
        files.append(file)

    folders: list[dict[str, Any]] = []
    for raw in arr(payload, ("folders", "directories")):
        if not isinstance(raw, dict):
            continue
        child_id = str(raw.get("id") or raw.get("folder_id") or "").strip()
        if not child_id:
            continue
        child_name = str(raw.get("name") or raw.get("title") or child_id).strip() or child_id
        folders.append({"id": child_id, "folderId": child_id, "name": child_name})

    return {"configured": True, "folderId": folder_id, "files": files, "folders": folders}


@router.get("/api/seedr/files")
async def seedr_files():
    # Backwards-compatible full file endpoint. New UI code uses
    # /api/seedr/library + /api/seedr/folders/{id}/contents instead.
    if not current_seedr_token():
        return {"configured": False, "files": []}

    root = "0"

    result = await collect_folder(root, "/Torrent Studio")
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        item_id = str(item.get("id") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            unique.append(item)

    return {"configured": True, "files": unique}

@router.get("/api/seedr/files/{file_id}/download/url")
async def seedr_file_download_url(file_id: str):
    # Resolve a fresh direct Seedr URL only when the user explicitly requests it.
    return await download_url(file_id)

@router.get("/api/seedr/files/{file_id}/download")
async def seedr_file_download(file_id: str):
    # Redirect the browser to Seedr's temporary direct URL so large downloads
    # do not flow through the Render Free instance.
    result = await download_url(file_id)
    return RedirectResponse(result["url"], status_code=307)


@router.get("/api/seedr/files/{file_id}/download/direct")
async def seedr_file_download_direct(
    file_id: str,
    filename: str = Query(""),
):
    """Stream a Seedr file with an explicit browser download filename."""
    result = await download_url(file_id)
    filename_value = _safe_download_filename(
        filename or result.get("name") or "",
        f"seedr-file-{file_id}",
    )
    body, content_type, headers = await _stream_seedr_download(result["url"])
    ascii_name = filename_value.encode("ascii", errors="ignore").decode("ascii").strip() or f"seedr-file-{file_id}"
    headers["Content-Disposition"] = (
        'attachment; filename="' + ascii_name.replace('"', "_") + '"'
        + "; filename*=UTF-8''" + quote(filename_value, safe="")
    )
    return StreamingResponse(
        body(),
        media_type=content_type,
        headers=headers,
    )


async def seedr_folder_download_url(folder_id: str) -> str:
    folder_id = str(folder_id or "").strip()
    if not folder_id or not folder_id.isdigit():
        raise HTTPException(400, "Invalid Seedr folder id")

    # Known-good Torrent Studio implementation:
    # initialize a temporary archive and let Seedr return the signed URL.
    archive_id = str(uuid.uuid4())
    payload = seedr_data(
        await seedr_request(
            f"/download/archive/init/{quote(archive_id)}",
            "PUT",
            {"archive_arr": [{"type": "folder", "id": int(folder_id)}]},
        )
    )

    if isinstance(payload, dict):
        url = str(
            payload.get("url")
            or payload.get("download_url")
            or payload.get("downloadUrl")
            or payload.get("signed_url")
            or payload.get("signedUrl")
            or ""
        ).strip()
    elif isinstance(payload, str):
        url = payload.strip()
    else:
        url = ""

    if not url:
        raise HTTPException(502, "Seedr did not return a folder download URL")
    return url


@router.get("/api/seedr/folders/{folder_id}/download/url")
async def seedr_folder_download_url_api(folder_id: str):
    # Resolve the temporary direct Seedr folder URL only on an explicit click.
    url = await seedr_folder_download_url(folder_id)
    return {"url": url}

@router.get("/api/seedr/folders/{folder_id}/download")
async def seedr_folder_download(folder_id: str):
    # Redirect the browser to Seedr's temporary direct folder URL rather than
    # streaming the archive through Render.
    url = await seedr_folder_download_url(folder_id)
    return RedirectResponse(url, status_code=307)


@router.get("/api/seedr/folders/{folder_id}/download/direct")
async def seedr_folder_download_direct(
    folder_id: str,
    filename: str = Query(""),
):
    """Stream a Seedr folder archive with an explicit .zip filename."""
    url = await seedr_folder_download_url(folder_id)
    filename_value = _safe_download_filename(
        filename,
        f"seedr-folder-{folder_id}.zip",
    )
    if not filename_value.lower().endswith(".zip"):
        filename_value += ".zip"

    body, content_type, headers = await _stream_seedr_download(url)
    ascii_name = filename_value.encode("ascii", errors="ignore").decode("ascii").strip() or f"seedr-folder-{folder_id}.zip"
    headers["Content-Disposition"] = (
        'attachment; filename="' + ascii_name.replace('"', "_") + '"'
        + "; filename*=UTF-8''" + quote(filename_value, safe="")
    )
    return StreamingResponse(
        body(),
        media_type=content_type or "application/zip",
        headers=headers,
    )

# HLS stream sources are kept server-side. The browser receives a same-origin
# manifest URL so the Seedr access token never needs to be exposed to the client.
SEEDR_HLS_CACHE_SECONDS = 600
_seedr_hls_sources: dict[str, tuple[float, str, set[str]]] = {}


def _seedr_media_url(file_id: str, media_type: str) -> str:
    if media_type == "video":
        endpoint = f"/media/hls/{quote(file_id)}"
    elif media_type == "audio":
        endpoint = f"/media/mp3/{quote(file_id)}"
    else:
        raise HTTPException(400, "Unsupported Seedr media type")
    return SEEDR_MEDIA_BASE.rstrip("/") + endpoint + "?access_token=" + quote(current_seedr_token(), safe="")

def seedr_v2_bearer_token() -> str:
    """Accept a raw Seedr PAT or MediaFusion-style base64 JSON token."""
    raw = current_seedr_token().strip()
    if not raw:
        return ""
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        payload = json.loads(decoded)
        token = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
        if token:
            return token
    except Exception:
        pass
    return raw


async def seedr_v2_request(path: str) -> Any:
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")
    bearer = seedr_v2_bearer_token()
    if not bearer:
        raise HTTPException(503, "Seedr access token is empty")
    url = SEEDR_V2_BASE.rstrip("/") + "/" + str(path).lstrip("/")
    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
        )
    raw = response.text
    try:
        data = response.json() if raw else None
    except Exception:
        data = raw
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            seedr_error_message(response.status_code, data, raw),
        )
    return data

async def seedr_v2_video_url(file_id: str, audio_index: int | None = None) -> str:
    """Use Seedr V2 current presentation URL, with direct-download fallback."""
    if not file_id:
        return ""
    try:
        presentation_path = f"/presentations/file/{quote(file_id)}/video"
        if audio_index is not None and audio_index >= 0:
            presentation_path += "?" + urlencode({"audio": str(audio_index)})
        payload = seedr_data(await seedr_v2_request(presentation_path))
        if isinstance(payload, dict):
            link = payload.get("link")
            link_url = link.get("url") if isinstance(link, dict) else ""
            url = str(payload.get("url") or payload.get("stream_url") or link_url or "").strip()
            if url.startswith(("http://", "https://")):
                return url
    except HTTPException:
        pass

    try:
        payload = seedr_data(await seedr_v2_request(f"/download/file/{quote(file_id)}/url"))
        if isinstance(payload, dict):
            url = str(payload.get("url") or payload.get("download_url") or "").strip()
            if url.startswith(("http://", "https://")):
                return url
    except HTTPException:
        pass

    return ""


def _absolute_hls_uri(base_url: str, uri: str) -> str:
    absolute = urljoin(base_url, uri)
    # Some HLS manifests use one access query string on the playlist URL and
    # omit it from relative segment/variant URLs. Carry it forward.
    if not urlsplit(uri).query:
        base_query = urlsplit(base_url).query
        if base_query and not urlsplit(absolute).query:
            absolute += "?" + base_query
    return absolute


def _encode_hls_target(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_hls_target(value: str) -> str:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding).decode("utf-8")
    except Exception as exc:
        raise HTTPException(400, "Invalid HLS resource token") from exc


def _rewrite_hls_manifest(file_id: str, manifest_text: str, base_url: str) -> str:
    lines = manifest_text.splitlines()
    rewritten: list[str] = []

    def proxy_url(absolute: str) -> str:
        return "/api/seedr/hls/" + quote(file_id, safe="") + "/resource?u=" + _encode_hls_target(absolute)

    for line in lines:
        current = line
        def replace_uri(match: re.Match[str]) -> str:
            uri = match.group(1)
            return 'URI="' + proxy_url(_absolute_hls_uri(base_url, uri)) + '"'
        current = re.sub(r'URI="([^"]+)"', replace_uri, current)

        stripped = current.strip()
        if stripped and not stripped.startswith("#"):
            current = proxy_url(_absolute_hls_uri(base_url, stripped))
        rewritten.append(current)

    return "\n".join(rewritten) + ("\n" if manifest_text.endswith("\n") else "")


async def _presentation_is_hls(url: str) -> bool:
    """Probe a Seedr presentation URL without downloading the full media file."""
    if not url:
        return False
    try:
        async with _InstrumentedAsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*", "Range": "bytes=0-2047"})
        content_type = str(response.headers.get("content-type") or "").lower()
        prefix = response.content[:2048].decode("utf-8", errors="ignore")
        return "mpegurl" in content_type or "#EXTM3U" in prefix
    except Exception as exc:
        logger.info("Seedr presentation probe failed: %s", exc)
        return False


async def _fetch_seedr_hls_manifest(file_id: str) -> tuple[str, str]:
    """Resolve a browser-playable HLS manifest from Seedr V2, then v1 fallback."""
    candidates: list[str] = []
    presentation_url = await seedr_v2_video_url(file_id)
    if presentation_url:
        candidates.append(presentation_url)
    # Seedr's legacy HLS endpoint explicitly requests a converted browser stream.
    candidates.append(_seedr_media_url(file_id, "video"))

    last_detail = "Seedr did not return an HLS manifest"
    for upstream_url in dict.fromkeys(candidates):
        try:
            async with _InstrumentedAsyncClient(timeout=35, follow_redirects=True) as client:
                response = await client.get(
                    upstream_url,
                    headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*"},
                )
            if response.status_code >= 400:
                last_detail = response.text[:500] or f"Seedr returned HTTP {response.status_code}"
                continue

            content_type = str(response.headers.get("content-type") or "").lower()
            text = response.text
            if "#EXTM3U" not in text[:200]:
                last_detail = f"Seedr returned {content_type or 'non-HLS content'}"
                continue

            final_url = str(response.url)
            host = urlsplit(final_url).hostname or ""
            if not host:
                last_detail = "Seedr returned an invalid HLS URL"
                continue

            allowed_hosts = {host.lower()}
            for raw_uri in re.findall(r'(?:URI="([^"]+)"|^([^#\s][^\r\n]*))', text, flags=re.M):
                uri = raw_uri[0] or raw_uri[1]
                if uri:
                    try:
                        ref_host = urlsplit(_absolute_hls_uri(final_url, uri)).hostname
                        if ref_host:
                            allowed_hosts.add(ref_host.lower())
                    except Exception:
                        pass

            _seedr_hls_sources[file_id] = (
                asyncio.get_running_loop().time() + SEEDR_HLS_CACHE_SECONDS,
                final_url,
                allowed_hosts,
            )
            logger.info("Seedr HLS manifest resolved: file=%s source=%s", file_id, urlsplit(final_url).hostname)
            return text, final_url
        except Exception as exc:
            last_detail = str(exc)
            continue

    raise HTTPException(502, last_detail)

async def _get_hls_source(file_id: str) -> tuple[str, set[str]]:
    now = asyncio.get_running_loop().time()
    cached = _seedr_hls_sources.get(file_id)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    _manifest, final_url = await _fetch_seedr_hls_manifest(file_id)
    cached = _seedr_hls_sources[file_id]
    return final_url, cached[2]


async def resolve_seedr_stream_id(file_id: str, name: str = "") -> str:
    """Resolve the Seedr playback file identifier without requiring HLS."""
    candidate = str(file_id or "").strip()
    if candidate:
        try:
            presentation = await seedr_v2_video_url(candidate)
            if presentation:
                return candidate
        except HTTPException:
            pass
        try:
            await _fetch_seedr_hls_manifest(candidate)
            return candidate
        except HTTPException:
            pass

    if not name:
        raise HTTPException(404, "Seedr playback file could not be resolved")

    try:
        result = seedr_data(await seedr_request(f"/search/fs?query={quote(name)}"))
    except HTTPException as exc:
        raise HTTPException(exc.status_code, "Seedr file lookup failed") from exc

    candidates = arr(result, ("files", "items"))
    wanted_name = Path(name).name.lower()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        raw_name = str(raw.get("name") or raw.get("title") or "").strip()
        if raw_name.lower() != wanted_name:
            continue

        # Match MediaFusion: Seedr V2 playback uses the actual file id.
        resolved = str(
            raw.get("id")
            or raw.get("file_id")
            or raw.get("folder_file_id")
            or raw.get("folderFileId")
            or ""
        ).strip()
        if not resolved:
            continue

        try:
            await _fetch_seedr_hls_manifest(resolved)
            logger.info("Seedr playback id resolved by filename: %s -> %s", name, resolved)
            return resolved
        except HTTPException:
            continue

    raise HTTPException(404, f"No playable Seedr stream found for {name}")


@router.get("/api/seedr/files/stream")
async def seedr_file_stream(
    file_id: str = Query(""),
    type: str = Query("video"),
    name: str = Query(""),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    resolved_id = await resolve_seedr_stream_id(file_id, name)

    if type == "video":
        # Restore the tested direct-browser-stream strategy from
        # fix-seedr-direct-browser-stream:
        #   1) ask Seedr V2 for its presentation URL;
        #   2) if it is a browser-playable direct presentation, proxy it with
        #      Range support;
        #   3) otherwise use the existing HLS proxy.
        presentation_url = await seedr_v2_video_url(resolved_id)
        if presentation_url and not await _presentation_is_hls(presentation_url):
            return {
                "url": "/api/seedr/media/video/" + quote(resolved_id, safe=""),
                "externalUrl": presentation_url,
                "name": name or resolved_id,
                "resolvedFileId": resolved_id,
                "protocol": "direct",
            }

        try:
            await _fetch_seedr_hls_manifest(resolved_id)
            return {
                "url": "/api/seedr/hls/" + quote(resolved_id, safe=""),
                "externalUrl": presentation_url or _seedr_media_url(resolved_id, "video"),
                "name": name or resolved_id,
                "resolvedFileId": resolved_id,
                "protocol": "hls",
            }
        except HTTPException:
            if presentation_url:
                return {
                    "url": "/api/seedr/media/video/" + quote(resolved_id, safe=""),
                    "externalUrl": presentation_url,
                    "name": name or resolved_id,
                    "resolvedFileId": resolved_id,
                    "protocol": "direct",
                }
            raise

    return {
        "url": "/api/seedr/media/audio/" + quote(resolved_id, safe=""),
        "externalUrl": _seedr_media_url(resolved_id, "audio"),
        "name": name or resolved_id,
        "resolvedFileId": resolved_id,
        "protocol": "mp3",
    }

@router.get("/api/seedr/hls/{file_id}")
async def seedr_hls_manifest(file_id: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    manifest, final_url = await _fetch_seedr_hls_manifest(file_id)
    cached = _seedr_hls_sources.get(file_id)
    allowed_hosts = cached[2] if cached else {urlsplit(final_url).hostname.lower()}
    rewritten = _rewrite_hls_manifest(file_id, manifest, final_url)

    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/seedr/hls/{file_id}/resource")
async def seedr_hls_resource(request: Request, file_id: str, u: str = Query(...)):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    target = _decode_hls_target(u)
    parsed = urlsplit(target)
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(400, "Invalid HLS target URL")

    try:
        base_url, allowed_hosts = await _get_hls_source(file_id)
    except HTTPException:
        raise

    if host not in allowed_hosts:
        raise HTTPException(403, "HLS resource host is not allowed")

    headers: dict[str, str] = {"Accept": "*/*"}
    if request is not None:
        range_header = request.headers.get("range")
        if range_header:
            headers["Range"] = range_header

    async with _InstrumentedAsyncClient(timeout=35, follow_redirects=True) as client:
        response = await client.get(target, headers=headers)

    if response.status_code >= 400:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    content_type = str(response.headers.get("content-type") or "").lower()
    body = response.content
    _record_media_bytes(file_id, len(body))

    if "mpegurl" in content_type or "#EXTM3U" in body[:200].decode("utf-8", errors="ignore"):
        text = body.decode("utf-8", errors="replace")
        final_url = str(response.url)
        final_host = urlsplit(final_url).hostname
        if final_host:
            allowed_hosts.add(final_host.lower())
        _seedr_hls_sources[file_id] = (
            asyncio.get_running_loop().time() + SEEDR_HLS_CACHE_SECONDS,
            final_url,
            allowed_hosts,
        )
        body = _rewrite_hls_manifest(file_id, text, final_url).encode("utf-8")
        content_type = "application/vnd.apple.mpegurl"

    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
    }
    for header in ("content-range", "content-length", "etag", "last-modified"):
        if response.headers.get(header):
            response_headers[header.title()] = response.headers[header]

    return Response(
        content=body,
        status_code=response.status_code,
        media_type=content_type or "application/octet-stream",
        headers=response_headers,
    )


async def _seedr_media_source_url(file_id: str) -> str:
    result = await download_url(file_id)
    url = str(result.get("url") or "").strip()
    if not url:
        raise HTTPException(502, "Seedr returned no media URL")
    return url


_SEEDR_FFPROBE_CACHE_SECONDS = 600
_seedr_ffprobe_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def _ffprobe_seedr_file(file_id: str) -> dict[str, Any]:
    """Inspect a Seedr file and reuse the result for media/subtitle requests.

    The same MKV was previously probed once for track discovery and then probed
    again when the user selected an embedded subtitle. Reusing the probe keeps
    Render Free from doing the expensive remote MKV inspection twice.
    """
    now = asyncio.get_running_loop().time()
    cached = _seedr_ffprobe_cache.get(file_id)
    if cached and cached[0] > now:
        return cached[1]

    source_url = await _seedr_media_source_url(file_id)
    command = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        "-analyzeduration", "10M",
        "-probesize", "20M",
        source_url,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise HTTPException(504, "Media track inspection timed out") from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, "FFmpeg is not installed on the media server") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise HTTPException(502, detail or "FFprobe could not inspect the Seedr file")

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise HTTPException(502, "FFprobe returned invalid metadata") from exc

    _seedr_ffprobe_cache[file_id] = (now + _SEEDR_FFPROBE_CACHE_SECONDS, data)
    return data


_SEEDR_MEDIA_INFO_CACHE_SECONDS = 600
_seedr_media_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SEEDR_EMBEDDED_SUBTITLE_CACHE_SECONDS = 600
_seedr_embedded_subtitle_cache: dict[str, tuple[float, bytes]] = {}


def _stream_tags(stream: dict[str, Any]) -> dict[str, Any]:
    raw = stream.get("tags")
    if not isinstance(raw, dict):
        return {}
    # FFprobe normally emits lowercase Matroska tag keys, but some containers
    # expose alternate casing/names. Normalize them before building labels.
    return {str(key).strip().lower(): value for key, value in raw.items()}


def _track_language(stream: dict[str, Any]) -> str:
    tags = _stream_tags(stream)
    for key in ("language", "lang", "language-eng", "language_ietf"):
        value = str(tags.get(key) or "").strip().lower()
        if value:
            return value.split("-")[0]
    return ""


def _track_title(stream: dict[str, Any], fallback: str) -> str:
    tags = _stream_tags(stream)
    for key in ("title", "handler_name", "name", "track_name"):
        value = str(tags.get(key) or "").strip()
        if value:
            return value
    return fallback


@router.get("/api/seedr/media-info/{file_id}")
async def seedr_media_info(file_id: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    cached = _seedr_media_info_cache.get(file_id)
    now = asyncio.get_running_loop().time()
    if cached and cached[0] > now:
        return cached[1]

    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    if not isinstance(streams, list):
        streams = []

    language_names = {
        "en": "English", "eng": "English",
        "hi": "Hindi", "hin": "Hindi",
        "fr": "French", "fra": "French",
        "de": "German", "deu": "German",
        "es": "Spanish", "spa": "Spanish",
        "it": "Italian", "ita": "Italian",
        "pt": "Portuguese", "por": "Portuguese",
        "ru": "Russian", "rus": "Russian",
        "ja": "Japanese", "jpn": "Japanese",
        "ko": "Korean", "kor": "Korean",
        "zh": "Chinese", "zho": "Chinese",
        "ar": "Arabic", "ara": "Arabic",
        "bn": "Bengali", "ben": "Bengali",
    }

    audio_tracks = []
    subtitle_tracks = []
    audio_index = 0
    subtitle_index = 0

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = str(stream.get("codec_type") or "").lower()
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        lang = _track_language(stream)
        title = _track_title(stream, "")
        disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
        if codec_type == "audio":
            language_label = language_names.get(lang, lang.upper() if lang else "")
            # Keep the raw mix title separate from the language. The frontend
            # combines them into a clearer label such as "English (BD 5.1)".
            label = title or language_label or f"Audio {audio_index + 1}"
            audio_tracks.append({
                "index": audio_index,
                "streamIndex": int(stream.get("index") or 0),
                "language": lang,
                "title": label,
                "codec": str(stream.get("codec_name") or "").upper(),
                "channels": int(stream.get("channels") or 0),
                "default": bool(disposition.get("default")),
            })
            audio_index += 1
        elif codec_type == "subtitle":
            codec = str(stream.get("codec_name") or "").lower()
            # Bitmap subtitle codecs cannot be represented as browser WebVTT.
            if codec in {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}:
                continue
            language_label = language_names.get(lang, lang.upper() if lang else "")
            forced = bool(disposition.get("forced"))
            default = bool(disposition.get("default"))
            codec_label = {
                "subrip": "SRT",
                "ass": "ASS",
                "ssa": "SSA",
                "webvtt": "WebVTT",
                "mov_text": "Text",
                "text": "Text",
            }.get(codec, codec.upper() or "Text")
            # Preserve the real Matroska title/language whenever available.
            # Some MKVs contain no subtitle language/title tags at all. In that
            # case the old fallback produced identical entries such as
            # "SRT", making it impossible to tell tracks apart. Give unnamed
            # tracks a stable ordinal while keeping the real language when one
            # is available.
            if title:
                label = title
            elif language_label:
                label = f"{language_label} {subtitle_index + 1}"
            else:
                label = f"{codec_label} {subtitle_index + 1}"

            if forced and "forced" not in label.lower():
                label += " · Forced"
            elif default and "default" not in label.lower():
                label += " · Default"
            stream_index = int(stream.get("index") or 0)
            subtitle_tracks.append({
                "index": subtitle_index,
                "streamIndex": stream_index,
                "language": lang,
                "title": label,
                "codec": str(stream.get("codec_name") or "").upper(),
                "url": f"/api/seedr/media-info/{quote(file_id, safe='')}/subtitle?stream={stream_index}&name={quote(label, safe='')}",
            })
            subtitle_index += 1

    result = {
        "name": str((data.get("format") or {}).get("filename") or file_id) if isinstance(data, dict) else file_id,
        "audioTracks": audio_tracks,
        "subtitleTracks": subtitle_tracks,
    }
    _seedr_media_info_cache[file_id] = (now + _SEEDR_MEDIA_INFO_CACHE_SECONDS, result)
    return result


@router.get("/api/seedr/media-info/{file_id}/subtitle")
async def seedr_embedded_subtitle(
    file_id: str,
    track: int | None = Query(None, ge=0),
    stream: int | None = Query(None, ge=0),
    name: str = Query("subtitle"),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    cache_key = f"{file_id}:{track}"
    now = asyncio.get_running_loop().time()
    cached = _seedr_embedded_subtitle_cache.get(cache_key)
    if cached and cached[0] > now:
        return Response(
            content=cached[1],
            media_type="text/vtt; charset=utf-8",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "private, max-age=600",
                "Content-Disposition": f'inline; filename="{Path(name).name.replace(chr(34), "_")}.vtt"',
            },
        )

    # Reuses the media-info FFprobe result instead of probing the remote MKV
    # a second time when the user selects an embedded subtitle.
    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    subtitle_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "subtitle"
        and str(stream.get("codec_name") or "").lower() not in {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
    ]
    if stream is not None:
        selected = next(
            (
                item for item in subtitle_streams
                if int(item.get("index") or -1) == stream
            ),
            None,
        )
        if selected is None:
            raise HTTPException(404, "Subtitle stream not found")
        stream_index = int(selected.get("index") or 0)
        cache_key = f"{file_id}:stream:{stream_index}"
    else:
        if track is None or track >= len(subtitle_streams):
            raise HTTPException(404, "Subtitle track not found")
        stream_index = int(subtitle_streams[track].get("index") or 0)
        cache_key = f"{file_id}:{track}"

    source_url = await _seedr_media_source_url(file_id)
    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-i", source_url,
        "-map", f"0:{stream_index}",
        "-c:s", "webvtt",
        "-f", "webvtt",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise HTTPException(504, "Subtitle extraction timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise HTTPException(502, detail or "Subtitle extraction failed")

    _seedr_embedded_subtitle_cache[cache_key] = (
        now + _SEEDR_EMBEDDED_SUBTITLE_CACHE_SECONDS,
        stdout,
    )

    return Response(
        content=stdout,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "private, max-age=600",
            "Content-Disposition": f'inline; filename="{Path(name).name.replace(chr(34), "_")}.vtt"',
        },
    )


async def _stream_selected_audio(file_id: str, audio_index: int, start: float = 0.0) -> StreamingResponse:
    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    audio_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "audio"
    ]
    if audio_index >= len(audio_streams):
        raise HTTPException(404, "Audio track not found")

    source_url = await _seedr_media_source_url(file_id)
    stream = audio_streams[audio_index]
    video_streams = [
        item for item in streams
        if isinstance(item, dict) and str(item.get("codec_type") or "").lower() == "video"
    ]
    video_codec = str((video_streams[0] if video_streams else {}).get("codec_name") or "").lower()

    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        *([ "-ss", str(max(0.0, start)) ] if start > 0 else []),
        "-i", source_url,
        "-map", "0:v:0",
        "-map", f"0:a:{audio_index}",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    ]
    if video_codec in {"h264", "avc1"}:
        command[command.index("-c:a"):command.index("-c:a")] = ["-c:v", "copy"]
    else:
        command[command.index("-c:a"):command.index("-c:a")] = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
        ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def body():
        try:
            while True:
                chunk = await process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                await process.wait()
            except Exception:
                pass

    return StreamingResponse(
        body(),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/api/seedr/media/video/{file_id}/stats")
async def seedr_video_media_stats(file_id: str):
    return {
        "bytesPerSecond": round(_media_download_speed(file_id), 2),
        "windowSeconds": _MEDIA_STATS_WINDOW_SECONDS,
    }

@router.get("/api/seedr/media/video/{file_id}")
async def seedr_video_media(
    file_id: str,
    request: Request,
    audio: int | None = Query(None, ge=0),
    start: float = Query(0.0, ge=0.0),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    if audio is not None:
        return await _stream_selected_audio(file_id, audio, start=start)

    upstream_url = await seedr_v2_video_url(file_id)
    if not upstream_url:
        raise HTTPException(404, "Seedr returned no video presentation URL")

    headers = {"Accept": "video/*,application/octet-stream,*/*"}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = _InstrumentedAsyncClient(timeout=60, follow_redirects=True)
    try:
        response = await client.send(
            client.build_request("GET", upstream_url, headers=headers),
            stream=True,
        )
    except Exception:
        await client.aclose()
        raise

    if response.status_code >= 400:
        body = await response.aread()
        status = response.status_code
        content_type = response.headers.get("content-type", "application/octet-stream")
        await response.aclose()
        await client.aclose()
        return Response(
            content=body,
            status_code=status,
            media_type=content_type,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
        "Cache-Control": "no-store",
    }
    for header in ("content-range", "content-length", "etag", "last-modified"):
        if response.headers.get(header):
            response_headers[header.title()] = response.headers[header]

    async def body_stream():
        try:
            async for chunk in response.aiter_bytes():
                _record_media_bytes(file_id, len(chunk))
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "video/mp4"),
        headers=response_headers,
    )


@router.get("/api/seedr/media/audio/{file_id}")
async def seedr_audio_media_route(
    file_id: str,
    request: Request,
    track: int = Query(0, ge=0),
    start: float = Query(0.0, ge=0.0),
):
    """Stream one Seedr audio track as browser-compatible fragmented MP4.

    This route is used for alternate-audio playback so the video element never
    has to be replaced. Keeping video on its original timeline avoids the
    shortened-duration and A/V drift caused by remuxing the whole video when a
    user changes audio tracks.
    """
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    audio_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "audio"
    ]
    if track >= len(audio_streams):
        raise HTTPException(404, "Audio track not found")

    source_url = await _seedr_media_source_url(file_id)
    source = audio_streams[track]
    codec = str(source.get("codec_name") or "").lower()

    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        *(["-ss", str(max(0.0, start))] if start > 0 else []),
        "-i", source_url,
        "-map", f"0:a:{track}",
    ]

    # Emit a plain MP3 stream for the hidden browser audio element.
    # MP3 is broadly supported by Chrome/Edge/Android and does not require the
    # fragmented MP4/WebM demuxers that can stall on a non-seekable pipe.
    command += [
        "-vn",
        "-sn",
        "-dn",
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        "-f", "mp3",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, "FFmpeg is not installed on the media server") from exc

    async def body():
        try:
            while True:
                chunk = await process.stdout.read(512 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                await process.wait()
            except Exception:
                pass

    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )


async def _cancel_seedr_task_and_partial_folder(
    tid: str,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stop an unfinished Seedr task and remove its partial folder, never a completed download."""
    global _seedr_metadata_cache

    task_id_value = str(tid or "").strip()
    if not task_id_value:
        raise HTTPException(400, "A Seedr task id is required")

    task_found = isinstance(task, dict) and bool(task)
    task_value = task if isinstance(task, dict) else {}
    if not task_found:
        try:
            raw = seedr_data(await seedr_request(f"/tasks/{quote(task_id_value, safe='')}"))
            task_value = unwrap_seedr_task(raw)
            task_found = bool(task_value)
        except (HTTPException, SeedrError) as exc:
            if getattr(exc, "status_code", 0) != 404:
                raise
            task_value = {}

    complete = task_complete(task_value) if task_found else False
    active = task_found and not complete
    task_name = seedr_task_name(task_value) or f"Torrent {task_id_value}"
    folder_id = seedr_task_folder_id(task_value) if task_found else ""
    task_files: list[dict[str, Any]] = []

    # Some Seedr API variants expose the created folder only in task contents.
    if active and not folder_id:
        try:
            task_files = await task_contents(task_id_value)
            folder_id = (
                _seedr_effective_task_folder_id(task_value, task_files)
                or _seedr_file_folder_id(task_files)
            )
        except (HTTPException, SeedrError):
            task_files = []

    folder_size = 0
    for file in task_files:
        if not isinstance(file, dict):
            continue
        try:
            folder_size += max(0, int(float(file.get("size") or 0)))
        except (TypeError, ValueError):
            continue
    task_deleted = False
    if task_found:
        try:
            await seedr_request(f"/tasks/{quote(task_id_value, safe='')}", "DELETE")
            task_deleted = True
        except (HTTPException, SeedrError) as exc:
            status_code = getattr(exc, "status_code", 0)
            if status_code == 405:
                try:
                    await seedr_request(f"/tasks/{quote(task_id_value, safe='')}/delete", "POST")
                    task_deleted = True
                except (HTTPException, SeedrError) as fallback_exc:
                    if getattr(fallback_exc, "status_code", 0) != 404:
                        raise
            elif status_code != 404:
                raise

    folder_deleted = False
    if active and folder_id and folder_id != "0":
        # Seedr can remove the task before its partial folder is ready to be
        # deleted. Retry the folder DELETE with backoff instead of returning an
        # error that forces the user to click Prepare a second time.
        max_delete_attempts = 5
        last_delete_error: Exception | None = None
        for attempt in range(max_delete_attempts):
            try:
                await seedr_request(f"/fs/folder/{quote(folder_id, safe='')}", "DELETE")
                folder_deleted = True
                last_delete_error = None
                break
            except (HTTPException, SeedrError) as exc:
                status_code = getattr(exc, "status_code", 0)
                if status_code == 404:
                    # A previous attempt or Seedr's own task deletion already
                    # removed the transient folder.
                    folder_deleted = True
                    last_delete_error = None
                    break

                last_delete_error = exc
                if attempt + 1 < max_delete_attempts:
                    delay = min(0.75 * (2 ** attempt), 4.0)
                    logger.warning(
                        "Seedr partial-folder delete retry task=%s folder=%s attempt=%s/%s delay_seconds=%.2f status=%s detail=%s",
                        task_id_value,
                        folder_id,
                        attempt + 1,
                        max_delete_attempts,
                        delay,
                        status_code,
                        getattr(exc, "detail", str(exc)),
                    )
                    await asyncio.sleep(delay)

        if not folder_deleted:
            # Do not abort the new Prepare solely because the partial-folder
            # deletion endpoint briefly failed. The old task has already been
            # cancelled; continue to quota cleanup and the requested add, which
            # will trigger the existing storage-recovery retry if necessary.
            logger.error(
                "Seedr partial-folder deletion did not confirm success after retries; continuing with new add task=%s folder=%s status=%s detail=%s",
                task_id_value,
                folder_id,
                getattr(last_delete_error, "status_code", 0),
                getattr(last_delete_error, "detail", str(last_delete_error)),
            )

    _seedr_cleanup_jobs.pop(task_id_value, None)
    _seedr_torrent_names_by_task.pop(task_id_value, None)
    if folder_id:
        _seedr_torrent_names.pop(folder_id, None)
        _seedr_folder_cache.pop(folder_id, None)
    _save_seedr_cleanup_jobs()
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()

    return {
        "taskId": task_id_value,
        "name": task_name,
        "found": task_found,
        "active": active,
        "completed": complete,
        "taskDeleted": task_deleted,
        "folderId": folder_id,
        "folderDeleted": folder_deleted,
        "size": folder_size,
    }


async def _cancel_active_seedr_tasks_for_replacement(
    replace_task_id: str = "",
) -> list[dict[str, Any]]:
    """Cancel all unfinished tasks in the connected Seedr account before a new torrent is added."""
    explicit_id = str(replace_task_id or "").strip()
    tracked_ids = {str(task_id_value).strip() for task_id_value in _seedr_cleanup_jobs}
    tracked_ids.discard("")

    try:
        payload = seedr_data(await seedr_request("/tasks"))
    except (HTTPException, SeedrError) as exc:
        logger.warning("Could not list Seedr tasks before replacement: %s", getattr(exc, "detail", str(exc)))
        raise SeedrError(
            "SEEDR_TASK_LIST_FAILED",
            503,
            "Could not check the current Seedr download before replacing it. Please retry.",
        ) from exc

    cancelled: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_task in arr(payload, ("tasks", "torrents", "items")):
        task = unwrap_seedr_task(seedr_data(raw_task))
        if not task:
            continue
        task_id_value = task_id(task)
        if task_id_value:
            seen_ids.add(task_id_value)
        if not task_id_value or task_complete(task):
            continue
        if task_id_value in {str(item.get("taskId") or "") for item in cancelled}:
            continue

        result = await _cancel_seedr_task_and_partial_folder(task_id_value, task)
        if result.get("active"):
            cancelled.append(result)

    # A tracked or explicitly selected task may be temporarily absent from the
    # list endpoint. Check those IDs directly so stale Seedr tasks do not survive
    # simply because the backend restarted or /tasks omitted a row.
    fallback_ids = tracked_ids | ({explicit_id} if explicit_id else set())
    for task_id_value in sorted(fallback_ids - seen_ids):
        try:
            result = await _cancel_seedr_task_and_partial_folder(task_id_value)
        except (HTTPException, SeedrError) as exc:
            logger.warning(
                "Seedr replacement could not cancel stale task=%s: %s",
                task_id_value,
                getattr(exc, "detail", str(exc)),
            )
            raise
        if result.get("active"):
            cancelled.append(result)

    if cancelled:
        logger.info(
            "Seedr replacement cancelled %s unfinished task(s): %s",
            len(cancelled),
            ",".join(str(item.get("taskId") or "") for item in cancelled),
        )
    else:
        logger.info("Seedr replacement found no unfinished Seedr tasks")
    return cancelled


@router.delete("/api/seedr/tasks/{tid}")
async def seedr_task_delete(tid: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")
    return await _cancel_seedr_task_and_partial_folder(tid)

@router.delete("/api/seedr/files/{file_id}")
async def seedr_file_delete(file_id: str):
    global _seedr_metadata_cache
    result = await seedr_request(f"/fs/file/{quote(file_id)}", "DELETE")
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()
    return result

@router.delete("/api/seedr/folders/{folder_id}")
async def seedr_folder_delete(folder_id: str):
    global _seedr_metadata_cache
    result = await seedr_request(f"/fs/folder/{quote(folder_id)}", "DELETE")
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()
    return result
