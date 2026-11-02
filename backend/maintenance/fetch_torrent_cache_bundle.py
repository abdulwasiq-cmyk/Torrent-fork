#!/usr/bin/env python3
"""Install the newest verified torrent-only cache bundle into APP_DATA_DIR."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalogues.torrent_caches import (
    RUNTIME_MANIFEST_NAME,
    TORRENT_CACHE_DIR,
    TORRENT_CACHE_FILES,
    TorrentCacheError,
    _validate_manifest,
    store,
)

DEFAULT_BASE = "https://github.com/wroxtaaar/Torrent-Studio/releases/download/cache-data"
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/wroxtaaar/Torrent-Studio/"
    "cache-manifests/cache-bundles/torrent.json"
)
BUNDLE_MANIFEST_NAME = "torrent-cache-bundle.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 1024 * 1024 * 1024


def _download(url: str, limit: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "torrent-studio-torrent-cache-fetch/1",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Torrent cache bundle download exceeds the size limit")
    return content


def _url(base: str, asset: str, **params: str) -> str:
    parts = urlsplit(f"{base.rstrip('/')}/{asset}")
    query = urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _manifest_url(base: str, manifest_url: str | None, cache_bust: str) -> str:
    if manifest_url is None:
        return _url(base, BUNDLE_MANIFEST_NAME, cacheBust=cache_bust)
    return _with_query(manifest_url, cacheBust=cache_bust)


def _bundle_url(base: str, pointer: dict) -> str:
    return _url(
        base,
        pointer["bundle"],
        generation=str(pointer["generation"]),
    )


def _installed_cache_status() -> str:
    runtime = TORRENT_CACHE_DIR
    has_runtime_cache = (
        (runtime / "current").is_symlink()
        or (runtime / RUNTIME_MANIFEST_NAME).is_file()
        or any((runtime / filename).is_file() for filename in TORRENT_CACHE_FILES)
    )
    source = "persistent" if has_runtime_cache else "baked-in-seed"
    try:
        manifest = store.initialize()
    except (OSError, TorrentCacheError) as exc:
        return (
            f"cache_readiness=not-ready installed_generation=unknown "
            f"cache_source={source} cache_error={type(exc).__name__}"
        )
    return (
        f"cache_readiness=ready installed_generation={manifest['generation']} "
        f"cache_source={source}"
    )


def _read_pointer(blob: bytes) -> dict:
    try:
        value = json.loads(blob)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Torrent bundle pointer is invalid JSON") from exc
    pointer = _validate_manifest(value, BUNDLE_MANIFEST_NAME)
    bundle_name = pointer.get("bundle")
    expected_hash = pointer.get("bundleSha256")
    if (
        not isinstance(bundle_name, str)
        or Path(bundle_name).name != bundle_name
        or not bundle_name.startswith(f"torrent-cache-bundle-{pointer['generation']}-")
        or not bundle_name.endswith(".tar.gz")
    ):
        raise ValueError("Torrent bundle pointer has an invalid archive name")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("Torrent bundle pointer has an invalid archive checksum")
    if any(character not in "0123456789abcdefABCDEF" for character in expected_hash):
        raise ValueError("Torrent bundle pointer has an invalid archive checksum")
    return pointer


def _extract_and_install(bundle: bytes, pointer: dict) -> str:
    actual_hash = hashlib.sha256(bundle).hexdigest()
    if actual_hash.lower() != pointer["bundleSha256"].lower():
        raise ValueError("Torrent bundle archive checksum mismatch")

    expected_members = set(TORRENT_CACHE_FILES) | {RUNTIME_MANIFEST_NAME}
    staging_root = TORRENT_CACHE_DIR / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"generation-{pointer['generation']}-",
        dir=str(staging_root),
    ) as temporary:
        stage = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or set(names) != expected_members:
                raise ValueError("Torrent bundle must contain exactly nine files and its manifest")
            total_size = 0
            for member in members:
                if (
                    not member.isreg()
                    or Path(member.name).name != member.name
                    or member.name in {".", ".."}
                ):
                    raise ValueError(f"Unsafe torrent bundle member: {member.name}")
                total_size += member.size
                if total_size > MAX_UNPACKED_BYTES:
                    raise ValueError("Torrent cache bundle expands beyond the size limit")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"Could not read torrent bundle member: {member.name}")
                with source, (stage / member.name).open("wb") as target:
                    while block := source.read(1024 * 1024):
                        target.write(block)

        embedded = _validate_manifest(
            json.loads((stage / RUNTIME_MANIFEST_NAME).read_text(encoding="utf-8")),
            RUNTIME_MANIFEST_NAME,
        )
        if (
            embedded.get("generation") != pointer["generation"]
            or embedded.get("files") != pointer["files"]
        ):
            raise ValueError("Torrent bundle manifest does not match its release pointer")
        return store.install_bundle(stage, pointer)


def apply_torrent_cache_bundle(base: str, manifest_url: str | None = None) -> str:
    pointer_url = _manifest_url(
        base,
        manifest_url,
        str(time.time_ns()),
    )
    manifest_blob = _download(pointer_url, MAX_MANIFEST_BYTES)
    pointer = _read_pointer(manifest_blob)
    bundle = _download(_bundle_url(base, pointer), MAX_BUNDLE_BYTES)
    install_status = _extract_and_install(bundle, pointer)
    installed = store.initialize()
    return (
        f"published_generation={pointer['generation']} "
        f"installed_generation={installed['generation']} "
        f"status={install_status}"
    )


def main() -> int:
    base = os.getenv("TORRENT_CACHE_BUNDLE_BASE_URL", DEFAULT_BASE).strip()
    manifest_url = os.getenv(
        "TORRENT_CACHE_BUNDLE_MANIFEST_URL", DEFAULT_MANIFEST_URL
    ).strip()
    if not base or base.casefold() in {"off", "false", "0", "none"}:
        print(f"torrent cache bundle: disabled; {_installed_cache_status()}")
        return 0
    try:
        result = apply_torrent_cache_bundle(base, manifest_url or None)
        print(f"torrent cache bundle: {_installed_cache_status()} {result}")
    except (OSError, ValueError, tarfile.TarError, TorrentCacheError) as exc:
        print(
            f"torrent cache bundle: fetch_status=failed "
            f"published_generation=unknown {_installed_cache_status()}; "
            f"error={type(exc).__name__}: {exc}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
