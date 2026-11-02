import base64
import hashlib
import importlib.util
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


METADATA_PUBLISHER = _load_module(
    "metadata_cache_publisher", "scripts/publish_cache_bundle.py"
)
TORRENT_PUBLISHER = _load_module(
    "torrent_cache_publisher", "scripts/publish_torrent_cache_bundle.py"
)


class FakeGitHub:
    def __init__(self):
        self.lock = threading.RLock()
        self.assets: dict[str, bytes] = {}
        self.refs = {"main": "main-commit", "cache-manifests": "main-commit"}
        self.trees = {"main-tree": []}
        self.commits = {"main-commit": {"tree": {"sha": "main-tree"}, "parents": []}}
        self.blobs: dict[str, bytes] = {}
        self.branch_read_barrier: threading.Barrier | None = None
        self._barrier_reads = 0
        self.fail_next_pointer_update = False

    @staticmethod
    def _sha(value: bytes) -> str:
        return hashlib.sha1(value).hexdigest()

    @staticmethod
    def _result(command, value=None, *, status=0, stderr=""):
        stdout = json.dumps(value) if value is not None else ""
        if status:
            raise subprocess.CalledProcessError(
                status, command, output=stdout, stderr=stderr
            )
        return subprocess.CompletedProcess(command, status, stdout=stdout, stderr=stderr)

    def _api(self, command, endpoint: str, method: str, payload: dict | None):
        if endpoint == "git/ref/heads/cache-manifests":
            sha = self.refs.get("cache-manifests")
            if self.branch_read_barrier is not None and self._barrier_reads < 2:
                self._barrier_reads += 1
                barrier = self.branch_read_barrier
                if self._barrier_reads == 2:
                    self.branch_read_barrier = None
                barrier.wait(timeout=10)
            if sha is None:
                return self._result(command, status=1, stderr="404 Not Found")
            return self._result(command, {"object": {"sha": sha}})
        if endpoint == "git/ref/heads/main":
            return self._result(command, {"object": {"sha": self.refs["main"]}})
        if endpoint == "git/refs" and method == "POST":
            branch = payload["ref"].removeprefix("refs/heads/")
            if branch in self.refs:
                return self._result(command, status=1, stderr="422 Reference already exists")
            self.refs[branch] = payload["sha"]
            return self._result(command, {"object": {"sha": payload["sha"]}})
        if endpoint.startswith("git/commits/") and method == "GET":
            sha = endpoint.rsplit("/", 1)[1]
            return self._result(command, self.commits[sha])
        if endpoint.startswith("git/trees/") and method == "GET":
            tree_sha = endpoint.split("/", 2)[2].split("?", 1)[0]
            return self._result(command, {"tree": self.trees[tree_sha]})
        if endpoint.startswith("git/blobs/") and method == "GET":
            sha = endpoint.rsplit("/", 1)[1]
            return self._result(command, {
                "content": base64.b64encode(self.blobs[sha]).decode("ascii"),
                "encoding": "base64",
            })
        if endpoint == "git/blobs" and method == "POST":
            content = payload["content"].encode("utf-8")
            sha = self._sha(content)
            self.blobs[sha] = content
            return self._result(command, {"sha": sha})
        if endpoint == "git/trees" and method == "POST":
            entries = {
                item["path"]: item
                for item in self.trees[payload["base_tree"]]
            }
            for item in payload["tree"]:
                entries[item["path"]] = item
            ordered = [entries[key] for key in sorted(entries)]
            sha = self._sha(json.dumps(ordered, sort_keys=True).encode())
            self.trees[sha] = ordered
            return self._result(command, {"sha": sha})
        if endpoint == "git/commits" and method == "POST":
            sha = self._sha(json.dumps(payload, sort_keys=True).encode())
            self.commits[sha] = {
                "tree": {"sha": payload["tree"]},
                "parents": [{"sha": value} for value in payload["parents"]],
            }
            return self._result(command, {"sha": sha})
        if endpoint == "git/refs/heads/cache-manifests" and method == "PATCH":
            if self.fail_next_pointer_update:
                self.fail_next_pointer_update = False
                return self._result(command, status=1, stderr="403 Forbidden")
            current = self.refs["cache-manifests"]
            commit = self.commits[payload["sha"]]
            parent = commit["parents"][0]["sha"]
            if parent != current:
                return self._result(command, status=1, stderr="422 Reference update failed")
            self.refs["cache-manifests"] = payload["sha"]
            return self._result(command, {"object": {"sha": payload["sha"]}})
        raise AssertionError(f"Unexpected GitHub API call: {method} {endpoint}")

    def runner(self, command, **kwargs):
        if command[:3] == ["gh", "release", "view"]:
            with self.lock:
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="".join(f"{name}\n" for name in sorted(self.assets)),
                    stderr="",
                )
        if command[:3] == ["gh", "release", "upload"]:
            path = Path(command[4])
            with self.lock:
                if path.name in self.assets and "--clobber" not in command:
                    raise subprocess.CalledProcessError(1, command, stderr="asset exists")
                self.assets[path.name] = path.read_bytes()
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "release", "download"]:
            name = command[command.index("--pattern") + 1]
            directory = Path(command[command.index("--dir") + 1])
            with self.lock:
                content = self.assets.get(name)
                if content is None:
                    raise subprocess.CalledProcessError(1, command, stderr="asset missing")
                directory.mkdir(parents=True, exist_ok=True)
                (directory / name).write_bytes(content)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:2] == ["gh", "api"]:
            endpoint = command[2].split("/", 3)[3]
            method = "GET"
            if "--method" in command:
                method = command[command.index("--method") + 1]
            payload = json.loads(kwargs["input"]) if kwargs.get("input") else None
            if endpoint == "git/ref/heads/cache-manifests":
                return self._api(command, endpoint, method, payload)
            with self.lock:
                return self._api(command, endpoint, method, payload)
        raise AssertionError(f"Unexpected publisher command: {command}")

    def pointer(self, path: str) -> dict | None:
        with self.lock:
            commit = self.commits[self.refs["cache-manifests"]]
            tree = self.trees[commit["tree"]["sha"]]
            entry = next((item for item in tree if item["path"] == path), None)
            if entry is None:
                return None
            return json.loads(self.blobs[entry["sha"]])

    def synchronize_next_two_ref_reads(self):
        self.branch_read_barrier = threading.Barrier(2)
        self._barrier_reads = 0


