import hashlib
import io
import json
import sys
import tarfile
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintenance"))
import fetch_cache_bundle as fcb  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def make_bundle(dirpath: Path, files: dict[str, bytes], version="v1", sha=None):
    dirpath.mkdir(parents=True, exist_ok=True)
    section_names = (
        "hollywood", "bollywood", "marvel", "dc", "highest-rated",
        "korean", "pakistani", "anime", "favourites",
    )
    section_files = {
        f"{section}.json": json.dumps({
            "section": section,
            "metadataSelfContained": True,
            "subsections": {"movies": {"results": []}},
        }).encode()
        for section in section_names
    }
    section_files.update(files)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in section_files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()
    bundle_name = f"cache-bundle-{version}.tar.gz"
    (dirpath / bundle_name).write_bytes(blob)
    (dirpath / "cache-bundle.tar.gz").write_bytes(blob)
    (dirpath / "cache-bundle.json").write_text(json.dumps({
        "version": version,
        "sha256": sha or hashlib.sha256(blob).hexdigest(),
        "bundle": bundle_name,
    }))


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    requests = []

    class CapturingHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            super().do_GET()

    handler = partial(CapturingHandler, directory=str(root))
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_port}", requests
    httpd.shutdown()


def seed_dir(tmp_path):
    seed = tmp_path / "seed"
    (seed / "pages").mkdir(parents=True)
    (seed / "pages" / "old.json.gz").write_bytes(b"x")
    (seed / "marvel.json").write_text(json.dumps({
        "section": "marvel",
        "metadataSelfContained": False,
        "subsections": {"movies": {"results": [{"title": "Old"}]}},
    }))
    return seed


def test_installs_bundle_and_replaces_pages_and_cache_busts_requests(tmp_path, server):
    root, base, requests = server
    make_bundle(root, {"marvel.json": json.dumps({
                           "section": "marvel",
                           "metadataSelfContained": True,
                           "subsections": {"movies": {"results": [{"title": "New"}]}},
                       }).encode(),
                       "runtime/imdb_rating_cache.json": b"{}",
                       "pages/marvel/1.json.gz": b"gz"})
    seed = seed_dir(tmp_path)
    result = fcb.apply_bundle(seed, base)
    assert "manifest_version=v1" in result
    assert f"downloaded_sha256={hashlib.sha256((root / 'cache-bundle-v1.tar.gz').read_bytes()).hexdigest()}" in result
    assert "installed_version=v1" in result
    assert "status=installed" in result
    assert json.loads((seed / "marvel.json").read_text())["subsections"]["movies"]["results"] == [{"title": "New"}]
    assert (seed / "runtime" / "imdb_rating_cache.json").is_file()
    assert (seed / "pages" / "marvel" / "1.json.gz").is_file() and not (seed / "pages" / "old.json.gz").exists()
    assert "status=already-current" in fcb.apply_bundle(seed, base)

    manifest_request = urlsplit(requests[0])
    assert manifest_request.path.endswith("/cache-bundle.json")
    cache_bust = parse_qs(manifest_request.query).get("cacheBust")
    assert cache_bust and cache_bust[0]
    bundle_request = urlsplit(requests[1])
    assert bundle_request.path.endswith("/cache-bundle-v1.tar.gz")
    assert parse_qs(bundle_request.query).get("version") == ["v1"]


