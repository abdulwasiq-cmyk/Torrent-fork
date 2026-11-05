"""Per-title torrent lookups: dictionary hits on memoized files, never part of page loads.

The loader module has no FastAPI dependency, so most of this runs without the app.
"""

import json
import shutil
import time
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

import pytest

from catalogues import torrent_options as T

SEED = Path(__file__).resolve().parents[1] / "cache-seed"


def write_file(directory: Path, section: str, titles: dict, trackers=("udp://t.example:1/announce",)):
    document = {"schemaVersion": 2, "kind": "torrent-options", "section": section,
                "trackers": list(trackers), "titles": titles}
    (directory / f"{section}-torrents.json").write_text(json.dumps(document), encoding="utf-8")


def release(h, seeders=5, title="Dune (2021) 1080p", size=900 * 1024 * 1024, **extra):
    return {"infoHash": h * 40, "title": title, "size": size, "seeders": seeders, "leechers": 1,
            "indexer": "X", **extra}


@pytest.fixture(autouse=True)
def _fresh_memory():
    T.clear_memory_cache()
    yield
    T.clear_memory_cache()


def test_magnet_is_built_from_hash_title_and_shared_trackers():
    magnet = T.build_magnet("a" * 40, "Dune (2021) [1080p]", ["udp://t.example:1/announce"])
    parts = urlsplit(magnet)
    assert magnet.startswith("magnet:?xt=urn:btih:" + "a" * 40)
    query = parse_qsl(parts.query, keep_blank_values=True)
    assert ("dn", "Dune (2021) [1080p]") in query
    assert [v for k, v in query if k == "tr"] == ["udp://t.example:1/announce"]
    assert "%3A" in magnet and unquote(magnet).count("udp://") == 1


def test_lookup_by_tmdb_id_then_by_title_and_year(tmp_path):
    write_file(tmp_path, "hollywood", {"movie:438631": {"title": "Dune", "year": 2021, "releases": [release("a")]}})
    by_id = T.lookup(("hollywood",), tmdb_id="438631", seed_dir=tmp_path)
    assert [r["infoHash"] for r in by_id] == ["a" * 40]
    assert by_id[0]["magnetUrl"].startswith("magnet:?xt=urn:btih:" + "a" * 40)
    assert by_id[0]["protocol"] == "torrent" and by_id[0]["mediaTitle"] == "Dune" and by_id[0]["year"] == 2021
    by_title = T.lookup(("hollywood",), title="dune", year="2021", seed_dir=tmp_path)
    assert [r["infoHash"] for r in by_title] == ["a" * 40]
    assert T.lookup(("hollywood",), title="Dune", year="1984", seed_dir=tmp_path) == []   # remake guard
    assert T.lookup(("hollywood",), title="Dune", seed_dir=tmp_path) == []                # a year is required
    assert T.lookup(("hollywood",), tmdb_id="1", seed_dir=tmp_path) == []


def test_all_sections_merge_and_dedupe_keeping_the_best_swarm(tmp_path):
    write_file(tmp_path, "hollywood", {"movie:1": {"title": "Dune", "year": 2021,
               "releases": [release("a", seeders=5), release("b", seeders=50)]}})
    write_file(tmp_path, "marvel", {"movie:1": {"title": "Dune", "year": 2021,
               "releases": [release("a", seeders=99, infoUrl="https://x.example/a"), release("c", seeders=1)]}},
               trackers=("udp://other.example:2/announce",))
    rows = T.lookup(None, tmdb_id="1", seed_dir=tmp_path)
    assert [r["infoHash"][0] for r in rows] == ["a", "b", "c"]            # best seeded first
    assert rows[0]["seeders"] == 99 and rows[0]["sourceUrl"] == "https://x.example/a"
    assert len(rows) == 3
    only_marvel = T.lookup(("marvel",), tmdb_id="1", seed_dir=tmp_path)
    assert {r["infoHash"][0] for r in only_marvel} == {"a", "c"}
    assert "other.example" in unquote(only_marvel[0]["magnetUrl"])      # each file's own trackers


