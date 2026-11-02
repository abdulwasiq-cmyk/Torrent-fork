"""Moved out of main.py (see docs/main-split-plan.md)."""

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

import httpx
from fastapi import HTTPException

from core.cache_diagnostics import _InstrumentedAsyncClient
from seedr.seedr_session import (
    _seedr_session_auth_mode,
    _seedr_session_fingerprint,
    current_seedr_token,
    normalize_seedr_token,
)
from core.settings import SEEDR_BASE, SEEDR_PAT_BASE, logger
from core.shared import SeedrError, _seedr_request_session_id

def seedr_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def seedr_access_token() -> str:
    """Access token used only by Seedr's legacy resource.php API."""
    return normalize_seedr_token(current_seedr_token())


async def legacy_seedr_request(
    func: str,
    method: str = "POST",
    body: dict[str, Any] | None = None,
) -> Any:
    """Call Seedr's documented legacy resource API using form data."""
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    access_token = seedr_access_token()
    if not access_token:
        raise HTTPException(503, "Seedr access token is empty")

    url = "https://www.seedr.cc/oauth_test/resource.php"
    params = {
        "access_token": access_token,
        "func": str(func),
    }
    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        response = await client.request(
            method,
            url,
            params=params,
            data=body or {},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    raw = response.text
    try:
        data = response.json() if raw else None
    except Exception:
        data = raw

    if response.status_code >= 400:
        raise SeedrError(
            *seedr_problem(response.status_code, data, raw)
        )

    if isinstance(data, dict):
        raw_error = str(data.get("error") or "").strip().lower()
        error_detail = str(
            data.get("error_description") or data.get("message") or data.get("error") or ""
        ).strip()
        normalized_error = error_detail.lower().replace("_", " ")
        if raw_error not in ("", "0"):
            if (
                "not enough space" in normalized_error
                or "insufficient space" in normalized_error
                or "not enough storage" in normalized_error
                or "storage full" in normalized_error
                or "not_enough_space" in raw_error
                or "insufficient_space" in raw_error
                or "not_enough_space" in normalized_error
                or normalized_error.startswith("not enough space")
                or normalized_error.startswith("insufficient space")
            ):
                raise SeedrError(
                    "SEEDR_INSUFFICIENT_SPACE",
                    413,
                    "Seedr does not have enough free space for this torrent.",
                )
            if "access_denied" in raw_error or "access denied" in normalized_error:
                raise SeedrError(
                    "SEEDR_LIBRARY_ACCESS_DENIED",
                    403,
                    "Seedr denied this account operation.",
                )
            if "unauthor" in raw_error or "invalid token" in normalized_error:
                raise SeedrError(
                    "SEEDR_TOKEN_REJECTED",
                    401,
                    "Seedr rejected the API token.",
                )
            # Seedr's legacy API often reports operation failures inside a 200
            # JSON response. Preserve the provider's error text instead of
            # treating that as a successful task creation.
            raise SeedrError(
                "SEEDR_API_ERROR",
                502,
                error_detail or "Seedr rejected the torrent.",
            )

    return data


async def legacy_seedr_list_contents(folder_id: str = "0") -> Any:
    """List a Seedr folder using the legacy resource endpoint.
    
    The free account/token used by Torrent Studio can deny the modern root
    filesystem endpoint while still permitting list_contents through Seedr's
    legacy resource API.
    """
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    access_token = seedr_access_token()
    if not access_token:
        raise HTTPException(503, "Seedr access token is empty")

    url = "https://www.seedr.cc/oauth_test/resource.php"
    params = {
        "access_token": access_token,
        "func": "list_contents",
    }
    form = {
        "content_type": "folder",
        "content_id": str(folder_id),
    }
    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        response = await client.post(
            url,
            params=params,
            data=form,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
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

    if isinstance(data, dict) and str(data.get("error") or "").strip() not in ("", "0"):
        raw_error = str(data.get("error") or "").strip().lower()
        if "access_denied" in raw_error or "access denied" in raw_error:
            raise SeedrError(
                "SEEDR_LIBRARY_ACCESS_DENIED",
                403,
                "Seedr denied access to the account library. The token is recognized, but this library operation is not permitted.",
            )
        if "unauthor" in raw_error or "invalid token" in raw_error:
            raise SeedrError(
                "SEEDR_TOKEN_REJECTED",
                401,
                "Seedr rejected the API token. Generate a fresh Seedr API token and update SEEDR_API_TOKEN in Render.",
            )
        raise SeedrError(
            "SEEDR_API_ERROR",
            502,
            f"Seedr legacy library request failed: {data.get('error')}",
        )

    return data


async def seedr_root_request() -> Any:
    """Fetch the Seedr account root using Seedr's dedicated root endpoint."""
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    url = "https://www.seedr.cc/api/folder"
    headers = {"Accept": "application/json"}
    params = {"access_token": seedr_access_token()}

    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        response = await client.get(url, headers=headers, params=params)

    raw = response.text
    try:
        data = response.json() if raw else None
    except Exception:
        data = raw

    if response.status_code >= 400:
        detail = raw
        if isinstance(data, dict):
            detail = (
                data.get("error_description")
                or data.get("reason_phrase")
                or data.get("message")
                or data.get("error")
                or raw
            )
        raise HTTPException(response.status_code, str(detail or "Seedr root request failed"))

    return data


def seedr_problem(status_code: int, data: Any, raw: str) -> tuple[str, int, str]:
    reason = ""
    if isinstance(data, dict):
        reason = str(
            data.get("reason_phrase")
            or data.get("error_description")
            or data.get("message")
            or data.get("error")
            or data.get("detail")
            or ""
        ).strip()

    normalized = reason.lower().replace("_", " ").strip()

    if status_code == 401 or "unauthorized" in normalized or normalized in {"invalid token", "token expired", "token invalid"}:
        return (
            "SEEDR_TOKEN_REJECTED",
            401,
            "Seedr rejected the API token. Generate a fresh Seedr API token and update SEEDR_API_TOKEN in Render.",
        )

    if status_code == 403 or normalized in {"access denied", "forbidden", "access_denied"}:
        return (
            "SEEDR_LIBRARY_ACCESS_DENIED",
            403,
            "Seedr denied access to this library operation. The API token is valid, but this operation/folder is not permitted.",
        )

    if status_code == 413 or normalized == "not enough space" or "not enough space" in normalized:
        return (
            "SEEDR_QUOTA_UNAVAILABLE",
            413,
            "Seedr reports insufficient storage space for this operation.",
        )

    if status_code == 429:
        return (
            "SEEDR_QUOTA_UNAVAILABLE",
            429,
            "Seedr rate limit reached. Please wait a moment and try again.",
        )

    if status_code >= 500:
        return (
            "SEEDR_QUOTA_UNAVAILABLE",
            status_code,
            "Seedr is temporarily unavailable. Please try again in a moment.",
        )

    return (
        "SEEDR_API_ERROR",
        status_code,
        reason or raw[:500] or f"Seedr API request failed (HTTP {status_code})",
    )


def seedr_error_message(status_code: int, data: Any, raw: str) -> str:
    return seedr_problem(status_code, data, raw)[2]

async def seedr_request(path: str, method: str = "GET", body: Any = None, form: bool = False, base_url: str = SEEDR_BASE) -> Any:
    if not current_seedr_token():
        raise SeedrError(
            "SEEDR_TOKEN_MISSING",
            503,
            "No Seedr account is connected to this browser session.",
        )

    request_path = str(path).lstrip("/")
    selected_base_url = base_url
    if base_url == SEEDR_BASE and _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat":
        selected_base_url = SEEDR_PAT_BASE
    url = f"{str(selected_base_url).rstrip("/")}/{request_path}"
    token = normalize_seedr_token(current_seedr_token())

    kwargs: dict[str, Any] = {}
    if body is not None:
        if form:
            headers_base = {"Content-Type": "application/x-www-form-urlencoded"}
            kwargs["data"] = body
        else:
            headers_base = {"Content-Type": "application/json"}
            kwargs["json"] = body
    else:
        headers_base = {}

    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        tried_tokens: list[str] = []
        # Never fall back from one browser session to another Seedr credential.
        candidates = [token]

        last_status = 0
        last_data: Any = None
        last_raw = ""

        for candidate in candidates:
            if not candidate or candidate in tried_tokens:
                continue
            tried_tokens.append(candidate)

            headers = {
                "Authorization": f"Bearer {candidate}",
                "Accept": "application/json",
                **headers_base,
            }
            request_started = time.monotonic()
            logger.info(
                "Seedr API request start: session=%s mode=%s method=%s url=%s "
                "token_present=%s token_length=%s token_fingerprint=%s body_keys=%s",
                _seedr_session_fingerprint(_seedr_request_session_id.get().strip()),
                _seedr_session_auth_mode(_seedr_request_session_id.get().strip()),
                method,
                url,
                bool(token),
                len(token),
                hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else "none",
                sorted(body.keys()) if isinstance(body, dict) else [],
            )
            try:
                response = await client.request(method, url, headers=headers, **kwargs)
            except Exception as exc:
                elapsed_ms = int((time.monotonic() - request_started) * 1000)
                logger.exception(
                    "Seedr API transport failure: session=%s mode=%s method=%s url=%s "
                    "elapsed_ms=%s exception_type=%s exception=%s",
                    _seedr_session_fingerprint(_seedr_request_session_id.get().strip()),
                    _seedr_session_auth_mode(_seedr_request_session_id.get().strip()),
                    method,
                    url,
                    elapsed_ms,
                    type(exc).__name__,
                    str(exc)[:1000],
                )
                raise SeedrError(
                    "SEEDR_NETWORK_ERROR",
                    502,
                    f"Seedr request could not be completed: {type(exc).__name__}: {str(exc)[:500]}",
                ) from exc

            elapsed_ms = int((time.monotonic() - request_started) * 1000)
            raw = response.text
            try:
                data = response.json() if raw else None
            except Exception:
                data = raw

            response_request_id = (
                response.headers.get("x-request-id")
                or response.headers.get("x-correlation-id")
                or response.headers.get("cf-ray")
                or ""
            )
            logger.info(
                "Seedr API response: session=%s mode=%s method=%s path=%s status=%s "
                "elapsed_ms=%s response_bytes=%s content_type=%s provider_request_id=%s",
                _seedr_session_fingerprint(_seedr_request_session_id.get().strip()),
                _seedr_session_auth_mode(_seedr_request_session_id.get().strip()),
                method,
                request_path,
                response.status_code,
                elapsed_ms,
                len(raw.encode("utf-8", errors="ignore")),
                response.headers.get("content-type", ""),
                response_request_id[:200],
            )

            if response.status_code < 400:
                if isinstance(data, dict):
                    soft = str(data.get("reason_phrase") or "").strip().lower()
                    if soft == "not_enough_space":
                        raise SeedrError(
                            "SEEDR_QUOTA_UNAVAILABLE",
                            413,
                            "Seedr reports insufficient storage space for this operation.",
                        )
                return data

            last_status, last_data, last_raw = response.status_code, data, raw
            logger.warning(
                "Seedr API request failed: session=%s mode=%s method=%s path=%s url=%s "
                "status=%s elapsed_ms=%s token_length=%s token_fingerprint=%s "
                "provider_request_id=%s response_json=%s response_body=%s",
                _seedr_session_fingerprint(_seedr_request_session_id.get().strip()),
                _seedr_session_auth_mode(_seedr_request_session_id.get().strip()),
                method,
                request_path,
                url,
                response.status_code,
                elapsed_ms,
                len(token),
                hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else "none",
                response_request_id[:200],
                json.dumps(data, ensure_ascii=False, default=str)[:4000] if isinstance(data, (dict, list)) else "<not-json>",
                raw[:4000] if raw else "<empty>",
            )

            break

    code, status_code, detail = seedr_problem(last_status, last_data, last_raw)
    raise SeedrError(code, status_code, detail)


def arr(value: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                return value[key]
    return []

def unwrap_seedr_task(value: Any) -> dict[str, Any]:
    """Normalize task responses that may be wrapped in data/task objects."""
    current = value
    for _ in range(4):
        if not isinstance(current, dict):
            return {}
        nested = current.get("task")
        if isinstance(nested, dict):
            current = nested
            continue
        return current
    return current if isinstance(current, dict) else {}


def seedr_task_folder_id(task: dict[str, Any]) -> str:
    nested_torrent = task.get("torrent") if isinstance(task.get("torrent"), dict) else {}
    payload = task.get("torrent_payload") if isinstance(task.get("torrent_payload"), dict) else {}

    return str(
        task.get("folder_created_id")
        or task.get("folder_created")
        or task.get("folder_id")
        or task.get("folderId")
        or nested_torrent.get("folder_created_id")
        or nested_torrent.get("folder_id")
        or nested_torrent.get("folderId")
        or payload.get("folder_created_id")
        or payload.get("folder_id")
        or payload.get("folderId")
        or ""
    ).strip()


def magnet_display_name(value: Any) -> str:
    """Extract the torrent display name (dn) from a magnet-like value."""
    raw = str(value or "").strip()
    if not raw.lower().startswith("magnet:?"):
        return ""
    try:
        params = parse_qs(urlsplit(raw).query, keep_blank_values=True)
        return str((params.get("dn") or [""])[0]).strip()
    except Exception:
        return ""


def task_complete(task: dict[str, Any]) -> bool:
    """Return True only when Seedr reports a task as finished."""
    if not isinstance(task, dict):
        return False

    # Explicit completion flags are authoritative.
    for key in ("completed", "complete", "finished", "done", "is_completed", "isComplete"):
        value = task.get(key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, (int, float)) and value == 1:
            return True

    state = str(
        task.get("state")
        or task.get("status")
        or task.get("phase")
        or ""
    ).strip().lower().replace("-", "_")

    try:
        progress = float(task.get("progress") or 0)
    except (TypeError, ValueError):
        progress = 0.0

    # A new Prepare must be able to replace stuck, queued, paused, or
    # metadata/seed-discovery tasks, even if the provider calls them "seeding".
    # Keep these as unfinished unless Seedr's explicit completion flags above
    # confirm completion. This avoids treating "Collecting Seeds" as completed.
    active_states = {
        "paused", "paused_dl", "pauseddl", "paused_download",
        "queued", "queued_dl", "queueddl", "queued_download",
        "downloading", "download", "collecting_seeds", "collecting seeds",
        "waiting", "metadata", "fetching_metadata", "checking",
    }
    if state in active_states:
        return False

    completed_states = {"complete", "completed", "finished", "done", "success"}
    if state in completed_states:
        return True

    # "seeding" normally means the payload is complete, but some Seedr task
    # variants use it for a stalled seed-discovery state without progress.
    if state == "seeding":
        return progress >= 100

    # A numeric 100% is authoritative even when the state field is absent or
    # uses a provider-specific value.
    return progress >= 100

def seedr_task_name(task: dict[str, Any]) -> str:
    nested_torrent = task.get("torrent") if isinstance(task.get("torrent"), dict) else {}
    payload = task.get("torrent_payload") if isinstance(task.get("torrent_payload"), dict) else {}
    meta = task.get("meta") if isinstance(task.get("meta"), dict) else {}
    nested_link = (
        task.get("torrent_magnet")
        or task.get("magnet")
        or task.get("magnet_url")
        or nested_torrent.get("torrent_magnet")
        or nested_torrent.get("magnet")
        or payload.get("torrent_magnet")
        or payload.get("magnet")
        or ""
    )
    magnet_name = magnet_display_name(nested_link)

    # A magnet's dn is the closest match to the title the user selected from
    # search. Prefer it before Seedr's own generated/provider title.
    return str(
        task.get("torrent_name")
        or magnet_name
        or nested_torrent.get("torrent_name")
        or payload.get("torrent_name")
        or task.get("torrent_title")
        or task.get("torrentTitle")
        or nested_torrent.get("title")
        or nested_torrent.get("name")
        or payload.get("title")
        or payload.get("name")
        or task.get("title")
        or task.get("name")
        or meta.get("torrent_name")
        or meta.get("title")
        or ""
    ).strip()


def normalize_magnet(magnet: str) -> str:
    """Normalize the BTIH while preserving the magnet's tracker and name parameters."""
    value = re.sub(r"[\r\n\t]+", "", str(magnet or "").strip())
    decoded = unquote(value)
    if decoded.lower().startswith("magnet:?"):
        value = decoded
    if not value.lower().startswith("magnet:?"):
        return value

    try:
        parsed = urlsplit(value)
        params = parse_qs(parsed.query, keep_blank_values=True)
        valid_hash = ""
        for raw in params.get("xt", []):
            raw = unquote(raw)
            match = re.fullmatch(r"urn:btih:([A-Za-z0-9]{32,40})", raw, re.I)
            if not match:
                continue
            candidate = match.group(1)
            if len(candidate) == 32:
                candidate = base64.b32decode(
                    candidate.upper() + "=" * ((8 - len(candidate) % 8) % 8)
                ).hex()
            if len(candidate) == 40 and re.fullmatch(r"[0-9a-fA-F]{40}", candidate):
                valid_hash = candidate.lower()
                break

        if not valid_hash:
            return value

        # Keep the human-readable name and all supplied trackers. Some
        # metadata-only peers are reachable only through the trackers present
        # in the original magnet.
        rebuilt: list[tuple[str, str]] = [("xt", "urn:btih:" + valid_hash)]
        for key in ("dn", "tr"):
            for item in params.get(key, []):
                text_value = str(item or "").strip()
                if text_value:
                    rebuilt.append((key, text_value))

        return "magnet:?" + urlencode(rebuilt, doseq=True)
    except Exception:
        return value

def info_hash(magnet: str) -> str:
    for _ in range(3):
        m = re.search(r"(?:urn:btih:|btih:)([A-Za-z0-9]{32,40})", magnet, re.I)
        if m:
            h = m.group(1)
            if len(h) == 40 and re.fullmatch(r"[0-9a-fA-F]{40}", h):
                return h.lower()
            if len(h) == 32:
                try:
                    return base64.b32decode(h.upper() + "=" * ((8-len(h)%8)%8)).hex()
                except Exception:
                    pass
        magnet = unquote(magnet)
    return ""

def task_id(task: dict[str, Any]) -> str:
    return str(task.get("user_torrent_id") or task.get("id") or task.get("task_id") or "").strip()

async def rename_seedr_folder(folder_id: str, name: str) -> bool:
    # Folder rename is deliberately not part of the free-account download path.
    # Seedr can expose the generated folder name asynchronously.
    return False


async def add_task(magnet: str, folder_id: int = 0) -> dict[str, Any]:
    # Forward the exact magnet URI supplied by the caller.
    # Do not parse, rebuild, decode, lowercase, or add/remove query parameters.
    logger.info(
        "Seedr direct add: POST /tasks folder_id=%s magnet_length=%s",
        int(folder_id),
        len(magnet),
    )
    result = await seedr_request(
        "/tasks",
        method="POST",
        body={
            "torrent_magnet": magnet,
            "folder_id": int(folder_id),
        },
    )
    if not isinstance(result, dict):
        raise HTTPException(502, "Seedr did not return a valid task response")
    return result


def normalize_file(item: Any, folder_id: str = "") -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"id": "", "name": "Unnamed file", "size": 0, "folderId": folder_id}
    return {
        "id": str(item.get("id") or item.get("file_id") or ""),
        # Seedr V2 presentation endpoints use the canonical file id.
        # Keep legacy folder_file_id only as a fallback for older API shapes.
        "streamId": str(
            item.get("id")
            or item.get("file_id")
            or item.get("folder_file_id")
            or item.get("folderFileId")
            or ""
        ),
        "name": str(item.get("name") or item.get("title") or "Unnamed file"),
        "size": int(float(item.get("size") or 0)),
        "folderId": str(item.get("folder_id") or item.get("folderId") or folder_id),
    }

async def task_contents(tid: str) -> list[dict[str, Any]]:
    payload = seedr_data(await seedr_request(f"/tasks/{quote(tid)}/contents"))
    if not isinstance(payload, dict):
        return []
    files = [normalize_file(x, str(payload.get("folder_created_id") or "")) for x in arr(payload, ("files", "items"))]
    folder = str(payload.get("folder_created_id") or "").strip()
    if folder and (not files or any(not x["id"] for x in files)):
        try:
            folder_payload = seedr_data(await seedr_request(f"/fs/folder/{quote(folder)}/contents"))
            folder_files = arr(folder_payload, ("files", "items"))
            if folder_files:
                files = [normalize_file(x, folder) for x in folder_files]
        except HTTPException:
            pass
    return files

async def folder_name(folder_id: str) -> str:
    for endpoint in (f"/fs/folder/{quote(folder_id)}", f"/fs/folder/{quote(folder_id)}/contents"):
        try:
            payload = seedr_data(await seedr_request(endpoint))
            if isinstance(payload, dict):
                for key in ("name", "title", "folder_name", "folderName", "path"):
                    value = str(payload.get(key) or "").strip()
                    if value:
                        return Path(value.rstrip("/")).name
                for key in ("folder", "directory"):
                    child = payload.get(key)
                    if isinstance(child, dict):
                        for name_key in ("name", "title", "folder_name", "folderName", "path"):
                            value = str(child.get(name_key) or "").strip()
                            if value:
                                return Path(value.rstrip("/")).name
        except HTTPException:
            continue
    return ""
