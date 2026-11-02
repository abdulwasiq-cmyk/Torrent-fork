#!/usr/bin/env python3
"""Refresh only the nine torrent section files from the local torrent-search API."""

from __future__ import annotations

import argparse
import asyncio
import base64
import fcntl
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

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
TORRENT_FILES = tuple(f"{section}-torrents.json" for section in SECTIONS)
SEED_MANIFEST = "torrent-cache-manifest.json"
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
_MISSING = (None, "")
Searcher = Callable[[str], Awaitable[list[dict[str, Any]]]]


def normalize_info_hash(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.casefold()
    if re.fullmatch(r"[a-z2-7]{32}", text):
        try:
            text = base64.b32decode(text.upper()).hex()
        except (ValueError, base64.binascii.Error):
            return ""
    return text if _HASH_RE.fullmatch(text) else ""


def result_info_hash(result: dict[str, Any]) -> str:
    direct = normalize_info_hash(result.get("infoHash") or result.get("identity"))
    if direct:
        return direct
    magnet = str(result.get("magnetUrl") or "")
    match = re.search(r"(?:^|[?&])xt=urn:btih:([^&\s]+)", magnet, re.IGNORECASE)
    if not match:
        match = re.search(r"btih:([^&\s]+)", magnet, re.IGNORECASE)
    if not match:
        return ""
    return normalize_info_hash(urllib.parse.unquote(match.group(1)))


def _read_manifest(seed_dir: Path) -> dict[str, Any]:
    path = seed_dir / SEED_MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read torrent manifest: {path}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schemaVersion") != 1
        or isinstance(manifest.get("generation"), bool)
        or not isinstance(manifest.get("generation"), int)
        or manifest["generation"] < 1
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != set(TORRENT_FILES)
    ):
        raise ValueError("Torrent manifest has an invalid schema or file set")
    for filename in TORRENT_FILES:
        details = manifest["files"][filename]
        if not isinstance(details, dict) or not re.fullmatch(
            r"[0-9a-f]{64}", str(details.get("sha256") or "")
        ):
            raise ValueError(f"Torrent manifest has invalid checksum metadata for {filename}")
    return manifest


def _read_section(seed_dir: Path, section: str, manifest: dict[str, Any]) -> dict[str, Any]:
    filename = f"{section}-torrents.json"
    path = seed_dir / filename
    try:
        content = path.read_bytes()
        document = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read torrent section document: {filename}") from exc
    details = manifest["files"][filename]
    if hashlib.sha256(content).hexdigest() != details["sha256"]:
        raise ValueError(f"Torrent section checksum mismatch: {filename}")
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != 1
        or document.get("section") != section
        or not isinstance(document.get("records"), list)
        or len(document["records"]) != details.get("recordCount")
    ):
        raise ValueError(f"Torrent section document has an invalid structure: {filename}")
    seen: set[str] = set()
    for record in document["records"]:
        if not isinstance(record, dict):
            raise ValueError(f"Torrent section document contains a non-object record: {filename}")
        identity = normalize_info_hash(record.get("identity"))
        if (
            record.get("identityKind") != "infoHash"
            or not identity
            or identity != record.get("identity")
            or identity != normalize_info_hash(record.get("infoHash"))
            or identity in seen
        ):
            raise ValueError(f"Torrent section document has an invalid/duplicate hash: {filename}")
        seen.add(identity)
    return document


def _metadata_cards(seed_dir: Path, section: str) -> list[dict[str, Any]]:
    path = seed_dir / f"{section}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read metadata section document: {path.name}") from exc
    subsections = document.get("subsections") if isinstance(document, dict) else None
    if not isinstance(subsections, dict):
        raise ValueError(f"Metadata section has no subsection map: {path.name}")

    cards: dict[tuple[str, ...], dict[str, Any]] = {}
    for subsection_name, subsection in subsections.items():
        if not isinstance(subsection, dict):
            continue
        rows = subsection.get("results")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("name") or "").strip()
            if not title:
                continue
            media_type = str(
                row.get("mediaType") or subsection.get("mediaType") or "movie"
            ).strip().casefold()
            year = row.get("year")
            stable_ids = {
                name: row[name]
                for name in ("tmdbId", "imdbId", "tvdbId", "malId")
                if row.get(name) not in _MISSING
            }
            if not stable_ids and row.get("id") not in _MISSING:
                stable_ids["id"] = row["id"]
            identity = (
                ("ids", media_type, *(f"{key}:{stable_ids[key]}" for key in sorted(stable_ids)))
                if stable_ids
                else ("title", media_type, re.sub(r"[^a-z0-9]+", "", title.casefold()), str(year or ""))
            )
            card = cards.setdefault(identity, {
                "title": title,
                "year": year,
                "mediaType": media_type,
                "stableIds": stable_ids,
                "seasonNumber": row.get("seasonNumber", row.get("season")),
                "episodeNumber": row.get("episodeNumber", row.get("episode")),
                "subsections": [],
            })
            if subsection_name not in card["subsections"]:
                card["subsections"].append(subsection_name)
    return list(cards.values())


