"""Torrent migration: filters mirror the Prepare card, matching is by TMDB id or title+year,
and the committed per-section torrent files stay small, valid and out of the metadata files."""
import base64
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("migrate_torrent_cache", ROOT / "scripts" / "migrate_torrent_cache.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)

SEED = ROOT / "backend" / "cache-seed"
MB = 1024 * 1024
LIMITS = {"minSizeBytes": 250 * MB, "maxSizeBytes": 2 * 1024 * MB}


def release(title, size=700 * MB, seeders=10, leechers=1, h="a" * 40, **extra):
    return {"infoHash": h, "title": title, "size": size, "seeders": seeders, "leechers": leechers,
            "indexer": "X", **extra}


def test_normalize_title_matches_frontend_rules():
    assert M.normalize_title("The Fantastic Four: First Steps") == "fantastic four first steps"
    assert M.normalize_title("Fantastic.Four_First-Steps (2025)") == "fantastic four first steps 2025"
    assert M.normalize_title("Tom & Jerry") == "tom and jerry"
    assert M.normalize_title("Don't Move") == "dont move"


def test_info_hash_accepts_hex_base32_and_magnet():
    digest = "0123456789abcdef0123456789abcdef01234567"
    assert M.info_hash_of(digest.upper()) == digest
    assert M.info_hash_of(base64.b32encode(bytes.fromhex(digest)).decode()) == digest
    assert M.info_hash_of("", f"magnet:?xt=urn:btih:{digest}&dn=x&tr=udp%3A%2F%2Ft%3A1%2Fannounce") == digest
    assert M.info_hash_of("not-a-hash") == ""


def test_size_window_low_quality_and_phrase_filters():
    candidates = [
        release("Dune (2021) 1080p", h="1" * 40),
        release("Dune (2021) 1080p HDCAM", h="2" * 40),             # cam
        release("Dune (2021) 1080p", size=100 * MB, h="3" * 40),    # too small
        release("Dune (2021) 2160p", size=9 * 1024 * MB, h="4" * 40),  # too big
        release("Duneland (2021) 1080p", h="5" * 40),               # title is only part of a word
        release("Other Movie 1080p", h="6" * 40),                   # different title
    ]
    kept = M.select_releases(candidates, "Dune", LIMITS)
    assert [r["infoHash"] for r in kept] == ["1" * 40]


def test_alias_in_brackets_matches_base_title_and_active_swarms_are_preferred():
    candidates = [
        release("Dhood 2025 720p", seeders=0, h="a" * 40),
        release("Dhood 2025 1080p", seeders=5, h="b" * 40),
    ]
    kept = M.select_releases(candidates, "Dhood (Sandstorm)", LIMITS)
    assert [r["infoHash"] for r in kept] == ["b" * 40]
    # with no seeded release at all, nothing is hidden
    unseeded = M.select_releases([release("Dhood 2025 720p", seeders=0)], "Dhood (Sandstorm)", LIMITS)
    assert len(unseeded) == 1


def test_per_resolution_and_per_title_caps():
    candidates = [release(f"Heat 1995 1080p v{i}", seeders=100 - i, h=f"{i:040x}") for i in range(8)]
    candidates += [release(f"Heat 1995 720p v{i}", seeders=50 - i, h=f"{i + 100:040x}") for i in range(8)]
    candidates += [release(f"Heat 1995 2160p v{i}", seeders=20 - i, h=f"{i + 200:040x}") for i in range(8)]
    kept = M.select_releases(candidates, "Heat", LIMITS)
    assert len(kept) == M.MAX_RELEASES_PER_BAND   # all three resolutions sit in one size band
    assert sum(1 for r in kept if "1080p" in r["title"]) == M.MAX_RELEASES_PER_RESOLUTION
    assert [r["seeders"] for r in kept] == sorted((r["seeders"] for r in kept), reverse=True)


def test_pool_matches_by_tmdb_id_or_title_and_year_and_merges_duplicates():
    pool = M.Pool()
    pool.add(release("Dune 2021 1080p", h="a" * 40, magnetUrl="magnet:?xt=urn:btih:" + "a" * 40 + "&tr=udp%3A%2F%2Ft%3A1"),
             [{"mediaType": "movie", "tmdbId": "438631", "title": "Dune", "year": "2021"}])
    pool.add(release("Heat 1995 1080p", h="b" * 40), [{"mediaType": "movie", "title": "Heat", "year": "1995"}])
    pool.add(release("Show S01 1080p", h="c" * 40), [{"mediaType": "tv", "tmdbId": "1", "title": "Show", "year": "2020"}])
    pool.add(release("Dune 2021 1080p", seeders=99, h="a" * 40), [])  # same torrent again, fresher numbers
    assert [r["infoHash"] for r in pool.candidates("438631", "Dune", "")] == ["a" * 40]
    assert pool.releases["a" * 40]["seeders"] == 99
    assert pool.releases["a" * 40]["_trackers"] == ["udp://t:1"]  # kept from the first sighting
    assert [r["infoHash"] for r in pool.candidates("", "Heat", "1995")] == ["b" * 40]
    assert pool.candidates("", "Heat", "1996") == []   # a remake with another year must not match
    assert pool.candidates("1", "Show", "2020") == []  # TV is not migrated


def test_build_section_is_slim_deduplicated_and_tracker_list_drops_dead_hosts():
    pool = M.Pool()
    live, dead = "udp://tracker.opentrackr.org:1337/announce", "udp://9.rarbg.to:2710/announce"
    magnet = "magnet:?xt=urn:btih:{h}&tr=" + live.replace(":", "%3A").replace("/", "%2F") + "&tr=" + dead.replace(":", "%3A").replace("/", "%2F")
    pool.add(release("Dune 2021 1080p", h="a" * 40, magnetUrl=magnet.format(h="a" * 40), overview="long text", posterUrl="p"),
             [{"mediaType": "movie", "tmdbId": "438631", "title": "Dune", "year": "2021"}])
    document = {"subsections": {
        "latest": {"mediaType": "movie", "results": [{"title": "Dune", "tmdbId": 438631, "year": 2021}]},
        "popular": {"mediaType": "movie", "results": [{"title": "Dune", "id": 438631, "year": 2021}]},
        "series": {"mediaType": "tv", "results": [{"title": "Show", "tmdbId": 9}]},
    }}
    output, report = M.build_section("hollywood", document, pool, LIMITS, "2026-01-01T00:00:00+00:00")
    assert report == {"movieRows": 1, "titlesWithReleases": 1, "releases": 1}
    assert output["trackers"] == [live]
    (entry,) = output["titles"].values()
    assert set(entry["releases"][0]) <= {"infoHash", "title", "size", "seeders", "leechers", "indexer", "infoUrl"}
    assert "magnetUrl" not in json.dumps(output) and "overview" not in json.dumps(output)


# ---- the committed files ---------------------------------------------------------------
def test_committed_torrent_files_are_valid_small_and_match_their_section_rows():
    for section in M.SECTIONS:
        raw = (SEED / f"{section}-torrents.json").read_text(encoding="utf-8")
        assert len(raw.encode()) < 1024 * 1024, f"{section}-torrents.json must stay small (lookups, not a data dump)"
        doc = json.loads(raw)
        assert (doc["schemaVersion"], doc["kind"], doc["section"]) == (M.SCHEMA_VERSION, "torrent-options", section)
        metadata = json.loads((SEED / f"{section}.json").read_text(encoding="utf-8"))
        known = {f"movie:{M.row_tmdb_id(row)}" for row in M.movie_rows(metadata) if M.row_tmdb_id(row)}
        for key, entry in doc["titles"].items():
            if key.startswith("movie:"):
                assert key in known, f"{section}: {key} is not a row of {section}.json"
            assert 1 <= len(entry["releases"]) <= M.MAX_RELEASES_PER_TITLE
            hashes = [r["infoHash"] for r in entry["releases"]]
            assert len(hashes) == len(set(hashes)) and all(M.HEX40.match(h) for h in hashes)
            # The shared section file also contains TV season/complete-series packs. Those are\n            # intentionally discovered with the movie size window disabled (see build_tv_torrent_cache.py),\n            # so the declared cache limits apply only to movie lookup entries.\n            if key.startswith("movie:"):\n                assert all(doc["limits"]["minSizeBytes"] <= r["size"] <= doc["limits"]["maxSizeBytes"] for r in entry["releases"])\n            else:\n                assert key.startswith("tv:") and all(r["size"] > 0 for r in entry["releases"])
        # torrent data must never leak back into the fast metadata files
        for field in ("magnetUrl", "infoHash", "torrentMatches", "downloadUrl"):
            assert field not in metadata_text(section), f"{section}.json must not contain {field}"


def metadata_text(section):
    return (SEED / f"{section}.json").read_text(encoding="utf-8")


def test_size_bands_keep_in_window_releases_when_big_ones_have_more_seeders():
    """A 2 GB display window must still find releases when the best-seeded ones are all 4 GB."""
    big = [release(f"Heat 1995 1080p big{i}", size=4 * 1024 * MB, seeders=500 - i, h=f"{i + 300:040x}") for i in range(12)]
    small = [release(f"Heat 1995 1080p small{i}", size=int(1.5 * 1024) * MB, seeders=5 - (i % 3), h=f"{i + 400:040x}") for i in range(3)]
    limits = {"minSizeBytes": 100 * MB, "maxSizeBytes": 10 * 1024 * MB}
    kept = M.select_releases(big + small, "Heat", limits)
    in_window = [r for r in kept if r["size"] <= 2 * 1024 * MB]
    assert len(in_window) == 3, "the 1.5 GB releases survive although the 4 GB ones out-seed them"
    assert sum(1 for r in kept if r["size"] > 3 * 1024 * MB) == M.MAX_RELEASES_PER_RESOLUTION