def _metadata_bundle(directory: Path, version: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    archive_name = f"cache-bundle-{version}.tar.gz"
    archive = directory / archive_name
    archive.write_bytes(f"metadata archive {version}".encode())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = directory / "cache-bundle.json"
    manifest.write_text(json.dumps({
        "version": version,
        "sha256": digest,
        "bundle": archive_name,
    }), encoding="utf-8")
    legacy = directory / "cache-bundle.tar.gz"
    legacy.write_bytes(b"legacy metadata cache")
    return manifest, legacy


def _torrent_bundle(directory: Path, generation: int, identity: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    archive_bytes = f"torrent generation {generation}".encode()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    archive_name = f"torrent-cache-bundle-{generation}-{digest[:8]}.tar.gz"
    (directory / archive_name).write_bytes(archive_bytes)
    pointer = {
        "schemaVersion": 1,
        "generation": generation,
        "files": {"hollywood-torrents.json": {"sha256": identity * 64, "recordCount": 1}},
        "bundle": archive_name,
        "bundleSha256": digest,
    }
    manifest_path = directory / "torrent-cache-bundle.json"
    manifest_path.write_text(json.dumps(pointer), encoding="utf-8")
    return manifest_path


def test_concurrent_domain_publishers_use_cas_and_preserve_both_pointers(tmp_path):
    github = FakeGitHub()
    github.synchronize_next_two_ref_reads()
    torrent_manifest = _torrent_bundle(tmp_path / "torrent", 8, "a")
    metadata_manifest, legacy = _metadata_bundle(
        tmp_path / "metadata", "20250301T010203Z-aaaaaaaa"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        metadata_job = pool.submit(
            METADATA_PUBLISHER.publish_cache_bundle,
            metadata_manifest,
            legacy,
            "owner/repository",
            runner=github.runner,
        )
        torrent_job = pool.submit(
            TORRENT_PUBLISHER.publish_torrent_cache_bundle,
            torrent_manifest,
            "owner/repository",
            runner=github.runner,
        )
        metadata_job.result(timeout=30)
        torrent_job.result(timeout=30)

    metadata_pointer = github.pointer(METADATA_PUBLISHER.POINTER_PATH)
    torrent_pointer = github.pointer(TORRENT_PUBLISHER.POINTER_PATH)
    assert metadata_pointer["version"] == "20250301T010203Z-aaaaaaaa"
    assert torrent_pointer["generation"] == 8
    assert metadata_pointer["bundle"] in github.assets
    assert torrent_pointer["bundle"] in github.assets
    assert "cache-bundle.json" not in github.assets
    assert "torrent-cache-bundle.json" not in github.assets


def test_publishers_reject_stale_generations_after_cas_read(tmp_path):
    github = FakeGitHub()
    current, current_legacy = _metadata_bundle(
        tmp_path / "current", "20250302T010203Z-bbbbbbbb"
    )
    METADATA_PUBLISHER.publish_cache_bundle(
        current, current_legacy, "owner/repository", runner=github.runner
    )
    stale, stale_legacy = _metadata_bundle(
        tmp_path / "stale", "20250301T010203Z-aaaaaaaa"
    )
    with pytest.raises(RuntimeError, match="Refusing stale metadata"):
        METADATA_PUBLISHER.publish_cache_bundle(
            stale, stale_legacy, "owner/repository", runner=github.runner
        )
    assert github.pointer(METADATA_PUBLISHER.POINTER_PATH)["version"].startswith("20250302")

    latest_torrent = _torrent_bundle(tmp_path / "latest-torrent", 10, "a")
    TORRENT_PUBLISHER.publish_torrent_cache_bundle(
        latest_torrent, "owner/repository", runner=github.runner
    )
    old_torrent = _torrent_bundle(tmp_path / "old-torrent", 9, "b")
    with pytest.raises(RuntimeError, match="Refusing stale torrent"):
        TORRENT_PUBLISHER.publish_torrent_cache_bundle(
            old_torrent, "owner/repository", runner=github.runner
        )
    assert github.pointer(TORRENT_PUBLISHER.POINTER_PATH)["generation"] == 10


def test_failed_pointer_update_leaves_previous_manifest_available(tmp_path):
    github = FakeGitHub()
    previous, previous_legacy = _metadata_bundle(
        tmp_path / "previous", "20250301T010203Z-aaaaaaaa"
    )
    METADATA_PUBLISHER.publish_cache_bundle(
        previous, previous_legacy, "owner/repository", runner=github.runner
    )
    previous_pointer = github.pointer(METADATA_PUBLISHER.POINTER_PATH)
    incoming, incoming_legacy = _metadata_bundle(
        tmp_path / "incoming", "20250302T010203Z-bbbbbbbb"
    )
    github.fail_next_pointer_update = True

    with pytest.raises(subprocess.CalledProcessError):
        METADATA_PUBLISHER.publish_cache_bundle(
            incoming, incoming_legacy, "owner/repository", runner=github.runner
        )

    assert github.pointer(METADATA_PUBLISHER.POINTER_PATH) == previous_pointer
    assert f"cache-bundle-{json.loads(incoming.read_text())['version']}.tar.gz" in github.assets
