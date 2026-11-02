#!/usr/bin/env python3
"""Build nine section torrent caches from existing local snapshots only."""
from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote

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
EXPECTED_UNIQUE_HASHES = {
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
DESTINATION_FILES = {section: f"{section}-torrents.json" for section in SECTIONS}
SOURCE_FILE_GROUPS = {
    "bollywood_torrent_matched_catalogue.json": "bollywood",
    "latest_bollywood_catalogue.json": "bollywood",
    "latest_hollywood_catalogue.json": "hollywood",
    "hollywood-torrents.json": "hollywood",
    "classics_catalogue.json": "favourites",
    "classics_web_series_tv_catalogue.json": "favourites",
    "classics_anime_tv_catalogue.json": "favourites",
    "dc_animated_catalogue.json": "dc",
    "dc_live_action_catalogue.json": "dc",
    "dc_live_action_hindi_catalogue.json": "dc",
    "marvel_catalogue.json": "marvel",
    "marvel_hindi_catalogue.json": "marvel",
    "marvel_web_series_catalogue.json": "marvel",
}
SECTION_METADATA_FILES = {f"{section}.json": section for section in SECTIONS}
TORRENT_FIELDS = frozenset({"infoHash", "magnetUrl", "downloadUrl", "guid"})
IDENTITY_FIELDS = (
    "tmdbId",
    "tmdb_id",
    "movieId",
    "showId",
    "tvId",
    "imdbId",
    "imdb_id",
    "mediaType",
    "media_type",
    "year",
    "releaseYear",
    "firstAirYear",
    "releaseDate",
    "firstAirDate",
    "catalogueTitle",
    "mediaTitle",
    "seriesTitle",
    "catalogueKey",
    "catalogues",
    "seasonNumber",
    "episodeNumber",
)
TIMESTAMP_FIELDS = (
    "builtAt",
    "scannedAt",
    "checkedAt",
    "torrentCheckedAt",
    "torrentCheckedAtEpoch",
    "updatedAt",
    "createdAt",
    "timestamp",
)
TITLE_YEAR_RE = re.compile(r"^(?P<title>.+)\|(?P<year>\d{4})$")
RELEASE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")
SEASON_RE = re.compile(r"(?i)(?:^|[^A-Z0-9])S(?P<season>\d{1,2})(?!\d)")
EPISODE_RE = re.compile(r"(?i)(?:^|[^A-Z0-9])S(?P<season>\d{1,2})E(?P<episode>\d{1,3})(?!\d)")


class MigrationError(RuntimeError):
    """Raised when an input snapshot cannot be read or safely interpreted."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def normalized_year(value: Any) -> str:
    match = re.match(r"^(\d{4})", str(value or "").strip())
    return match.group(1) if match else ""


def _normalize_hash(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.casefold()
    if re.fullmatch(r"[a-z2-7]{32}", text):
        try:
            return base64.b32decode(text.upper()).hex()
        except (ValueError, base64.binascii.Error):
            pass
    return text


def info_hash(result: dict[str, Any]) -> str:
    direct = _normalize_hash(result.get("infoHash"))
    if direct:
        return direct
    magnet = str(result.get("magnetUrl") or "")
    match = re.search(r"(?:^|[?&])xt=urn:btih:([^&]+)", magnet, re.IGNORECASE)
    if not match:
        match = re.search(r"btih:([^&\s]+)", magnet, re.IGNORECASE)
    if not match:
        return ""
    return _normalize_hash(unquote(match.group(1)))


def _is_torrent_result(value: dict[str, Any]) -> bool:
    if value.get("infoHash") or value.get("magnetUrl"):
        return True
    return bool(value.get("guid") and any(value.get(key) not in (None, "") for key in (
        "indexer", "protocol", "seeders", "leechers", "size",
    )))


def _source_group(relative_path: Path) -> str | None:
    name = relative_path.name
    if name.startswith("regional_movie_prebuilt_cache.json"):
        return "regional"
    if name.startswith("regional_movie_prebuilt_state.json"):
        return "state"
    for source_name, section in SOURCE_FILE_GROUPS.items():
        if name == source_name or name.startswith(source_name + "."):
            return section
    if name in SECTION_METADATA_FILES:
        return SECTION_METADATA_FILES[name]
    parts = relative_path.parts
    if len(parts) >= 3 and parts[-3] == "pages":
        page_group = parts[-2].casefold()
        if page_group == "classics":
            return "favourites"
        for token, section in (
            ("hollywood", "hollywood"),
            ("bollywood", "bollywood"),
            ("marvel", "marvel"),
            ("dc", "dc"),
            ("korean", "korean"),
            ("pakistani", "pakistani"),
            ("anime", "anime"),
        ):
            if token in page_group:
                return section
    return None


def _is_json_snapshot(path: Path) -> bool:
    name = path.name
    return name.endswith(".json") or ".json." in name or name.endswith(".json.gz")


def _read_json(path: Path) -> Any:
    try:
        opener = gzip.open if path.name.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Could not read JSON snapshot {path}: {exc}") from exc


def _context_for_node(node: dict[str, Any], inherited: dict[str, Any]) -> dict[str, Any]:
    context = dict(inherited)
    for field in IDENTITY_FIELDS:
        value = node.get(field)
        if value not in (None, ""):
            context[field] = value
    for field in TIMESTAMP_FIELDS:
        value = node.get(field)
        if value not in (None, ""):
            context[field] = value
    if node.get("id") not in (None, "") and any(
        node.get(field) not in (None, "")
        for field in ("title", "name", "year", "releaseYear", "firstAirYear")
    ):
        context.setdefault("sourceMediaId", node["id"])

    media_type = str(node.get("mediaType") or node.get("media_type") or "").casefold()
    season_number = node.get("seasonNumber")
    episode_number = node.get("episodeNumber")
    title = node.get("title") or node.get("name")
    if title:
        if episode_number not in (None, ""):
            context["episodeTitle"] = title
        elif season_number not in (None, ""):
            context["seasonTitle"] = title
        elif not (node.get("mediaTitle") or node.get("seriesTitle")):
            context["title"] = title
    if media_type in {"tv", "series", "show"}:
        context["mediaType"] = "tv"
    elif media_type == "movie":
        context["mediaType"] = "movie"

    episode_metadata = node.get("episodes")
    if isinstance(episode_metadata, dict):
        tmdb_id = episode_metadata.get("tmdbId")
        series_title = episode_metadata.get("title")
        if tmdb_id not in (None, ""):
            context.setdefault("tmdbId", tmdb_id)
        if series_title:
            context.setdefault("seriesTitle", series_title)
        context.setdefault("mediaType", "tv")
    if episode_number not in (None, ""):
        context["episodeNumber"] = episode_number
    if season_number not in (None, ""):
        context["seasonNumber"] = season_number
    return context


def _records(node: Any, context: dict[str, Any] | None = None, path: tuple[str, ...] = ()):
    context = context or {}
    if isinstance(node, dict):
        if _is_torrent_result(node):
            result_context = dict(context)
            for field in IDENTITY_FIELDS:
                if field in node and node[field] not in (None, ""):
                    result_context[field] = node[field]
            yield node, result_context, path
            return

        updated = _context_for_node(node, context)
        for key, value in node.items():
            if key == "torrentMatch" and isinstance(node.get("torrentMatches"), list):
                continue
            yield from _records(value, updated, path + (str(key),))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _records(value, context, path + (str(index),))


def _stable_media_id(context: dict[str, Any]) -> tuple[str, str]:
    tmdb_id = (
        context.get("tmdbId")
        or context.get("tmdb_id")
        or context.get("movieId")
        or context.get("showId")
        or context.get("tvId")
        or context.get("sourceMediaId")
    )
    if tmdb_id not in (None, ""):
        return "tmdb", str(tmdb_id).strip()
    imdb_id = context.get("imdbId") or context.get("imdb_id")
    if imdb_id:
        return "imdb", str(imdb_id).strip().casefold()
    return "", ""


def _media_type(context: dict[str, Any], source_group: str, source_file: str = "") -> str:
    value = str(context.get("mediaType") or context.get("media_type") or "").casefold()
    if value in {"tv", "series", "show", "episode"}:
        return "tv"
    if value == "movie":
        return "movie"
    if source_file in {
        "marvel_web_series_catalogue.json",
        "classics_web_series_tv_catalogue.json",
        "classics_anime_tv_catalogue.json",
    }:
        return "tv"
    if source_group in {"marvel", "favourites"}:
        return "tv" if context.get("episodeNumber") or context.get("seasonNumber") else "movie"
    return "movie"


def _source_entity_key(context: dict[str, Any], path: tuple[str, ...]) -> str:
    return next((part for part in reversed(path[:-1]) if "|" in part), "")


def _entity_title_year(
    result: dict[str, Any], context: dict[str, Any], source_group: str, path: tuple[str, ...]
) -> tuple[str, str]:
    title = (
        context.get("seriesTitle")
        or context.get("mediaTitle")
        or context.get("catalogueTitle")
        or context.get("title")
        or context.get("name")
        or ""
    )
    year = context.get("year") or context.get("releaseYear") or context.get("firstAirYear") or ""
    key = _source_entity_key(context, path)
    if source_group == "state" and key:
        match = TITLE_YEAR_RE.fullmatch(key.casefold())
        if match:
            title = title or match.group("title")
            year = year or match.group("year")
    if not title:
        title = result.get("mediaTitle") or result.get("catalogueTitle") or ""
    if not year:
        year_match = RELEASE_YEAR_RE.search(str(result.get("title") or ""))
        if year_match:
            year = year_match.group(1)
    return str(title).strip(), normalized_year(year)


def _catalogue_sections(context: dict[str, Any]) -> set[str]:
    sections: set[str] = set()
    for value in _catalogue_identifiers(context):
        key = value.casefold().replace("_", "-")
        if "highest-rated" in key:
            sections.add("highest-rated")
            continue
        for token, section in (
            ("hollywood", "hollywood"),
            ("bollywood", "bollywood"),
            ("marvel", "marvel"),
            ("dc", "dc"),
            ("korean", "korean"),
            ("pakistani", "pakistani"),
            ("anime", "anime"),
        ):
            if token in key:
                sections.add(section)
        if any(token in key for token in ("classic", "favourite", "favorite")):
            sections.add("favourites")
    return sections


def _catalogue_identifiers(context: dict[str, Any]) -> list[str]:
    values = context.get("catalogues") or context.get("catalogueKey") or []
    if isinstance(values, str):
        values = [values]
    return sorted(
        {
            str(value).strip()
            for value in values if isinstance(values, list)
            if str(value).strip()
        }
    )


def _media_identity(
    result: dict[str, Any],
    context: dict[str, Any],
    source_group: str,
    path: tuple[str, ...],
    source_file: str = "",
) -> dict[str, Any]:
    title, year = _entity_title_year(result, context, source_group, path)
    media_type = _media_type(context, source_group, source_file)
    identity_type, identity_value = _stable_media_id(context)
    identity: dict[str, Any] = {"mediaType": media_type}
    if identity_type and identity_value:
        identity[identity_type + "Id"] = identity_value
    if title:
        identity["title"] = title
    if year:
        identity["year"] = year
    if context.get("seasonNumber") not in (None, ""):
        identity["seasonNumber"] = context["seasonNumber"]
    if context.get("episodeNumber") not in (None, ""):
        identity["episodeNumber"] = context["episodeNumber"]
    if context.get("episodeTitle"):
        identity["episodeTitle"] = context["episodeTitle"]

    release_title = str(result.get("title") or "")
    if media_type == "tv":
        episode = EPISODE_RE.search(release_title)
        season = SEASON_RE.search(release_title)
        if "seasonNumber" not in identity and episode:
            identity["seasonNumber"] = int(episode.group("season"))
        if "episodeNumber" not in identity and episode:
            identity["episodeNumber"] = int(episode.group("episode"))
        if "seasonNumber" not in identity and season:
            identity["seasonNumber"] = int(season.group("season"))
    return identity


def _card_matches(
    identity: dict[str, Any],
    card_index: dict[str, set[tuple[str, ...]]],
) -> list[dict[str, str]]:
    media_type = str(identity.get("mediaType") or "")
    title = normalized_title(identity.get("title"))
    year = normalized_year(identity.get("year"))
    stable_ids = [
        ("tmdb", str(identity.get("tmdbId") or "")),
        ("imdb", str(identity.get("imdbId") or "").casefold()),
    ]
    id_matches: set[tuple[str, str, str]] = set()
    for section in SECTIONS:
        for id_type, id_value in stable_ids:
            if not id_value:
                continue
            id_matches.update(
                (section, card[3], id_type)
                for card in card_index[section]
                if card[:3] == (media_type, id_type, id_value)
            )
    if id_matches:
        selected = id_matches
    elif title and year:
        selected = {
            (section, card[4], "title-year")
            for section in SECTIONS
            for card in card_index[section]
            if card[:4] == (media_type, "title-year", title, year)
        }
    else:
        selected = set()
    return [
        {"section": section, "subsection": subsection, "matchType": match_type}
        for section, subsection, match_type in sorted(selected)
    ]


def _matches_card(
    identity: dict[str, Any],
    card_index: dict[str, set[tuple[str, ...]]],
) -> set[str]:
    return {
        match["section"]
        for match in _card_matches(identity, card_index)
    }


def _load_card_index(metadata_dir: Path) -> dict[str, set[tuple[str, ...]]]:
    index: dict[str, set[tuple[str, ...]]] = {section: set() for section in SECTIONS}
    for section in SECTIONS:
        path = metadata_dir / f"{section}.json"
        document = _read_json(path)
        if not isinstance(document, dict) or not isinstance(document.get("subsections"), dict):
            raise MigrationError(f"Invalid metadata document shape: {path}")
        for subsection_name, subsection in document["subsections"].items():
            if not isinstance(subsection, dict):
                continue
            media_type = str(subsection.get("mediaType") or "").casefold()
            media_type = "tv" if media_type in {"tv", "series", "show"} else "movie"
            for card in subsection.get("results") or []:
                if not isinstance(card, dict):
                    continue
                tmdb = card.get("tmdbId") or card.get("tmdb_id") or card.get("id")
                imdb = card.get("imdbId") or card.get("imdb_id")
                title = card.get("title") or card.get("name")
                year = card.get("year") or card.get("firstAirYear") or card.get("releaseYear")
                if tmdb not in (None, ""):
                    index[section].add(
                        (media_type, "tmdb", str(tmdb), subsection_name)
                    )
                if imdb:
                    index[section].add(
                        (media_type, "imdb", str(imdb).casefold(), subsection_name)
                    )
                if title and year:
                    title_key = normalized_title(title)
                    year_key = normalized_year(year)
                    if title_key and year_key:
                        index[section].add(
                            (
                                media_type,
                                "title-year",
                                title_key,
                                year_key,
                                subsection_name,
                            )
                        )
    return index


def _canonical_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _merge_missing(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in sorted(incoming):
        value = incoming[key]
        if key not in target or target[key] in (None, "", [], {}):
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing(target[key], value)
        elif isinstance(target[key], list) and isinstance(value, list):
            values = {_canonical_value(item): item for item in target[key]}
            values.update({_canonical_value(item): item for item in value})
            target[key] = [values[item] for item in sorted(values)]


def _provenance(
    source: dict[str, Any], context: dict[str, Any], path: tuple[str, ...]
) -> dict[str, Any]:
    timestamps = {
        key: context[key]
        for key in TIMESTAMP_FIELDS
        if key in context and context[key] not in (None, "")
    }
    return {
        "sourceGroup": source["group"],
        "sourceFile": source["relativePath"],
        "sourceFiles": sorted(source["sourceFiles"]),
        "sourceFileNames": sorted(source["sourceFileNames"]),
        "sourceSnapshotSha256": source["sha256"],
        "sourceLocations": source["locations"],
        "sourceRecordPath": list(path),
        "catalogueKeys": _catalogue_identifiers(context),
        "catalogueSections": sorted(_catalogue_sections(context)),
        "sourceTimestamps": timestamps,
    }


def _record_identity(
    result: dict[str, Any], source: dict[str, Any], path: tuple[str, ...], ordinal: int
) -> tuple[str, str]:
    hash_value = info_hash(result)
    if hash_value:
        return "infoHash", hash_value
    magnet = str(result.get("magnetUrl") or "").strip()
    if magnet:
        return "magnetUrl", magnet.casefold()
    guid = str(result.get("guid") or "").strip()
    if guid:
        return "guid", guid.casefold()
    fallback = sha256_bytes(
        canonical_json([source["sha256"], source["relativePath"], list(path), ordinal])
    )
    return "unresolved", fallback


def _add_source_variant(record: dict[str, Any], result: dict[str, Any], provenance: dict[str, Any]) -> None:
    key = _canonical_value(result)
    variants: dict[str, dict[str, Any]] = record["_variants"]
    if key not in variants:
        variants[key] = {"result": result, "sourceProvenance": []}
    provenance_key = _canonical_value(provenance)
    if all(_canonical_value(item) != provenance_key for item in variants[key]["sourceProvenance"]):
        variants[key]["sourceProvenance"].append(provenance)


def _preferred_variant(variants: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def rank(item: tuple[str, dict[str, Any]]) -> tuple[int, int, str]:
        key, variant = item
        result = variant["result"]
        populated = sum(value not in (None, "", [], {}) for value in result.values())
        dated = max(
            (str(result.get(field) or "") for field in TIMESTAMP_FIELDS),
            default="",
        )
        return populated, len(dated), key

    return max(variants.items(), key=rank)[1]["result"]


def _new_output_record(
    identity_kind: str,
    identity_value: str,
) -> dict[str, Any]:
    return {
        "identityKind": identity_kind,
        "identity": identity_value,
        "_variants": {},
        "_mediaIdentities": {},
        "_metadataCardMatches": {},
        "_assignmentEvidence": {},
        "_provenance": [],
    }


def _attach(
    section_records: dict[str, dict[str, Any]],
    section: str,
    result: dict[str, Any],
    identity_kind: str,
    identity_value: str,
    media_identity: dict[str, Any],
    metadata_card_matches: list[dict[str, str]],
    assignment_evidence: dict[str, Any],
    provenance: dict[str, Any],
) -> None:
    records = section_records[section]
    record_key = (
        identity_value
        if identity_kind == "infoHash"
        else f"{identity_kind}:{identity_value}"
    )
    record = records.get(record_key)
    if record is None:
        record = _new_output_record(identity_kind, identity_value)
        records[record_key] = record
    _add_source_variant(record, result, provenance)
    media_key = _canonical_value(media_identity)
    record["_mediaIdentities"][media_key] = media_identity
    for match in metadata_card_matches:
        match_key = _canonical_value(match)
        record["_metadataCardMatches"][match_key] = match
    evidence_key = _canonical_value(assignment_evidence)
    record["_assignmentEvidence"][evidence_key] = assignment_evidence
    provenance_key = _canonical_value(provenance)
    if all(_canonical_value(item) != provenance_key for item in record["_provenance"]):
        record["_provenance"].append(provenance)


def _source_files(roots: list[tuple[str, Path]], output_dir: Path) -> list[dict[str, Any]]:
    files_by_content: dict[tuple[str, str], dict[str, Any]] = {}
    resolved_output = output_dir.resolve()
    for label, root in roots:
        if not root.is_dir():
            raise MigrationError(f"Source root does not exist or is not a directory: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or not _is_json_snapshot(path):
                continue
            resolved_path = path.resolve()
            if resolved_path.parent == resolved_output and path.name in DESTINATION_FILES.values():
                continue
            relative = path.relative_to(root)
            group = _source_group(relative)
            try:
                data = _read_json(path)
            except MigrationError:
                raise
            found = list(_records(data))
            if not found:
                continue
            content = path.read_bytes()
            digest = sha256_bytes(content)
            if group is None:
                group = "unresolved"
            source_name_match = re.match(r"^.*?\.json(?:\.gz)?", path.name)
            source_file_name = source_name_match.group(0) if source_name_match else path.name
            key = (group, digest)
            source = files_by_content.get(key)
            if source is None:
                source = {
                    "group": group,
                    "sourceFileName": source_file_name,
                    "sha256": digest,
                    "relativePath": f"{label}/{relative.as_posix()}",
                    "locations": [],
                    "sourceFiles": [],
                    "sourceFileNames": [],
                    "data": data,
                    "records": found,
                }
                files_by_content[key] = source
            location = f"{label}/{relative.as_posix()}"
            if location not in source["locations"]:
                source["locations"].append(location)
            source_file = f"{label}/{relative.as_posix()}"
            if source_file not in source["sourceFiles"]:
                source["sourceFiles"].append(source_file)
            if source_file_name not in source["sourceFileNames"]:
                source["sourceFileNames"].append(source_file_name)
    return sorted(
        (
            {**source, "locations": sorted(source["locations"])}
            for source in files_by_content.values()
        ),
        key=lambda item: (item["group"], item["relativePath"], item["sha256"]),
    )


def _regional_memberships(sources: list[dict[str, Any]]) -> dict[str, set[str]]:
    memberships: dict[str, set[str]] = defaultdict(set)
    for source in sources:
        if source["group"] != "regional":
            continue
        movies = source["data"].get("movies")
        if not isinstance(movies, dict):
            continue
        for key, entry in movies.items():
            if isinstance(entry, dict):
                key_text = str(key).casefold()
                sections = _catalogue_sections(entry)
                memberships[key_text].update(sections)
                match = TITLE_YEAR_RE.fullmatch(key_text)
                if match:
                    normalized_key = (
                        f"{normalized_title(match.group('title'))}|{match.group('year')}"
                    )
                    memberships[normalized_key].update(sections)
    return memberships


def _regional_membership_evidence(
    sources: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        if source["group"] != "regional":
            continue
        movies = source["data"].get("movies")
        if not isinstance(movies, dict):
            continue
        for key, entry in movies.items():
            if not isinstance(entry, dict):
                continue
            catalogue_evidence = {
                "sourceGroup": "regional",
                "sourceFile": source["relativePath"],
                "sourceFiles": sorted(source["sourceFiles"]),
                "sourceFileNames": sorted(source["sourceFileNames"]),
                "sourceSnapshotSha256": source["sha256"],
                "sourceRecordPath": ["movies", str(key)],
                "catalogueKeys": _catalogue_identifiers(entry),
                "catalogueSections": sorted(_catalogue_sections(entry)),
            }
            if not catalogue_evidence["catalogueKeys"]:
                continue
            key_text = str(key).casefold()
            keys = {key_text}
            match = TITLE_YEAR_RE.fullmatch(key_text)
            if match:
                keys.add(
                    f"{normalized_title(match.group('title'))}|{match.group('year')}"
                )
            for membership_key in keys:
                evidence_key = _canonical_value(catalogue_evidence)
                if all(
                    _canonical_value(existing) != evidence_key
                    for existing in evidence[membership_key]
                ):
                    evidence[membership_key].append(catalogue_evidence)
    return {
        key: sorted(rows, key=_canonical_value)
        for key, rows in evidence.items()
    }


def _state_key(path: tuple[str, ...]) -> str:
    return next((part for part in reversed(path[:-1]) if "|" in part), "")


def _entry_identity(
    result: dict[str, Any],
    context: dict[str, Any],
    source: dict[str, Any],
    path: tuple[str, ...],
    ordinal: int,
) -> dict[str, Any]:
    media_identity = _media_identity(
        result, context, source["group"], path, source["sourceFileName"]
    )
    if source["group"] == "state" and not media_identity.get("title"):
        match = TITLE_YEAR_RE.fullmatch(_state_key(path).casefold())
        if match:
            media_identity["title"] = match.group("title")
            media_identity["year"] = match.group("year")
    identity_kind, identity_value = _record_identity(result, source, path, ordinal)
    provenance = _provenance(source, context, path)
    return {
        "result": result,
        "mediaIdentity": media_identity,
        "identityKind": identity_kind,
        "identity": identity_value,
        "provenance": provenance,
        "source": source,
        "path": path,
    }


def _source_sections(
    entry: dict[str, Any],
    regional_memberships: dict[str, set[str]],
    card_index: dict[str, set[tuple[str, ...]]],
) -> set[str]:
    source = entry["source"]
    group = source["group"]
    if group == "unresolved":
        return set()
    sections = {group} if group in SECTIONS and group != "highest-rated" else set()
    if group == "regional":
        sections.update(
            _catalogue_sections(entry["context"]) - {"highest-rated"}
        )
    if group == "state":
        key = _state_key(entry["path"]).casefold()
        title = normalized_title(entry["mediaIdentity"].get("title"))
        year = normalized_year(entry["mediaIdentity"].get("year"))
        sections.update(
            regional_memberships.get(key, set()) - {"highest-rated"}
        )
        if title and year:
            sections.update(
                regional_memberships.get(f"{title}|{year}", set())
                - {"highest-rated"}
            )
    sections.update(
        match["section"]
        for match in entry.get(
            "metadataCardMatches",
            _card_matches(entry["mediaIdentity"], card_index),
        )
    )
    return sections


def _section_assignment_evidence(
    entry: dict[str, Any],
    section: str,
) -> dict[str, Any]:
    source = entry["source"]
    evidence: list[dict[str, Any]] = []
    if source["group"] == section and section != "highest-rated":
        evidence.append({
            "reason": "explicit-source-file-mapping",
            "sourceGroup": source["group"],
            "sourceFiles": sorted(source["sourceFiles"]),
            "sourceSnapshotSha256": source["sha256"],
        })
    if (
        section != "highest-rated"
        and section in _catalogue_sections(entry["context"])
    ):
        evidence.append({
            "reason": "explicit-source-catalogue-membership",
            "sourceGroup": source["group"],
            "catalogueKeys": _catalogue_identifiers(entry["context"]),
            "sourceFiles": sorted(source["sourceFiles"]),
            "sourceSnapshotSha256": source["sha256"],
        })
    for catalogue_evidence in entry.get("regionalCatalogueEvidence", []):
        if (
            section != "highest-rated"
            and section in catalogue_evidence["catalogueSections"]
        ):
            evidence.append({
                **catalogue_evidence,
                "reason": "state-title-year-joined-to-regional-catalogue",
            })
    for match in entry.get("metadataCardMatches", []):
        if match["section"] == section:
            evidence.append({
                "reason": "current-metadata-card-match",
                "metadataDocument": f"{section}.json",
                **match,
                "mediaIdentity": entry["mediaIdentity"],
            })
    return {
        "section": section,
        "evidence": sorted(
            {
                _canonical_value(item): item
                for item in evidence
            }.values(),
            key=_canonical_value,
        ),
    }


def _merge_result_variants(record: dict[str, Any]) -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = record["_variants"]
    merged = copy.deepcopy(_preferred_variant(variants))
    for variant_key in sorted(variants):
        _merge_missing(merged, copy.deepcopy(variants[variant_key]["result"]))
    if record["identityKind"] == "infoHash":
        merged["infoHash"] = record["identity"]
    return merged


def _finalize_record(record: dict[str, Any]) -> dict[str, Any]:
    results = _merge_result_variants(record)
    results["identityKind"] = record["identityKind"]
    results["identity"] = record["identity"]
    results["mediaIdentities"] = [
        record["_mediaIdentities"][key] for key in sorted(record["_mediaIdentities"])
    ]
    results["metadataCardMatches"] = [
        record["_metadataCardMatches"][key]
        for key in sorted(record["_metadataCardMatches"])
    ]
    results["sectionAssignmentEvidence"] = [
        record["_assignmentEvidence"][key]
        for key in sorted(record["_assignmentEvidence"])
    ]
    results["sourceProvenance"] = [
        item
        for _, item in sorted(
            ((_canonical_value(item), item) for item in record["_provenance"]),
            key=lambda pair: pair[0],
        )
    ]
    results["sourceVariants"] = [
        {
            "result": record["_variants"][key]["result"],
            "sourceProvenance": sorted(
                record["_variants"][key]["sourceProvenance"],
                key=_canonical_value,
            ),
        }
        for key in sorted(record["_variants"])
    ]
    return results


def _write_atomic(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fchmod(handle.fileno(), mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _container_source(spec: str, temporary_root: Path, index: int) -> tuple[str, Path]:
    container, separator, remote_path = spec.partition(":")
    if not separator or not container or not remote_path.startswith("/"):
        raise MigrationError(f"Invalid container source {spec!r}; expected CONTAINER:/absolute/path")
    target = temporary_root / f"container-{index}"
    target.mkdir(parents=True)
    command = ["docker", "cp", f"{container}:{remote_path.rstrip('/')}/.", str(target)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise MigrationError(f"Could not read container source {spec!r}: {detail.strip()}") from exc
    return f"container:{container}:{remote_path.rstrip('/')}", target


def build_migration(
    source_roots: list[tuple[str, Path]],
    metadata_dir: Path,
    output_dir: Path,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    card_index = _load_card_index(metadata_dir)
    sources = _source_files(source_roots, output_dir)
    regional_memberships = _regional_memberships(sources)
    regional_evidence = _regional_membership_evidence(sources)
    section_records: dict[str, dict[str, dict[str, Any]]] = {
        section: {} for section in SECTIONS
    }
    unresolved: list[dict[str, Any]] = []
    missing_hash_records: list[dict[str, Any]] = []
    source_entries: dict[str, dict[str, Any]] = {}
    global_hashes: set[str] = set()
    global_identities: set[tuple[str, str]] = set()
    destination_raw_occurrences: Counter[str] = Counter()

    ordinal = 0
    for source in sources:
        source_count = 0
        source_hashes: set[str] = set()
        for result, context, path in source["records"]:
            ordinal += 1
            source_count += 1
            entry = _entry_identity(result, context, source, path, ordinal)
            entry["context"] = context
            entry["metadataCardMatches"] = _card_matches(
                entry["mediaIdentity"], card_index
            )
            if source["group"] == "state":
                key = _state_key(path).casefold()
                title = normalized_title(entry["mediaIdentity"].get("title"))
                year = normalized_year(entry["mediaIdentity"].get("year"))
                entry["regionalCatalogueEvidence"] = regional_evidence.get(
                    key,
                    regional_evidence.get(f"{title}|{year}", []),
                )
            hash_value = info_hash(result)
            if hash_value:
                global_hashes.add(hash_value)
            global_identities.add((entry["identityKind"], entry["identity"]))
            if not hash_value:
                missing_hash_records.append({
                    "sourceFile": source["relativePath"],
                    "sourceRecordPath": list(path),
                    "identityKind": entry["identityKind"],
                    "identity": entry["identity"],
                    "guid": str(result.get("guid") or ""),
                })
            else:
                source_hashes.add(hash_value)

            sections = _source_sections(entry, regional_memberships, card_index)
            if not sections:
                unresolved.append({
                    "sourceFile": source["relativePath"],
                    "sourceRecordPath": list(path),
                    "sourceGroup": source["group"],
                    "infoHash": hash_value,
                    "identityKind": entry["identityKind"],
                    "identity": entry["identity"],
                    "title": entry["mediaIdentity"].get("title", ""),
                    "year": entry["mediaIdentity"].get("year", ""),
                    "mediaType": entry["mediaIdentity"].get("mediaType", ""),
                    "reason": "No explicit section provenance or current metadata-card match",
                    "result": result,
                    "sourceProvenance": entry["provenance"],
                })
            for section in sorted(sections):
                destination_raw_occurrences[section] += 1
                _attach(
                    section_records,
                    section,
                    result,
                    entry["identityKind"],
                    entry["identity"],
                    entry["mediaIdentity"],
                    entry["metadataCardMatches"],
                    _section_assignment_evidence(entry, section),
                    entry["provenance"],
                )

        source_entries[source["relativePath"] + "#" + source["sha256"]] = {
            "sourceGroup": source["group"],
            "sourceLocations": source["locations"],
            "sha256": source["sha256"],
            "rawResultOccurrences": source_count,
            "uniqueNormalizedInfoHashes": sorted(source_hashes),
            "uniqueNormalizedInfoHashCount": len(source_hashes),
        }

    final_documents: dict[str, dict[str, Any]] = {}
    contents: dict[str, bytes] = {}
    hash_sections: dict[str, set[str]] = defaultdict(set)
    for section in SECTIONS:
        records = section_records[section]
        final_records = [_finalize_record(records[key]) for key in sorted(records)]
        for identity in records:
            record = records[identity]
            if record["identityKind"] == "infoHash":
                hash_sections[identity].add(section)
        document = {
            "schemaVersion": 1,
            "section": section,
            "records": final_records,
        }
        final_documents[section] = document
        contents[DESTINATION_FILES[section]] = canonical_json(document)

    destinations: dict[str, Any] = {}
    for section in SECTIONS:
        records = final_documents[section]["records"]
        hashes = sorted(
            record["identity"]
            for record in records
            if record["identityKind"] == "infoHash"
        )
        shared_count = sum(len(hash_sections[value]) > 1 for value in hashes)
        destinations[DESTINATION_FILES[section]] = {
            "rawResultOccurrences": destination_raw_occurrences[section],
            "uniqueNormalizedInfoHashes": len(hashes),
            "uniqueInfoHashes": hashes,
            "missingInfoHashRecords": sum(
                record["identityKind"] != "infoHash" for record in records
            ),
            "unresolvedSectionAssociations": 0,
            "sharedInfoHashCount": shared_count,
            "sha256": sha256_bytes(contents[DESTINATION_FILES[section]]),
        }

    manifest = {
        "manifestSchemaVersion": 1,
        "migrationTool": "scripts/migrate_torrent_cache.py",
        "mode": "offline-existing-cache-migration",
        "sourceSnapshotCount": len(sources),
        "sourceRawResultOccurrences": sum(
            entry["rawResultOccurrences"] for entry in source_entries.values()
        ),
        "sourceFiles": [source_entries[key] for key in sorted(source_entries)],
        "globalUniqueNormalizedInfoHashCount": len(global_hashes),
        "globalUniqueNormalizedInfoHashes": sorted(global_hashes),
        "globalUniqueIdentityCount": len(global_identities),
        "destinations": destinations,
        "unresolvedRecords": sorted(unresolved, key=_canonical_value),
        "unresolvedRecordCount": len(unresolved),
        "missingInfoHashRecords": sorted(missing_hash_records, key=_canonical_value),
        "missingInfoHashRecordCount": len(missing_hash_records),
        "crossSectionDuplicateInfoHashCount": sum(
            len(sections) > 1 for sections in hash_sections.values()
        ),
        "sectionLevelUniqueInfoHashEntryCount": sum(
            item["uniqueNormalizedInfoHashes"]
            for item in destinations.values()
        ),
        "expectedSectionCounts": EXPECTED_UNIQUE_HASHES,
        "sectionCountDifferences": {
            name: {
                "expected": EXPECTED_UNIQUE_HASHES[name],
                "actual": destinations[DESTINATION_FILES[name]][
                    "uniqueNormalizedInfoHashes"
                ],
            }
            for name in SECTIONS
            if destinations[DESTINATION_FILES[name]][
                "uniqueNormalizedInfoHashes"
            ] != EXPECTED_UNIQUE_HASHES[name]
        },
    }
    return manifest, contents


def _write_manifest(path: Path, manifest: dict[str, Any]) -> str:
    content = canonical_json(manifest)
    _write_atomic(path, content)
    return sha256_bytes(content)


def _apply_outputs(output_dir: Path, contents: dict[str, bytes]) -> list[str]:
    existing_differences: list[str] = []
    for filename, content in contents.items():
        path = output_dir / filename
        if path.exists() and path.read_bytes() != content:
            existing_differences.append(str(path))
    if existing_differences:
        raise MigrationError(
            "Refusing to overwrite existing torrent destinations that differ from this "
            "migration. Back them up and reconcile explicitly: "
            + ", ".join(sorted(existing_differences))
        )

    written: list[str] = []
    for filename in sorted(contents):
        path = output_dir / filename
        if path.exists():
            continue
        _write_atomic(path, contents[filename])
        written.append(str(path))
    return written


def _default_source_roots() -> list[tuple[str, Path]]:
    home = Path.home()
    checkout = home / "Torrent-Studio"
    return [
        ("production", checkout / "backend" / "cache-seed"),
        ("refresh-seed", home / "torrent-studio-refresh" / "seed"),
        ("refresh-repo", home / "torrent-studio-refresh" / "repo" / "backend" / "cache-seed"),
        ("host-data", home / "home-data"),
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        action="append",
        default=None,
        metavar="LABEL=PATH",
        help="Local read-only source root; may be supplied more than once.",
    )
    parser.add_argument(
        "--container-source",
        action="append",
        default=[],
        metavar="CONTAINER:/ABSOLUTE/PATH",
        help="Read a container directory using docker cp into temporary storage.",
    )
    parser.add_argument(
        "--metadata-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend" / "cache-seed",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend" / "cache-seed",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional path for the detailed deterministic manifest.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report only; this is the default.")
    mode.add_argument("--apply", action="store_true", help="Atomically create missing torrent files.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    roots: list[tuple[str, Path]] = []
    if args.source_root:
        for value in args.source_root:
            label, separator, raw_path = value.partition("=")
            if not separator or not label or not raw_path:
                raise MigrationError(f"Invalid --source-root {value!r}; expected LABEL=PATH")
            roots.append((label, Path(raw_path).expanduser().resolve()))
    else:
        roots = [(label, path.resolve()) for label, path in _default_source_roots()]

    with tempfile.TemporaryDirectory(prefix="torrent-cache-sources-") as temporary:
        temporary_root = Path(temporary)
        for index, spec in enumerate(args.container_source):
            roots.append(_container_source(spec, temporary_root, index))
        manifest, contents = build_migration(
            roots,
            args.metadata_dir.expanduser().resolve(),
            args.output_dir.expanduser().resolve(),
        )
        written: list[str] = []
        if args.apply:
            written = _apply_outputs(args.output_dir.expanduser().resolve(), contents)
        manifest_sha256 = (
            _write_manifest(args.manifest.expanduser().resolve(), manifest)
            if args.manifest
            else sha256_bytes(canonical_json(manifest))
        )
        print(json.dumps({
            "mode": "apply" if args.apply else "dry-run",
            "sourceSnapshots": manifest["sourceSnapshotCount"],
            "sourceRawResultOccurrences": manifest["sourceRawResultOccurrences"],
            "globalUniqueNormalizedInfoHashes": manifest[
                "globalUniqueNormalizedInfoHashCount"
            ],
            "sectionLevelUniqueInfoHashEntries": manifest[
                "sectionLevelUniqueInfoHashEntryCount"
            ],
            "destinationCounts": {
                filename: details["uniqueNormalizedInfoHashes"]
                for filename, details in manifest["destinations"].items()
            },
            "unresolvedRecords": manifest["unresolvedRecordCount"],
            "missingInfoHashRecords": manifest["missingInfoHashRecordCount"],
            "sectionCountDifferences": manifest["sectionCountDifferences"],
            "manifestSha256": manifest_sha256,
            "manifestPath": str(args.manifest.resolve()) if args.manifest else None,
            "writtenFiles": written,
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MigrationError as exc:
        raise SystemExit(f"migration error: {exc}") from exc