def _search_query(card: dict[str, Any]) -> str:
    parts = [card["title"]]
    if card.get("year"):
        parts.append(str(card["year"]))
    if card.get("seasonNumber") is not None:
        season = str(card["seasonNumber"]).strip()
        parts.append("S" + season.zfill(2) if season.isdigit() else "S" + season)
    if card.get("episodeNumber") is not None:
        episode = str(card["episodeNumber"]).strip()
        parts.append("E" + episode.zfill(2) if episode.isdigit() else "E" + episode)
    return " ".join(parts)


def _normalized_words(value: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _matches_card(result: dict[str, Any], card: dict[str, Any]) -> bool:
    expected = _normalized_words(card["title"])
    if not expected:
        return False
    title_fields = (
        result.get("mediaTitle"),
        result.get("catalogueTitle"),
        result.get("seriesTitle"),
        result.get("title"),
    )
    candidates = [_normalized_words(value) for value in title_fields if value]
    candidates = [words for words in candidates if words]
    if not candidates:
        return False
    matched_title = False
    for words in candidates:
        for start in range(len(words) - len(expected) + 1):
            if words[start:start + len(expected)] == expected:
                matched_title = True
                break
        if matched_title:
            break
    if not matched_title:
        return False

    expected_year = str(card.get("year") or "")
    if expected_year:
        explicit_years = {
            year
            for value in title_fields
            for year in re.findall(r"\b(?:19|20)\d{2}\b", str(value or ""))
        }
        result_year = str(result.get("year") or "")
        if result_year and result_year.isdigit():
            explicit_years.add(result_year)
        if explicit_years and expected_year not in explicit_years:
            return False
    return True


def _card_match(section: str, card: dict[str, Any], subsection: str) -> dict[str, Any]:
    return {
        "section": section,
        "subsection": subsection,
        "title": card["title"],
        "year": card.get("year"),
        "mediaType": card["mediaType"],
        **card["stableIds"],
        **({"seasonNumber": card["seasonNumber"]} if card.get("seasonNumber") is not None else {}),
        **({"episodeNumber": card["episodeNumber"]} if card.get("episodeNumber") is not None else {}),
    }


def _append_unique(target: dict[str, Any], field: str, value: Any) -> None:
    values = target.setdefault(field, [])
    if not isinstance(values, list):
        values = target[field] = [values]
    fingerprint = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if all(
        json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":")) != fingerprint
        for existing in values
    ):
        values.append(value)


def _merge_result(
    existing: dict[str, Any] | None,
    result: dict[str, Any],
    identity: str,
    section: str,
    card: dict[str, Any],
    refreshed_at: str,
) -> dict[str, Any]:
    record = dict(existing or {})
    for key, value in result.items():
        if key in {"sourceProvenance", "metadataCardMatches", "sectionAssignmentEvidence"}:
            continue
        if key in {"seeders", "leechers"} and value not in _MISSING:
            record[key] = value
        elif record.get(key) in _MISSING and value not in _MISSING:
            record[key] = value
    record.update({
        "identityKind": "infoHash",
        "identity": identity,
        "infoHash": identity,
        "mediaTitle": record.get("mediaTitle") or card["title"],
        "mediaType": record.get("mediaType") or card["mediaType"],
    })
    if record.get("year") in _MISSING and card.get("year") is not None:
        record["year"] = card["year"]

    for subsection in card["subsections"]:
        match = _card_match(section, card, subsection)
        _append_unique(record, "metadataCardMatches", match)
        _append_unique(record, "sectionAssignmentEvidence", {
            "source": "metadata-section-card",
            "section": section,
            "subsection": subsection,
            "mediaTitle": card["title"],
            "year": card.get("year"),
            **card["stableIds"],
        })
        _append_unique(record, "sourceProvenance", {
            "source": "torrent-refresh",
            "sourceGroup": "metadata-section-card",
            "sourceFile": f"{section}.json",
            "catalogueSections": [subsection],
            "mediaTitle": card["title"],
            "year": card.get("year"),
            "mediaType": card["mediaType"],
            **card["stableIds"],
            **({"seasonNumber": card["seasonNumber"]} if card.get("seasonNumber") is not None else {}),
            **({"episodeNumber": card["episodeNumber"]} if card.get("episodeNumber") is not None else {}),
        })
        media_identity = {
            "mediaType": card["mediaType"],
            "title": card["title"],
            "year": card.get("year"),
            **card["stableIds"],
            **({"seasonNumber": card["seasonNumber"]} if card.get("seasonNumber") is not None else {}),
            **({"episodeNumber": card["episodeNumber"]} if card.get("episodeNumber") is not None else {}),
        }
        _append_unique(record, "mediaIdentities", media_identity)
    return record


