#!/usr/bin/env python3
"""Publish an immutable torrent-only archive, then advance its separate pointer."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
import tempfile
from typing import Any

try:
    from cache_bundle_pointer import advance_pointer
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cache_bundle_pointer import advance_pointer

BUNDLE_MANIFEST_NAME = "torrent-cache-bundle.json"
POINTER_PATH = "cache-bundles/torrent.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read torrent bundle manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise TypeError("Torrent bundle manifest must be an object")
    generation = manifest.get("generation")
    bundle = manifest.get("bundle")
    digest = manifest.get("bundleSha256")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise ValueError("Torrent bundle manifest has an invalid generation")
    if not isinstance(bundle, str) or Path(bundle).name != bundle:
        raise ValueError("Torrent bundle manifest has an invalid archive name")
    if not bundle.startswith(f"torrent-cache-bundle-{generation}-") or not bundle.endswith(".tar.gz"):
        raise ValueError("Torrent bundle archive name does not match its generation")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Torrent bundle manifest has an invalid archive checksum")
    return manifest


def _release_assets(
    tag: str,
    repository: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> set[str]:
    result = runner(
        [
            "gh", "release", "view", tag, "-R", repository,
            "--json", "assets", "--jq", ".assets[].name",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _remote_manifest(
    tag: str,
    repository: str,
    assets: set[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any] | None:
    if BUNDLE_MANIFEST_NAME not in assets:
        return None
    with tempfile.TemporaryDirectory(prefix="torrent-cache-publish-") as directory:
        runner(
            [
                "gh", "release", "download", tag, "-R", repository,
                "--pattern", BUNDLE_MANIFEST_NAME, "--dir", directory, "--clobber",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return _read_manifest(Path(directory) / BUNDLE_MANIFEST_NAME)


def _publish_torrent_cache_bundle_locked(
    manifest_path: Path,
    repository: str,
    *,
    tag: str = "cache-data",
    pointer_branch: str = "cache-manifests",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> set[str]:
    manifest = _read_manifest(manifest_path)
    bundle_path = manifest_path.parent / manifest["bundle"]
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Manifest-referenced archive does not exist: {bundle_path}")
    actual = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if actual.lower() != manifest["bundleSha256"].lower():
        raise ValueError("Torrent bundle archive checksum does not match its manifest")

    assets = _release_assets(tag, repository, runner)
    if manifest["bundle"] not in assets:
        runner(
            ["gh", "release", "upload", tag, str(bundle_path), "-R", repository],
            check=True,
        )
        assets = _release_assets(tag, repository, runner)
    if manifest["bundle"] not in assets:
        raise RuntimeError("GitHub release is missing the immutable torrent bundle")

    with tempfile.TemporaryDirectory(prefix="torrent-cache-verify-") as directory:
        runner(
            [
                "gh", "release", "download", tag, "-R", repository,
                "--pattern", manifest["bundle"], "--dir", directory, "--clobber",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        remote_bundle = Path(directory) / manifest["bundle"]
        if not remote_bundle.is_file() or hashlib.sha256(remote_bundle.read_bytes()).hexdigest().lower() != manifest["bundleSha256"].lower():
            raise RuntimeError(
                f"GitHub immutable torrent asset failed verification: {manifest['bundle']}"
            )

    def same_or_stale(incoming: dict[str, Any], current: dict[str, Any]) -> bool:
        if incoming["generation"] < current["generation"]:
            raise RuntimeError(
                f"Refusing stale torrent generation {incoming['generation']}; "
                f"GitHub already has {current['generation']}"
            )
        if incoming["generation"] == current["generation"]:
            if incoming.get("files") != current.get("files"):
                raise RuntimeError("Conflicting torrent bundles have the same generation")
            return True
        return False

    advance_pointer(
        repository,
        POINTER_PATH,
        manifest,
        same_or_stale,
        label="torrent",
        branch=pointer_branch,
        runner=runner,
    )
    final_assets = _release_assets(tag, repository, runner)
    if manifest["bundle"] not in final_assets:
        raise RuntimeError("GitHub release is missing the immutable torrent bundle")
    print(
        f"Published torrent bundle generation={manifest['generation']} "
        f"asset={manifest['bundle']} pointer={pointer_branch}:{POINTER_PATH}"
    )
    return final_assets


def publish_torrent_cache_bundle(
    manifest_path: Path,
    repository: str,
    *,
    tag: str = "cache-data",
    pointer_branch: str = "cache-manifests",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> set[str]:
    manifest_path = Path(manifest_path)
    lock_path = manifest_path.parent / ".torrent-cache-publish.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _publish_torrent_cache_bundle_locked(
                manifest_path,
                repository,
                tag=tag,
                pointer_branch=pointer_branch,
                runner=runner,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", default="cache-data")
    parser.add_argument("--pointer-branch", default="cache-manifests")
    args = parser.parse_args()
    publish_torrent_cache_bundle(
        args.manifest,
        args.repository,
        tag=args.tag,
        pointer_branch=args.pointer_branch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
