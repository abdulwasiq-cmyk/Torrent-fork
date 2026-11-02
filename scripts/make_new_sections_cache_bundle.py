#!/usr/bin/env python3
"""Pack only the selected new-section cache files; do not run page builders."""
import hashlib
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("usage: make_new_sections_cache_bundle.py <seed_dir> <out_dir>")

seed, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
selected = (
    Path("runtime/regional_movie_prebuilt_cache.json"),
    Path("regional_tv_prebuilt_cache.json"),
)
out.mkdir(parents=True, exist_ok=True)
files = []
for rel in selected:
    source = seed / rel
    if not source.is_file():
        raise SystemExit(f"required targeted cache missing: {source}")
    json.loads(source.read_text(encoding="utf-8"))
    files.append((source, rel))

bundle = out / "cache-bundle.tar.gz"
with tarfile.open(bundle, "w:gz") as tar:
    for source, rel in files:
        tar.add(source, arcname=rel.as_posix())

digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
manifest = {
    "version": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-sections-" + digest[:8],
    "sha256": digest,
    "size": bundle.stat().st_size,
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "scope": [rel.as_posix() for _, rel in files],
}
(out / "cache-bundle.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest))