def _atomic_write(path: Path, content: bytes) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


async def refresh_torrent_cache(seed_dir: Path, searcher: Searcher) -> dict[str, Any]:
    seed_dir = Path(seed_dir)
    manifest = _read_manifest(seed_dir)
    documents = {
        section: _read_section(seed_dir, section, manifest)
        for section in SECTIONS
    }
    initial_bytes = {
        filename: (seed_dir / filename).read_bytes()
        for filename in TORRENT_FILES
    }
    refreshed_at = datetime.now(timezone.utc).isoformat()
    totals: dict[str, dict[str, int]] = {}
    rejected_missing_hashes = 0
    changed_sections: set[str] = set()

    for section in SECTIONS:
        document = documents[section]
        records = {record["identity"]: dict(record) for record in document["records"]}
        searches = 0
        additions = 0
        section_changed = False
        for card in _metadata_cards(seed_dir, section):
            searches += 1
            results = await searcher(_search_query(card))
            for result in results:
                if not _matches_card(result, card):
                    continue
                identity = result_info_hash(result)
                if not identity:
                    rejected_missing_hashes += 1
                    continue
                previous = records.get(identity)
                merged = _merge_result(
                    previous, result, identity, section, card, refreshed_at
                )
                if merged != previous:
                    records[identity] = merged
                    section_changed = True
                    additions += int(previous is None)
        if section_changed:
            document["records"] = [records[key] for key in sorted(records)]
            changed_sections.add(section)
        totals[section] = {
            "metadataCardsSearched": searches,
            "newHashes": additions,
            "recordCount": len(document["records"]),
        }

    updated: dict[str, bytes] = {}
    for section in SECTIONS:
        if section not in changed_sections:
            continue
        filename = f"{section}-torrents.json"
        content = json.dumps(
            documents[section], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8") + b"\n"
        if content != initial_bytes[filename]:
            updated[filename] = content

    if updated:
        seed_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in updated.items():
            _atomic_write(seed_dir / filename, content)
        files = {
            filename: {
                "sha256": hashlib.sha256((seed_dir / filename).read_bytes()).hexdigest(),
                "recordCount": len(documents[section]["records"]),
            }
            for section, filename in zip(SECTIONS, TORRENT_FILES)
        }
        all_hashes = {
            record["identity"]
            for document in documents.values()
            for record in document["records"]
        }
        next_manifest = {
            **manifest,
            "generation": max(manifest["generation"] + 1, int(datetime.now(timezone.utc).timestamp())),
            "createdAt": refreshed_at,
            "source": "torrent-refresh",
            "files": files,
            "globalUniqueNormalizedInfoHashes": len(all_hashes),
            "sectionLevelEntries": sum(len(doc["records"]) for doc in documents.values()),
        }
        _atomic_write(
            seed_dir / SEED_MANIFEST,
            json.dumps(next_manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n",
        )
    return {
        "generation": manifest["generation"] + int(bool(updated)),
        "updatedFiles": sorted(updated),
        "rejectedResultsWithoutInfoHash": rejected_missing_hashes,
        "sections": totals,
    }


def _http_searcher(base_url: str, timeout: float) -> Searcher:
    async def search(query: str) -> list[dict[str, Any]]:
        url = f"{base_url.rstrip('/')}/api/search?{urllib.parse.urlencode({'q': query, 'limit': 50})}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "torrent-studio-torrent-refresh/1"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("results") or payload.get("torrents")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        raise ValueError(f"Torrent search returned an invalid response for {query!r}")

    return search


async def _run_locked(seed_dir: Path, searcher: Searcher) -> dict[str, Any]:
    return await refresh_torrent_cache(seed_dir, searcher)


async def run(seed_dir: Path, searcher: Searcher) -> dict[str, Any]:
    seed_dir = Path(seed_dir).resolve()
    if os.getenv("TORRENT_REFRESH_LOCK_HELD", "").strip().casefold() in {"1", "true", "yes", "on"}:
        return await _run_locked(seed_dir, searcher)
    lock_path = seed_dir.parent / ".torrent-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return await _run_locked(seed_dir, searcher)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=Path(os.getenv("REFRESH_SEED_DIR", Path(__file__).resolve().parents[1] / "backend" / "cache-seed")),
    )
    parser.add_argument("--api-base", default=os.getenv("HOME_API_BASE", "http://127.0.0.1:10000"))
    parser.add_argument("--timeout", type=float, default=150)
    args = parser.parse_args()
    summary = asyncio.run(run(args.seed_dir, _http_searcher(args.api_base, args.timeout)))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
