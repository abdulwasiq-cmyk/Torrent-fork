import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

import pytest
from fastapi import FastAPI, Response
from fastapi.middleware.gzip import GZipMiddleware
from catalogues import section_caches, torrent_caches
from fastapi.testclient import TestClient
from main import app

SEED_DIR = Path(__file__).resolve().parents[1] / "cache-seed"
ROOT = Path(__file__).resolve().parents[2]
EXPECTED_COUNTS = {
    "hollywood": 2400,
    "bollywood": 1934,
    "marvel": 3544,
    "dc": 2155,
    "highest-rated": 1014,
    "korean": 0,
    "pakistani": 0,
    "anime": 0,
    "favourites": 1706,
}


def test_large_api_responses_are_gzip_compressed():
    assert any(middleware.cls is GZipMiddleware for middleware in app.user_middleware)

    test_app = FastAPI()
    test_app.add_middleware(GZipMiddleware, minimum_size=500)
    payload = b"cached torrent data " * 200

    @test_app.get("/large")
    async def large_response():
        return Response(content=payload)

    response = TestClient(test_app).get(
        "/large",
        headers={"Accept-Encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.content == payload


def _load_torrent_bundle_builder():
    script = ROOT / "scripts" / "make_torrent_cache_bundle.py"
    spec = importlib.util.spec_from_file_location("make_torrent_cache_bundle", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_metadata_bundle_builder():
    script = ROOT / "scripts" / "make_cache_bundle.py"
    spec = importlib.util.spec_from_file_location("make_metadata_cache_bundle", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_torrent_bundle_fetcher():
    script = ROOT / "backend" / "maintenance" / "fetch_torrent_cache_bundle.py"
    spec = importlib.util.spec_from_file_location("fetch_torrent_cache_bundle_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_torrent_fetcher_builds_published_manifest_and_archive_urls():
    fetcher = _load_torrent_bundle_fetcher()
    pointer = {
        "generation": 1793595213,
        "bundle": "torrent-cache-bundle-1793595213-d5b636b7.tar.gz",
    }

    assert fetcher.DEFAULT_MANIFEST_URL == (
        "https://raw.githubusercontent.com/wroxtaaar/Torrent-Studio/"
        "cache-manifests/cache-bundles/torrent.json"
    )
    assert fetcher._manifest_url(
        fetcher.DEFAULT_BASE,
        fetcher.DEFAULT_MANIFEST_URL,
        "12345",
    ) == (
        "https://raw.githubusercontent.com/wroxtaaar/Torrent-Studio/"
        "cache-manifests/cache-bundles/torrent.json?cacheBust=12345"
    )
    assert fetcher._bundle_url(fetcher.DEFAULT_BASE, pointer) == (
        "https://github.com/wroxtaaar/Torrent-Studio/releases/download/cache-data/"
        "torrent-cache-bundle-1793595213-d5b636b7.tar.gz?generation=1793595213"
    )


@pytest.mark.parametrize("invocation", ["script", "module"])
def test_torrent_fetcher_imports_in_script_and_module_modes(tmp_path, invocation):
    fetcher_path = ROOT / "backend" / "maintenance" / "fetch_torrent_cache_bundle.py"
    runtime_dir = tmp_path / "app-data"
    env = os.environ.copy()
    env.update({
        "APP_DATA_DIR": str(runtime_dir),
        "TORRENT_CACHE_SEED_DIR": str(ROOT / "backend" / "cache-seed"),
        "TORRENT_CACHE_BUNDLE_BASE_URL": "off",
    })
    env.pop("PYTHONPATH", None)
    if invocation == "script":
        command = [sys.executable, str(fetcher_path)]
        cwd = tmp_path
    else:
        command = [sys.executable, "-m", "maintenance.fetch_torrent_cache_bundle"]
        cwd = ROOT / "backend"

    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "torrent cache bundle: disabled" in result.stdout
    assert "cache_readiness=ready installed_generation=1" in result.stdout
    assert "cache_source=baked-in-seed" in result.stdout


def test_torrent_fetch_failure_logs_fallback_generation_and_readiness(
    tmp_path, monkeypatch, capsys
):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=7)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    fetcher = _load_torrent_bundle_fetcher()
    monkeypatch.setattr(fetcher, "store", store)
    monkeypatch.setattr(fetcher, "TORRENT_CACHE_DIR", runtime_dir)
    monkeypatch.setenv("TORRENT_CACHE_BUNDLE_BASE_URL", "https://example.invalid/releases")
    monkeypatch.setenv("TORRENT_CACHE_BUNDLE_MANIFEST_URL", "https://example.invalid/torrent.json")

    def fail_download(_url, _limit):
        raise OSError("HTTP Error 404: Not Found")

    monkeypatch.setattr(fetcher, "_download", fail_download)

    assert fetcher.main() == 0

    output = capsys.readouterr().out
    assert "fetch_status=failed" in output
    assert "published_generation=unknown" in output
    assert "cache_readiness=ready" in output
    assert "installed_generation=7" in output
    assert "cache_source=baked-in-seed" in output


def test_docker_fetches_torrent_bundle_before_starting_api():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    torrent_fetch = "python -m maintenance.fetch_torrent_cache_bundle"
    api_start = "uvicorn fullstack_app:app"

    assert torrent_fetch in dockerfile
    assert dockerfile.index(torrent_fetch) < dockerfile.index(api_start)


def _write_fixture_cache(seed_dir: Path, generation: int = 1) -> dict[str, dict]:
    seed_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for index, section in enumerate(torrent_caches.TORRENT_CACHE_NAMES, start=1):
        identity = index.to_bytes(20, "big").hex()
        document = {
            "schemaVersion": 1,
            "section": section,
            "records": [{
                "identityKind": "infoHash",
                "identity": identity,
                "infoHash": identity,
                "magnetUrl": f"magnet:?xt=urn:btih:{identity}",
                "title": f"{section} cached result",
                "provider": "ExistingIndexer",
                "seeders": 5,
            }],
        }
        content = json.dumps(document, sort_keys=True).encode()
        filename = f"{section}-torrents.json"
        (seed_dir / filename).write_bytes(content)
        files[filename] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "recordCount": len(document["records"]),
        }
    manifest = {
        "schemaVersion": 1,
        "generation": generation,
        "files": files,
        "globalUniqueNormalizedInfoHashes": len(files),
        "sectionLevelEntries": len(files),
    }
    (seed_dir / torrent_caches.SEED_MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return manifest


def _write_runtime_manifest(runtime_dir: Path, seed_manifest: dict, generation: int) -> dict:
    files = {}
    for filename in torrent_caches.TORRENT_CACHE_FILES:
        content = (runtime_dir / filename).read_bytes()
        records = json.loads(content)["records"]
        files[filename] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "recordCount": len(records),
        }
    manifest = {
        **seed_manifest,
        "generation": generation,
        "files": files,
    }
    (runtime_dir / torrent_caches.RUNTIME_MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return manifest


def test_all_nine_bundled_torrent_caches_load_with_approved_counts(tmp_path):
    store = torrent_caches.TorrentCacheStore(SEED_DIR, tmp_path / "torrent-cache")
    total = 0
    for section, expected_count in EXPECTED_COUNTS.items():
        document, generation = store.load_section(section)
        assert generation == 1
        assert len(document["records"]) == expected_count
        total += len(document["records"])
    assert total == 12753


def test_metadata_endpoint_response_remains_the_seed_document():
    section = "hollywood"
    expected = json.loads((section_caches.SECTION_CACHE_DIR / f"{section}.json").read_text())
    response = TestClient(app).get(f"/api/sections/{section}")
    assert response.status_code == 200
    assert response.json() == expected
    assert "torrentCache" not in response.json()


def test_torrent_endpoint_returns_independent_document_and_generation(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    manifest = _write_fixture_cache(seed_dir)
    store = torrent_caches.TorrentCacheStore(seed_dir, tmp_path / "data" / "torrent-cache")
    monkeypatch.setattr(torrent_caches, "store", store)
    response = TestClient(app).get("/api/sections/hollywood/torrents")
    assert response.status_code == 200
    assert response.headers["x-torrent-cache-generation"] == "1"
    assert response.json()["section"] == "hollywood"
    assert response.json()["records"][0]["provider"] == "ExistingIndexer"
    assert response.json()["records"][0]["magnetUrl"].startswith("magnet:?xt=")
    assert response.json()["records"] == store.load_section("hollywood")[0]["records"]
    assert len(manifest["files"]) == 9


def test_existing_persistent_files_take_precedence_over_seed(tmp_path):
    seed_dir = tmp_path / "seed"
    seed_manifest = _write_fixture_cache(seed_dir)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    runtime_dir.mkdir(parents=True)
    for filename in torrent_caches.TORRENT_CACHE_FILES:
        (runtime_dir / filename).write_bytes((seed_dir / filename).read_bytes())

    section_file = runtime_dir / "hollywood-torrents.json"
    persistent = json.loads(section_file.read_text())
    persistent["records"][0]["title"] = "Persistent newer result"
    section_file.write_text(json.dumps(persistent, sort_keys=True))
    _write_runtime_manifest(runtime_dir, seed_manifest, generation=99)

    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    loaded, generation = store.load_section("hollywood")
    assert generation == 99
    assert loaded["records"][0]["title"] == "Persistent newer result"
    assert json.loads(section_file.read_text())["records"][0]["title"] == "Persistent newer result"
    assert json.loads((runtime_dir / "current" / section_file.name).read_text())["records"][0]["title"] == "Persistent newer result"
    assert (runtime_dir / ".generations" / torrent_caches.TorrentCacheStore._generation_name(99)).is_dir()


def test_missing_persistent_files_initialize_from_seed_without_overwriting_existing(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    runtime_dir.mkdir(parents=True)
    existing = runtime_dir / "hollywood-torrents.json"
    existing.write_bytes((seed_dir / existing.name).read_bytes())
    before = existing.read_bytes()

    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    document, generation = store.load_section("hollywood")

    assert generation == 1
    assert len(document["records"]) == 1
    assert existing.read_bytes() == before
    assert all((runtime_dir / "current" / filename).is_file() for filename in torrent_caches.TORRENT_CACHE_FILES)
    assert (runtime_dir / "current" / torrent_caches.RUNTIME_MANIFEST_NAME).is_file()


def test_torrent_generation_switch_is_atomic_and_retains_previous_generation(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=1)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    previous_target = (runtime_dir / "current").readlink()
    previous_generation = runtime_dir / previous_target

    staged_dir = tmp_path / "staged-generation-2"
    incoming = _write_fixture_cache(staged_dir, generation=2)
    (staged_dir / torrent_caches.RUNTIME_MANIFEST_NAME).write_text(
        json.dumps(incoming), encoding="utf-8"
    )
    assert store.install_bundle(staged_dir, incoming) == "installed"

    assert (runtime_dir / "current").is_symlink()
    assert json.loads((runtime_dir / "current" / torrent_caches.RUNTIME_MANIFEST_NAME).read_text())["generation"] == 2
    assert previous_generation.is_dir()
    assert json.loads((previous_generation / torrent_caches.RUNTIME_MANIFEST_NAME).read_text())["generation"] == 1


def test_interrupted_staging_does_not_change_active_generation(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=1)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    active = (runtime_dir / "current").readlink()
    interrupted = runtime_dir / ".staging" / "generation-2-interrupted"
    interrupted.mkdir(parents=True)
    (interrupted / "partial.json").write_text("{")

    restarted = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    manifest = restarted.initialize()

    assert manifest["generation"] == 1
    assert (runtime_dir / "current").readlink() == active
    assert restarted.ready is True


def test_all_nine_documents_validate_before_readiness(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    (runtime_dir / "current" / "korean-torrents.json").write_text("{corrupt")

    restarted = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    with pytest.raises(torrent_caches.TorrentCacheError, match="checksum mismatch"):
        restarted.initialize()
    assert restarted.ready is False


def test_torrent_cache_readiness_endpoint_requires_all_documents(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    store = torrent_caches.TorrentCacheStore(seed_dir, tmp_path / "data" / "torrent-cache")
    monkeypatch.setattr(torrent_caches, "store", store)

    response = TestClient(app).get("/api/torrent-cache/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "generation": 1}
    assert store.ready is True
    (tmp_path / "data" / "torrent-cache" / "current" / "korean-torrents.json").write_text(
        "{corrupt", encoding="utf-8"
    )
    failed = TestClient(app).get("/api/torrent-cache/ready")
    assert failed.status_code == 503
    assert store.ready is False


def test_application_startup_initializes_all_torrent_sections(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    store = torrent_caches.TorrentCacheStore(seed_dir, tmp_path / "data" / "torrent-cache")
    monkeypatch.setattr(torrent_caches, "store", store)

    torrent_caches.initialize_torrent_cache()

    assert store.ready is True
    assert (store.runtime_dir / "current").is_symlink()
    assert {
        path.name
        for path in (store.runtime_dir / "current").glob("*-torrents.json")
    } == set(torrent_caches.TORRENT_CACHE_FILES)


def test_fetcher_installs_verified_generation_as_one_pointer_switch(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=1)
    output_dir = tmp_path / "release"
    pointer = _load_torrent_bundle_builder().make_torrent_cache_bundle(
        seed_dir, output_dir, generation=2
    )
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    fetcher = _load_torrent_bundle_fetcher()
    monkeypatch.setattr(fetcher, "store", store)
    monkeypatch.setattr(fetcher, "TORRENT_CACHE_DIR", runtime_dir)
    archive = (output_dir / pointer["bundle"]).read_bytes()

    assert fetcher._extract_and_install(archive, pointer) == "installed"
    document, generation = store.load_section("hollywood")
    assert generation == 2
    assert len(document["records"]) == 1
    assert (runtime_dir / ".generations" / store._generation_name(1)).is_dir()


def test_fetcher_rejects_bad_bundle_without_switching_current_generation(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=1)
    output_dir = tmp_path / "release"
    pointer = _load_torrent_bundle_builder().make_torrent_cache_bundle(
        seed_dir, output_dir, generation=2
    )
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    current_link = (runtime_dir / "current").readlink()
    fetcher = _load_torrent_bundle_fetcher()
    monkeypatch.setattr(fetcher, "store", store)
    monkeypatch.setattr(fetcher, "TORRENT_CACHE_DIR", runtime_dir)
    archive = bytearray((output_dir / pointer["bundle"]).read_bytes())
    archive[-1] ^= 0x01

    with pytest.raises(ValueError, match="archive checksum mismatch"):
        fetcher._extract_and_install(bytes(archive), pointer)

    assert (runtime_dir / "current").readlink() == current_link
    assert store.load_section("hollywood")[1] == 1


def test_torrent_bundle_contains_only_nine_torrent_files_and_manifest(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    output_dir = tmp_path / "release"

    pointer = _load_torrent_bundle_builder().make_torrent_cache_bundle(
        seed_dir, output_dir, generation=2
    )

    with tarfile.open(output_dir / pointer["bundle"], "r:gz") as archive:
        assert set(archive.getnames()) == {
            *torrent_caches.TORRENT_CACHE_FILES,
            torrent_caches.RUNTIME_MANIFEST_NAME,
        }
    assert pointer["generation"] == 2
    assert set(pointer["files"]) == set(torrent_caches.TORRENT_CACHE_FILES)


def test_metadata_bundle_builder_excludes_torrent_artifacts(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    for section in torrent_caches.TORRENT_CACHE_NAMES:
        (seed_dir / f"{section}.json").write_text(json.dumps({
            "section": section,
            "metadataSelfContained": True,
            "subsections": {},
        }))
    for filename in (
        *torrent_caches.TORRENT_CACHE_FILES,
        torrent_caches.SEED_MANIFEST_NAME,
        "torrent-cache-bundle.json",
        "torrent-cache-bundle-999-deadbeef.tar.gz",
    ):
        (seed_dir / filename).write_text("{}")
    regional = seed_dir / "runtime" / "regional_movie_prebuilt_cache.json"
    regional.parent.mkdir()
    regional_payload = {
        "movies": {
            "sample|2024": {
                "movie": {"title": "Sample"},
                "torrentDetails": {"results": [{"infoHash": "ab" * 20}]},
            }
        }
    }
    regional.write_text(json.dumps(regional_payload), encoding="utf-8")
    legacy_catalogue = seed_dir / "marvel_catalogue.json"
    legacy_catalogue.write_text(json.dumps({"results": [{"infoHash": "cd" * 20}]}), encoding="utf-8")
    regional_before = regional.read_bytes()
    legacy_before = legacy_catalogue.read_bytes()

    builder = _load_metadata_bundle_builder()
    monkeypatch.setattr(builder, "prepare_section_documents", lambda _seed: None)
    monkeypatch.setattr(builder.subprocess, "run", lambda *_args, **_kwargs: None)
    output_dir = tmp_path / "release"
    pointer = builder.make_cache_bundle(seed_dir, output_dir)

    with tarfile.open(output_dir / pointer["bundle"], "r:gz") as archive:
        members = set(archive.getnames())
        bundled_regional = json.load(archive.extractfile("runtime/regional_movie_prebuilt_cache.json"))
    assert {f"{section}.json" for section in torrent_caches.TORRENT_CACHE_NAMES} <= members
    assert "runtime/regional_movie_prebuilt_cache.json" in members
    assert "marvel_catalogue.json" not in members
    assert "torrentDetails" not in json.dumps(bundled_regional)
    assert regional.read_bytes() == regional_before
    assert legacy_catalogue.read_bytes() == legacy_before
    assert not any(
        name.endswith("-torrents.json")
        or name in {torrent_caches.SEED_MANIFEST_NAME, "torrent-cache-bundle.json"}
        or name.startswith("torrent-cache-bundle-")
        for name in members
    )


def test_older_bundle_cannot_replace_newer_persistent_generation(tmp_path):
    seed_dir = tmp_path / "seed"
    seed_manifest = _write_fixture_cache(seed_dir)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    runtime_dir.mkdir(parents=True)
    for filename in torrent_caches.TORRENT_CACHE_FILES:
        (runtime_dir / filename).write_bytes((seed_dir / filename).read_bytes())
    _write_runtime_manifest(runtime_dir, seed_manifest, generation=5)

    staged_dir = tmp_path / "older-bundle"
    staged_dir.mkdir()
    for filename in torrent_caches.TORRENT_CACHE_FILES:
        (staged_dir / filename).write_bytes((seed_dir / filename).read_bytes())
    older_manifest = _write_runtime_manifest(staged_dir, seed_manifest, generation=2)
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)

    assert store.install_bundle(staged_dir, older_manifest) == "older-bundle-ignored"
    assert json.loads((runtime_dir / "current" / torrent_caches.RUNTIME_MANIFEST_NAME).read_text())[
        "generation"
    ] == 5


def test_invalid_incoming_generation_never_changes_active_pointer(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir, generation=1)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.initialize()
    current_link = (runtime_dir / "current").readlink()
    staged_dir = tmp_path / "incoming-generation-2"
    incoming = _write_fixture_cache(staged_dir, generation=2)
    (staged_dir / torrent_caches.RUNTIME_MANIFEST_NAME).write_text(
        json.dumps(incoming), encoding="utf-8"
    )
    (staged_dir / "korean-torrents.json").write_text("{invalid")

    with pytest.raises(torrent_caches.TorrentCacheError, match="checksum mismatch"):
        store.install_bundle(staged_dir, incoming)

    assert (runtime_dir / "current").readlink() == current_link
    assert json.loads((runtime_dir / "current" / torrent_caches.RUNTIME_MANIFEST_NAME).read_text())[
        "generation"
    ] == 1


def test_corrupt_persistent_file_fails_without_falling_back_to_seed(tmp_path):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    runtime_dir = tmp_path / "data" / "torrent-cache"
    store = torrent_caches.TorrentCacheStore(seed_dir, runtime_dir)
    store.load_section("hollywood")
    corrupt = runtime_dir / "current" / "hollywood-torrents.json"
    corrupt.write_text("{corrupt json", encoding="utf-8")

    with pytest.raises(torrent_caches.TorrentCacheError, match="checksum mismatch"):
        store.load_section("hollywood")
    assert corrupt.read_text() == "{corrupt json"


def test_loader_does_not_make_provider_or_http_requests(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    _write_fixture_cache(seed_dir)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("torrent-cache loading must not make HTTP requests")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    document, _generation = torrent_caches.TorrentCacheStore(
        seed_dir, tmp_path / "data" / "torrent-cache"
    ).load_section("marvel")
    assert document["records"][0]["provider"] == "ExistingIndexer"
    assert calls == []


def test_torrent_endpoint_rejects_unknown_section():
    response = TestClient(app).get("/api/sections/not-a-section/torrents")
    assert response.status_code == 404
