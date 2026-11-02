import asyncio
import json

import pytest
from fastapi import HTTPException

from catalogues import catalogues_movies as movies
from catalogues import catalogues_tv as tv
from core.settings import REGIONAL_MOVIE_CATALOGUE_KEYS
from metadata import imdb


def test_new_regional_movie_catalogue_pages_contain_18_entries(monkeypatch):
    async def fetch_source_page(catalogue_key, page, released_only=True):
        return {
            "page": page,
            "totalPages": 1,
            "totalResults": 20,
            "results": [
                {
                    "id": index,
                    "title": f"Anime {index}",
                    "releaseDate": "2025-01-01",
                }
                for index in range(20)
            ],
        }

    async def enrich(payload):
        return payload

    monkeypatch.setattr(movies, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(movies, "CACHE_FIRST", False)
    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", {})
    monkeypatch.setattr(movies, "_read_tmdb_persistent_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(movies, "_write_tmdb_persistent_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(movies, "_tmdb_fetch_movie_catalogue", fetch_source_page)
    monkeypatch.setattr(movies, "_enrich_regional_movie_catalogue_metadata", enrich)

    result = asyncio.run(
        movies._api_tmdb_movie_catalogue("popular-anime", 1, True, 5, False)
    )

    assert result["pageSize"] == 18
    assert len(result["results"]) == 18


def test_highest_rated_movie_catalogue_bypasses_stale_regional_cache(monkeypatch):
    expected = {
        "catalogue": "highest-rated-hollywood",
        "page": 1,
        "totalResults": 250,
        "results": [
            {"title": "The Shawshank Redemption", "imdbListRank": 1},
            {"title": "The Godfather", "imdbListRank": 2},
        ],
    }

    async def curated_page(catalogue_key, page):
        assert catalogue_key == "highest-rated-hollywood"
        assert page == 1
        return expected

    monkeypatch.setattr(movies, "_highest_rated_movie_curated_page", curated_page)
    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", {
        ("highest-rated-hollywood|eligible-v8", 1): (
            0,
            {"provider": "stale regional cache", "results": [{"title": "Avatar Aang"}]},
        ),
    })
    monkeypatch.setattr(movies, "_prebuilt_final_page", lambda *args: {
        "provider": "stale prebuilt", "results": [{"title": "Swapped"}],
    })

    result = asyncio.run(
        movies._api_tmdb_movie_catalogue("highest-rated-hollywood", 1, True, 5, False)
    )

    assert result is expected
    assert [row["title"] for row in result["results"]] == [
        "The Shawshank Redemption",
        "The Godfather",
    ]


def test_highest_rated_movie_route_keeps_manifest_page_count(monkeypatch):
    expected = {
        "catalogue": "highest-rated-hollywood",
        "page": 1,
        "totalPages": 14,
        "totalResults": 250,
        "results": [{"title": "The Shawshank Redemption", "imdbListRank": 1}],
    }

    async def curated_page(catalogue_key, page):
        return expected

    async def regional_cache_path(*args):
        raise AssertionError("Highest Rated must not use the regional cache builder")

    monkeypatch.setattr(movies, "_highest_rated_movie_curated_page", curated_page)
    monkeypatch.setattr(movies, "_live_regional_candidates", regional_cache_path)

    result = asyncio.run(movies.api_tmdb_movie_catalogue(
        "highest-rated-hollywood",
        page=1,
        released_only=True,
        max_size_gb=5,
        basic=False,
        live=True,
    ))

    assert result is expected
    assert result["totalPages"] == 14
    assert result["totalResults"] == 250


def test_removed_regional_movie_catalogues_are_not_served():
    removed = (
        "trending-korean",
        "latest-korean",
        "popular-pakistani",
    )
    assert not set(removed).intersection(REGIONAL_MOVIE_CATALOGUE_KEYS)
    for catalogue_key in removed:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(movies._api_tmdb_movie_catalogue(catalogue_key, 1, True, 5, False))
        assert exc.value.status_code == 404


