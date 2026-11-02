#!/usr/bin/env python3
"""Publish a versioned cache archive before advancing the rolling release manifest."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

try:
    from cache_bundle_pointer import advance_pointer
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cache_bundle_pointer import advance_pointer

POINTER_PATH = "cache-bundles/metadata.json"

def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read cache bundle manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Cache bundle manifest must be an object")

    version = manifest.get("version")
    bundle_name = manifest.get("bundle")
    expected_hash = manifest.get("sha256")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("Cache bundle manifest has no version")
    if not isinstance(bundle_name, str) or Path(bundle_name).name != bundle_name:
        raise ValueError("Cache bundle manifest has an invalid bundle filename")
    if bundle_name != f"cache-bundle-{version}.tar.gz":
        raise ValueError(
            "Cache bundle filename does not match manifest version: "
            f"{bundle_name!r} != {f'cache-bundle-{version}.tar.gz'!r}"
        )
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("Cache bundle manifest has an invalid SHA-256")
    return manifest


def _release_asset_names(
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
    manifest_name = "cache-bundle.json"
    if manifest_name not in assets:
        return None
    with tempfile.TemporaryDirectory(prefix="metadata-cache-publish-") as directory:
        runner(
            [
                "gh", "release", "download", tag, "-R", repository,
                "--pattern", manifest_name, "--dir", directory, "--clobber",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return _read_manifest(Path(directory) / manifest_name)


def _version_timestamp(manifest: dict[str, Any]) -> str:
    version = manifest["version"]
    match = re.match(r"^(\d{8}T\d{6}Z)(?:-|$)", version)
    if not match:
        raise ValueError(f"Cannot determine metadata bundle generation from version {version!r}")
    return match.group(1)


def _check_generation(incoming: dict[str, Any], current: dict[str, Any]) -> bool:
    incoming_generation = _version_timestamp(incoming)
    current_generation = _version_timestamp(current)
    if incoming_generation < current_generation:
        raise RuntimeError(
            f"Refusing stale metadata generation {incoming_generation}; "
            f"GitHub already has {current_generation}"
        )
    if incoming_generation == current_generation:
        if (
            incoming["version"] != current["version"]
            or incoming["sha256"].lower() != current["sha256"].lower()
        ):
            raise RuntimeError("Conflicting metadata bundles have the same generation")
        return True
    return False


def _publish_cache_bundle_locked(
    manifest_path: Path,
    legacy_bundle_path: Path,
    repository: str,
    *,
    tag: str = "cache-data",
    pointer_branch: str = "cache-manifests",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> set[str]:
    manifest = _read_manifest(manifest_path)
    version = manifest["version"]
    asset_name = manifest["bundle"]
    immutable_bundle = manifest_path.parent / asset_name
    if not immutable_bundle.is_file():
        raise FileNotFoundError(f"Manifest-referenced archive does not exist: {immutable_bundle}")

    actual_hash = hashlib.sha256(immutable_bundle.read_bytes()).hexdigest()
    if actual_hash.lower() != manifest["sha256"].lower():
        raise ValueError(
            f"Manifest-referenced archive checksum mismatch: {asset_name} "
            f"({actual_hash} != {manifest['sha256']})"
        )

    uploaded_names = _release_asset_names(tag, repository, runner)
    if asset_name not in uploaded_names:
        runner(
            ["gh", "release", "upload", tag, str(immutable_bundle), "-R", repository],
            check=True,
        )
        uploaded_names = _release_asset_names(tag, repository, runner)
    if asset_name not in uploaded_names:
        raise RuntimeError(f"GitHub release is missing uploaded immutable asset {asset_name}")
    with tempfile.TemporaryDirectory(prefix="metadata-cache-verify-") as directory:
        runner(
            [
                "gh", "release", "download", tag, "-R", repository,
                "--pattern", asset_name, "--dir", directory, "--clobber",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        remote_archive = Path(directory) / asset_name
        if not remote_archive.is_file() or hashlib.sha256(remote_archive.read_bytes()).hexdigest().lower() != manifest["sha256"].lower():
            raise RuntimeError(f"GitHub immutable metadata asset failed verification: {asset_name}")

    advance_pointer(
        repository,
        POINTER_PATH,
        manifest,
        _check_generation,
        label="metadata",
        branch=pointer_branch,
        runner=runner,
    )
    final_names = _release_asset_names(tag, repository, runner)
    if asset_name not in final_names:
        raise RuntimeError(f"GitHub release lost immutable metadata asset {asset_name}")
    print(
        f"Published cache bundle version={version} asset={asset_name} "
        f"pointer={pointer_branch}:{POINTER_PATH}"
    )
    return final_names


def publish_cache_bundle(
    manifest_path: Path,
    legacy_bundle_path: Path,
    repository: str,
    *,
    tag: str = "cache-data",
    pointer_branch: str = "cache-manifests",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> set[str]:
    manifest_path = Path(manifest_path)
    lock_path = manifest_path.parent / ".metadata-cache-publish.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return _publish_cache_bundle_locked(
                manifest_path,
                legacy_bundle_path,
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
    parser.add_argument("--legacy-bundle", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", default="cache-data")
    parser.add_argument("--pointer-branch", default="cache-manifests")
    args = parser.parse_args()
    publish_cache_bundle(
        args.manifest,
        args.legacy_bundle,
        args.repository,
        tag=args.tag,
        pointer_branch=args.pointer_branch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
