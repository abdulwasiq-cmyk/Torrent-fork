#!/usr/bin/env python3
"""Best-effort: overlay the latest published cache bundle onto the bundled seed.

Runs at container start, before the app. The rolling manifest points to an immutable
versioned bundle asset published by the refresh job on the VPS. Any problem
(offline, bad checksum, corrupt JSON, unsafe archive) leaves the seed baked into the image
untouched, and this script always exits 0 so it can never stop the app from starting.

Env: CACHE_BUNDLE_BASE_URL (default: the cache-data release; "off" disables),
     CACHE_SEED_DIR (default /app/cache-seed).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_BASE = "https://github.com/wroxtaaar/Torrent-Studio/releases/download/cache-data"
VERSION_FILE = ".bundle-version"
MANIFEST = "cache-bundle.json"
BUNDLE = "cache-bundle.tar.gz"
MAX_BYTES = 120 * 1024 * 1024
SECTION_FILES = (
    "hollywood.json",
    "bollywood.json",
    "marvel.json",
    "dc.json",
    "highest-rated.json",
    "korean.json",
    "pakistani.json",
    "anime.json",
    "favourites.json",
)


def _get(url: str, timeout: float, limit: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "torrent-studio-cache-fetch/1",
            "Cache-Control": "no-cache, no-store",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("download too large")
    return data


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.isdir():
            continue
        if not m.isreg() or m.name.startswith("/") or ".." in parts:
            raise ValueError(f"unsafe archive member: {m.name}")
        members.append(m)
    return members


def _validate_section_documents(stage: Path) -> None:
    for filename in SECTION_FILES:
        path = stage / filename
        if not path.is_file():
            raise ValueError(f"bundle is missing required section document: {filename}")
        document = json.loads(path.read_text(encoding="utf-8"))
        section = Path(filename).stem
        if not isinstance(document, dict):
            raise ValueError(f"{filename}: document must be an object")
        if document.get("section") != section:
            raise ValueError(f"{filename}: section must equal {section!r}")
        if document.get("metadataSelfContained") is not True:
            raise ValueError(f"{filename}: metadataSelfContained must be true")
        if not isinstance(document.get("subsections"), dict):
            raise ValueError(f"{filename}: subsections must be an object")


def _write_version_marker(path: Path, version: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(version)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def apply_bundle(seed: Path, base: str) -> str:
    base = base.rstrip("/")
    manifest_url = _with_query(f"{base}/{MANIFEST}", cacheBust=str(time.time_ns()))
    manifest = json.loads(_get(manifest_url, 10, 1024 * 1024))
    if not isinstance(manifest, dict):
        raise ValueError("invalid cache bundle manifest")
    version = manifest.get("version")
    expected_sha256 = manifest.get("sha256")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("cache bundle manifest has no version")
    version = version.strip()
    print(f"cache bundle: manifest_version={version}")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise ValueError("cache bundle manifest has an invalid SHA-256")
    version_path = seed / VERSION_FILE
    if version_path.is_file() and version_path.read_text().strip() == version:
        return (
            f"manifest_version={version} downloaded_sha256=not-downloaded "
            f"installed_version={version} status=already-current"
        )

    bundle_name = manifest.get("bundle", BUNDLE)
    if (
        not isinstance(bundle_name, str)
        or Path(bundle_name).name != bundle_name
        or not bundle_name.endswith(".tar.gz")
    ):
        raise ValueError("cache bundle manifest has an invalid bundle asset name")
    bundle_url = _with_query(
        f"{base}/{bundle_name}",
        version=version,
    )
    blob = _get(bundle_url, 90)
    downloaded_sha256 = hashlib.sha256(blob).hexdigest()
    if downloaded_sha256.lower() != expected_sha256.lower():
        raise ValueError(
            f"checksum mismatch manifest_version={version} "
            f"downloaded_sha256={downloaded_sha256} expected_sha256={expected_sha256}"
        )

    with tempfile.TemporaryDirectory(prefix="cache-bundle-", dir=str(seed.parent)) as tmp:
        stage = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            members = _safe_members(tar)
            for m in members:
                dest = stage / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        for f in stage.rglob("*.json"):  # refuse to install anything that does not parse
            json.loads(f.read_text(encoding="utf-8"))
        _validate_section_documents(stage)

        # Replace the pre-split pages as a unit. In a container image the old `pages` directory sits in a
        # read-only lower layer and cannot be renamed (EXDEV), so build the new one beside it, delete
        # the old one, and only rename the directory we just created ourselves.
        if (stage / "pages").is_dir():
            new_pages = seed / "pages.new"
            shutil.rmtree(new_pages, ignore_errors=True)
            shutil.copytree(stage / "pages", new_pages)
            shutil.rmtree(seed / "pages", ignore_errors=True)
            os.rename(new_pages, seed / "pages")
        for f in stage.rglob("*"):
            if f.is_file() and f.relative_to(stage).parts[0] != "pages":
                dest = seed / f.relative_to(stage)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))  # falls back to copy when a rename is not possible
    _write_version_marker(version_path, version)
    return (
        f"manifest_version={version} downloaded_sha256={downloaded_sha256} "
        f"installed_version={version} status=installed"
    )


def main() -> int:
    base = os.getenv("CACHE_BUNDLE_BASE_URL", DEFAULT_BASE).strip()
    if not base or base.lower() in ("off", "false", "0", "none"):
        print("cache bundle: disabled")
        return 0
    seed = Path(os.getenv("CACHE_SEED_DIR", "/app/cache-seed"))
    try:
        print("cache bundle:", apply_bundle(seed, base))
    except Exception as exc:  # never block startup
        version_path = seed / VERSION_FILE
        installed_version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "baked-in"
        print(
            f"cache bundle: skipped ({type(exc).__name__}: {exc}); "
            f"installed_version={installed_version}; using the existing seed"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