def test_removed_anime_tv_modes_are_not_served():
    for catalogue_key in ("anime-trending", "anime-latest"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(tv.api_tmdb_regional_tv_catalogue(catalogue_key, page=1))
        assert exc.value.status_code == 404


def test_pakistani_tv_catalogue_uses_fixed_curated_drama_order(monkeypatch, tmp_path):
    async def get_json(path, params):
        # Model successful exact-title TMDB matches so this test exercises
        # curated ordering without relying on synthetic, non-playable IDs.
        if path == "search/tv":
            title = params["query"]
            return {
                "page": 1,
                "total_pages": 1,
                "total_results": 1,
                "results": [{
                    "id": 1000 + len(title),
                    "name": title,
                    "original_name": title,
                    "origin_country": ["PK"],
                    "first_air_date": "2010-01-01",
                    "original_language": "ur",
                }],
            }
        return {}

    async def streaming_providers(tmdb_id):
        return []

    monkeypatch.setattr(tv, "_read_regional_tv_prebuilt_page", lambda *args: None)
    monkeypatch.setattr(tv, "_REGIONAL_TV_DISCOVERY_CACHE", {})
    monkeypatch.setattr(tv, "_PAKISTANI_DRAMA_ROWS", {})
    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    monkeypatch.setattr(tv, "_tv_streaming_providers", streaming_providers)
    monkeypatch.setattr(tv, "TMDB_READ_ACCESS_TOKENS", ["test-token"])
    monkeypatch.setattr(tv, "REGIONAL_TV_PREBUILT_CACHE_FILE", tmp_path / "regional-tv.json")

    result = asyncio.run(tv.api_tmdb_regional_tv_catalogue("pakistani-popular", page=1))

    assert result["pageSize"] == 18
    assert result["totalResults"] == 144
    assert len(result["results"]) == 18
    assert [row["title"] for row in result["results"][:4]] == ["Humsafar", "Daam", "Mora Piya", "Kankar"]
    assert result["curatedOrder"] is True


def test_pakistani_tv_cache_filter_rejects_indian_titles():
    assert tv._is_pakistani_tv_row({"originCountry": ["PK"], "originalLanguage": "ur"})
    assert not tv._is_pakistani_tv_row({"originCountry": ["IN"], "originalLanguage": "hi"})
    assert not tv._is_pakistani_tv_row({"originCountry": ["PK", "IN"], "originalLanguage": "ur"})


def test_pakistani_tv_prebuilt_pages_backfill_after_filtering(monkeypatch, tmp_path):
    rows = [
        {"id": index, "title": f"Pakistani Series {index}", "originCountry": ["PK"]}
        for index in range(19)
    ]
    rows.insert(3, {"id": 99, "title": "Indian Series", "originCountry": ["IN"]})
    cache_path = tmp_path / "regional-tv.json"
    cache_path.write_text(json.dumps({
        "schemaVersion": 3,
        "catalogues": {
            "pakistani-popular": {
                "status": "ready",
                "seriesCount": len(rows),
                "pages": [{"page": 1, "results": rows}],
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(tv, "REGIONAL_TV_PREBUILT_CACHE_FILE", cache_path)

    first_page = tv._read_regional_tv_prebuilt_page("pakistani-popular", 1)
    second_page = tv._read_regional_tv_prebuilt_page("pakistani-popular", 2)

    assert len(first_page["results"]) == 18
    assert len(second_page["results"]) == 1
    assert first_page["totalResults"] == 19
    assert all(row["originCountry"] == ["PK"] for row in first_page["results"] + second_page["results"])


def test_regional_tv_response_is_enriched_with_imdb_rating(monkeypatch):
    monkeypatch.setattr(tv, "BACKFILL_MISSING_METADATA", True)

    async def get_rating(title, year, media_type, tmdb_id):
        assert (title, year, media_type, tmdb_id) == ("Example Series", 2024, "tv", 12)
        return {
            "status": "found",
            "imdbRating": 8.2,
            "imdbVotes": 1234,
            "imdbId": "tt0000012",
            "imdbUrl": "https://www.imdb.com/title/tt0000012/",
        }

    monkeypatch.setattr(tv, "_get_imdb_rating_record", get_rating)
    payload = {"results": [{"id": 12, "title": "Example Series", "year": 2024}]}

    result = asyncio.run(tv._enrich_regional_tv_imdb_ratings(payload))

    assert result["results"][0]["imdbRating"] == 8.2
    assert result["results"][0]["imdbId"] == "tt0000012"
    assert result["results"][0]["imdbRatingStatus"] == "found"


def test_regional_tv_rows_deduplicate_same_series_by_id_and_title_year():
    rows = [
        {"id": 101, "title": "Example Drama", "year": 2022},
        {"id": 101, "title": "Example Drama", "year": 2022},
        {"id": 202, "title": " Example Drama! ", "year": 2022},
        {"id": 303, "title": "Another Drama", "year": 2022},
    ]

    result = tv._dedupe_regional_tv_rows(rows)

    assert [row["id"] for row in result] == [101, 303]



def test_korean_tv_trending_prebuilt_results_apply_release_type_origin_and_ott_filters(monkeypatch):
    async def get_json(path, params):
        tmdb_id = int(path.split("/")[-1])
        return {
            1: {
                "id": 1, "name": "Old Korean Drama", "first_air_date": "2014-12-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
            2: {
                "id": 2, "name": "Eligible Korean Drama", "first_air_date": "2022-01-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
            3: {
                "id": 3, "name": "Korean Variety Show", "first_air_date": "2022-01-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Reality",
                "genres": [{"id": 10764, "name": "Reality"}],
            },
            4: {
                "id": 4, "name": "Non-Korean Series", "first_air_date": "2022-01-01",
                "origin_country": ["US"], "original_language": "en", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
        }[tmdb_id]

    async def streaming_providers(tmdb_id):
        return [{"name": "Example OTT", "type": "subscription"}] if tmdb_id == 2 else []

    async def enrich(payload):
        return payload

    monkeypatch.setattr(tv, "_read_regional_tv_prebuilt_page", lambda *args: {
        "catalogue": "korean-trending",
        "page": 1,
        "totalPages": 1,
        "totalResults": 4,
        "results": [
            {"id": 1, "title": "Old Korean Drama", "releaseDate": "2014-12-01"},
            {"id": 2, "title": "Eligible Korean Drama", "releaseDate": "2022-01-01"},
            {"id": 3, "title": "Korean Variety Show", "releaseDate": "2022-01-01"},
            {"id": 4, "title": "Non-Korean Series", "releaseDate": "2022-01-01"},
        ],
    })
    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    monkeypatch.setattr(tv, "_tv_streaming_providers", streaming_providers)
    monkeypatch.setattr(tv, "_enrich_regional_tv_imdb_ratings", enrich)

    result = asyncio.run(tv.api_tmdb_regional_tv_catalogue("korean-trending", page=1))

    assert [row["title"] for row in result["results"]] == ["Eligible Korean Drama"]



def test_korean_prebuilt_movies_filter_origin_language_and_unreleased_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(movies, "REGIONAL_MOVIE_PREBUILT_CACHE_PATH", tmp_path / "prebuilt.json")
    monkeypatch.setattr(movies, "_CACHE_SEED_DIR", tmp_path)
    monkeypatch.setattr(movies, "read_json_cached", lambda path: {
        "catalogues": {
            "popular-korean": {
                "final": [
                    {"id": 1, "title": "Eligible Korean Film", "originCountry": ["KR"], "originalLanguage": "ko", "releaseDate": "2024-01-01"},
                    {"id": 2, "title": "Non-Korean Korean-Language Film", "originCountry": ["US"], "originalLanguage": "ko", "releaseDate": "2024-01-01"},
                    {"id": 3, "title": "Korean Dubbed Film", "originCountry": ["KR"], "originalLanguage": "en", "releaseDate": "2024-01-01"},
                    {"id": 4, "title": "Unreleased Korean Film", "originCountry": ["KR"], "originalLanguage": "ko", "releaseDate": "2999-01-01"},
                ],
            },
        },
    })

    result = movies._prebuilt_final_page("popular-korean", 1)

    assert [row["title"] for row in result["results"]] == ["Eligible Korean Film"]


def test_korean_movie_source_filters_out_non_korean_origin(monkeypatch):
    async def get_json(path, params):
        assert params["with_origin_country"] == "KR"
        return {
            "page": 1,
            "total_pages": 1,
            "total_results": 3,
            "results": [
                {"id": 1, "title": "Korean Film", "original_language": "ko", "origin_country": ["KR"], "release_date": "2024-01-01"},
                {"id": 2, "title": "Korean-Language US Film", "original_language": "ko", "origin_country": ["US"], "release_date": "2024-01-01"},
                {"id": 3, "title": "English Korean Co-Production", "original_language": "en", "origin_country": ["KR"], "release_date": "2024-01-01"},
            ],
        }

    monkeypatch.setattr(movies, "_tmdb_get_json", get_json)
    result = asyncio.run(movies._tmdb_fetch_movie_catalogue("popular-korean", 1))

    assert [row["title"] for row in result["results"]] == ["Korean Film"]


def test_imdb_lookup_endpoint_accepts_non_persistent_incomplete_refresh(monkeypatch):
    observed = {}

    async def get_rating(title, year, media_type, tmdb_id, *, persist, refresh_incomplete):
        observed.update({
            "title": title,
            "year": year,
            "media_type": media_type,
            "tmdb_id": tmdb_id,
            "persist": persist,
            "refresh_incomplete": refresh_incomplete,
        })
        return {
            "status": "found", "title": title, "year": year, "mediaType": media_type,
            "imdbId": "tt1234567", "imdbRating": 7.6, "checkedAt": 1761690000,
        }

    monkeypatch.setattr(imdb, "_get_imdb_rating_record", get_rating)
    result = asyncio.run(imdb.api_catalogue_imdb_ratings(
        titles=["Chirp (2024)"],
        media_types=["movie"],
        tmdb_ids=[1807573],
        persist=False,
        refresh_incomplete=True,
    ))

    assert observed == {
        "title": "Chirp", "year": 2024, "media_type": "movie",
        "tmdb_id": 1807573, "persist": False, "refresh_incomplete": True,
    }
    assert result["results"][0]["imdbId"] == "tt1234567"
    assert result["results"][0]["imdbRating"] == 7.6


def test_incomplete_cached_imdb_record_is_refetched_without_persisting(monkeypatch):
    cache_key = imdb._imdb_rating_cache_key("Chirp", 2024)
    monkeypatch.setattr(imdb, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(imdb, "CACHE_FIRST", True)
    monkeypatch.setattr(imdb, "_load_imdb_rating_cache", lambda: {
        cache_key: {
            "cacheKey": cache_key, "title": "Chirp", "year": 2024,
            "status": "found", "imdbId": "tt1234567", "imdbRating": 0,
            "checkedAt": 1761690000,
        },
    })
    monkeypatch.setattr(imdb, "_IMDB_RATING_INFLIGHT", {})
    calls = {"fetch": 0, "save": 0}

    async def fetch(title, year, key, media_type, tmdb_id):
        calls["fetch"] += 1
        assert tmdb_id == 1807573
        return {
            "cacheKey": key, "title": title, "year": year, "mediaType": media_type,
            "status": "found", "imdbId": "tt1234567", "imdbRating": 7.6,
            "checkedAt": 1761690000,
        }

    async def save(_record):
        calls["save"] += 1

    monkeypatch.setattr(imdb, "_fetch_imdb_rating", fetch)
    monkeypatch.setattr(imdb, "_save_imdb_rating_cache_record", save)
    result = asyncio.run(imdb._get_imdb_rating_record(
        "Chirp", 2024, "movie", 1807573,
        persist=False, refresh_incomplete=True,
    ))

    assert result["imdbId"] == "tt1234567"
    assert calls == {"fetch": 1, "save": 0}


def test_live_catalogue_refresh_can_skip_application_cache_writes(monkeypatch):
    observed = {}

    async def fetch(catalogue_key, page, *, cache_write):
        observed.update({"catalogue_key": catalogue_key, "page": page, "cache_write": cache_write})
        return {"catalogue": catalogue_key, "page": page, "results": []}

    async def enrich(*args, **kwargs):
        raise AssertionError("No-cache refresh must not run cache-writing IMDb/OTT enrichment")

    monkeypatch.setattr(movies, "_fetch_paginated_regional_movie_catalogue", fetch)
    monkeypatch.setattr(movies, "_enrich_regional_movie_catalogue_metadata", enrich)
    result = asyncio.run(movies._live_regional_candidates(
        "latest-hollywood", 1, cache_write=False,
    ))

    assert observed == {"catalogue_key": "latest-hollywood", "page": 1, "cache_write": False}
    assert result["catalogue"] == "latest-hollywood"


def test_no_cache_live_fetch_leaves_memory_and_disk_catalogue_caches_untouched(monkeypatch):
    cache_key = ("popular-hollywood|released-v6", 1)
    original_cache = {cache_key: (0.0, {"results": [{"id": 999, "title": "Cached"}]})}
    writes = []

    async def fetch_source(catalogue_key, page, released_only):
        assert catalogue_key == "popular-hollywood"
        assert page == 1
        assert released_only is True
        return {
            "totalPages": 1,
            "totalResults": 19,
            "results": [{"id": index, "title": f"Film {index}"} for index in range(19)],
        }

    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", original_cache)
    monkeypatch.setattr(movies, "_read_tmdb_persistent_cache", lambda *args: pytest.fail("No-cache refresh read disk cache"))
    monkeypatch.setattr(movies, "_write_tmdb_persistent_cache", lambda *args: writes.append(args))
    monkeypatch.setattr(movies, "_tmdb_fetch_movie_catalogue", fetch_source)
    refresh_token = movies._REGIONAL_MOVIE_SOURCE_FORCE_REFRESH.set(True)
    keys_token = movies._REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS.set(set())
    try:
        result = asyncio.run(movies._fetch_paginated_regional_movie_catalogue(
            "popular-hollywood", 1, cache_write=False,
        ))
    finally:
        movies._REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS.reset(keys_token)
        movies._REGIONAL_MOVIE_SOURCE_FORCE_REFRESH.reset(refresh_token)

    assert len(result["results"]) == 18
    assert original_cache[cache_key][1]["results"][0]["id"] == 999
    assert writes == []


def test_movie_catalogue_route_passes_cache_write_opt_out(monkeypatch):
    observed = {}

    async def live_page(catalogue_key, page, *, cache_write):
        observed.update({"catalogue_key": catalogue_key, "page": page, "cache_write": cache_write})
        return {"results": []}

    monkeypatch.setattr(movies, "_live_regional_candidates", live_page)
    asyncio.run(movies.api_tmdb_movie_catalogue(
        "popular-hollywood",
        page=1,
        released_only=True,
        max_size_gb=5,
        basic=False,
        live=True,
        cache_write=False,
    ))
    assert observed == {
        "catalogue_key": "popular-hollywood", "page": 1, "cache_write": False,
    }


def test_tmdb_details_endpoint_returns_metadata_by_existing_tmdb_id(monkeypatch):
    async def get_json(path, params, *, request_timeout):
        assert path == "movie/1807573"
        assert params == {"language": "en-US"}
        assert request_timeout == 6.0
        return {
            "id": 1807573,
            "title": "Chirp",
            "release_date": "2024-06-01",
            "overview": "A verified synopsis.",
            "poster_path": "/chirp.jpg",
            "backdrop_path": "/chirp-backdrop.jpg",
            "vote_average": 6.2,
        }

    monkeypatch.setattr(movies, "_tmdb_get_json", get_json)
    result = asyncio.run(movies.api_tmdb_movie_metadata(1807573))

    assert result["tmdbId"] == 1807573
    assert result["year"] == 2024
    assert result["overview"] == "A verified synopsis."
    assert result["posterUrl"].endswith("/chirp.jpg")


def test_tmdb_tv_metadata_endpoint_parses_year_and_returns_in_region_providers(monkeypatch):
    async def get_json(path, params):
        if path == "tv/42":
            assert params == {"language": "en-US"}
            return {
                "name": "Example Series",
                "first_air_date": "2021-08-12",
                "overview": "A verified TV synopsis.",
                "poster_path": "/series.jpg",
                "backdrop_path": "/series-backdrop.jpg",
                "vote_average": 8.1,
            }
        if path == "tv/42/watch/providers":
            assert params == {}
            return {"results": {"IN": {
                "flatrate": [{"provider_id": 8, "provider_name": "Provider"}],
                "rent": [{"provider_id": 9, "provider_name": "Rental"}],
            }}}
        if path == "tv/42/external_ids":
            return {"imdb_id": "tt0000042"}
        raise AssertionError(f"Unexpected TMDB path: {path}")

    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    result = asyncio.run(tv.api_tmdb_tv_metadata(42))

    assert result["year"] == 2021
    assert result["releaseDate"] == "2021-08-12"
    assert result["imdbId"] == "tt0000042"
    assert result["ottAvailability"]["region"] == "IN"
    assert result["ottAvailability"]["streamingProviders"][0]["name"] == "Provider"
    assert result["ottAvailability"]["rentProviders"][0]["name"] == "Rental"


@pytest.mark.parametrize(
    ("media_type", "result_key", "title_key", "title"),
    [
        ("movie", "movie_results", "title", "Example Film"),
        ("tv", "tv_results", "name", "Example Series"),
    ],
)
def test_tmdb_find_resolves_valid_imdb_ids_for_requested_media_type(
    monkeypatch, media_type, result_key, title_key, title,
):
    async def get_json(path, params):
        assert path == "find/tt1234567"
        assert params == {"external_source": "imdb_id"}
        return {result_key: [{"id": 987, title_key: title}]}

    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    result = asyncio.run(tv.api_find_tmdb_by_imdb_id("tt1234567", media_type=media_type))

    assert result["found"] is True
    assert result["mediaType"] == media_type
    assert result["tmdbId"] == 987
    assert result["title"] == title


def test_tmdb_find_rejects_malformed_imdb_ids_before_lookup(monkeypatch):
    async def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("Malformed IDs must not trigger TMDB requests")

    monkeypatch.setattr(tv, "_tmdb_get_json", unexpected_lookup)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tv.api_find_tmdb_by_imdb_id("ttnot-an-id", media_type="tv"))

    assert exc.value.status_code == 400


def test_explicit_non_persistent_incomplete_refresh_remains_cache_only(monkeypatch):
    cache_key = imdb._imdb_rating_cache_key("Chirp", 2024)
    monkeypatch.setattr(imdb, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(imdb, "CACHE_FIRST", True)
    monkeypatch.setattr(imdb, "_load_imdb_rating_cache", lambda: {
        cache_key: {
            "cacheKey": cache_key, "title": "Chirp", "year": 2024,
            "status": "not_found", "imdbRating": None, "checkedAt": 1761690000,
        },
    })
    monkeypatch.setattr(imdb, "_IMDB_RATING_INFLIGHT", {})
    calls = {"fetch": 0, "save": 0}

    async def fetch(title, year, key, media_type, tmdb_id):
        calls["fetch"] += 1
        assert (title, year, tmdb_id) == ("Chirp", 2024, 1807573)
        return {
            "cacheKey": key, "title": title, "year": year, "mediaType": media_type,
            "status": "found", "imdbId": "tt1234567", "imdbRating": 7.6,
            "checkedAt": 1761690000,
        }

    async def save(_record):
        calls["save"] += 1

    monkeypatch.setattr(imdb, "_fetch_imdb_rating", fetch)
    monkeypatch.setattr(imdb, "_save_imdb_rating_cache_record", save)
    result = asyncio.run(imdb._get_imdb_rating_record(
        "Chirp", 2024, "movie", 1807573,
        persist=False, refresh_incomplete=True,
    ))

    assert result["status"] == "not_found"
    assert calls == {"fetch": 0, "save": 0}


def test_cache_only_mode_still_blocks_ordinary_imdb_lookup(monkeypatch):
    cache_key = imdb._imdb_rating_cache_key("Chirp", 2024)
    cached = {
        "cacheKey": cache_key, "title": "Chirp", "year": 2024,
        "status": "not_found", "imdbRating": None,
    }
    monkeypatch.setattr(imdb, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(imdb, "_load_imdb_rating_cache", lambda: {cache_key: cached})

    async def unexpected_fetch(*args, **kwargs):
        raise AssertionError("ordinary cache-only lookup must not call providers")

    monkeypatch.setattr(imdb, "_fetch_imdb_rating", unexpected_fetch)
    result = asyncio.run(imdb._get_imdb_rating_record("Chirp", 2024, "movie", 1807573))

    assert result is cached
