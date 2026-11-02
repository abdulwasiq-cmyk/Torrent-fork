"""Load the independent, persistent torrent-cache documents."""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import unicodedata
from pathlib import Path
from typing import Any

from core.settings import TORRENT_CACHE_DIR, TORRENT_CACHE_SEED_DIR
from core.torrent_size import filter_torrent_records
from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter()
logger = logging.getLogger("torrent-studio")

TORRENT_CACHE_NAMES = (
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
TORRENT_CACHE_FILES = tuple(f"{name}-torrents.json" for name in TORRENT_CACHE_NAMES)
SEED_MANIFEST_NAME = "torrent-cache-manifest.json"
RUNTIME_MANIFEST_NAME = "manifest.json"
_INFO_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MOVIE_TITLE_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)
_LOCK = threading.RLock()


class TorrentCacheError(RuntimeError):
    """Raised when a torrent cache cannot be verified or safely initialized."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise TorrentCacheError(f"Could not read torrent cache file {path.name}") from exc
    return digest.hexdigest()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TorrentCacheError(f"Could not read torrent cache manifest {path.name}") from exc
    return _validate_manifest(manifest, path.name)


def _validate_manifest(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schemaVersion") != 1:
        raise TorrentCacheError(f"{label} has an invalid schema version")
    generation = value.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        raise TorrentCacheError(f"{label} has an invalid generation")
    files = value.get("files")
    if not isinstance(files, dict) or set(files) != set(TORRENT_CACHE_FILES):
        raise TorrentCacheError(f"{label} must describe exactly nine torrent files")
    for filename, details in files.items():
        if (
            not isinstance(details, dict)
            or not isinstance(details.get("sha256"), str)
            or not _SHA256_RE.fullmatch(details["sha256"])
            or isinstance(details.get("recordCount"), bool)
            or not isinstance(details.get("recordCount"), int)
            or details["recordCount"] < 0
        ):
            raise TorrentCacheError(f"{label} has invalid metadata for {filename}")
    return value


def _read_document(path: Path, section: str, expected_count: int | None = None) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TorrentCacheError(f"Could not read torrent cache document {path.name}") from exc
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or document.get("section") != section
        or not isinstance(document.get("records"), list)
    ):
        raise TorrentCacheError(f"{path.name} has an invalid torrent-cache structure")
    records = document["records"]
    if expected_count is not None and len(records) != expected_count:
        raise TorrentCacheError(f"{path.name} record count does not match its manifest")
    identities: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise TorrentCacheError(f"{path.name} contains a non-object record")
        identity = record.get("identity")
        if (
            record.get("identityKind") != "infoHash"
            or not isinstance(identity, str)
            or not _INFO_HASH_RE.fullmatch(identity)
            or record.get("infoHash") != identity
            or identity in identities
        ):
            raise TorrentCacheError(f"{path.name} contains an invalid or duplicate info hash")
        identities.add(identity)
    return document


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


class TorrentCacheStore:
    def __init__(self, seed_dir: Path, runtime_dir: Path):
        self.seed_dir = Path(seed_dir)
        self.runtime_dir = Path(runtime_dir)
        self._manifest: dict[str, Any] | None = None
        self._lock = _LOCK
        self._validated_signatures: dict[tuple[int, str], tuple[int, int, int]] = {}
        self._movie_record_indexes: dict[
            tuple[int, str], dict[str, tuple[dict[str, Any], ...]]
        ] = {}
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    @staticmethod
    def _generation_name(generation: int) -> str:
        return f"generation-{generation:020d}"

    def _active_directory(self) -> Path | None:
        current = self.runtime_dir / "current"
        if not current.is_symlink():
            if current.exists():
                raise TorrentCacheError("Torrent cache current pointer is not a symlink")
            return None
        try:
            generation_dir = current.resolve(strict=True)
        except OSError as exc:
            raise TorrentCacheError("Torrent cache current pointer is broken") from exc
        generations_dir = (self.runtime_dir / ".generations").resolve()
        try:
            generation_dir.relative_to(generations_dir)
        except ValueError as exc:
            raise TorrentCacheError("Torrent cache current pointer escapes its generation directory") from exc
        return generation_dir

    def _seed_manifest_and_validate(self) -> dict[str, Any]:
        manifest = _read_manifest(self.seed_dir / SEED_MANIFEST_NAME)
        for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
            path = self.seed_dir / filename
            details = manifest["files"][filename]
            if _sha256_file(path) != details["sha256"]:
                raise TorrentCacheError(f"Seed torrent cache checksum mismatch: {filename}")
            _read_document(path, section, details["recordCount"])
        return manifest

    def _validate_generation(self, generation_dir: Path) -> dict[str, Any]:
        manifest = _read_manifest(generation_dir / RUNTIME_MANIFEST_NAME)
        for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
            path = generation_dir / filename
            if not path.is_file():
                raise TorrentCacheError(f"Persistent torrent cache is missing {filename}")
            self._validate_file(generation_dir, manifest, section, filename)
        return manifest

    def _validate_file(
        self,
        generation_dir: Path,
        manifest: dict[str, Any],
        section: str,
        filename: str,
    ) -> None:
        path = generation_dir / filename
        stat = path.stat()
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        cache_key = (manifest["generation"], filename)
        if self._validated_signatures.get(cache_key) == signature:
            return
        details = manifest["files"][filename]
        if _sha256_file(path) != details["sha256"]:
            raise TorrentCacheError(f"Persistent torrent cache checksum mismatch: {filename}")
        _read_document(path, section, details["recordCount"])
        self._validated_signatures[cache_key] = signature

    def _install_generation_locked(
        self,
        manifest: dict[str, Any],
        source_files: dict[str, Path],
    ) -> Path:
        generations_dir = self.runtime_dir / ".generations"
        generations_dir.mkdir(parents=True, exist_ok=True)
        generation_dir = generations_dir / self._generation_name(manifest["generation"])

        if generation_dir.exists():
            existing = self._validate_generation(generation_dir)
            if existing["files"] != manifest["files"]:
                raise TorrentCacheError(
                    "Conflicting torrent cache contents have the same generation"
                )
        else:
            temporary = Path(tempfile.mkdtemp(
                prefix=f".{self._generation_name(manifest['generation'])}.",
                dir=generations_dir,
            ))
            try:
                for filename in TORRENT_CACHE_FILES:
                    _atomic_write(temporary / filename, source_files[filename].read_bytes())
                _atomic_write(
                    temporary / RUNTIME_MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
                    + b"\n",
                )
                self._validate_generation(temporary)
                os.rename(temporary, generation_dir)
                generations_fd = os.open(generations_dir, os.O_RDONLY)
                try:
                    os.fsync(generations_fd)
                finally:
                    os.close(generations_fd)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise

        current = self.runtime_dir / "current"
        temporary_link = self.runtime_dir / f".current-{os.getpid()}-{threading.get_ident()}"
        temporary_link.unlink(missing_ok=True)
        os.symlink(
            os.path.relpath(generation_dir, self.runtime_dir),
            temporary_link,
        )
        os.replace(temporary_link, current)
        directory_fd = os.open(self.runtime_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return generation_dir

    def _initialize_legacy_directory(self) -> dict[str, Any]:
        legacy_manifest = self.runtime_dir / RUNTIME_MANIFEST_NAME
        seed_manifest = self._seed_manifest_and_validate()
        manifest = _read_manifest(legacy_manifest) if legacy_manifest.is_file() else seed_manifest
        source_files: dict[str, Path] = {}
        for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
            persistent = self.runtime_dir / filename
            details = manifest["files"][filename]
            if persistent.is_file():
                if _sha256_file(persistent) != details["sha256"]:
                    raise TorrentCacheError(f"Unverified persistent torrent cache file: {filename}")
                _read_document(persistent, section, details["recordCount"])
                source_files[filename] = persistent
            else:
                seed_details = seed_manifest["files"][filename]
                if (
                    seed_manifest["generation"] != manifest["generation"]
                    or seed_details != details
                ):
                    raise TorrentCacheError(
                        f"Cannot initialize missing persistent file from another generation: {filename}"
                    )
                source_files[filename] = self.seed_dir / filename

        self._install_generation_locked(manifest, source_files)
        return manifest

    def _initialize_locked(self) -> dict[str, Any]:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        active = self._active_directory()
        if active is None:
            manifest = self._initialize_legacy_directory()
            active = self._active_directory()
        else:
            manifest = _read_manifest(active / RUNTIME_MANIFEST_NAME)
            if active.name != self._generation_name(manifest["generation"]):
                raise TorrentCacheError(
                    "Torrent cache generation directory does not match its manifest"
                )
        if active is None:
            raise TorrentCacheError("Torrent cache generation was not activated")
        for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
            self._validate_file(active, manifest, section, filename)
        self._manifest = manifest
        self._ready = True
        return manifest

    def initialize(self) -> dict[str, Any]:
        with self._lock:
            lock_handle = _file_lock(self.runtime_dir.parent / ".torrent-cache.lock")
            try:
                self._ready = False
                return self._initialize_locked()
            except Exception:
                self._ready = False
                raise
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                lock_handle.close()

    def load_section(self, section: str) -> tuple[dict[str, Any], int]:
        if section not in TORRENT_CACHE_NAMES:
            raise KeyError(section)
        with self._lock:
            lock_handle = _file_lock(self.runtime_dir.parent / ".torrent-cache.lock")
            try:
                self._ready = False
                manifest = self._initialize_locked()
                active = self._active_directory()
                if active is None:
                    raise TorrentCacheError("Torrent cache generation was not activated")
                filename = f"{section}-torrents.json"
                self._validate_file(active, manifest, section, filename)
                document = _read_document(
                    active / filename,
                    section,
                    manifest["files"][filename]["recordCount"],
                )
                document["records"], _ = filter_torrent_records(document["records"])
                self._ready = True
                return document, manifest["generation"]
            except Exception:
                self._ready = False
                raise
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                lock_handle.close()

    @staticmethod
    def _normalized_movie_title(title: str) -> str:
        decomposed = unicodedata.normalize("NFKD", title).casefold()
        unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
        return " ".join(_MOVIE_TITLE_SEPARATORS.sub(" ", unaccented.replace("&", " and ")).split())

    def movie_records(
        self,
        section: str,
        *,
        tmdb_id: str | None,
        imdb_id: str | None,
        title: str | None,
        year: int | None,
    ) -> tuple[list[dict[str, Any]], int]:
        if section not in TORRENT_CACHE_NAMES:
            raise KeyError(section)
        with self._lock:
            generation = self.initialize()["generation"]
            index_key = (generation, section)
            index = self._movie_record_indexes.get(index_key)
            if index is None:
                document, loaded_generation = self.load_section(section)
                if loaded_generation != generation:
                    raise TorrentCacheError("Torrent cache generation changed during movie lookup")
                mutable_index: dict[str, list[dict[str, Any]]] = {}
                for record in document["records"]:
                    for identity in record.get("mediaIdentities", []):
                        if not isinstance(identity, dict) or identity.get("mediaType") != "movie":
                            continue
                        keys = []
                        if identity.get("tmdbId") is not None:
                            keys.append(f"tmdb:{str(identity['tmdbId']).casefold()}")
                        if identity.get("imdbId"):
                            keys.append(f"imdb:{str(identity['imdbId']).casefold()}")
                        identity_title = self._normalized_movie_title(str(identity.get("title") or ""))
                        identity_year = str(identity.get("year") or "")[:4]
                        if identity_title and identity_year:
                            keys.append(f"title-year:{identity_title}|{identity_year}")
                        for key in keys:
                            mutable_index.setdefault(key, []).append(record)
                index = {
                    key: tuple(records)
                    for key, records in mutable_index.items()
                }
                self._movie_record_indexes = {
                    key: value
                    for key, value in self._movie_record_indexes.items()
                    if key[0] == generation
                }
                self._movie_record_indexes[index_key] = index

            stable_matches: dict[str, dict[str, Any]] = {}
            for kind, identifier in (("tmdb", tmdb_id), ("imdb", imdb_id)):
                if identifier:
                    for record in index.get(f"{kind}:{identifier.casefold()}", ()):
                        stable_matches[str(record["identity"])] = record
                    if stable_matches:
                        break

            selected = stable_matches
            if not selected and title and year is not None:
                title_key = self._normalized_movie_title(title)
                selected = {
                    str(record["identity"]): record
                    for record in index.get(f"title-year:{title_key}|{year}", ())
                }
            return list(selected.values()), generation

    def install_bundle(self, staged_dir: Path, bundle_manifest: dict[str, Any]) -> str:
        staged_dir = Path(staged_dir)
        incoming = _validate_manifest(bundle_manifest, "torrent bundle manifest")
        embedded = _read_manifest(staged_dir / RUNTIME_MANIFEST_NAME)
        if embedded["generation"] != incoming["generation"] or embedded["files"] != incoming["files"]:
            raise TorrentCacheError("Torrent bundle manifest does not match its archive")
        for section, filename in zip(TORRENT_CACHE_NAMES, TORRENT_CACHE_FILES):
            path = staged_dir / filename
            details = incoming["files"][filename]
            if _sha256_file(path) != details["sha256"]:
                raise TorrentCacheError(f"Torrent bundle checksum mismatch: {filename}")
            _read_document(path, section, details["recordCount"])

        with self._lock:
            lock_handle = _file_lock(self.runtime_dir.parent / ".torrent-cache.lock")
            try:
                self._initialize_locked()
                active = self._active_directory()
                if active is None:
                    raise TorrentCacheError("Torrent cache generation was not activated")
                current = _read_manifest(active / RUNTIME_MANIFEST_NAME)
                if incoming["generation"] < current["generation"]:
                    return "older-bundle-ignored"
                if incoming["generation"] == current["generation"]:
                    if incoming["files"] != current["files"]:
                        raise TorrentCacheError(
                            "Conflicting torrent bundles have the same generation"
                        )
                    return "already-current"
                generation_dir = self._install_generation_locked(
                    incoming,
                    {filename: staged_dir / filename for filename in TORRENT_CACHE_FILES},
                )
                self._validate_generation(generation_dir)
                self._manifest = incoming
                self._ready = True
                return "installed"
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
                lock_handle.close()


store = TorrentCacheStore(TORRENT_CACHE_SEED_DIR, TORRENT_CACHE_DIR)


def initialize_torrent_cache() -> None:
    store.initialize()


@router.get("/api/torrent-cache/ready")
async def api_torrent_cache_ready() -> dict[str, Any]:
    try:
        manifest = store.initialize()
    except TorrentCacheError as exc:
        logger.error("Torrent cache readiness check failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Torrent cache is unavailable or failed integrity validation",
        ) from exc
    return {"status": "ready", "generation": manifest["generation"]}


@router.get("/api/sections/{section}/torrents")
async def api_get_torrent_cache(section: str, response: Response) -> dict[str, Any]:
    if section not in TORRENT_CACHE_NAMES:
        raise HTTPException(status_code=404, detail="Torrent cache not found")
    try:
        document, generation = store.load_section(section)
    except TorrentCacheError as exc:
        logger.error("Torrent cache unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Torrent cache is unavailable or failed integrity validation",
        ) from exc
    response.headers["X-Torrent-Cache-Generation"] = str(generation)
    return document


@router.get("/api/sections/{section}/torrent-options")
async def api_get_movie_torrent_options(
    section: str,
    response: Response,
    tmdb_id: str | None = Query(None, min_length=1, max_length=64, pattern=r"^\d+$"),
    imdb_id: str | None = Query(None, min_length=1, max_length=32),
    title: str | None = Query(None, min_length=1, max_length=256),
    year: int | None = Query(None, ge=1800, le=3000),
) -> dict[str, Any]:
    if section not in TORRENT_CACHE_NAMES:
        raise HTTPException(status_code=404, detail="Torrent cache not found")
    if not tmdb_id and not imdb_id and not (title and year is not None):
        raise HTTPException(
            status_code=422,
            detail="Provide a TMDB ID, IMDb ID, or both a movie title and year",
        )
    try:
        records, generation = store.movie_records(
            section,
            tmdb_id=tmdb_id.strip() if tmdb_id else None,
            imdb_id=imdb_id.strip() if imdb_id else None,
            title=title,
            year=year,
        )
    except TorrentCacheError as exc:
        logger.error("Movie torrent cache unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Torrent cache is unavailable or failed integrity validation",
        ) from exc
    response.headers["X-Torrent-Cache-Generation"] = str(generation)
    return {"schemaVersion": 1, "section": section, "records": records}
