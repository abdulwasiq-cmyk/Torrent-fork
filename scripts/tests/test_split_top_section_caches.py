"""Regression tests for metadata-only top-section cache splitting."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

SCRIPT = Path(__file__).resolve().parents[1] / "split_top_section_caches.py"
SPEC = importlib.util.spec_from_file_location("split_top_section_caches", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

ENRICH_SCRIPT = Path(__file__).resolve().parents[1] / "enrich_top_section_metadata.py"
ENRICH_SPEC = importlib.util.spec_from_file_location("enrich_top_section_metadata", ENRICH_SCRIPT)
ENRICH = importlib.util.module_from_spec(ENRICH_SPEC)
assert ENRICH_SPEC and ENRICH_SPEC.loader
ENRICH_SPEC.loader.exec_module(ENRICH)


class MetadataRowTests(unittest.TestCase):
    def test_tmdb_list_id_is_also_stored_as_tmdb_id(self):
        row = MODULE.metadata_row({"id": 1234, "title": "Film", "posterUrl": "/p.jpg"})
        self.assertEqual(row["tmdbId"], 1234)
        kept = MODULE.metadata_row({"id": 1, "tmdbId": 99, "title": "Film"})
        self.assertEqual(kept["tmdbId"], 99)  # an explicit tmdbId is never replaced
        self.assertNotIn("tmdbId", MODULE.metadata_row({"id": "abc", "title": "Film"}))

    def test_stale_stream_fields_are_dropped_but_broken_flag_is_kept(self):
        row = MODULE.metadata_row({
            "id": 5, "title": "Film", "nexStreamPlayable": False, "nexStreamVerified": False,
            "directStreamAvailability": {"provider": "VidRift"}, "directStreamBroken": True,
        })
        for key in ("nexStreamPlayable", "nexStreamVerified", "directStreamAvailability"):
            self.assertNotIn(key, row)
        self.assertTrue(row["directStreamBroken"])


class MarvelSeriesSplitterTests(unittest.TestCase):
    def test_legacy_marvel_uses_only_top_level_catalogue_cards(self):
        payload = {
            "results": [{
                "key": "wandavision",
                "title": "WandaVision",
                "year": 2021,
                "tmdbId": 85271,
                "posterUrl": "/poster.jpg",
                "torrent": {"results": [{"title": "WandaVision S01E01 1080p"}]},
                "nexStream": {"streams": [{"title": "WandaVision S01E01 WEB-DL"}]},
                "episodes": [{
                    "title": "WandaVision S01E01",
                    "tmdbId": 999001,
                    "posterUrl": "/episode.jpg",
                    "torrentResults": [{"title": "WandaVision S01E01 1080p"}],
                }],
            }],
        }

        rows = MODULE.collect_top_level_results(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "WandaVision")
        self.assertEqual(rows[0]["tmdbId"], 85271)
        self.assertNotIn("torrent", rows[0])
        self.assertNotIn("nexStream", rows[0])
        self.assertNotIn("episodes", rows[0])

    def test_nested_episode_titles_are_not_collected(self):
        payload = {
            "results": [{
                "title": "Loki",
                "year": 2021,
                "tmdbId": 84958,
                "posterUrl": "/loki.jpg",
                "episodes": [{
                    "title": "Loki S01E01 1080p WEB-DL",
                    "tmdbId": 999002,
                    "posterUrl": "/episode.jpg",
                }],
            }],
        }

        rows = MODULE.collect_top_level_results(payload)

        self.assertEqual([row["title"] for row in rows], ["Loki"])


class MetadataEnrichmentTests(unittest.TestCase):
    def test_tmdb_image_urls_normalize_repeated_size_prefixes(self):
        cases = {
            "https://image.tmdb.org/t/p/w500/w780/poster.jpg": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "https://image.tmdb.org/t/p/original/w500/backdrop.jpg": "https://image.tmdb.org/t/p/w780/backdrop.jpg",
            "/w500/w780/poster.jpg": "https://image.tmdb.org/t/p/w500/poster.jpg",
            "original/backdrop.jpg": "https://image.tmdb.org/t/p/w780/backdrop.jpg",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(ENRICH.image_url(source, "w500" if "poster" in source else "w780"), expected)

    def test_failed_imdb_refresh_preserves_valid_cached_values(self):
        row = {
            "imdbId": "tt0133093", "imdbRating": 8.7, "imdbVotes": "2.1M",
            "imdbUrl": "https://www.imdb.com/title/tt0133093/", "imdbRatingStatus": "found",
        }

        ENRICH.apply_imdb(row, {"status": "unavailable", "checkedAt": 123}, overwrite=True)

        self.assertEqual(row["imdbId"], "tt0133093")
        self.assertEqual(row["imdbRating"], 8.7)
        self.assertEqual(row["imdbRatingStatus"], "found")

    def test_deep_metadata_refresh_replaces_only_with_valid_values(self):
        row = {"title": "Curated title", "overview": "Known overview", "rating": 7.1}
        details = {"title": "TMDB title", "overview": "Updated overview", "rating": 8.2, "posterUrl": ""}

        ENRICH.merge_metadata(row, details, mode="missing")
        self.assertEqual(row["overview"], "Known overview")
        self.assertEqual(row["title"], "Curated title")

        ENRICH.merge_metadata(row, details, mode="deep")
        self.assertEqual(row["overview"], "Updated overview")
        self.assertEqual(row["rating"], 8.2)
        self.assertEqual(row["title"], "Curated title")

    def test_metadata_refresh_derives_missing_year_from_verified_release_date(self):
        row = {"year": None, "releaseDate": "2021-08-12"}
        changed = ENRICH.merge_metadata(row, {}, mode="missing")
        self.assertEqual(row["year"], 2021)
        self.assertEqual(changed, 1)

    def test_metadata_refresh_preserves_existing_year_when_date_differs(self):
        row = {"year": 2020, "releaseDate": "2021-08-12"}
        changed = ENRICH.merge_metadata(row, {}, mode="deep")
        self.assertEqual(row["year"], 2020)
        self.assertEqual(changed, 0)

    def test_request_retries_rate_limit_and_honors_retry_after(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"ok": true}'

        rate_limited = urllib.error.HTTPError(
            "http://localhost/api/health", 429, "rate limited", {"Retry-After": "0"}, None
        )
        with patch.dict("os.environ", {"SECTION_METADATA_RETRIES": "1"}), \
             patch.object(ENRICH.urllib.request, "urlopen", side_effect=[rate_limited, FakeResponse()]) as urlopen, \
             patch.object(ENRICH.time, "sleep") as sleep:
            self.assertEqual(ENRICH.request_json("http://localhost/api/health"), {"ok": True})

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_unsupported_endpoint_is_not_requested_repeatedly(self):
        url = "http://localhost/api/tv/tmdb-metadata/42"
        template = ENRICH.endpoint_template(url)
        ENRICH.UNSUPPORTED_ENDPOINTS.discard(template)
        missing = urllib.error.HTTPError(url, 404, "not found", {}, None)
        try:
            with patch.object(ENRICH.urllib.request, "urlopen", side_effect=missing) as urlopen:
                with self.assertRaises(ENRICH.UnsupportedEndpoint):
                    ENRICH.request_json(url)
                with self.assertRaises(ENRICH.UnsupportedEndpoint):
                    ENRICH.request_json(url)
            self.assertEqual(urlopen.call_count, 1)
        finally:
            ENRICH.UNSUPPORTED_ENDPOINTS.discard(template)

    def test_refresh_preserves_order_and_never_reads_or_writes_torrent_files(self):
        rows = [
            {
                "id": 11, "tmdbId": 11, "title": "First", "year": 2020, "mediaType": "movie",
                "imdbId": "tt0000011", "imdbRating": 7.1, "imdbVotes": "100",
                "imdbUrl": "https://www.imdb.com/title/tt0000011/", "posterUrl": "/first.jpg",
                "backdropUrl": "/first-backdrop.jpg", "overview": "First overview", "rating": 7.1,
                "releaseDate": "2020-01-01", "ottAvailability": {"region": "IN"},
            },
            {
                "id": 22, "tmdbId": 22, "title": "Second", "year": 2021, "mediaType": "movie",
                "imdbId": "tt0000022", "imdbRating": 7.2, "imdbVotes": "200",
                "imdbUrl": "https://www.imdb.com/title/tt0000022/", "posterUrl": "/second.jpg",
                "backdropUrl": "/second-backdrop.jpg", "overview": "Second overview", "rating": 7.2,
                "releaseDate": "2021-01-01", "ottAvailability": {"region": "IN"},
            },
        ]
        document = {"section": "hollywood", "subsections": {
            "popular": {"mediaType": "movie", "results": rows},
        }}
        with tempfile.TemporaryDirectory() as temp_dir:
            seed = Path(temp_dir)
            section_path = seed / "hollywood.json"
            torrent_path = seed / "hollywood-torrents.json"
            section_path.write_text(json.dumps(document), encoding="utf-8")
            torrent_before = b"not-json-and-must-remain-untouched"
            torrent_path.write_bytes(torrent_before)
            with patch.object(ENRICH, "SEED", seed), \
                 patch.object(ENRICH, "request_json", side_effect=AssertionError("complete rows need no API calls")):
                result = ENRICH.refresh_section(
                    "hollywood", mode="missing", imdb_cache={}, ott_items={},
                    detail_cache={}, ott_lookup_cache={}, backup_dir=seed / "backup",
                )
            updated = json.loads(section_path.read_text(encoding="utf-8"))
            self.assertEqual([row["title"] for row in updated["subsections"]["popular"]["results"]],
                             ["First", "Second"])
            self.assertEqual(torrent_path.read_bytes(), torrent_before)
            self.assertTrue(Path(result["backup"]).is_file())
            self.assertEqual(result["unresolved"], 0)
            self.assertFalse(any(ENRICH.has_torrent_payload(row) for row in rows))

    def test_torrent_fields_in_a_section_block_writes(self):
        document = {"section": "hollywood", "subsections": {
            "popular": {"mediaType": "movie", "results": [{"title": "A", "magnetUrl": "magnet:?xt=abc"}]},
        }}
        with tempfile.TemporaryDirectory() as temp_dir:
            seed = Path(temp_dir)
            section_path = seed / "hollywood.json"
            original = json.dumps(document).encode()
            section_path.write_bytes(original)
            with patch.object(ENRICH, "SEED", seed):
                with self.assertRaisesRegex(RuntimeError, "torrent-specific data"):
                    ENRICH.refresh_section(
                        "hollywood", mode="missing", imdb_cache={}, ott_items={},
                        detail_cache={}, ott_lookup_cache={}, backup_dir=seed / "backup",
                    )
            self.assertEqual(section_path.read_bytes(), original)
            self.assertFalse((seed / "backup").exists())


if __name__ == "__main__":
    unittest.main()
