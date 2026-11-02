import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "build_self_contained_section_cache.py"
SPEC = importlib.util.spec_from_file_location("build_self_contained_section_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
ROOT = Path(__file__).resolve().parents[2]
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_cache_bundle",
    ROOT / "scripts" / "publish_cache_bundle.py",
)
PUBLISH_MODULE = importlib.util.module_from_spec(PUBLISH_SPEC)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH_SPEC.loader.exec_module(PUBLISH_MODULE)


class SelfContainedSectionCacheTests(unittest.TestCase):
    def test_page_offsets_reflow_records_into_eighteen_item_pages(self):
        self.assertEqual(MODULE.page_offsets(54), [0, 18, 36, 54])
        self.assertEqual(MODULE.page_offsets(51), [0, 18, 36, 51])

    def test_regional_tv_source_boundaries_are_reflowed_without_reordering(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "regional-tv.json"
            catalogues = {}
            for key in MODULE.REGIONAL_TV_CATALOGUES:
                rows = [
                    {"id": 1000 + row_index, "title": f"Show {row_index:02}"}
                    for row_index in range(51 if key == "hollywood-popular" else 1)
                ]
                chunk_sizes = (16, 18, 17) if key == "hollywood-popular" else (1,)
                pages = []
                offset = 0
                for page_number, chunk_size in enumerate(chunk_sizes, start=1):
                    page_rows = rows[offset:offset + chunk_size]
                    offset += chunk_size
                    if page_rows:
                        pages.append({"page": page_number, "results": page_rows})
                catalogues[key] = {"pages": pages, "totalResults": len(rows)}
            path.write_text(json.dumps({"catalogues": catalogues}), encoding="utf-8")

            tv_sections = MODULE.regional_tv_subsections(path)
            node = tv_sections["hollywood"]["tv-popular"]

            self.assertEqual(node["pageSize"], 18)
            self.assertEqual(node["pageCount"], 3)
            self.assertEqual(node["pageOffsets"], [0, 18, 36, 51])
            self.assertEqual(node["totalResults"], 51)
            self.assertEqual([row["title"] for row in node["results"]], [f"Show {i:02}" for i in range(51)])

    def test_numeric_section_id_is_authoritative_tmdb_id(self):
        row = {"id": 123, "tmdbId": 999, "title": "Film"}

        MODULE.complete_row_fields(row, "movie")

        self.assertEqual(row["id"], 123)
        self.assertEqual(row["tmdbId"], 123)
        self.assertEqual(row["tmdbUrl"], "https://www.themoviedb.org/movie/123")

    def test_missing_id_is_added_from_existing_tmdb_id_only(self):
        row = {"tmdbId": 456, "title": "Film"}

        MODULE.complete_row_fields(row, "movie")

        self.assertEqual(row["id"], 456)
        self.assertEqual(row["tmdbId"], 456)

    def test_migration_adds_metadata_without_changing_section_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            caches = root / "caches"
            output = root / "output"
            source.mkdir()
            caches.mkdir()
            (root / "poster_map.json").write_text("[]", encoding="utf-8")
            for section in MODULE.SECTIONS:
                results = [
                    {"id": 101, "title": "First Film", "year": 2020, "mediaType": "movie"},
                    {"id": 202, "title": "Second Film", "year": 2021, "mediaType": "movie"},
                ]
                if section == "hollywood":
                    results[0].update({
                        "imdbId": "tt0000101",
                        "imdbRating": 8.4,
                        "imdbRatingStatus": "found",
                        "posterUrl": "https://example.test/known-poster.jpg",
                    })
                (source / f"{section}.json").write_text(json.dumps({
                    "section": section,
                    "subsections": {
                        "movies": {
                            "mediaType": "movie",
                            "results": results,
                        },
                    },
                }), encoding="utf-8")

            (caches / "tmdb_movie_catalogue_cache.json").write_text(json.dumps({
                "catalogues": {
                    "example": {
                        "payload": {
                            "results": [{
                                "id": 101,
                                "title": "First Film",
                                "year": 2020,
                                "releaseDate": "2020-05-01",
                                "overview": "Known overview",
                                "posterUrl": "https://example.test/cache-poster.jpg",
                                "backdropUrl": "https://example.test/backdrop.jpg",
                                "rating": 7.5,
                            }],
                        },
                    },
                },
            }), encoding="utf-8")
            (caches / "tmdb_search_metadata_cache.json").write_text(json.dumps({
                "results": [{
                    "id": 202,
                    "tmdbId": 202,
                    "title": "Second Film",
                    "mediaType": "movie",
                    "year": 2021,
                    "releaseDate": "2021-06-02",
                    "overview": "Second overview",
                    "posterUrl": "https://example.test/second-poster.jpg",
                    "backdropUrl": "https://example.test/second-backdrop.jpg",
                    "rating": 6.8,
                    "tmdbUrl": "https://www.themoviedb.org/movie/202",
                }],
            }), encoding="utf-8")
            (caches / "imdb_rating_cache.json").write_text(json.dumps({
                "results": [{
                    "title": "Second Film",
                    "year": 2021,
                    "tmdbIdTried": 202,
                    "imdbId": "tt0000202",
                    "imdbRating": 7.9,
                    "imdbVotes": "1200",
                    "imdbUrl": "https://www.imdb.com/title/tt0000202/",
                    "checkedAt": "2024-01-02T03:04:05Z",
                    "status": "found",
                }],
            }), encoding="utf-8")
            (caches / "tmdb_ott_availability_cache.json").write_text(json.dumps({
                "items": {
                    "202:IN": {
                        "payload": {
                            "region": "IN",
                            "status": "streaming",
                            "streamingProviders": [{"name": "Example"}],
                            "rentProviders": [],
                            "buyProviders": [],
                            "providerLink": "https://example.test/watch",
                            "checkedAt": "2024-01-02T03:04:05Z",
                        },
                    },
                },
            }), encoding="utf-8")

            summary = MODULE.migrate(source, caches, output)

            self.assertEqual(len(summary), 9)
            for section in MODULE.SECTIONS:
                document = json.loads((output / f"{section}.json").read_text(encoding="utf-8"))
                rows = document["subsections"]["movies"]["results"]
                self.assertEqual([row["title"] for row in rows], ["First Film", "Second Film"])
                self.assertEqual([row["tmdbId"] for row in rows], [101, 202])
                self.assertTrue(document["metadataSelfContained"])
                self.assertEqual(
                    {*MODULE.SHARED_METADATA_FILES, "poster_map.json"},
                    set(document["metadataSources"]),
                )
                for row in rows:
                    for field in (
                        "imdbId", "imdbRating", "imdbRatingStatus", "posterUrl",
                        "backdropUrl", "overview", "releaseDate", "ottAvailability",
                    ):
                        self.assertIn(field, row)

            first, second = json.loads((output / "hollywood.json").read_text(encoding="utf-8"))["subsections"]["movies"]["results"]
            self.assertEqual(first["imdbId"], "tt0000101")
            self.assertEqual(first["imdbRating"], 8.4)
            self.assertEqual(first["posterUrl"], "https://example.test/known-poster.jpg")
            self.assertEqual(first["overview"], "Known overview")
            self.assertEqual(first["rating"], 7.5)
            self.assertEqual(second["imdbId"], "tt0000202")
            self.assertEqual(second["imdbRating"], 7.9)
            self.assertEqual(second["ottAvailability"]["status"], "streaming")
            self.assertEqual(
                sorted(path.name for path in output.glob("*.json")),
                sorted(f"{section}.json" for section in MODULE.SECTIONS),
            )

    def test_in_place_migration_preserves_curated_rows_and_non_section_caches(self):
        with tempfile.TemporaryDirectory() as temporary:
            seed = Path(temporary) / "seed"
            runtime = seed / "runtime"
            runtime.mkdir(parents=True)
            regional_tv = seed / "regional_tv_prebuilt_cache.json"
            catalogues = {
                key: {"pages": [{"page": 1, "results": [{
                    "id": index + 9000,
                    "title": f"Regional {key}",
                }]}]}
                for index, key in enumerate(MODULE.REGIONAL_TV_CATALOGUES)
            }
            regional_tv.write_text(json.dumps({"catalogues": catalogues}), encoding="utf-8")
            for filename, payload in (
                ("tmdb_movie_catalogue_cache.json", {"catalogues": {}}),
                ("tmdb_search_metadata_cache.json", {"results": []}),
                ("imdb_rating_cache.json", {"results": []}),
                ("tmdb_ott_availability_cache.json", {"items": {}}),
                ("yenime_mal_resolution_cache.json", {
                    "version": 2,
                    "tmdbMappings": {"101": {"tmdbId": 101, "malId": 5114}},
                }),
                ("nexstream_episode_metadata_cache.json", {
                    "shows": {"101": {"episodesBySeason": {"1": []}}},
                }),
            ):
                (runtime / filename).write_text(json.dumps(payload), encoding="utf-8")

            for section in MODULE.SECTIONS:
                (seed / f"{section}.json").write_text(json.dumps({
                    "section": section,
                    "subsections": {
                        "movies": {
                            "mediaType": "movie",
                            "pageSize": 18,
                            "pageCount": 1,
                            "pageOffsets": [0, 2],
                            "totalResults": 2,
                            "results": [
                                {
                                    "id": 101,
                                    "title": "Curated First",
                                    "year": 2020,
                                    "posterUrl": "https://example.test/keep.jpg",
                                },
                                {"id": 202, "title": "Curated Second", "year": 2021},
                            ],
                        },
                    },
                    "customMetadata": {"preserve": True},
                }), encoding="utf-8")

            preserved = {
                path: path.read_bytes()
                for path in (regional_tv, *runtime.glob("*.json"))
            }
            MODULE.migrate(seed, runtime, seed, regional_tv)

            for section in MODULE.SECTIONS:
                document = json.loads((seed / f"{section}.json").read_text(encoding="utf-8"))
                subsection = document["subsections"]["movies"]
                self.assertEqual(
                    [row["title"] for row in subsection["results"]],
                    ["Curated First", "Curated Second"],
                )
                self.assertEqual(subsection["results"][0]["posterUrl"], "https://example.test/keep.jpg")
                self.assertEqual(subsection["pageOffsets"], [0, 2])
                self.assertEqual(subsection["totalResults"], 2)
                self.assertEqual(document["customMetadata"], {"preserve": True})
                self.assertIs(document["metadataSelfContained"], True)
            for path, contents in preserved.items():
                self.assertEqual(path.read_bytes(), contents)

    def test_publisher_builds_validates_and_uses_manifest_asset_publisher(self):
        publisher = SCRIPT.parent / "vps" / "refresh_and_publish.sh"
        script = publisher.read_text(encoding="utf-8")
        builder_call = script.index("repo/scripts/build_self_contained_section_cache.py")
        validator_call = script.index("repo/scripts/validate_section_caches.py")
        bundle_call = script.index("repo/scripts/make_cache_bundle.py")
        upload_call = script.index("repo/scripts/publish_cache_bundle.py")

        self.assertLess(builder_call, validator_call)
        self.assertLess(validator_call, bundle_call)
        self.assertLess(bundle_call, upload_call)
        self.assertIn('--source-dir "$REFRESH_SEED_DIR"', script)
        self.assertIn('--cache-dir "$REFRESH_SEED_DIR/runtime"', script)
        self.assertIn('--regional-tv-cache "$REFRESH_SEED_DIR/regional_tv_prebuilt_cache.json"', script)
        self.assertIn('--output-dir "$REFRESH_SEED_DIR"', script)
        self.assertIn("--require-all", script)
        self.assertIn("--require-self-contained", script)

    def test_bundle_builder_repairs_legacy_hollywood_and_keeps_all_persistent_caches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "seed"
            runtime = seed / "runtime"
            runtime.mkdir(parents=True)

            for name, payload in (
                ("tmdb_movie_catalogue_cache.json", {"catalogues": {}}),
                ("tmdb_search_metadata_cache.json", {"results": []}),
                ("imdb_rating_cache.json", {"results": []}),
                ("tmdb_ott_availability_cache.json", {"items": {}}),
                ("yenime_mal_resolution_cache.json", {
                    "version": 2,
                    "entries": {},
                    "tmdbMappings": {
                        "101": {
                            "tmdbId": 101,
                            "malId": 5114,
                            "title": "Keep this mapping",
                            "source": "AniList",
                            "resolvedAt": "test",
                        },
                    },
                    "cooldownUntil": 0,
                }),
                ("nexstream_episode_metadata_cache.json", {
                    "shows": {
                        "202": {
                            "tmdbId": 202,
                            "episodesBySeason": {"1": [{"episodeNumber": 1, "name": "Keep this episode"}]},
                        },
                    },
                }),
            ):
                (runtime / name).write_text(json.dumps(payload), encoding="utf-8")

            for section in MODULE.SECTIONS:
                # This reproduces the production failure: legacy Hollywood lacks the API marker.
                document = {
                    "section": section,
                    "subsections": {
                        "movies": {
                            "mediaType": "movie",
                            "results": [
                                {"id": 101, "title": f"{section} curated first"},
                                {"id": 102, "title": f"{section} curated second"},
                            ],
                        },
                    },
                }
                (seed / f"{section}.json").write_text(json.dumps(document), encoding="utf-8")

            regional_tv = {
                catalogue_key: {
                    "pages": [{
                        "page": 1,
                        "results": [{"id": 9000 + index, "title": f"Regional {catalogue_key}"}],
                    }],
                }
                for index, catalogue_key in enumerate(MODULE.REGIONAL_TV_CATALOGUES)
            }
            (seed / "regional_tv_prebuilt_cache.json").write_text(
                json.dumps({"catalogues": regional_tv}),
                encoding="utf-8",
            )
            (seed / "poster_map.json").write_text("[]", encoding="utf-8")

            preserved_paths = (
                runtime / "yenime_mal_resolution_cache.json",
                runtime / "nexstream_episode_metadata_cache.json",
            )
            preserved_bytes = {path: path.read_bytes() for path in preserved_paths}
            output = root / "out"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "make_cache_bundle.py"),
                    str(seed),
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            manifest = json.loads((output / "cache-bundle.json").read_text(encoding="utf-8"))
            with tarfile.open(output / manifest["bundle"], "r:gz") as archive:
                names = set(archive.getnames())
                for section in MODULE.SECTIONS:
                    section_path = f"{section}.json"
                    self.assertIn(section_path, names)
                    bundled = json.load(archive.extractfile(section_path))
                    self.assertEqual(bundled["section"], section)
                    self.assertIs(bundled["metadataSelfContained"], True)
                    self.assertIsInstance(bundled["subsections"], dict)
                    self.assertEqual(
                        [row["title"] for row in bundled["subsections"]["movies"]["results"]],
                        [f"{section} curated first", f"{section} curated second"],
                    )
                for path in preserved_paths:
                    member = path.relative_to(seed).as_posix()
                    self.assertIn(member, names)
                    self.assertEqual(archive.extractfile(member).read(), preserved_bytes[path])

            for path, contents in preserved_bytes.items():
                self.assertEqual(path.read_bytes(), contents)

            calls = []
            release_assets = set()

            def fake_runner(command, **_kwargs):
                calls.append(command)
                if command[:3] == ["gh", "release", "upload"]:
                    release_assets.add(Path(command[4]).name)
                    return subprocess.CompletedProcess(command, 0)
                if command[:3] == ["gh", "release", "view"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="".join(f"{name}\n" for name in sorted(release_assets)),
                        stderr="",
                    )
                raise AssertionError(f"Unexpected publisher command: {command}")

            uploaded_assets = PUBLISH_MODULE.publish_cache_bundle(
                output / "cache-bundle.json",
                output / "cache-bundle.tar.gz",
                "wroxtaaar/Torrent-Studio",
                runner=fake_runner,
            )
            immutable_upload = next(
                call for call in calls
                if call[:3] == ["gh", "release", "upload"] and "--clobber" not in call
            )
            self.assertEqual(Path(immutable_upload[4]).name, manifest["bundle"])
            self.assertEqual(
                uploaded_assets,
                {manifest["bundle"], "cache-bundle.tar.gz", "cache-bundle.json"},
            )

    def test_publisher_uploads_the_exact_filename_named_by_generated_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            version = "20261031T073047Z-ce0c8825"
            archive_name = f"cache-bundle-{version}.tar.gz"
            archive_bytes = b"immutable-test-archive"
            (output / archive_name).write_bytes(archive_bytes)
            (output / "cache-bundle.tar.gz").write_bytes(b"legacy-archive")
            manifest_path = output / "cache-bundle.json"
            manifest_path.write_text(json.dumps({
                "version": version,
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                "bundle": archive_name,
            }), encoding="utf-8")

            calls = []
            release_assets = set()

            def fake_runner(command, **_kwargs):
                calls.append(command)
                if command[:3] == ["gh", "release", "upload"]:
                    release_assets.add(Path(command[4]).name)
                    return subprocess.CompletedProcess(command, 0)
                if command[:3] == ["gh", "release", "view"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="".join(f"{name}\n" for name in sorted(release_assets)),
                        stderr="",
                    )
                raise AssertionError(f"Unexpected publisher command: {command}")

            result = PUBLISH_MODULE.publish_cache_bundle(
                manifest_path,
                output / "cache-bundle.tar.gz",
                "wroxtaaar/Torrent-Studio",
                runner=fake_runner,
            )

            immutable_uploads = [
                call for call in calls
                if call[:3] == ["gh", "release", "upload"] and "--clobber" not in call
            ]
            self.assertEqual(len(immutable_uploads), 1)
            self.assertEqual(Path(immutable_uploads[0][4]).name, archive_name)
            self.assertEqual(
                result,
                {archive_name, "cache-bundle.tar.gz", "cache-bundle.json"},
            )
            legacy_index = next(
                i for i, call in enumerate(calls)
                if call[:3] == ["gh", "release", "upload"]
                and Path(call[4]).name == "cache-bundle.tar.gz"
            )
            manifest_index = next(
                i for i, call in enumerate(calls)
                if call[:3] == ["gh", "release", "upload"]
                and Path(call[4]).name == "cache-bundle.json"
            )
            self.assertLess(calls.index(immutable_uploads[0]), legacy_index)
            self.assertLess(legacy_index, manifest_index)

    def test_failed_imdb_cache_result_does_not_replace_good_values(self):
        row = {
            "id": 101,
            "title": "Known Film",
            "year": 2020,
            "imdbId": "tt0000101",
            "imdbRating": 8.4,
            "imdbRatingStatus": "found",
        }
        imdb_indexes = MODULE.imdb_index([{
            "title": "Known Film",
            "year": 2020,
            "status": "unavailable",
            "checkedAt": "2024-01-02T03:04:05Z",
        }])

        MODULE.enrich_row(row, "movie", (({}, {}, {}), ({}, {}, {})), imdb_indexes, {}, {})

        self.assertEqual(row["imdbId"], "tt0000101")
        self.assertEqual(row["imdbRating"], 8.4)
        self.assertEqual(row["imdbRatingStatus"], "found")

    def test_invalid_cached_values_are_repaired_without_replacing_valid_values(self):
        row = {
            "id": 101,
            "title": "Known Film",
            "year": 2020,
            "imdbId": "invalid",
            "imdbRating": "N/A",
            "posterUrl": "not-a-url",
        }
        changed = MODULE.fill_missing(row, {
            "imdbId": "tt0000101",
            "imdbRating": 8.4,
            "posterUrl": "https://example.test/poster.jpg",
        }, ("imdbId", "imdbRating", "posterUrl"))

        self.assertEqual(changed, 3)
        self.assertEqual(row["imdbId"], "tt0000101")
        self.assertEqual(row["imdbRating"], 8.4)
        self.assertEqual(row["posterUrl"], "https://example.test/poster.jpg")

    def test_poster_map_fills_only_missing_poster_with_exact_title_and_year(self):
        row = {"id": 101, "title": "Exact Match", "year": 2020}
        changed = MODULE.enrich_row(
            row,
            "movie",
            (({}, {}, {}), ({}, {}, {})),
            ({}, {}),
            {},
            {("exact match", 2020): "https://example.test/poster.jpg"},
        )

        self.assertGreater(changed, 0)
        self.assertEqual(row["posterUrl"], "https://example.test/poster.jpg")

    def test_regional_tv_metadata_fills_existing_rows_without_changing_membership(self):
        existing = {
            "results": [
                {"id": 101, "title": "First", "year": 2020, "overview": "Keep this"},
                {
                    "id": 202,
                    "title": "Second",
                    "year": 2021,
                    "ottAvailability": {"region": "IN", "status": "streaming"},
                },
            ],
        }
        source = {
            "results": [
                {
                    "id": 202,
                    "title": "Second",
                    "year": 2021,
                    "ottAvailability": {
                        "region": "IN",
                        "status": "streaming",
                        "streamingProviders": [{"name": "Second Provider"}],
                    },
                },
                {
                    "id": 101,
                    "title": "First",
                    "year": 2020,
                    "overview": "Do not replace",
                    "ottAvailability": {
                        "region": "IN",
                        "status": "unavailable",
                        "streamingProviders": [{"name": "First Provider"}],
                    },
                },
                {"id": 303, "title": "Not Curated", "year": 2022},
            ],
        }

        changed = MODULE.merge_regional_tv_subsection(existing, source)

        self.assertGreater(changed, 0)
        self.assertEqual([row["id"] for row in existing["results"]], [101, 202])
        self.assertEqual(existing["results"][0]["overview"], "Keep this")
        self.assertEqual(existing["results"][0]["ottAvailability"]["status"], "unavailable")
        self.assertEqual(
            existing["results"][1]["ottAvailability"]["streamingProviders"],
            [{"name": "Second Provider"}],
        )

    def test_availability_is_built_only_from_explicit_provider_types(self):
        self.assertIsNone(MODULE.availability_from_provider_rows([]))
        self.assertIsNone(MODULE.availability_from_provider_rows([{"name": "Unknown"}]))

        availability = MODULE.availability_from_provider_rows([
            {"name": "Stream", "type": "subscription", "region": "IN"},
            {"name": "Rent", "type": "rent", "region": "IN"},
            {"name": "Buy", "type": "buy", "region": "IN"},
        ])

        self.assertEqual(availability["status"], "streaming")
        self.assertEqual([p["name"] for p in availability["streamingProviders"]], ["Stream"])
        self.assertEqual([p["name"] for p in availability["rentProviders"]], ["Rent"])
        self.assertEqual([p["name"] for p in availability["buyProviders"]], ["Buy"])

    def test_rent_buy_only_sources_are_not_marked_as_streaming(self):
        availability = MODULE.availability_from_provider_rows([
            {"name": "Rent", "type": "rent"},
            {"name": "Buy", "type": "buy"},
        ])

        self.assertEqual(availability["status"], "rent_buy")
        self.assertEqual(availability["streamingProviders"], [])
        self.assertEqual(len(availability["rentProviders"]), 1)
        self.assertEqual(len(availability["buyProviders"]), 1)

    def test_regional_tv_catalogues_are_embedded_separately_without_torrent_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            caches = root / "caches"
            output = root / "output"
            source.mkdir()
            caches.mkdir()
            for section in MODULE.SECTIONS:
                (source / f"{section}.json").write_text(json.dumps({
                    "section": section,
                    "subsections": {
                        "movies": {
                            "mediaType": "movie",
                            "results": [{"id": 101, "title": f"{section} Movie"}],
                        },
                    },
                }), encoding="utf-8")

            tv_rows = [
                {
                    "id": 501,
                    "title": "TV First",
                    "year": 2020,
                    "releaseDate": "2020-01-02",
                    "overview": "Existing TV overview",
                    "posterUrl": "https://example.test/tv-poster.jpg",
                    "backdropUrl": "https://example.test/tv-backdrop.jpg",
                    "rating": 7.5,
                    "streamingProviders": [{"name": "Example TV", "type": "subscription"}],
                    "providerLink": "https://example.test/watch",
                    "genres": [{"id": 80, "name": "Crime"}],
                    "magnetUrl": "must-not-be-copied",
                    "seeders": 99,
                    "torrentMatches": [{"title": "must-not-be-copied"}],
                },
                *[
                    {"id": 600 + index, "title": f"TV {index:02}", "year": 2020}
                    for index in range(1, 19)
                ],
            ]
            catalogues = {}
            for catalogue_key in MODULE.REGIONAL_TV_CATALOGUES:
                rows = tv_rows if catalogue_key == "hollywood-popular" else [
                    {"id": 700 + len(catalogues), "title": catalogue_key, "year": 2022}
                ]
                page_chunks = [rows[:18], rows[18:]]
                pages = [
                    {"page": number, "results": page_rows}
                    for number, page_rows in enumerate(page_chunks, start=1)
                    if page_rows
                ]
                catalogues[catalogue_key] = {
                    "pages": pages,
                    "seriesCount": len(rows),
                    "totalResults": len(rows),
                }
            tv_cache = root / "regional_tv_prebuilt_cache.json"
            tv_cache.write_text(json.dumps({"catalogues": catalogues}), encoding="utf-8")
            source_snapshot = tv_cache.read_bytes()

            (caches / "tmdb_movie_catalogue_cache.json").write_text(json.dumps({"catalogues": {}}), encoding="utf-8")
            (caches / "tmdb_search_metadata_cache.json").write_text(json.dumps({
                "results": [{
                    "id": 501,
                    "tmdbId": 501,
                    "title": "TV First",
                    "year": 2020,
                    "mediaType": "tv",
                    "overview": "Do not replace existing overview",
                    "releaseDate": "2020-01-02",
                    "posterUrl": "https://example.test/cache-poster.jpg",
                    "backdropUrl": "https://example.test/cache-backdrop.jpg",
                    "rating": 6.1,
                    "tmdbUrl": "https://www.themoviedb.org/tv/501",
                }],
            }), encoding="utf-8")
            (caches / "imdb_rating_cache.json").write_text(json.dumps({
                "results": [{
                    "title": "TV First",
                    "year": 2020,
                    "mediaType": "tv",
                    "tmdbIdTried": 501,
                    "imdbId": "tt0000501",
                    "imdbRating": 8.2,
                    "imdbVotes": "5000",
                    "imdbUrl": "https://www.imdb.com/title/tt0000501/",
                    "status": "found",
                }],
            }), encoding="utf-8")
            (caches / "tmdb_ott_availability_cache.json").write_text(json.dumps({"items": {}}), encoding="utf-8")

            summary = MODULE.migrate(
                source,
                caches,
                output,
                tv_cache,
                sections=("hollywood", "bollywood"),
            )

            hollywood = json.loads((output / "hollywood.json").read_text(encoding="utf-8"))
            bollywood = json.loads((output / "bollywood.json").read_text(encoding="utf-8"))
            self.assertEqual(set(summary), {"hollywood", "bollywood"})
            self.assertEqual(
                sorted(path.name for path in output.glob("*.json")),
                ["bollywood.json", "hollywood.json"],
            )
            self.assertEqual(hollywood["subsections"]["movies"]["mediaType"], "movie")
            self.assertEqual(hollywood["subsections"]["tv-popular"]["mediaType"], "tv")
            self.assertEqual(bollywood["subsections"]["movies"]["mediaType"], "movie")
            self.assertEqual(bollywood["subsections"]["tv-popular"]["mediaType"], "tv")

            tv_node = hollywood["subsections"]["tv-popular"]
            self.assertEqual(tv_node["pageSize"], 18)
            self.assertEqual(tv_node["pageCount"], 2)
            self.assertEqual(tv_node["pageOffsets"], [0, 18, 19])
            self.assertEqual(tv_node["totalResults"], 19)
            self.assertEqual([row["title"] for row in tv_node["results"]], ["TV First", *[f"TV {i:02}" for i in range(1, 19)]])
            first = tv_node["results"][0]
            self.assertEqual(first["tmdbId"], 501)
            self.assertEqual(first["imdbId"], "tt0000501")
            self.assertEqual(first["imdbRating"], 8.2)
            self.assertEqual(first["posterUrl"], "https://example.test/tv-poster.jpg")
            self.assertEqual(first["backdropUrl"], "https://example.test/tv-backdrop.jpg")
            self.assertEqual(first["overview"], "Existing TV overview")
            self.assertEqual(first["releaseDate"], "2020-01-02")
            self.assertEqual(first["rating"], 7.5)
            self.assertEqual(first["streamingProviders"][0]["name"], "Example TV")
            self.assertNotIn("magnetUrl", first)
            self.assertNotIn("seeders", first)
            self.assertNotIn("torrentMatches", first)
            self.assertIn("regional_tv_prebuilt_cache.json", hollywood["metadataSources"])
            self.assertIn("regional_tv_prebuilt_cache.json", bollywood["metadataSources"])
            self.assertEqual(tv_cache.read_bytes(), source_snapshot)


if __name__ == "__main__":
    unittest.main()
