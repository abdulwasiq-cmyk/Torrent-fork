#!/usr/bin/env python3
"""Publish a versioned cache archive before advancing the rolling release manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable


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


def publish_cache_bundle(
    manifest_path: Path,
    legacy_bundle_path: Path,
    repository: str,
    *,
    tag: str = "cache-data",
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

    # GitHub release assets use the uploaded path's basename. Verify the remote asset before
    # advancing the mutable manifest, so clients can never observe a dangling version reference.
    uploaded_names = _release_asset_names(tag, repository, runner)
    if asset_name not in uploaded_names:
        runner(
            ["gh", "release", "upload", tag, str(immutable_bundle), "-R", repository],
            check=True,
        )
        uploaded_names = _release_asset_names(tag, repository, runner)
    if asset_name not in uploaded_names:
        raise RuntimeError(f"GitHub release is missing uploaded immutable asset {asset_name}")

    runner(
        ["gh", "release", "upload", tag, str(legacy_bundle_path), "-R", repository, "--clobber"],
        check=True,
    )
    runner(
        ["gh", "release", "upload", tag, str(manifest_path), "-R", repository, "--clobber"],
        check=True,
    )

    final_names = _release_asset_names(tag, repository, runner)
    required_names = {manifest_path.name, legacy_bundle_path.name, asset_name}
    missing = required_names - final_names
    if missing:
        raise RuntimeError(f"GitHub release is missing expected cache assets: {sorted(missing)}")
    print(
        f"Published cache bundle version={version} asset={asset_name} "
        f"assets={','.join(sorted(required_names))}"
    )
    return final_names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--legacy-bundle", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", default="cache-data")
    args = parser.parse_args()
    publish_cache_bundle(args.manifest, args.legacy_bundle, args.repository, tag=args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
