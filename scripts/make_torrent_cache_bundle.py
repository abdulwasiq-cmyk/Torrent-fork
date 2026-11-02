#!/usr/bin/env python3
"""Create a checksum-verified torrent-only cache bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from catalogues.torrent_caches import (
    RUNTIME_MANIFEST_NAME,
    SEED_MANIFEST_NAME,
    TORRENT_CACHE_FILES,
    TORRENT_CACHE_NAMES,
    TorrentCacheError,
    _read_document,
    _validate_manifest,
)

BUNDLE_PREFIX = "torrent-cache-bundle-"
BUNDLE_MANIFEST_NAME = "torrent-cache-bundle.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_seed_manifest(seed_dir: Path, generation: int = 1) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    hashes: set[str] = set()
    section_entries = 0
    for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
        path = seed_dir / filename
        document = _read_document(path, section)
        records = document["records"]
        section_entries += len(records)
        hashes.update(record["identity"] for record in records)
        files[filename] = {"sha256": _sha256(path), "recordCount": len(records)}
    manifest = {
        "schemaVersion": 1,
        "generation": generation,
        "createdAt": datetime.now(UTC).isoformat(),
        "source": "repository-seed",
        "files": files,
        "globalUniqueNormalizedInfoHashes": len(hashes),
        "sectionLevelEntries": section_entries,
    }
    return _validate_manifest(manifest, "generated seed manifest")


def write_seed_manifest(seed_dir: Path, generation: int = 1) -> dict[str, Any]:
    manifest = create_seed_manifest(seed_dir, generation)
    path = seed_dir / SEED_MANIFEST_NAME
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def make_torrent_cache_bundle(
    seed_dir: Path,
    output_dir: Path,
    *,
    generation: int | None = None,
) -> dict[str, Any]:
    seed_dir = seed_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    seed_manifest = _validate_manifest(
        json.loads((seed_dir / SEED_MANIFEST_NAME).read_text(encoding="utf-8")),
        SEED_MANIFEST_NAME,
    )
    for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
        path = seed_dir / filename
        details = seed_manifest["files"][filename]
        if _sha256(path) != details["sha256"]:
            raise TorrentCacheError(f"Seed torrent cache checksum mismatch: {filename}")
        _read_document(path, section, details["recordCount"])

    next_generation = generation if generation is not None else int(time.time())
    if next_generation < seed_manifest["generation"]:
        raise ValueError("Bundle generation cannot be older than the seed generation")
    bundle_manifest = dict(seed_manifest)
    bundle_manifest.update({
        "generation": next_generation,
        "createdAt": datetime.now(UTC).isoformat(),
        "source": "github-versioned-torrent-bundle",
    })

    staged_manifest = output_dir / RUNTIME_MANIFEST_NAME
    staged_manifest.write_text(
        json.dumps(bundle_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_bundle = output_dir / "torrent-cache-bundle.tar.gz"
    with tarfile.open(temporary_bundle, "w:gz") as archive:
        for filename in (*TORRENT_CACHE_FILES, RUNTIME_MANIFEST_NAME):
            archive.add(
                seed_dir / filename if filename != RUNTIME_MANIFEST_NAME else staged_manifest,
                arcname=filename if filename != RUNTIME_MANIFEST_NAME else RUNTIME_MANIFEST_NAME,
            )
    bundle_sha256 = _sha256(temporary_bundle)
    bundle_name = f"{BUNDLE_PREFIX}{next_generation}-{bundle_sha256[:8]}.tar.gz"
    immutable_bundle = output_dir / bundle_name
    temporary_bundle.replace(immutable_bundle)
    staged_manifest.unlink()

    pointer = {
        **bundle_manifest,
        "bundle": bundle_name,
        "bundleSha256": bundle_sha256,
    }
    (output_dir / BUNDLE_MANIFEST_NAME).write_text(
        json.dumps(pointer, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return pointer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("seed_dir", type=Path)
    parser.add_argument("output_dir", type=Path, nargs="?")
    parser.add_argument("--generation", type=int)
    parser.add_argument(
        "--write-seed-manifest",
        action="store_true",
        help="Create the repository seed manifest instead of a versioned archive.",
    )
    args = parser.parse_args()
    if args.write_seed_manifest:
        manifest = write_seed_manifest(args.seed_dir, args.generation or 1)
    else:
        if args.output_dir is None:
            parser.error("output_dir is required unless --write-seed-manifest is used")
        manifest = make_torrent_cache_bundle(
            args.seed_dir,
            args.output_dir,
            generation=args.generation,
        )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
