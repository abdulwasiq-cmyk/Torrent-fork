#!/usr/bin/env python3
"""Pack a seed directory into a validated cache bundle and versioned manifest.

    python scripts/make_cache_bundle.py <seed_dir> <out_dir>

Pre-splits catalogue pages and self-contains section metadata before packaging.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = (
    "hollywood",
    "bollywood",
    "marvel",
    "dc",
    "highest-rated",
    "korean",
    "pakistani",
    "anime",
    "favourites",
)


def section_documents_are_valid(seed: Path) -> bool:
    for section in SECTIONS:
        try:
            document: Any = json.loads((seed / f"{section}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if (
            not isinstance(document, dict)
            or document.get("section") != section
            or document.get("metadataSelfContained") is not True
            or not isinstance(document.get("subsections"), dict)
        ):
            return False
    return True


def prepare_section_documents(seed: Path) -> None:
    """Repair legacy section files from local caches; never package invalid API documents."""
    builder = ROOT / "scripts" / "build_self_contained_section_cache.py"
    validator = ROOT / "scripts" / "validate_section_caches.py"
    if not section_documents_are_valid(seed):
        subprocess.run(
            [
                sys.executable,
                str(builder),
                "--source-dir",
                str(seed),
                "--cache-dir",
                str(seed / "runtime"),
                "--regional-tv-cache",
                str(seed / "regional_tv_prebuilt_cache.json"),
                "--output-dir",
                str(seed),
            ],
            check=True,
        )
    subprocess.run(
        [
            sys.executable,
            str(validator),
            "--seed",
            str(seed),
            "--require-all",
            "--require-self-contained",
        ],
        check=True,
    )


def make_cache_bundle(seed: Path, out: Path) -> dict[str, Any]:
    seed = seed.resolve()
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    prepare_section_documents(seed)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "backend" / "maintenance" / "build_catalogue_pages.py"),
            str(seed),
        ],
        check=True,
    )

    bundle = out / "cache-bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        for path in sorted(seed.rglob("*")):
            relative = path.relative_to(seed)
            if (
                path.is_file()
                and relative.name not in ("README.md", ".bundle-version")
                and "pages.old" not in relative.parts
            ):
                json.loads(path.read_bytes()) if path.suffix == ".json" else None
                tar.add(path, arcname=relative.as_posix())

    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + digest[:8]
    immutable_bundle_name = f"cache-bundle-{version}.tar.gz"
    shutil.copy2(bundle, out / immutable_bundle_name)
    manifest = {
        "version": version,
        "sha256": digest,
        "size": bundle.stat().st_size,
        "bundle": immutable_bundle_name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    (out / "cache-bundle.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))
    return manifest


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: make_cache_bundle.py <seed_dir> <out_dir>")
    make_cache_bundle(Path(sys.argv[1]), Path(sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