def test_missing_corrupt_or_wrong_shape_files_are_ignored_not_fatal(tmp_path):
    (tmp_path / "hollywood-torrents.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "marvel-torrents.json").write_text(json.dumps({"schemaVersion": 1, "section": "marvel", "titles": {}}))
    write_file(tmp_path, "dc", {"movie:1": {"title": "Dune", "year": 2021, "releases": [release("a")]}})
    assert [r["infoHash"][0] for r in T.lookup(None, tmdb_id="1", seed_dir=tmp_path)] == ["a"]
    assert T.lookup(("anime",), tmdb_id="1", seed_dir=tmp_path) == []   # file does not exist


def test_file_is_parsed_once_and_reloaded_only_when_it_changes(tmp_path, monkeypatch):
    write_file(tmp_path, "dc", {"movie:1": {"title": "Dune", "year": 2021, "releases": [release("a")]}})
    parses = []
    real_loads = json.loads
    monkeypatch.setattr(T.json, "loads", lambda text, *a, **k: (parses.append(1), real_loads(text, *a, **k))[1])
    for _ in range(50):
        T.lookup(("dc",), tmdb_id="1", seed_dir=tmp_path)
    assert len(parses) == 1, "repeated lookups must be dictionary hits, not re-reads"
    time.sleep(0.01)
    write_file(tmp_path, "dc", {"movie:1": {"title": "Dune", "year": 2021, "releases": [release("a"), release("b")]}})
    assert len(T.lookup(("dc",), tmdb_id="1", seed_dir=tmp_path)) == 2   # picked up after a deploy/overlay
    assert len(parses) == 2


def test_results_are_capped(tmp_path):
    releases = [release(format(i, "x")[-1], seeders=i, title=f"Dune {i} 1080p") for i in range(1, 16)]
    releases = [{**r, "infoHash": format(i, "040x")} for i, r in enumerate(releases, 1)]
    write_file(tmp_path, "dc", {"movie:1": {"title": "Dune", "year": 2021, "releases": releases}})
    rows = T.lookup(("dc",), tmdb_id="1", seed_dir=tmp_path)
    assert len(rows) == T.MAX_RESULTS and rows[0]["seeders"] == 15


# ---- against the committed seed files ---------------------------------------------------
def test_real_seed_files_serve_prepare_rows_for_a_known_title():
    rows = T.lookup(None, tmdb_id="617126", seed_dir=SEED, min_size=250 * 1024 * 1024, max_size=2 * 1024 ** 3)   # The Fantastic Four: First Steps
    assert rows, "Marvel title must have releases in the committed torrent files"
    for row in rows:
        assert len(row["infoHash"]) == 40 and row["magnetUrl"].startswith("magnet:?xt=urn:btih:" + row["infoHash"])
        assert 250 * 1024 * 1024 <= row["size"] <= 2 * 1024 ** 3
    assert [r["seeders"] for r in rows] == sorted((r["seeders"] for r in rows), reverse=True)


def test_real_lookup_is_fast_enough_to_run_on_every_prepare_click():
    T.lookup(None, tmdb_id="617126", seed_dir=SEED)                 # warm: parses the nine files once
    started = time.perf_counter()
    for _ in range(200):
        T.lookup(None, tmdb_id="617126", seed_dir=SEED)
    per_call_ms = (time.perf_counter() - started) / 200 * 1000
    assert per_call_ms < 5, f"lookup took {per_call_ms:.2f} ms per call"


def test_route_exists_in_source_and_stays_out_of_page_load_paths():
    """FastAPI is not needed: check the wiring from source, like the structure snapshot does."""
    source = (SEED.parent / "catalogues" / "section_caches.py").read_text(encoding="utf-8")
    assert '"/api/sections/{section}/torrent-options"' in source
    # the section metadata route must never touch torrent data
    metadata_route = source.split('@router.get("/api/sections/{section}")')[1].split("@router.get(")[0]
    assert "torrent" not in metadata_route.lower()
    snapshot = json.loads((Path(__file__).parent / "snapshots" / "app_structure.json").read_text())
    for module in ("main", "fullstack_app"):
        names = [route[2] for route in snapshot[module]["routes"]]
        assert names.index("api_get_torrent_options") == names.index("api_get_section_cache") + 1


def test_seed_directory_is_not_modified_by_lookups(tmp_path):
    shutil.copytree(SEED, tmp_path / "seed", ignore=shutil.ignore_patterns("runtime"))
    before = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "seed").glob("*-torrents.json")}
    T.lookup(None, tmdb_id="617126", seed_dir=tmp_path / "seed")
    assert before == {p.name: p.stat().st_mtime_ns for p in (tmp_path / "seed").glob("*-torrents.json")}


def test_tv_lookup_orders_packs_and_never_mixes_with_movies(tmp_path):
    write_file(tmp_path, "hollywood", {
        "movie:5": {"title": "Reacher", "year": 2022, "releases": [release("m")]},
        "tv:5": {"title": "Reacher", "year": 2022, "releases": [
            release("b", 9, "Reacher S02", size=9 * 1024**3, season=2),
            release("c", 3, "Reacher Complete", size=40 * 1024**3, scope="complete"),
            release("a", 50, "Reacher S01", size=8 * 1024**3, season=1)]}})
    rows = T.lookup(("hollywood",), tmdb_id="5", seed_dir=tmp_path, media="tv")
    assert [(r["scope"], r["season"]) for r in rows] == [("complete", 0), ("season", 1), ("season", 2)]
    assert rows[0]["size"] == 40 * 1024**3                       # no size window for packs
    assert rows[0]["magnetUrl"].startswith("magnet:?xt=urn:btih:" + "c" * 40)
    assert [r["infoHash"][0] for r in T.lookup(("hollywood",), tmdb_id="5", seed_dir=tmp_path)] == ["m"]
    by_title = T.lookup(("hollywood",), title="reacher", year="2022", seed_dir=tmp_path, media="tv")
    assert len(by_title) == 3
    assert T.lookup(("hollywood",), tmdb_id="5", seed_dir=tmp_path, media="anime") == []
