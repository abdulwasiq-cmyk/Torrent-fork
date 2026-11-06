"""TV pack scanner: only season / complete-series packs of the right show are kept."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_tv_torrent_cache", ROOT / "scripts" / "build_tv_torrent_cache.py")
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


def cand(title, seeders=10, h="a", size=5 * 1024**3):
    return {"infoHash": h * 40, "title": title, "seeders": seeders, "leechers": 1, "size": size, "indexer": "X"}


def test_classify_packs_and_rejects_episodes_and_other_shows():
    assert B.classify("Reacher S02 1080p WEB-DL", "Reacher") == ("season", 2)
    assert B.classify("Reacher.Season.1.Complete.720p", "Reacher") == ("season", 1)        # complete SEASON 1
    assert B.classify("WandaVision.S01.COMPLETE.2160p.WEB-DL", "WandaVision") == ("season", 1)
    assert B.classify("Loki.S02.COMPLETE.1080p", "Loki") == ("season", 2)
    assert B.classify("Reacher Complete Series 1080p", "Reacher") == ("complete", 0)
    assert B.classify("Reacher S01 S02 S03 1080p", "Reacher") == ("complete", 0)
    assert B.classify("Reacher S01-S03 2160p", "Reacher") == ("complete", 0)
    assert B.classify("Reacher Seasons 1-3", "Reacher") == ("complete", 0)
    assert B.classify("Reacher S02E04 1080p", "Reacher") is None
    assert B.classify("Reacher 2x04 720p", "Reacher") is None
    assert B.classify("The Wire S01 1080p", "Reacher") is None
    assert B.classify("Reacher S01 CAM", "Reacher") is None


def test_select_keeps_best_per_season_orders_complete_first_and_dedupes():
    rows = [cand("Reacher S01 720p", 5, "1"), cand("Reacher S01 1080p", 50, "2"), cand("Reacher S01 2160p", 20, "3"),
            cand("Reacher S01 480p", 1, "4"), cand("Reacher S02 1080p", 9, "5"),
            cand("Reacher Complete Series 1080p", 7, "6"), cand("Reacher S02 1080p dup", 9, "5"),
            cand("Reacher S01E01 1080p", 99, "7"), {"title": "Reacher S03", "seeders": 3}]
    out = B.select_releases(rows, "Reacher")
    assert [(r["scope"], r["season"]) for r in out] == [("complete", 0), ("season", 1), ("season", 1), ("season", 1), ("season", 1), ("season", 2)]
    assert [r["infoHash"][0] for r in out if r["season"] == 1] == ["2", "3", "1", "4"]  # one per resolution, best seeded first


def test_entry_omits_season_for_complete_and_merge_keeps_movies():
    show = {"title": "Reacher", "year": 2022}
    entry = B.entry_for(show, B.select_releases([cand("Reacher Complete", 5, "1"), cand("Reacher S01", 4, "2")], "Reacher"))
    assert entry["year"] == 2022 and "season" not in entry["releases"][0] and entry["releases"][1]["season"] == 1
    existing = {"schemaVersion": 2, "kind": "torrent-options", "section": "x", "trackers": ["t"], "titles": {"movie:1": {"title": "M"}}}
    merged = B.merge_section(existing, {"tv:9": entry}, "x", "now")
    assert set(merged["titles"]) == {"movie:1", "tv:9"} and merged["trackers"] == ["t"]


def test_tv_rows_only_series_deduped():
    doc = {"subsections": {"a": {"mediaType": "tv", "results": [{"id": 5, "title": "A"}, {"tmdbId": 5, "title": "A"}]},
                           "b": {"mediaType": "movie", "results": [{"id": 6, "title": "M"}]}}}
    assert [r["title"] for r in B.tv_rows(doc)] == ["A"]


import asyncio


def test_discover_asks_complete_then_each_season_and_stops_after_two_misses():
    asked = []
    counter = iter("0123456789abcdef")

    async def searcher(query):
        asked.append(query)
        packs = {"Show complete": ["Show Complete Series 1080p"], "Show S01": ["Show S01 1080p"], "Show S02": ["Show S02 720p"],
                 "Show Season 3": ["Show Season 3 1080p"]}
        return [cand(t, 5, h=next(counter)) for t in packs.get(query, [])]

    rows = asyncio.run(B.discover("Show", searcher))
    assert asked == ["Show complete", "Show S01", "Show S02", "Show S03", "Show Season 3", "Show S04", "Show Season 4", "Show S05", "Show Season 5"]
    kept = B.select_releases(rows, "Show")
    assert [(r["scope"], r["season"]) for r in kept] == [("complete", 0), ("season", 1), ("season", 2), ("season", 3)]


def test_discover_ignores_episodes_and_other_shows_when_counting_misses():
    async def searcher(query):
        return [cand("Show S01E01 1080p", 99, "1"), cand("Other S01 1080p", 99, "2")]

    asked = []
    inner = searcher

    async def spy(query):
        asked.append(query)
        return await inner(query)

    asyncio.run(B.discover("Show", spy))
    assert asked == ["Show complete", "Show S01", "Show Season 1", "Show S02", "Show Season 2"]


def test_resolution_variety_beats_raw_seeders():
    rows = [cand(f"Show S01 720p v{i}", 100 - i, h=f"{i:x}") for i in range(6)] + [
        cand("Show S01 1080p", 3, "a"), cand("Show S01 2160p", 1, "b")]
    kept = B.select_releases(rows, "Show", per_bucket=4)
    assert {B.resolution_of(r["title"]) for r in kept} == {"720p", "1080p", "2160p"}
    assert len(kept) == 4
