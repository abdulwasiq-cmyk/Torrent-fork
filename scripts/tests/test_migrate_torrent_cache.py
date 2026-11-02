"""Tests for the offline torrent-cache migration utility."""
import base64
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "migrate_torrent_cache.py"
SPEC = importlib.util.spec_from_file_location("migrate_torrent_cache", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TorrentCacheMigrationTests(unittest.TestCase):
    def test_hash_normalization_accepts_hex_and_base32_magnet_hashes(self):
        raw_hash = "0123456789abcdef" * 2 + "01234567"
        base32_hash = base64.b32encode(bytes.fromhex(raw_hash)).decode("ascii").lower()

        self.assertEqual(MODULE._normalize_hash(raw_hash.upper()), raw_hash)
        self.assertEqual(MODULE._normalize_hash(base32_hash), raw_hash)
        self.assertEqual(
            MODULE.info_hash({"magnetUrl": f"magnet:?xt=urn:btih:{base32_hash}"}),
            raw_hash,
        )

    def test_merging_nested_result_fields_does_not_mutate_source_variants(self):
        record = MODULE._new_output_record(
            "infoHash", "0123456789abcdef" * 2 + "01234567"
        )
        variants = [
            {
                "infoHash": record["identity"],
                "details": {"first": {"value": "one"}},
                "availability": [{"region": "US"}],
            },
            {
                "infoHash": record["identity"],
                "details": {"second": {"value": "two"}},
                "availability": [{"provider": "existing"}],
            },
        ]
        for result in variants:
            MODULE._add_source_variant(record, result, {"source": "fixture"})
        originals = [MODULE._canonical_value(result) for result in variants]

        merged = MODULE._merge_result_variants(record)

        self.assertIn("first", merged["details"])
        self.assertIn("second", merged["details"])
        self.assertEqual(
            [MODULE._canonical_value(result) for result in variants],
            originals,
        )

    def test_build_preserves_results_merges_hashes_maps_sections_and_keeps_unresolved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "sources"
            metadata_dir = root / "metadata"
            output_dir = root / "output"
            source_dir.mkdir()
            history_dir = root / "history"
            history_dir.mkdir()
            metadata_dir.mkdir()

            cards = {
                "hollywood": ("movie", [
                    {"id": 11, "title": "Film A", "year": 2024},
                    {"id": 22, "title": "Film B", "year": 2023},
                ]),
                "highest-rated": ("movie", [{"id": 11, "title": "Film A", "year": 2024}]),
                "marvel": ("tv", [{"id": 88, "title": "Orbit Show", "year": 2022}]),
            }
            metadata_bytes = {}
            for section in MODULE.SECTIONS:
                media_type, results = cards.get(section, ("movie", []))
                content = MODULE.canonical_json({
                    "section": section,
                    "subsections": {
                        "hollywood" if section == "highest-rated" else "catalogue": {
                            "mediaType": media_type,
                            "results": results,
                        }
                    },
                })
                path = metadata_dir / f"{section}.json"
                path.write_bytes(content)
                metadata_bytes[path] = content

            movie_hash = "0123456789abcdef" * 2 + "01234567"
            hollywood_only_hash = "9876543210abcdef" * 2 + "98765432"
            show_hash = "abcdef0123456789" * 2 + "abcdef01"
            unresolved_hash = "1234567890abcdef" * 2 + "12345678"
            (source_dir / "latest_hollywood_catalogue.json").write_text(
                json.dumps({
                    "results": [{
                        "tmdbId": 11,
                        "title": "Film A",
                        "year": 2024,
                        "torrentMatches": [
                            {
                                "infoHash": movie_hash.upper(),
                                "magnetUrl": f"magnet:?xt=urn:btih:{movie_hash}",
                                "title": "Film A 2024 1080p",
                                "quality": "1080p",
                                "size": "2 GB",
                                "seeders": 10,
                                "provider": "ExistingIndexer",
                                "protocol": "torrent",
                                "publishedAt": "2024-01-02T03:04:05Z",
                                "checkedAt": 1704164645,
                            },
                            {
                                "infoHash": movie_hash,
                                "title": "Film A 2024",
                                "leechers": 3,
                                "guid": "existing-guid",
                            },
                        ],
                    }, {
                        "tmdbId": 22,
                        "title": "Film B",
                        "year": 2023,
                        "torrentMatches": [{
                            "infoHash": hollywood_only_hash,
                            "title": "Film B 2023 1080p",
                            "seeders": 2,
                        }],
                    }]
                }),
                encoding="utf-8",
            )
            (history_dir / "latest_hollywood_catalogue.json").write_text(
                json.dumps({
                    "results": [{
                        "tmdbId": 11,
                        "title": "Film A",
                        "year": 2024,
                        "torrentMatches": [{
                            "infoHash": movie_hash,
                            "indexer": "HistoricalIndexer",
                            "originalTimestamp": "2023-12-01T00:00:00Z",
                        }],
                    }]
                }),
                encoding="utf-8",
            )
            (source_dir / "classics_catalogue.json").write_text(
                json.dumps({
                    "results": [{
                        "title": "Film A",
                        "year": 2024,
                        "torrentMatches": [{"infoHash": movie_hash, "source": "classics"}],
                    }]
                }),
                encoding="utf-8",
            )
            (source_dir / "marvel_web_series_catalogue.json").write_text(
                json.dumps({
                    "shows": [{
                        "title": "Orbit Show",
                        "year": 2022,
                        "episodes": {
                            "tmdbId": 88,
                            "title": "Orbit Show",
                            "seasons": [{
                                "seasonNumber": 1,
                                "episodes": [{
                                    "episodeNumber": 2,
                                    "title": "Pilot",
                                    "torrentMatches": [{
                                        "infoHash": show_hash,
                                        "title": "Orbit Show S01E02 Pilot",
                                        "seeders": 7,
                                    }],
                                }],
                            }],
                        },
                    }]
                }),
                encoding="utf-8",
            )
            unresolved_result = {
                "infoHash": unresolved_hash,
                "magnetUrl": f"magnet:?xt=urn:btih:{unresolved_hash}&dn=unmapped",
                "title": "Unmapped 1999 720p",
                "size": "1 GB",
                "seeders": 4,
                "indexer": "HistoricalIndexer",
                "protocol": "torrent",
                "publishedAt": "1999-01-01",
                "guid": "unmapped-guid",
                "customOriginalField": {"keep": True},
            }
            (source_dir / "unclassified_snapshot.json").write_text(
                json.dumps({"results": [unresolved_result]}), encoding="utf-8"
            )

            before = {path: path.read_bytes() for path in metadata_bytes}
            roots = [("fixture", source_dir), ("history", history_dir)]
            first_manifest, first_contents = MODULE.build_migration(
                roots, metadata_dir, output_dir
            )
            second_manifest, second_contents = MODULE.build_migration(
                roots, metadata_dir, output_dir
            )

            self.assertEqual(first_contents, second_contents)
            self.assertEqual(
                MODULE.canonical_json(first_manifest),
                MODULE.canonical_json(second_manifest),
            )
            self.assertEqual(list(output_dir.iterdir()) if output_dir.exists() else [], [])
            self.assertEqual(before, {path: path.read_bytes() for path in metadata_bytes})
            self.assertEqual(first_manifest["globalUniqueNormalizedInfoHashCount"], 4)
            self.assertEqual(first_manifest["sectionLevelUniqueInfoHashEntryCount"], 5)
            self.assertEqual(
                first_manifest["destinations"]["hollywood-torrents.json"][
                    "uniqueNormalizedInfoHashes"
                ],
                2,
            )
            self.assertEqual(
                first_manifest["destinations"]["highest-rated-torrents.json"][
                    "uniqueNormalizedInfoHashes"
                ],
                1,
            )
            self.assertEqual(
                first_manifest["destinations"]["favourites-torrents.json"][
                    "uniqueNormalizedInfoHashes"
                ],
                1,
            )
            self.assertEqual(
                first_manifest["destinations"]["marvel-torrents.json"][
                    "uniqueNormalizedInfoHashes"
                ],
                1,
            )

            hollywood_records = json.loads(
                first_contents["hollywood-torrents.json"]
            )["records"]
            movie_record = hollywood_records[0]
            self.assertEqual(movie_record["infoHash"], movie_hash)
            self.assertEqual(movie_record["magnetUrl"], f"magnet:?xt=urn:btih:{movie_hash}")
            self.assertEqual(movie_record["provider"], "ExistingIndexer")
            self.assertEqual(movie_record["indexer"], "HistoricalIndexer")
            self.assertEqual(
                movie_record["originalTimestamp"], "2023-12-01T00:00:00Z"
            )
            self.assertEqual(movie_record["leechers"], 3)
            self.assertIn(
                {
                    "section": "highest-rated",
                    "subsection": "hollywood",
                    "matchType": "tmdb",
                },
                movie_record["metadataCardMatches"],
            )
            provenance_groups = {
                item["sourceGroup"] for item in movie_record["sourceProvenance"]
            }
            self.assertEqual(provenance_groups, {"hollywood", "favourites"})
            self.assertEqual(len(movie_record["sourceVariants"]), 4)

            marvel_record = json.loads(
                first_contents["marvel-torrents.json"]
            )["records"][0]
            identity = marvel_record["mediaIdentities"][0]
            self.assertEqual(identity["mediaType"], "tv")
            self.assertEqual(identity["tmdbId"], "88")
            self.assertEqual(identity["seasonNumber"], 1)
            self.assertEqual(identity["episodeNumber"], 2)
            self.assertEqual(identity["episodeTitle"], "Pilot")

            unresolved = first_manifest["unresolvedRecords"]
            self.assertEqual(first_manifest["unresolvedRecordCount"], 1)
            self.assertEqual(unresolved[0]["result"], unresolved_result)
            self.assertEqual(
                unresolved[0]["sourceProvenance"]["sourceGroup"], "unresolved"
            )
            highest_rated_hashes = {
                record["identity"]
                for record in json.loads(
                    first_contents["highest-rated-torrents.json"]
                )["records"]
            }
            self.assertIn(movie_hash, highest_rated_hashes)
            self.assertNotIn(hollywood_only_hash, highest_rated_hashes)

            applied_dir = root / "temporary-apply"
            self.assertEqual(
                len(MODULE._apply_outputs(applied_dir, first_contents)), len(MODULE.SECTIONS)
            )
            self.assertEqual(MODULE._apply_outputs(applied_dir, first_contents), [])
            self.assertEqual(
                {path.name for path in applied_dir.iterdir()},
                set(MODULE.DESTINATION_FILES.values()),
            )

            dry_run_dir = root / "cli-dry-run-output"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--dry-run",
                    "--source-root",
                    f"fixture={source_dir}",
                    "--metadata-dir",
                    str(metadata_dir),
                    "--output-dir",
                    str(dry_run_dir),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            summary = json.loads(completed.stdout)
            self.assertEqual(summary["mode"], "dry-run")
            self.assertEqual(summary["writtenFiles"], [])
            self.assertFalse(dry_run_dir.exists())

    def test_card_matching_uses_title_year_only_when_stable_id_does_not_match(self):
        card_index = {
            section: set()
            for section in MODULE.SECTIONS
        }
        card_index["hollywood"].add(("movie", "tmdb", "1", "popular"))
        card_index["bollywood"].add(
            ("movie", "title-year", "samefilm", "2020", "popular")
        )

        self.assertEqual(
            MODULE._matches_card(
                {
                    "mediaType": "movie",
                    "tmdbId": "1",
                    "title": "Same Film",
                    "year": "2020",
                },
                card_index,
            ),
            {"hollywood"},
        )
        self.assertEqual(
            MODULE._matches_card(
                {
                    "mediaType": "movie",
                    "tmdbId": "2",
                    "title": "Same Film",
                    "year": "2020",
                },
                card_index,
            ),
            {"bollywood"},
        )

    def test_catalogue_provenance_preserves_exact_source_keys_and_section_mapping(self):
        context = {
            "catalogues": [
                "highest-rated-hollywood",
                "popular-bollywood",
            ]
        }

        self.assertEqual(
            MODULE._catalogue_identifiers(context),
            ["highest-rated-hollywood", "popular-bollywood"],
        )
        self.assertEqual(
            MODULE._catalogue_sections(context),
            {"highest-rated", "bollywood"},
        )

    def test_highest_rated_catalogue_labels_do_not_grant_regional_membership(self):
        context = {"catalogues": ["highest-rated-hollywood"]}
        self.assertEqual(
            MODULE._catalogue_sections(context),
            {"highest-rated"},
        )

        entry = {
            "source": {"group": "regional"},
            "context": context,
            "mediaIdentity": {
                "mediaType": "movie",
                "title": "Unlisted Film",
                "year": "2020",
            },
            "metadataCardMatches": [],
        }
        empty_card_index = {
            section: set()
            for section in MODULE.SECTIONS
        }
        self.assertEqual(
            MODULE._source_sections(entry, {}, empty_card_index),
            set(),
        )

    def test_state_mapping_records_the_regional_catalogue_evidence(self):
        sources = [{
            "group": "regional",
            "relativePath": "fixture/regional_movie_prebuilt_cache.json",
            "sourceFiles": ["fixture/regional_movie_prebuilt_cache.json"],
            "sourceFileNames": ["regional_movie_prebuilt_cache.json"],
            "sha256": "snapshot-hash",
            "data": {
                "movies": {
                    "mapped-film|2020": {
                        "catalogues": ["popular-hollywood"],
                    }
                }
            },
        }]
        evidence = MODULE._regional_membership_evidence(sources)
        entry = {
            "source": {
                "group": "state",
                "sourceFiles": ["fixture/regional_movie_prebuilt_state.json"],
                "sha256": "state-hash",
            },
            "context": {},
            "mediaIdentity": {
                "mediaType": "movie",
                "title": "mapped film",
                "year": "2020",
            },
            "path": ("completed", "mapped-film|2020", "results", "0"),
            "regionalCatalogueEvidence": evidence["mapped-film|2020"],
            "metadataCardMatches": [],
        }

        assignment = MODULE._section_assignment_evidence(entry, "hollywood")
        self.assertEqual(len(assignment["evidence"]), 1)
        self.assertEqual(
            assignment["evidence"][0]["reason"],
            "state-title-year-joined-to-regional-catalogue",
        )
        self.assertEqual(
            assignment["evidence"][0]["catalogueKeys"],
            ["popular-hollywood"],
        )
        self.assertEqual(
            MODULE._section_assignment_evidence(entry, "highest-rated")["evidence"],
            [],
        )

    def test_identical_snapshots_with_different_page_names_are_counted_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pages = root / "pages" / "marvel"
            pages.mkdir(parents=True)
            payload = json.dumps({
                "results": [{
                    "infoHash": "0123456789abcdef" * 2 + "01234567",
                    "title": "Existing result",
                }]
            }).encode()
            compressed = gzip.compress(payload, mtime=0)
            (pages / "1.json.gz").write_bytes(compressed)
            (pages / "2.json.gz").write_bytes(compressed)

            sources = MODULE._source_files(
                [("fixture", root)],
                root / "output",
            )

            self.assertEqual(len(sources), 1)
            self.assertEqual(len(sources[0]["records"]), 1)
            self.assertEqual(
                sources[0]["sourceFileNames"], ["1.json.gz", "2.json.gz"]
            )
            self.assertEqual(
                sources[0]["sourceFiles"],
                ["fixture/pages/marvel/1.json.gz", "fixture/pages/marvel/2.json.gz"],
            )


if __name__ == "__main__":
    unittest.main()
