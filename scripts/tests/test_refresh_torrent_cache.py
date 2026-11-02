import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "refresh_torrent_cache.py"
SPEC = importlib.util.spec_from_file_location("refresh_torrent_cache", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fixture_seed(seed: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    seed.mkdir(parents=True)
    metadata_bytes = {}
    torrent_bytes = {}
    manifest_files = {}
    for index, section in enumerate(MODULE.SECTIONS, start=1):
        if section == "marvel":
            row = {
                "id": 900,
                "title": "Marvel Series",
                "year": 2024,
                "mediaType": "tv",
                "seasonNumber": 2,
                "episodeNumber": 3,
            }
            subsection = "webSeries"
        else:
            row = {"id": 1000 + index, "title": f"{section.title()} Sample", "year": 2024}
            subsection = "movies"
        metadata = {
            "section": section,
            "metadataSelfContained": True,
            "subsections": {
                subsection: {"mediaType": "tv" if section == "marvel" else "movie", "results": [row]}
            },
        }
        metadata_path = seed / f"{section}.json"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        metadata_bytes[metadata_path.name] = metadata_path.read_bytes()

        identity = index.to_bytes(20, "big").hex()
        document = {
            "schemaVersion": 1,
            "section": section,
            "records": [{
                "identityKind": "infoHash",
                "identity": identity,
                "infoHash": identity,
                "title": f"{section} cached torrent",
                "sourceProvenance": [{"sourceFile": "historical-source.json"}],
            }],
        }
        content = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        torrent_path = seed / f"{section}-torrents.json"
        torrent_path.write_bytes(content)
        torrent_bytes[torrent_path.name] = content
        manifest_files[torrent_path.name] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "recordCount": 1,
        }

    manifest = {
        "schemaVersion": 1,
        "generation": 1,
        "files": manifest_files,
        "globalUniqueNormalizedInfoHashes": 9,
        "sectionLevelEntries": 9,
    }
    (seed / MODULE.SEED_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return metadata_bytes, torrent_bytes


def test_empty_search_results_leave_migrated_torrent_and_metadata_files_unchanged(tmp_path):
    seed = tmp_path / "seed"
    metadata_before, torrent_before = _fixture_seed(seed)
    manifest_before = (seed / MODULE.SEED_MANIFEST).read_bytes()
    calls = []

    async def no_results(query):
        calls.append(query)
        return []

    summary = asyncio.run(MODULE.run(seed, no_results))

    assert len(calls) == 9
    assert summary["updatedFiles"] == []
    assert (seed / MODULE.SEED_MANIFEST).read_bytes() == manifest_before
    assert {name: (seed / name).read_bytes() for name in torrent_before} == torrent_before
    assert {name: (seed / name).read_bytes() for name in metadata_before} == metadata_before


def test_torrent_refresh_merges_hash_results_and_writes_no_metadata_files(tmp_path):
    seed = tmp_path / "seed"
    metadata_before, torrent_before = _fixture_seed(seed)
    old_hash = json.loads(torrent_before["hollywood-torrents.json"])["records"][0]["identity"]
    new_hash = "ab" * 20
    calls = []

    async def results_for_card(query):
        calls.append(query)
        if query.startswith("Hollywood Sample"):
            return [{
                "title": "Hollywood Sample 2024 1080p WEB-DL",
                "infoHash": old_hash.upper(),
                "magnetUrl": f"magnet:?xt=urn:btih:{old_hash}",
                "provider": "RefreshIndexer",
                "seeders": 37,
                "extraResultField": {"preserve": True},
            }]
        if query.startswith("Marvel Series"):
            return [{
                "title": "Marvel Series S02E03 2024",
                "infoHash": new_hash.upper(),
                "magnetUrl": f"magnet:?xt=urn:btih:{new_hash}",
                "provider": "EpisodeIndexer",
            }]
        return []

    summary = asyncio.run(MODULE.run(seed, results_for_card))

    assert summary["generation"] > 1
    assert summary["sections"]["hollywood"]["newHashes"] == 0
    assert summary["sections"]["marvel"]["newHashes"] == 1
    assert "S02 E03" in calls[1] or "S02 E03" in calls[2]
    assert {name: (seed / name).read_bytes() for name in metadata_before} == metadata_before
    assert set(summary["updatedFiles"]) == {"hollywood-torrents.json", "marvel-torrents.json"}

    hollywood = json.loads((seed / "hollywood-torrents.json").read_text())["records"][0]
    assert hollywood["sourceProvenance"][0]["sourceFile"] == "historical-source.json"
    assert hollywood["provider"] == "RefreshIndexer"
    assert hollywood["seeders"] == 37
    assert hollywood["extraResultField"] == {"preserve": True}

    marvel = json.loads((seed / "marvel-torrents.json").read_text())
    episode = next(record for record in marvel["records"] if record["identity"] == new_hash)
    assert any(
        match.get("seasonNumber") == 2 and match.get("episodeNumber") == 3
        for match in episode["metadataCardMatches"]
    )
    manifest = json.loads((seed / MODULE.SEED_MANIFEST).read_text())
    assert manifest["files"]["marvel-torrents.json"]["recordCount"] == 2
    assert manifest["files"]["hollywood-torrents.json"]["recordCount"] == 1


def test_unmatched_and_missing_hash_results_are_not_silently_added(tmp_path):
    seed = tmp_path / "seed"
    _metadata_before, torrent_before = _fixture_seed(seed)

    async def results(_query):
        return [
            {"title": "Unrelated Title", "infoHash": "ff" * 20},
            {"title": "Hollywood Sample 2024", "provider": "NoHashIndexer"},
        ]

    summary = asyncio.run(MODULE.run(seed, results))

    assert summary["rejectedResultsWithoutInfoHash"] == 1
    assert summary["updatedFiles"] == []
    assert {name: (seed / name).read_bytes() for name in torrent_before} == torrent_before


def test_normalizes_hex_and_base32_info_hashes():
    identity = "ab" * 20
    encoded = __import__("base64").b32encode(bytes.fromhex(identity)).decode().rstrip("=").lower()
    assert MODULE.normalize_info_hash(identity.upper()) == identity
    assert MODULE.result_info_hash({"magnetUrl": f"magnet:?xt=urn:btih:{encoded}"}) == identity