def test_stale_or_mismatched_bundle_is_rejected_without_changing_seed(tmp_path, server):
    root, base, _requests = server
    make_bundle(root, {"marvel_catalogue.json": b'{"new": 1}'}, sha="0" * 64)
    seed = seed_dir(tmp_path)
    before = {
        path.relative_to(seed): path.read_bytes()
        for path in seed.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError, match="checksum mismatch") as exc_info:
        fcb.apply_bundle(seed, base)
    assert "manifest_version=v1" in str(exc_info.value)
    assert "downloaded_sha256=" in str(exc_info.value)
    after = {
        path.relative_to(seed): path.read_bytes()
        for path in seed.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (seed / fcb.VERSION_FILE).exists()


def test_corrupt_json_and_unsafe_paths_rejected(tmp_path, server):
    root, base, _requests = server
    seed = seed_dir(tmp_path)
    make_bundle(root, {"marvel.json": b"{not json"}, version="v2")
    with pytest.raises(ValueError):
        fcb.apply_bundle(seed, base)
    make_bundle(root, {"../evil.json": b"{}"}, version="v3")
    with pytest.raises(ValueError):
        fcb.apply_bundle(seed, base)
    assert json.loads((seed / "marvel.json").read_text())["metadataSelfContained"] is False
    assert not (tmp_path / "evil.json").exists()


def test_main_never_raises_when_unreachable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CACHE_BUNDLE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CACHE_SEED_DIR", str(seed_dir(tmp_path)))
    assert fcb.main() == 0
    assert "skipped" in capsys.readouterr().out


def test_old_pages_directory_is_never_renamed(tmp_path, server, monkeypatch):
    """In a Docker image the baked-in `pages` directory cannot be renamed (cross-device link)."""
    import os
    real_rename = os.rename

    def picky_rename(src, dst, *a, **k):
        if Path(src).name == "pages":
            raise OSError(18, "Invalid cross-device link")
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(os, "rename", picky_rename)
    monkeypatch.setattr(Path, "rename", lambda self, target: picky_rename(self, target))
    root, base, _requests = server
    make_bundle(root, {"marvel.json": json.dumps({
                           "section": "marvel",
                           "metadataSelfContained": True,
                           "subsections": {"movies": {"results": [{"title": "New"}]}},
                       }).encode(),
                       "pages/marvel/1.json.gz": b"gz"})
    seed = seed_dir(tmp_path)
    assert "status=installed" in fcb.apply_bundle(seed, base)
    assert (seed / "pages" / "marvel" / "1.json.gz").is_file() and not (seed / "pages" / "old.json.gz").exists()
    assert json.loads((seed / "marvel.json").read_text())["section"] == "marvel"


def test_failed_bundle_download_leaves_existing_seed_untouched(tmp_path, server):
    root, base, _requests = server
    manifest = {
        "version": "v2",
        "sha256": "0" * 64,
        "bundle": "missing-v2.tar.gz",
    }
    (root / "cache-bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    seed = seed_dir(tmp_path)
    before = {
        path.relative_to(seed): path.read_bytes()
        for path in seed.rglob("*")
        if path.is_file()
    }

    with pytest.raises(HTTPError):
        fcb.apply_bundle(seed, base)

    after = {
        path.relative_to(seed): path.read_bytes()
        for path in seed.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (seed / fcb.VERSION_FILE).exists()


def test_bundle_with_invalid_section_document_is_rejected_before_install(tmp_path, server):
    root, base, _requests = server
    make_bundle(root, {"marvel.json": json.dumps({
        "section": "marvel",
        "metadataSelfContained": False,
        "subsections": {},
    }).encode()})
    seed = seed_dir(tmp_path)
    before = (seed / "marvel.json").read_bytes()

    with pytest.raises(ValueError, match="metadataSelfContained must be true"):
        fcb.apply_bundle(seed, base)

    assert (seed / "marvel.json").read_bytes() == before
    assert not (seed / fcb.VERSION_FILE).exists()


def test_cache_publisher_uploads_immutable_bundle_before_replacing_manifest():
    publisher = (ROOT / "scripts/vps/refresh_and_publish.sh").read_text(encoding="utf-8")
    publish_helper = (ROOT / "scripts/publish_cache_bundle.py").read_text(encoding="utf-8")
    publisher_call = publisher.index("repo/scripts/publish_cache_bundle.py")
    deploy_hook = publisher.index('curl -fsS -X POST "$RENDER_DEPLOY_HOOK"')

    assert publisher_call < deploy_hook
    assert 'asset_name = manifest["bundle"]' in publish_helper
    assert 'str(immutable_bundle)' in publish_helper
    assert "required_names = {manifest_path.name, legacy_bundle_path.name, asset_name}" in publish_helper
